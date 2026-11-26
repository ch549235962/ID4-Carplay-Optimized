"""Explicit local simulator video settings; resource sizing remains independent."""
import json
from pathlib import Path

SETTINGS=Path(__file__).resolve().parents[1]/'vm/video-profile.json'
DEFAULT={'target_fps':30}

def config(path=None):
    file=Path(path) if path is not None else SETTINGS
    value={**DEFAULT,**(json.loads(file.read_text()) if file.exists() else {})}
    if type(value['target_fps']) is not int or value['target_fps'] not in (30,60):
        raise ValueError('Video target must be 30 or 60 fps')
    if set(value)!={'target_fps'}:raise ValueError('Unknown local video setting')
    return value

if __name__=='__main__':
    import argparse,os,tempfile
    parser=argparse.ArgumentParser(description='Local NBT simulator video profile; stop services before changing.')
    parser.add_argument('--fps',type=int,choices=[30,60])
    args=parser.parse_args();value=config()
    if args.fps is not None:
        if (SETTINGS.parent/'ram.bin').exists():raise SystemExit('请先在桌面启动器点击“全部停止”，再更改视频配置。')
        if args.fps is not None:value['target_fps']=args.fps
        SETTINGS.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=SETTINGS.parent,delete=False) as file:
            temporary=Path(file.name);json.dump(value,file);file.flush();os.fsync(file.fileno())
        try:temporary.replace(SETTINGS)
        finally:temporary.unlink(missing_ok=True)
    print(json.dumps(value,ensure_ascii=False))
