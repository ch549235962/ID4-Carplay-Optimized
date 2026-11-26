#!/usr/bin/env python3
"""Install this source overlay into an existing local NBT development workspace."""
import argparse,datetime,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    workspace=args.workspace.resolve()
    for rel in ['NBT-Original/vm/selected-profile.json','NBT-Original/profiles/zh-CN-carplay-load/manifest.json','NBT-Dev-Cross/tools/linux_vm.py']:
        if not (workspace/rel).is_file():raise SystemExit('Missing existing runtime prerequisite: '+rel)
    files=json.loads((ROOT/'package-files.json').read_text());plan=[]
    for folder,names in files.items():
        for name in names:
            src=ROOT/'runtime'/folder/name;dst=workspace/folder/name
            if not src.is_file():raise SystemExit('Missing package source: '+str(src))
            if not dst.resolve().is_relative_to(workspace):raise SystemExit('Target resolves outside the selected workspace')
            plan.append((src,dst))
    if args.dry_run:print('Validated',len(plan),'source files; no files changed.');return
    # A running VM owns a live RAM file: stop using the desktop launcher first.
    if (workspace/'NBT-Original/vm/ram.bin').exists():raise SystemExit('Please click 全部停止 in the desktop launcher before deploying.')
    backup=workspace/'.id4-backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');backup.mkdir(parents=True)
    for src,dst in plan:
        rel=dst.relative_to(workspace)
        if dst.exists():saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,saved)
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    for rel in ['NBT-Launcher/backend.json','NBT-Original/vm/carplay-backend.json']:
        dst=workspace/rel
        if not dst.exists():dst.write_text(json.dumps({'backend':'macplay-usb'}))
    print('Source overlay installed. Backup:',backup)
    print('Follow docs/DEPLOYMENT.md to integrate and rebuild the local native profile.')
if __name__=='__main__':main()
