"""Exercise actual Paramiko channels against a local, throwaway SSH server."""
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
import paramiko
from vehicle_installer.payload import CONTROL, RW, InstallError
from vehicle_installer.remote import Remote, fingerprint
from test_installer import SHELL


class LocalServer(paramiko.ServerInterface):
    def __init__(self,folder):self.folder=folder
    def check_auth_password(self,username,password):
        return paramiko.AUTH_SUCCESSFUL if (username,password)==('root','TEST-ONLY') else paramiko.AUTH_FAILED
    def get_allowed_auths(self,username):return 'password'
    def check_channel_request(self,kind,channel_id):return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
    def check_channel_exec_request(self,channel,command):
        def execute():
            try:
                data=bytearray()
                while chunk:=channel.recv(32768):data.extend(chunk)
                command_text=command.decode().replace(RW,(self.folder/'rw').as_posix())
                result=subprocess.run([SHELL,'-c',command_text],input=data,capture_output=True,timeout=10)
                if result.stdout:channel.sendall(result.stdout)
                if result.stderr:channel.sendall_stderr(result.stderr)
                channel.send_exit_status(result.returncode)
            finally:channel.close()
        threading.Thread(target=execute,daemon=True).start()
        return True


class SSHTests(unittest.TestCase):
    def test_real_password_auth_exec_binary_transfer_and_pin(self):
        key=paramiko.RSAKey.generate(2048)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'rw').mkdir()
            listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(10)
            transports=[];ready=threading.Event()
            def serve():
                try:
                    connection,_=listener.accept();transport=paramiko.Transport(connection);transports.append(transport)
                    transport.add_server_key(key);transport.start_server(server=LocalServer(root));ready.set()
                    while transport.is_active():
                        channel=transport.accept(timeout=.2)
                        # Transport retains active channels; exec callback handles their lifetime.
                except (OSError,EOFError,paramiko.SSHException):pass
            server=threading.Thread(target=serve,daemon=True);server.start()
            remote=None
            try:
                remote=Remote('127.0.0.1','TEST-ONLY',fingerprint(key),listener.getsockname()[1])
                self.assertEqual(remote.fingerprint,fingerprint(key))
                remote.mkdir(CONTROL)
                binary=bytes(range(256))*2048
                remote.put(binary,CONTROL+'/binary',0o700)
                self.assertEqual(remote.read(CONTROL+'/binary'),binary)
                with self.assertRaisesRegex(InstallError,'超过'):remote.run('cat '+CONTROL+'/binary',max_output=100)
                with self.assertRaises(InstallError):remote.run('exit 7')
                self.assertEqual(remote.run('printf success')[1],b'success')
            finally:
                if remote:remote.close()
                for transport in transports:transport.close()
                listener.close();server.join(timeout=2)
