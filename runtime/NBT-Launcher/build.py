#!/opt/homebrew/bin/python3.13
"""Build the desktop application using the local Apple command-line tools."""
import plistlib, shutil, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent
APP = ROOT/'NBT CarPlay 启动器.app'
DESKTOP = Path.home()/'Desktop/NBT CarPlay 启动器.app'
INFO = APP/'Contents/Info.plist'
if APP.exists():
    old = plistlib.loads(INFO.read_bytes()) if INFO.exists() else {}
    if old.get('CFBundleIdentifier') != 'local.nbt.carplay-launcher':
        raise SystemExit('Refusing to overwrite another desktop application')
MAC = APP/'Contents/MacOS'
MAC.mkdir(parents=True, exist_ok=True)
(APP/'Contents/Resources').mkdir(exist_ok=True)
subprocess.run(['/usr/bin/clang','-fobjc-arc','-framework','Cocoa',str(ROOT/'Icon.m'),
                '-o',str(ROOT/'make-icon')], check=True)
subprocess.run([str(ROOT/'make-icon'),str(ROOT/'Launcher.iconset')],check=True)
subprocess.run(['/usr/bin/iconutil','-c','icns',str(ROOT/'Launcher.iconset'),'-o',
                str(APP/'Contents/Resources/Launcher.icns')],check=True)
subprocess.run(['/usr/bin/clang','-fobjc-arc','-framework','Cocoa',str(ROOT/'Launcher.m'),
                '-o',str(MAC/'NbtLauncher')], check=True)
INFO.write_bytes(plistlib.dumps({
    'CFBundleIdentifier':'local.nbt.carplay-launcher',
    'CFBundleName':'NBT CarPlay 启动器',
    'CFBundleDisplayName':'NBT CarPlay 启动器',
    'CFBundleExecutable':'NbtLauncher',
    'CFBundlePackageType':'APPL',
    'CFBundleShortVersionString':'1.2',
    'CFBundleVersion':'3',
    'CFBundleIconFile':'Launcher.icns',
    'LSMinimumSystemVersion':'13.0',
    'NSHighResolutionCapable':True,
    'ControllerRoot':str(ROOT),
    'NSBluetoothAlwaysUsageDescription':'用于通过本机蓝牙连接你的测试 iPhone 并启动 CarPlay。',
    'NSLocalNetworkUsageDescription':'用于在同一 Wi-Fi 内连接 iPhone 的 CarPlay 视频和控制服务。',
    'NSDocumentsFolderUsageDescription':'用于启动保存在 Documents/Codex 内的 NBT 虚拟机及 CarPlay 服务。',
}))
for attribute in ['com.apple.FinderInfo', 'com.apple.ResourceFork']:
    subprocess.run(['/usr/bin/xattr', '-dr', attribute, str(APP)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(APP)], check=True)
subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(APP)], check=True)
if DESKTOP.is_symlink():
    if DESKTOP.resolve() != APP.resolve():
        raise SystemExit('Another desktop shortcut already exists')
elif DESKTOP.exists():
    old_info=DESKTOP/'Contents/Info.plist'
    old=plistlib.loads(old_info.read_bytes()) if old_info.exists() else {}
    if old.get('CFBundleIdentifier') != 'local.nbt.carplay-launcher':
        raise SystemExit('Refusing to replace another desktop application')
    shutil.rmtree(DESKTOP)
if not DESKTOP.is_symlink():
    DESKTOP.symlink_to(APP, target_is_directory=True)
print(DESKTOP)
