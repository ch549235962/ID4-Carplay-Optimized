#!/usr/bin/env python3
"""Start/stop the local original-x86-NBT VM and its macOS renderer."""
import argparse,json,os,signal,socket,subprocess,time,urllib.request
from pathlib import Path
import resources
R=Path(__file__).resolve().parents[1]
SOCK='/tmp/nbt-original-qmp.sock'
URL='http://127.0.0.1:8876'
PROFILE_IMAGES={'en-GB':'nbt-boot.elf','zh-CN':'nbt-boot-zh-CN.elf','zh-CN-aa':'nbt-boot-zh-CN-aa.elf','zh-CN-carplay':'nbt-boot-zh-CN-carplay.elf','zh-CN-carplay-load':'nbt-boot-zh-CN-carplay-load.elf','zh-CN-carplay-native':'nbt-boot-zh-CN-carplay-native.elf'}
def selected_profile():
    p=R/'vm/selected-profile.json'
    profile=json.loads(p.read_text())['language'] if p.exists() else 'en-GB'
    if profile not in PROFILE_IMAGES:raise ValueError('Unknown language profile')
    return profile
def macplay_backend():
    try:return json.loads((R/'vm/carplay-backend.json').read_text()).get('backend') in ['macplay-usb','macplay-wireless']
    except (OSError,ValueError):return False
def boot_image():return resources.image_for_ram(R/'vm'/PROFILE_IMAGES[selected_profile()])

def qmp(command):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(3);s.connect(SOCK)
        with s.makefile('rwb',buffering=0) as f:
            json.loads(f.readline())
            for name in ['qmp_capabilities',command]:
                f.write((json.dumps({'execute':name})+'\n').encode())
                while True:
                    reply=json.loads(f.readline())
                    if 'return' in reply or 'error' in reply:break
                if 'error' in reply:raise RuntimeError(reply['error'])
            return reply['return']

def owned_pid(name):
    p=R/('vm/'+name+'.pid')
    try:
        pid=int(p.read_text())
        args=subprocess.check_output(['ps','-p',str(pid),'-o','args='],text=True).strip()
        expected={'renderer':str(R/'renderer/nbt-glhost-macos'),'viewer':str(R/'tools/viewer.py'),'video-metrics':str(R/'tools/video_metrics.py'),'carplay-input':str(R/'tools/carplay_input.mjs')}[name]
        return pid if expected in args else None
    except (OSError,ValueError,subprocess.CalledProcessError):return None

def status():
    result={'url':URL,'language_profile':selected_profile(),'qemu':'stopped','renderer_running':bool(owned_pid('renderer')),'viewer_running':bool(owned_pid('viewer'))}
    try:result['qemu']=qmp('query-status')['status']
    except (OSError,ValueError,RuntimeError):pass
    if result['viewer_running']:
        try:
            with urllib.request.urlopen(URL+'/status',timeout=2) as f:result.update(json.load(f))
        except OSError:pass
    return result

def stop():
    for name in ['carplay-input','video-metrics','viewer','renderer']:
        pid=owned_pid(name)
        if pid:
            os.kill(pid,signal.SIGTERM)
            for _ in range(30):
                if not owned_pid(name):break
                time.sleep(.1)
    try:
        if qmp('query-name').get('name')!='BMW-NBT-Original':raise RuntimeError('QMP socket belongs to another VM')
        qmp('quit')
    except (FileNotFoundError,ConnectionRefusedError):pass
    for _ in range(50):
        try:qmp('query-status')
        except (OSError,ValueError):break
        time.sleep(.1)
    else:raise RuntimeError('QEMU did not stop; RAM retained')
    for n in ['ram.bin','frame.ppm','renderer-metrics.json','boot-identity.json']:(R/'vm'/n).unlink(missing_ok=True)
    print('NBT stopped; host source and build files retained')

