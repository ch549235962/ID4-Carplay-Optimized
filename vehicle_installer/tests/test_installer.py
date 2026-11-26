"""Fault injection against an isolated filesystem, never a vehicle or running VM."""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch
from vehicle_installer.payload import RT, PLUGIN, RW, CONTROL, Entry, Package, InstallError, safe_relative
from vehicle_installer.remote import Remote, PinnedKey, fingerprint
from vehicle_installer.engine import Installer, local_lock
from vehicle_installer.backup import Snapshot
from vehicle_installer.transaction import commit_script
from vehicle_installer import gateway

SHELL = str(Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Git/bin/bash.exe') if os.name=='nt' else '/bin/sh'


class Sandbox(Remote):
    def __init__(self, folder, fail_move=0, fail_stage=False, corrupt=False, disconnect=False):
        self.folder=folder;self.host='169.254.199.99';self.fingerprint='SHA256:TEST-HEADUNIT'
        self.fail_move=fail_move;self.fail_stage=fail_stage;self.corrupt=corrupt;self.disconnect=disconnect;self.online=True
        self.path(RW).mkdir(parents=True,exist_ok=True)
    def path(self,path):return self.folder/path.removeprefix('/')
    def run(self,command,data=b'',timeout=60,max_output=16*1024*1024,check=True):
        if not self.online:raise InstallError('test disconnect')
        is_walk=command.startswith('walk()')
        command=command.replace(RW,self.path(RW).as_posix())
        result=subprocess.run([SHELL,'-c',command],input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
        if check and result.returncode:raise InstallError(result.stderr.decode(errors='replace'))
        if len(result.stdout)+len(result.stderr)>max_output:raise InstallError('output limit')
        output=result.stdout.replace(self.path(RW).as_posix().encode(),RW.encode()) if is_walk else result.stdout
        return result.returncode,output,result.stderr
    def close(self):pass
    def identity(self):return {'model':'原始 HU_NBT','system':'QNX','qnx_version':'6.5.0','architecture':'x86','fingerprint':self.fingerprint}
    def free_bytes(self):return 512*1024*1024
    def quiet_services(self):pass
    def put(self,data,target,mode=0o600):
        if self.fail_stage and target.endswith('/new-r/nbt_carplay'):raise InstallError('test upload failure')
        return super().put(data,target,mode)
    def read(self,target,max_bytes=16*1024*1024):
        data=super().read(target,max_bytes)
        if self.corrupt and target==RT+'/nbt_carplay' and any(self.path(CONTROL).glob('*/phase')):
            if any(p.read_text(encoding='utf-8').strip()=='committed' for p in self.path(CONTROL).glob('*/phase')):
                self.corrupt=False;return b'corrupt'
        return data
    def exec_script(self,path):
        source=self.read(path).decode().replace(RW,self.path(RW).as_posix())
        if path.endswith('/activate.sh') and self.fail_move:
            source=source.replace('set -eu','set -eu\n_count=0\nmv(){ _count=$((_count+1)); if test "$_count" = '+str(self.fail_move)+'; then return 1; fi; command mv "$@"; }',1)
        script=self.path(path).with_name('sandbox-run.sh');script.write_text(source,encoding='utf-8',newline='\n')
        result=subprocess.run([SHELL,script.as_posix()],capture_output=True,timeout=15)
        if path.endswith('/activate.sh') and self.disconnect:
            self.online=False;raise InstallError('test connection lost after remote activation')
        if result.returncode:raise InstallError('test activation failure '+result.stderr.decode())
        return 0,result.stdout,result.stderr


PACKAGE=Package('test-version','test-hash',(
    Entry('rt/nbt_carplay',RT+'/nbt_carplay',0o700,b'official-car-binary'),
    Entry('plugin/plugin.so',PLUGIN+'/plugin.so',0o755,b'official-plugin'),
    Entry('plugin/main.manifest',PLUGIN+'/main.manifest',0o644,b'official-manifest'),
))


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.car=Sandbox(self.base/'car');self.local=self.base/'local'
        self.patchers=[patch('vehicle_installer.engine.obtain_package',return_value=PACKAGE),patch('vehicle_installer.gateway.discover',return_value=None)]
        for p in self.patchers:p.start()
    def tearDown(self):
        for p in self.patchers:p.stop()
        self.temp.cleanup()
    def installer(self):return Installer(self.local,remote_factory=lambda *args:self.car)
    def old(self):
        for path,data in [(RT+'/nbt_carplay',b'old-runtime'),(PLUGIN+'/plugin.so',b'old-plugin'),(RT+'/iap.off',b''),
                          (RT+'/decoder.off',b''),(RT+'/carplay-pairing',b'PRIVATE-TEST-DATA')]:
            f=self.car.path(path);f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
    def install(self,**kwargs):return self.installer().operate(self.car.host,'TEST-PASSWORD',**kwargs)
    def assert_old(self):
        self.assertEqual(self.car.read(RT+'/nbt_carplay'),b'old-runtime')
        self.assertEqual(self.car.read(PLUGIN+'/plugin.so'),b'old-plugin')
    def test_first_install_and_remove_via_restore(self):
        result=self.install()
        self.assertIn('全部文件回读校验通过',result['message'])
        self.assertEqual(self.car.read(RT+'/nbt_carplay'),b'official-car-binary')
        self.assertTrue(self.car.exists(RT+'/decoder.hw'))
        if os.name!='nt':self.assertEqual(self.car.path(PLUGIN).stat().st_mode&0o777,0o755)
        self.install(restore=True)
        self.assertFalse(self.car.exists(RT));self.assertFalse(self.car.exists(PLUGIN))
    def test_update_preserves_settings_and_pairing(self):
        self.old();self.install()
        self.assertTrue(self.car.exists(RT+'/iap.off'));self.assertTrue(self.car.exists(RT+'/decoder.off'))
        self.assertFalse(self.car.exists(RT+'/decoder.hw'))
        self.assertEqual(self.car.read(RT+'/carplay-pairing'),b'PRIVATE-TEST-DATA')
        self.install(restore=True);self.assert_old()
    def test_failed_stage_never_replaces_original(self):
        self.old();self.car.fail_stage=True
        with self.assertRaises(InstallError):self.install()
        self.assert_old();self.assertFalse(self.car.exists(CONTROL+'/lock'))
    def test_each_activation_rename_failure_rolls_back(self):
        for move in range(1,5):
            with self.subTest(move=move):
                folder=self.base/('car-'+str(move));self.car=Sandbox(folder,fail_move=move);self.old()
                self.local=self.base/('local-'+str(move))
                with self.assertRaises(InstallError):self.install()
                self.assert_old();self.assertFalse(self.car.exists(CONTROL+'/lock'))
    def test_post_activation_corruption_rolls_back(self):
        self.old();self.car.corrupt=True
        with self.assertRaisesRegex(InstallError,'已恢复原插件'):self.install()
        self.assert_old();self.assertFalse(self.car.exists(CONTROL+'/lock'))
    def test_disconnect_keeps_recovery_lock_and_can_restore(self):
        self.old();self.car.disconnect=True
        with self.assertRaisesRegex(InstallError,'不能确认车机状态'):self.install()
        self.car.online=True;self.car.disconnect=False
        self.assertTrue(self.car.exists(CONTROL+'/lock'))
        self.install(restore=True);self.assert_old()
        self.assertFalse(self.car.exists(CONTROL+'/lock'))
    def test_read_only_check_makes_no_remote_files(self):
        before=list(self.car.path(RW).iterdir())
        result=self.installer().check(self.car.host,'TEST-PASSWORD')
        self.assertIn('尚未安装',result['message']);self.assertEqual(before,list(self.car.path(RW).iterdir()))
    def test_recovery_itself_interrupted_still_uses_original_snapshot(self):
        self.old();self.car.disconnect=True
        with self.assertRaises(InstallError):self.install()
        self.car.online=True
        with self.assertRaises(InstallError):self.install(restore=True)
        self.car.online=True;self.car.disconnect=False
        self.install(restore=True);self.assert_old()
    def test_no_space_prevents_writes(self):
        self.car.free_bytes=lambda:1024
        with self.assertRaisesRegex(InstallError,'空间不足'):self.install()
        self.assertFalse(self.car.exists(CONTROL));self.assertFalse(self.car.exists(RT))
    def test_symbolic_links_refused_before_mutation(self):
        if os.name=='nt':self.skipTest('Windows test symlink privilege is not assumed')
        self.old();self.car.path(RT+'/link').symlink_to(self.car.path(RT+'/nbt_carplay'))
        with self.assertRaisesRegex(InstallError,'符号链接'):self.install()
        self.assertFalse(self.car.exists(CONTROL));self.assert_old()
    def test_foreign_pending_lock_is_not_removed(self):
        self.car.mkdir(CONTROL);self.car.acquire(uuid.uuid4().hex)
        with self.assertRaisesRegex(InstallError,'未完成'):self.install()
        self.assertTrue(self.car.exists(CONTROL+'/lock'))
    def test_backup_corruption_and_wrong_vehicle_refused(self):
        self.old();self.install()
        folder=next((self.local/'backups').iterdir())
        with self.assertRaises(InstallError):Snapshot.read(folder,'SHA256:OTHER-CAR')
        meta=json.loads((folder/'backup.json').read_text(encoding='utf-8'));meta['files'][0]['sha256']='0'*64
        (folder/'backup.json').write_text(json.dumps(meta),encoding='utf-8')
        with self.assertRaisesRegex(InstallError,'校验失败'):Snapshot.read(folder,self.car.fingerprint)
    @unittest.skipIf(os.name=='nt','This test checks POSIX flock; Windows uses msvcrt locking')
    def test_two_instances_cannot_mutate_together(self):
        self.local.mkdir()
        with local_lock(self.local):
            with self.assertRaises(InstallError):
                with local_lock(self.local):pass
    def test_recovery_refuses_still_running_remote_script(self):
        self.old();self.car.disconnect=True
        with self.assertRaises(InstallError):self.install()
        self.car.online=True;self.car.disconnect=False
        token=self.car.read(CONTROL+'/lock/owner').decode()
        # A shell's own PID also works under Windows Git Bash's PID namespace.
        pid=self.car.run('echo $$')[1].strip()
        self.car.put(pid,CONTROL+'/'+token+'/pid')
        original_run=self.car.run
        self.car.run=lambda command,**kwargs:(0,b'',b'') if command.startswith('kill -0 ') else original_run(command,**kwargs)
        with self.assertRaisesRegex(InstallError,'仍在运行'):self.install(restore=True)


class PayloadTests(unittest.TestCase):
    def test_bad_paths_rejected(self):
        for name in ['/absolute','a/../../escape','a\\b','a\nfile']:
            with self.subTest(name=name),self.assertRaises(InstallError):safe_relative(name)
    def test_pinned_package_and_modified_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'official.zip';data=b'test-binary'
            entry={'source':'runtime/file','target':RT+'/file','mode':'700','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            with zipfile.ZipFile(file,'w') as archive:
                archive.writestr('release/payload/manifest.json',json.dumps({'version':'test','files':[entry]}))
                archive.writestr('release/payload/runtime/file',data)
            lock={'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'version':'test','files':[entry]}
            self.assertEqual(Package.read(file,lock).entries[0].data,data)
            file.write_bytes(file.read_bytes()+b'changed')
            with self.assertRaisesRegex(InstallError,'校验失败'):Package.read(file,lock)
            with file.open('wb') as output:output.truncate(17*1024*1024)
            with patch.object(Path,'open',side_effect=AssertionError('Large package must not be read')):
                with self.assertRaisesRegex(InstallError,'过大'):Package.read(file,lock)
    def test_forbidden_payload_target_even_if_manifest_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'bad.zip';entry={'source':'runtime/file','target':'/etc/passwd','mode':'700','size':1,'sha256':hashlib.sha256(b'x').hexdigest()}
            with zipfile.ZipFile(file,'w') as archive:
                archive.writestr('release/payload/manifest.json',json.dumps({'version':'test','files':[entry]}))
                archive.writestr('release/payload/runtime/file',b'x')
            lock={'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'version':'test','files':[entry]}
            with self.assertRaisesRegex(InstallError,'非插件目录'):Package.read(file,lock)


class IdentityTests(unittest.TestCase):
    def remote(self,info):
        remote=object.__new__(Remote);remote.fingerprint='test'
        def run(command,**kwargs):
            if command.startswith('uname'):return 0,info.encode(),b''
            if command.startswith('test -L') or command.startswith('test -d /opt/hmi/ID5'):return 1,b'',b''
            return 0,b'',b''
        remote.run=run;return remote
    def test_supported_nbt(self):self.assertEqual(self.remote('QNX x86pc 6.5.0 0').identity()['model'],'原始 HU_NBT')
    def test_incompatible_and_unprivileged_units(self):
        for info in ['Linux x86 6.5.0 0','QNX arm 6.5.0 0','QNX sh4 6.3.2 0','QNX x86 6.5.0 501']:
            with self.subTest(info=info),self.assertRaises(InstallError):self.remote(info).identity()
    def test_missing_apple_interface_refused(self):
        remote=self.remote('QNX x86 6.5.0 0');old=remote.run
        remote.run=lambda cmd,**kwargs:(1,b'',b'') if '/dev/i2c/' in cmd else old(cmd,**kwargs)
        with self.assertRaisesRegex(InstallError,'Apple'):remote.identity()
    def test_changed_host_key_refused(self):
        class Key:
            def asbytes(self):return b'key'
        with self.assertRaisesRegex(InstallError,'身份'):PinnedKey('SHA256:old').missing_host_key(None,'car',Key())


class Socket:
    def __init__(self,data):self.data=data;self.sent=b''
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def settimeout(self,*args):pass
    def sendall(self,data):self.sent+=data
    def recv(self,count):part=self.data[:min(count,2)];self.data=self.data[len(part):];return part


class GatewayTests(unittest.TestCase):
    @staticmethod
    def frame(body,control=1):return struct.pack('>IH',len(body),control)+body
    def test_ack_pending_accepted_and_exact_reset_packet(self):
        sock=Socket(self.frame(b'\xf4\x63',2)+self.frame(bytes.fromhex('63f47f1178'))+self.frame(bytes.fromhex('63f45101')))
        with patch('socket.create_connection',return_value=sock):self.assertTrue(gateway.reset('169.254.1.1'))
        self.assertEqual(sock.sent,bytes.fromhex('000000040001f4631101'))
    def test_refused_and_truncated_response_not_success(self):
        for data in [self.frame(bytes.fromhex('63f47f1122')),b'\x00',struct.pack('>IH',1000,1)]:
            with self.subTest(data=data),patch('socket.create_connection',return_value=Socket(data)),self.assertRaises(InstallError):gateway.reset('169.254.1.1')
    def test_no_os_shutdown_in_installation_code(self):
        folder=Path(__file__).parents[1]
        for name in ['engine.py','remote.py','transaction.py','gateway.py']:
            self.assertNotIn('/sbin/shutdown',(folder/name).read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
