#!/usr/bin/env python3
"""Compile an authorized external bridge source plus this project's extension."""
from pathlib import Path
import hashlib,io,json,subprocess,sys,tarfile
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'NBT-Dev/src/BMW-NBT-Emulator/work/bridge-v2/guest'
sys.path.insert(0,str(ROOT.parent/'NBT-Dev-Cross/tools'))
from linux_vm import ssh_args
names=['rt.c','virtio.c','dma.c','link.c','gles.c','egl.c','stubs.c','input.c','keyboard.c','physical_texture.c']
(ROOT/'logs').mkdir(exist_ok=True);(ROOT/'build').mkdir(exist_ok=True)
if not SOURCE.is_dir():raise SystemExit('Supply an authorized local emulator bridge checkout first.')
buf=io.BytesIO()
with tarfile.open(fileobj=buf,mode='w') as archive:
    for p in SOURCE.iterdir():
        if p.suffix in ['.c','.h']:archive.add(p,arcname=p.name)
    archive.add(ROOT/'src/physical_texture.c',arcname='physical_texture.c')
subprocess.run(ssh_args()+['mkdir -p native-carplay/graphics_bridge; tar -xf - -C native-carplay/graphics_bridge'],input=buf.getvalue(),check=True)
flags='-std=gnu99 -march=pentium4 -msse2 -mstackrealign -ffreestanding -fno-builtin -fno-stack-protector -nostdlib -fPIC -O2 -shared -fvisibility=hidden -fno-asynchronous-unwind-tables -fno-unwind-tables -Wl,--hash-style=sysv -Wl,-z,norelro -Wl,-soname,libnbtgl.so'
command='export QNX_HOST=$HOME/qnx650/host/linux/x86 QNX_TARGET=$HOME/qnx650/target/qnx6; cd native-carplay/graphics_bridge; $HOME/tools/nto-gcc.py '+flags+' '+' '.join(names)+' -o libnbtgl.so'
subprocess.run(ssh_args()+[command],check=True,timeout=90)
symbols=subprocess.check_output(ssh_args()+['$HOME/qnx650/host/linux/x86/usr/bin/ntox86-nm -D --undefined-only native-carplay/graphics_bridge/libnbtgl.so'],text=True)
assert '__sync_' not in symbols and '__atomic_' not in symbols and '__stack_chk' not in symbols,symbols
data=subprocess.check_output(ssh_args()+['cat native-carplay/graphics_bridge/libnbtgl.so'])
assert data[:7]==b'\x7fELF\x01\x01\x01'
(ROOT/'build/libnbtgl.so').write_bytes(data)
report={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'opcode':145,'decode_location':'QNX','scope':'local emulator only'}
(ROOT/'logs/physical-bridge-build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
