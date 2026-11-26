#!/opt/homebrew/bin/python3.13
"""Compile native QNX decoder/display binaries using the pinned cross environment."""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'NBT-Dev-Cross/tools'))
from linux_vm import ssh_args

if __name__=='__main__':
    for name in ['native_video.h','native_decoder.c','native_overlay.c','native_video_ctl.c']:
        subprocess.run(ssh_args()+['cat > native-carplay/'+name],input=(ROOT/'src'/name).read_bytes(),check=True)
    command='''export QNX_HOST=$HOME/qnx650/host/linux/x86
export QNX_TARGET=$HOME/qnx650/target/qnx6
cd native-carplay
set -e
$HOME/tools/nto-gcc.py -std=gnu99 -O2 -Wall -Wextra -Iffmpeg-lib/include -Iffmpeg native_decoder.c ffmpeg-lib/libavcodec.a ffmpeg-lib/libavutil.a -lm -o native_decoder
$HOME/tools/nto-gcc.py -std=gnu99 -O2 -Wall -Wextra -shared -fPIC native_overlay.c -o libnative_overlay.so
$HOME/tools/nto-gcc.py -std=gnu99 -O2 -Wall -Wextra native_video_ctl.c -o native_video_ctl
'''
    r=subprocess.run(ssh_args()+[command],capture_output=True,timeout=120)
    (ROOT/'logs/native-video-build.log').write_bytes(r.stdout+r.stderr)
    print((r.stdout+r.stderr).decode(errors='replace'))
    if r.returncode:raise SystemExit(r.returncode)
    report={}
    for name in ['native_decoder','libnative_overlay.so','native_video_ctl']:
        r=subprocess.run(ssh_args()+['cat native-carplay/'+name],capture_output=True,check=True)
        assert r.stdout[:7]==b'\x7fELF\x01\x01\x01'
        (ROOT/'build'/name).write_bytes(r.stdout)
        report[name]={'bytes':len(r.stdout),'sha256':hashlib.sha256(r.stdout).hexdigest()}
    (ROOT/'logs/native-video-build.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
