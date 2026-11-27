"""Regression checks for QEMU stuck before QMP starts; no actual processes."""
import os,signal,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import nbt_vm as vm

class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);(self.root/'vm').mkdir()
        self.ram=self.root/'vm/ram.bin';self.ram.write_bytes(b'keep-until-exit')
        self.root_patch=patch.object(vm,'R',self.root);self.root_patch.start();self.addCleanup(self.root_patch.stop)

    def test_missing_qmp_still_terminates_owned_starting_process(self):
        with patch.object(vm,'owned_pid',return_value=None),patch.object(vm,'qmp',side_effect=FileNotFoundError),patch.object(vm,'owned_qemu',side_effect=[4123,4123,None]),patch.object(vm.os,'kill') as kill,patch.object(vm.time,'sleep'):
            vm.stop()
        kill.assert_called_once_with(4123,signal.SIGTERM)
        self.assertFalse(self.ram.exists())

    def test_stop_timeout_retains_live_ram(self):
        with patch.object(vm,'owned_pid',return_value=None),patch.object(vm,'qmp',side_effect=FileNotFoundError),patch.object(vm,'owned_qemu',return_value=4123),patch.object(vm.os,'kill'),patch.object(vm.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'RAM retained'):vm.stop()
        self.assertEqual(self.ram.read_bytes(),b'keep-until-exit')

    def test_missing_qmp_reports_owned_process_as_starting(self):
        with patch.object(vm,'owned_pid',return_value=None),patch.object(vm,'qmp',side_effect=FileNotFoundError),patch.object(vm,'owned_qemu',return_value=4123),patch.object(vm,'selected_profile',return_value='en-GB'):
            self.assertEqual(vm.status()['qemu'],'starting')

    def test_pid_reuse_requires_same_owner_executable_and_workspace(self):
        (self.root/'vm/pid').write_text('4123')
        args=f'/opt/homebrew/bin/qemu-system-i386 -name BMW-NBT-Original -kernel {self.root}/vm/nbt-boot.elf'
        for uid,command,expected in [(os.getuid(),args,4123),(os.getuid()+1,args,None),(os.getuid(),'/bin/sleep 30',None),(os.getuid(),args.replace(str(self.root),'/different-workspace'),None)]:
            with self.subTest(uid=uid,command=command),patch.object(vm.subprocess,'check_output',return_value=f'{uid} {command}'):
                self.assertEqual(vm.owned_qemu(),expected)

if __name__=='__main__':unittest.main()