def start():
    current=status()
    if current['qemu']=='running' and current['renderer_running'] and current['viewer_running']:
        print(json.dumps(current,ensure_ascii=False));return
    if current['qemu']!='stopped' or current['renderer_running'] or current['viewer_running']:stop()
    required=[boot_image(),R/'renderer/nbt-glhost-macos',R/'renderer/lib/libEGL.dylib',R/'renderer/lib/libGLESv2.dylib']
    for p in required:
        if not p.is_file():raise RuntimeError('Required file missing: '+str(p))
    for port in [8876,27871,27872]:
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    for n in ['ram.bin','frame.ppm','renderer-metrics.json']:(R/'vm'/n).unlink(missing_ok=True)
    ram=resources.config()['ram_mib'];ram_bytes=ram*1024*1024
    args=['/opt/homebrew/bin/qemu-system-i386','-name','BMW-NBT-Original','-machine','pc,memory-backend=ram',
          '-accel','tcg,thread=single','-cpu','qemu32','-m',str(ram)+'M','-smp','1','-icount','shift=0,sleep=off',
          '-kernel',str(boot_image()),'-display','none','-serial','file:'+str(R/'logs/serial.log'),
          '-monitor','none','-qmp','unix:'+SOCK+',server=on,wait=off','-nic','none','-no-reboot','-no-shutdown',
          '-object','memory-backend-file,id=ram,size='+str(ram)+'M,mem-path='+str(R/'vm/ram.bin')+',share=on',
          '-device','virtio-serial-pci,id=vfast,disable-modern=on,disable-legacy=off,max_ports=3',
          '-chardev','socket,id=glbridge,host=127.0.0.1,port=27871,server=on,wait=on,nodelay=on',
          '-device','virtserialport,chardev=glbridge,bus=vfast.0,nr=1,name=nbtgl',
          '-chardev','socket,id=nbtinput,host=127.0.0.1,port=27872,server=on,wait=off,nodelay=on',
          '-device','virtserialport,chardev=nbtinput,bus=vfast.0,nr=2,name=nbtinput']
    if selected_profile()=='zh-CN-carplay-native':
        # SSH is reachable only from this Mac. The radio/projection receiver is
        # added explicitly by the native development tools, never exposed here.
        i=args.index('-nic');del args[i:i+2]
        args+=['-netdev','user,id=native-net,restrict=on,hostfwd=tcp:127.0.0.1:2225-:22',
               '-device','e1000,netdev=native-net']
    (R/'logs/serial.log').write_text('')
    with (R/'logs/qemu.log').open('ab') as f:
        child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
    (R/'vm/pid').write_text(str(child.pid));(R/'vm/command-active.json').write_text(json.dumps(args,indent=2))
    image=boot_image();info=image.stat()
    (R/'vm/boot-identity.json').write_text(json.dumps({'pid':child.pid,'image':str(image),
        'size':info.st_size,'mtime_ns':info.st_mtime_ns,'profile':selected_profile()}))
    time.sleep(.5)
    env=os.environ.copy();env.update({'DYLD_LIBRARY_PATH':str(R/'renderer/lib'),'GLHOST_QEMU_PORT':'27871','GLHOST_ANGLE_BACKEND':'metal',
        'GLHOST_DMA_CONFIG':str(R/'vm/ram.bin'),'MHI2_SHADER_CACHE':str(R.parent/'NBT-Dev/src/BMW-NBT-Emulator/work/graphics-port/host/shader-cache'),
        'MHI2_GL_FRAME':str(R/'vm/frame.ppm'),'GLHOST_RAM_BYTES':str(ram_bytes),'GLHOST_METRICS_FILE':str(R/'vm/renderer-metrics.json')})
    with (R/'logs/renderer.log').open('wb') as f:
        renderer=subprocess.Popen([str(R/'renderer/nbt-glhost-macos')],env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
    (R/'vm/renderer.pid').write_text(str(renderer.pid))
    with (R/'logs/viewer.log').open('wb') as f:
        viewer=subprocess.Popen(['/opt/homebrew/bin/python3.13',str(R/'tools/viewer.py')],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
    (R/'vm/viewer.pid').write_text(str(viewer.pid))
    if selected_profile()=='zh-CN-carplay-native':
        with (R/'logs/video-metrics.log').open('ab') as f:
            collector=subprocess.Popen(['/opt/homebrew/bin/python3.13',str(R/'tools/video_metrics.py')],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
        (R/'vm/video-metrics.pid').write_text(str(collector.pid))
        if not macplay_backend():
            with (R/'logs/carplay-input.log').open('ab') as f:
                input_relay=subprocess.Popen(['/opt/homebrew/bin/node',str(R/'tools/carplay_input.mjs')],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
            (R/'vm/carplay-input.pid').write_text(str(input_relay.pid))
    for _ in range(80):
        if any(p.poll() is not None for p in [child,renderer,viewer]):raise RuntimeError('Startup process exited; inspect logs/')
        try:
            with urllib.request.urlopen(URL+'/status',timeout=1) as f:json.load(f)
            print('NBT starting: '+URL+' (wait for original HMI and controller initialization)');return
        except OSError:time.sleep(.1)
    raise RuntimeError('Viewer did not become available; inspect logs/viewer.log')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','stop','status','restart']);a=p.parse_args()
    if a.action=='status':print(json.dumps(status(),ensure_ascii=False,indent=2))
    elif a.action=='stop':stop()
    elif a.action=='restart':stop();start()
    else:start()
if __name__=='__main__':main()
