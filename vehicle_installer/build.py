"""Build on the target OS; PyInstaller does not cross-compile executables."""
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
NAME='ID4-CarPlay-Installer'


def main():
    assets=ROOT/'build'/'installer-assets';assets.mkdir(parents=True,exist_ok=True)
    picture=Image.new('RGBA',(1024,1024),(0,0,0,0));draw=ImageDraw.Draw(picture)
    draw.rounded_rectangle((50,50,974,974),radius=210,fill='#10232F')
    draw.rounded_rectangle((190,260,834,700),radius=80,outline='#66E2C7',width=40)
    draw.line((300,790,724,790),fill='#66E2C7',width=38)
    draw.line((512,700,512,790),fill='#66E2C7',width=38)
    draw.polygon([(443,368),(443,598),(641,483)],fill='#FFFFFF')
    extension='icns' if sys.platform=='darwin' else 'ico'
    icon=assets/('installer.'+extension);picture.save(icon)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed',
             '--name',NAME,'--paths',str(ROOT),'--icon',str(icon),
             '--add-data',str(ROOT/'vehicle_installer'/'release-lock.json')+os.pathsep+'vehicle_installer']
    for dependency in ['paramiko','cryptography','bcrypt','PyNaCl','cffi','certifi','pyinstaller']:
        command+=['--copy-metadata',dependency]
    command+=['--add-data',str(ROOT/'LICENSE')+os.pathsep+'licenses',
              '--add-data',str(ROOT/'NOTICE.md')+os.pathsep+'licenses',
              '--add-data',str(ROOT/'vehicle_installer'/'README.md')+os.pathsep+'licenses',
              '--add-data',str(ROOT/'vehicle_installer'/'licenses')+os.pathsep+'licenses/third-party']
    candidates=[Path(sys.base_prefix)/'LICENSE.txt',Path(sysconfig.get_path('stdlib'))/'LICENSE.txt']
    python_license=next((p for p in candidates if p.is_file()),None)
    if not python_license:raise SystemExit('Missing Python distribution license; refusing to package.')
    destination=assets/'Python-LICENSE.txt';shutil.copyfile(python_license,destination)
    command+=['--add-data',str(destination)+os.pathsep+'licenses/third-party']
    if sys.platform=='darwin':
        command+=['--onedir','--osx-bundle-identifier','io.github.ch549235962.id4carplayinstaller']
    elif sys.platform=='win32':command+=['--onefile']
    else:raise SystemExit('Build this desktop application on macOS or Windows.')
    subprocess.run(command+[str(ROOT/'vehicle_installer'/'launch.py')],cwd=ROOT,check=True)
    if sys.platform=='darwin':
        import plistlib
        app=ROOT/'dist'/(NAME+'.app');file=app/'Contents'/'Info.plist'
        with file.open('rb') as input:plist=plistlib.load(input)
        plist.update(CFBundleShortVersionString='0.2.2',CFBundleVersion='4',
                     NSLocalNetworkUsageDescription='通过 ENET 连接您的 BMW NBT，安装和备份 CarPlay 插件。',
                     NSHighResolutionCapable=True)
        # Homebrew's current Tcl build can require the host major macOS release.
        import platform
        plist['LSMinimumSystemVersion']=platform.mac_ver()[0].split('.')[0]+'.0'
        with file.open('wb') as output:plistlib.dump(plist,output)
        subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
        subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
        archive=ROOT/'dist'/'ID4-CarPlay-macOS-AppleSilicon.zip'
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(archive)],check=True)
        print(archive)
    else:print(ROOT/'dist'/(NAME+'.exe'))


if __name__=='__main__':main()
