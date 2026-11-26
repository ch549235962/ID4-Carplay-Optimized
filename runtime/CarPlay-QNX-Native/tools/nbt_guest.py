#!/opt/homebrew/bin/python3.13
"""Pinned, loopback-only SSH access to the original NBT native-test profile."""
from pathlib import Path
import hashlib,subprocess
ROOT=Path(__file__).resolve().parents[1]
def ssh_args():
    return ['ssh','-F',str(ROOT/'build/nbt_ssh_config'),'-oBatchMode=yes','-oConnectTimeout=5','nbt-native']
def run(command,data=None,timeout=60):
    return subprocess.run(ssh_args()+['export PATH=/boot/bin; export LD_LIBRARY_PATH=/boot/lib; '+command],input=data,capture_output=True,timeout=timeout)
def upload(local,remote):
    if not remote.startswith('/var/tmp/nbt-native/') or any(c not in '/._-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' for c in remote):
        raise ValueError('Only safe paths in the native test directory are accepted')
    data=Path(local).read_bytes()
    p=run('umask 077; cat > '+remote,data)
    if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace'))
    check=run('cat '+remote)
    if check.returncode or check.stdout!=data:raise RuntimeError('Readback mismatch')
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'readback_verified':True}
