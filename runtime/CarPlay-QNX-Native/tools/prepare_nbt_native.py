#!/opt/homebrew/bin/python3.13
"""Create a separate original-NBT profile with local-only SSH and QNX video adapter."""
from pathlib import Path
import hashlib,importlib.util,json,struct,sys
ROOT=Path(__file__).resolve().parents[1]
NBT=ROOT.parent/'NBT-Original'
CROSS=ROOT.parent/'NBT-Dev-Cross'
SDK=CROSS/'runtimes/qnx650-linux/target/qnx6/x86'
sys.path.insert(0,str(NBT/'tools'))
sys.path.insert(0,str(ROOT.parent/'NBT-Dev/src/BMW-NBT-Emulator/tools'))
from compact_ifs import compact
from inspect_nbt_ifs import find_imagefs
from repack_nbt_ifs import repack
from probe_hardware import envelope

if __name__=='__main__':
    directory=NBT/'profiles/zh-CN-carplay-native';directory.mkdir(exist_ok=True)
    source=Path(json.loads((NBT/'profiles/zh-CN-carplay-load/manifest.json').read_text())['image']['output'])
    data=source.read_bytes();entries={e['path']:e for e in find_imagefs(data)['entries']}
    additions={
        'boot/bin/pci-bios':SDK/'sbin/pci-bios',
        'boot/lib/devnp-e1000.so':SDK/'lib/dll/devnp-e1000.so',
        'boot/bin/route':SDK/'sbin/route',
        'boot/bin/random':SDK/'usr/sbin/random',
        'boot/bin/sshd':SDK/'usr/sbin/sshd',
        'boot/lib/libcrypto.so.1':SDK/'usr/lib/libcrypto.so.1',
        'boot/native/native_decoder':ROOT/'build/native_decoder',
        'boot/native/native_hid':ROOT/'build/native_hid',
        'boot/native/native_video_ctl':ROOT/'build/native_video_ctl',
        'boot/lib/libnative_overlay.so':ROOT/'build/libnative_overlay.so',
    }
    if (ROOT/'build/native_airplay').exists():
        additions['boot/native/native_airplay']=ROOT/'build/native_airplay'
    tool_hashes={name:hashlib.sha256((ROOT/'build'/name).read_bytes()).hexdigest()
                 for name in ['native_decoder','native_hid','native_video_ctl']}
    tool_manifest=directory/'tool-hashes.json'
    tool_manifest.write_text(json.dumps(tool_hashes,sort_keys=True)+'\n')
    additions['boot/native/tool-hashes.json']=tool_manifest
    config=directory/'sshd_config'
    config.write_text('''Port 22
Protocol 2
HostKey /var/tmp/nbt-native/ssh_host_rsa_key
PidFile /var/tmp/nbt-native/sshd.pid
PermitRootLogin yes
PubkeyAuthentication yes
AuthorizedKeysFile /var/tmp/nbt-native/authorized_keys
PasswordAuthentication no
ChallengeResponseAuthentication no
PermitEmptyPasswords no
UsePrivilegeSeparation no
StrictModes yes
LogLevel INFO
UseDNS no
''')
    passwd=directory/'passwd';passwd.write_text('root::0:0:Local native NBT:/var/tmp/nbt-native:/boot/bin/sh\n')
    group=directory/'group';group.write_text('root::0:\n')
    additions.update({'boot/native/sshd_config':config,'etc/passwd':passwd,'etc/group':group})
    for name in ['ssh_host_rsa_key','authorized_keys']:
        additions['boot/native/'+name]=CROSS/'vm/qnx-runtime-config'/name
    network=directory/'network.sh'
    network.write_text('''#!/boot/bin/sh
export PATH=/boot/bin
export LD_LIBRARY_PATH=/boot/lib
umask 077
mkdir -p /var/tmp/nbt-native
chmod 0700 /var/tmp/nbt-native
cp /boot/native/ssh_host_rsa_key /var/tmp/nbt-native/ssh_host_rsa_key
cp /boot/native/authorized_keys /var/tmp/nbt-native/authorized_keys
chmod 0600 /var/tmp/nbt-native/ssh_host_rsa_key /var/tmp/nbt-native/authorized_keys
/boot/bin/pci-bios &
/boot/bin/waitfor /dev/pci 5
/boot/bin/io-pkt-v4 -de1000
/boot/bin/waitfor /dev/socket 10
/boot/bin/ifconfig lo0 127.0.0.1
/boot/bin/ifconfig wm0 10.0.2.15 netmask 255.255.255.0
/boot/bin/route add default 10.0.2.2
/boot/bin/random -p -t &
/boot/bin/waitfor /dev/random 5
(
attempt=0
while test $attempt -lt 10; do
    attempt=$((attempt+1))
    echo NBT_NATIVE_SSH_START attempt=$attempt
    /boot/bin/on -p 16 /boot/bin/sshd -D -e -f /boot/native/sshd_config
    /boot/bin/sleep 1
done
echo NBT_NATIVE_SSH_UNAVAILABLE
) &
echo NBT_NATIVE_NETWORK_READY
''')
    additions['boot/native/network.sh']=network
    entry=entries['proc/boot/.startupscript']
    script=data[entry['absolute_offset']:entry['absolute_offset']+entry['size']]
    out=bytearray();pos=0;changed=0
    old=b'/boot/bin/io-pkt-v4; /boot/bin/ifconfig lo0 127.0.0.1;'
    while pos<len(script):
        size=struct.unpack_from('<H',script,pos)[0]
        if not size:out.extend(script[pos:]);break
        record=script[pos:pos+size]
        if old in record:
            record=record.replace(old,b'/boot/bin/sh /boot/native/network.sh;')
            marker=b'LD_PRELOAD='
            assert marker in record
            record=record.replace(marker,marker+b'/boot/lib/libnative_overlay.so:')
            record+=bytes((-len(record))%4)
            record=struct.pack('<H',len(record))+record[2:];changed+=1
        out.extend(record);pos+=size
    assert changed==1
    startup=directory/'startup.bin';startup.write_bytes(out)
    replacements={'proc/boot/.startupscript':startup,'boot/bin/io-pkt-v4':SDK/'sbin/io-pkt-v4'}
    if (ROOT/'build/libnbtgl.so').exists():
        replacements['boot/lib/libnbtgl.so']=ROOT/'build/libnbtgl.so'
    assert not additions.keys()&entries.keys()
    identity=hashlib.sha256(out+b''.join(p.read_bytes() for k,p in sorted({**additions,**replacements}.items()))).hexdigest()[:12]
    raw=directory/('native-'+identity+'-raw.ifs')
    image=directory/('native-'+identity+'.ifs')
    if not raw.exists():repack(source,raw,replacements,additions,add_mode=0o755)
    if not image.exists():meta=compact(raw,image)
    else:meta=json.loads(image.with_suffix('.json').read_text())
    if image.stat().st_size>=253*1024*1024:raise RuntimeError('Native IFS exceeds the validated mapping limit')
    boot=envelope(image,NBT/'vm/nbt-boot-zh-CN-carplay-native.elf',512,1)
    image.chmod(0o600);raw.chmod(0o600)
    report={'source_profile':'zh-CN-carplay-load','image':meta,'envelope':boot,
            'network':'E1000, usernet restrict=on, local-only SSH 127.0.0.1:2225',
            'native_decoder_sha256':hashlib.sha256((ROOT/'build/native_decoder').read_bytes()).hexdigest(),
            'native_protocol_migrated':False,'native_display_verified':False,
            'native_tool_hashes':tool_hashes,
            'display_adapter_sha256':hashlib.sha256((ROOT/'build/libnative_overlay.so').read_bytes()).hexdigest(),
            'graphics_bridge_sha256':hashlib.sha256((ROOT/'build/libnbtgl.so').read_bytes()).hexdigest() if (ROOT/'build/libnbtgl.so').exists() else None,
            'display_strategy':'QNX-owned presentation batches bounded to 5 guest seconds, yielding to stock HMI heartbeat; bounded physical YUV texture upload',
            'original_hmi_preserved':True}
    (directory/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    pub=(CROSS/'vm/qnx-runtime-config/ssh_host_rsa_key.pub').read_text().split()
    (ROOT/'build/nbt_known_hosts').write_text('[127.0.0.1]:2225 '+pub[0]+' '+pub[1]+'\n')
    ssh=(CROSS/'vm/qnx_ssh_config').read_text().replace('Host qnx-runtime','Host nbt-native').replace('Port 2224','Port 2225').replace(str(CROSS/'vm/qnx_known_hosts'),str(ROOT/'build/nbt_known_hosts'))
    (ROOT/'build/nbt_ssh_config').write_text(ssh)
    print(json.dumps({'image':str(image),'bytes':image.stat().st_size,'profile':'zh-CN-carplay-native'}))
