#!/opt/homebrew/bin/python3.13
"""Compile the native HID encoder with the installed QNX 6.5 toolchain."""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'NBT-Dev-Cross/tools'))
from linux_vm import ssh_args
source=ROOT/'src/native_hid.c'
subprocess.run(ssh_args()+['mkdir -p native-carplay/hid; cat > native-carplay/hid/native_hid.c'],input=source.read_bytes(),check=True,timeout=20)
command='cd native-carplay/hid && $HOME/tools/nto-gcc.py -std=gnu99 -D_QNX_SOURCE -O2 -Wall -Wextra native_hid.c -lm -o native_hid'
result=subprocess.run(ssh_args()+[command],capture_output=True,timeout=120)
(ROOT/'logs/native-hid-build.log').write_bytes(result.stdout+result.stderr)
if result.returncode:raise SystemExit('QNX HID compilation failed; inspect logs/native-hid-build.log')
binary=subprocess.run(ssh_args()+['cat native-carplay/hid/native_hid'],capture_output=True,check=True,timeout=15).stdout
if binary[:7]!=b'\x7fELF\x01\x01\x01':raise SystemExit('Unexpected QNX binary format')
(ROOT/'build/native_hid').write_bytes(binary)
report={'bytes':len(binary),'sha256':hashlib.sha256(binary).hexdigest(),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
(ROOT/'logs/native-hid-build.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
