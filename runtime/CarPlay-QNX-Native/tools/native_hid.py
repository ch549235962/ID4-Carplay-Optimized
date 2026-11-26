#!/opt/homebrew/bin/python3.13
"""Install the native HID encoder into the guest's volatile test directory."""
from pathlib import Path
import hashlib,json
from nbt_guest import run,upload
ROOT=Path(__file__).resolve().parents[1]
def ensure():
    binary=ROOT/'build/native_hid'
    data=binary.read_bytes()
    check=run('cat /var/tmp/nbt-native/native_hid',timeout=10)
    installed=check.returncode==0 and check.stdout==data
    if not installed:
        upload(binary,'/var/tmp/nbt-native/native_hid.next')
        run('chmod 700 /var/tmp/nbt-native/native_hid.next && mv /var/tmp/nbt-native/native_hid.next /var/tmp/nbt-native/native_hid',timeout=10).check_returncode()
    return {'native_hid_installed':True,'uploaded':not installed,'sha256':hashlib.sha256(data).hexdigest()}
if __name__=='__main__':print(json.dumps(ensure()))
