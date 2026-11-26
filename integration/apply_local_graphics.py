#!/usr/bin/env python3
"""Integrate own extensions into an existing authorized local graphics bridge.
Upstream source and binaries are not copied into this repository.
"""
import argparse,datetime,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent

def insert_case(text,function,case):
    start=text.index(function);switch=text.index('switch (op)',start);opening=text.index('{',switch)+1
    # Existing opcode 145 from an earlier deployment is retained.
    if 'case 145:' in text[start:]:return text
    return text[:opening]+'\n'+case+'\n'+text[opening:]
def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    root=a.workspace.resolve();renderer=root/'NBT-Original/renderer'
    render=renderer/'render.c';validate=renderer/'validate.c'
    values={render:insert_case(render.read_text(),'static int execute(','''    case 145:
        if(!R.dma_attached||!R.dma.process||!id4_physical_texture_valid(p,L))return END_BREAK;
        id4_physical_texture_upload(R.dma.process,p);return RUN_ON;'''),
      validate:insert_case(validate.read_text(),'int glh_validate(','''    case 145:return id4_physical_texture_valid(p,L);''')}
    for path,header in [(render,'physical_texture_upload.h'),(validate,'physical_texture_validate.h')]:
        if values[path]!=path.read_text():values[path]='#include "'+header+'"\n'+values[path]
    if a.dry_run:print('Validated local integration targets:',render,validate);return
    backup=root/'.id4-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S')/'renderer';backup.mkdir(parents=True)
    for path,text in values.items():shutil.copy2(path,backup/path.name);path.write_text(text)
    for name in ['physical_texture_validate.h','physical_texture_upload.h']:shutil.copy2(HERE/name,renderer/name)
    target=root/'CarPlay-QNX-Native/src/physical_texture.c';target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(HERE/'physical_texture.c',target)
    print('Local graphics extension installed; rebuild the renderer and guest bridge next.')
if __name__=='__main__':main()
