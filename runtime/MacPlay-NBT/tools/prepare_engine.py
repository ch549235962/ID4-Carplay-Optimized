#!/opt/homebrew/bin/python3.13
"""Create a version-pinned, separate MacPlay engine adaptation; do not edit the app."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('/Applications/MacPlay.app/Contents/Resources/engine')
ENGINE=ROOT/'engine'
def patch(text,old,new):
    if text.count(old)!=1:raise RuntimeError('Unexpected MacPlay source version at '+old[:70])
    return text.replace(old,new,1)
def prepare():
    source_hash=hashlib.sha256((SOURCE/'main.js').read_bytes()).hexdigest()
    preparer_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest=ROOT/'engine-manifest.json'
    try:
        cached=json.loads(manifest.read_text())
        if cached.get('source_main_sha256')==source_hash and cached.get('preparer_sha256')==preparer_hash and hashlib.sha256((ENGINE/'main.js').read_bytes()).hexdigest()==cached['adapted_main_sha256']:
            return cached
    except (OSError,ValueError,KeyError):pass
    ENGINE.mkdir(parents=True,exist_ok=True)
    for p in SOURCE.iterdir():
        if p.name=='node_modules':
            link=ENGINE/p.name
            if not link.exists():link.symlink_to(p,target_is_directory=True)
        elif p.is_dir():shutil.copytree(p,ENGINE/p.name,dirs_exist_ok=True)
        else:shutil.copy2(p,ENGINE/p.name)
    for name in ['nbt_bridge.cjs','avc.cjs']:
        p=ENGINE/name
        if p.is_symlink():p.unlink()
        # Bridge root stays tools/.. even when required from the generated engine.
        p.symlink_to(ROOT/'tools'/name)
    main=(SOURCE/'main.js').read_text()
    main=patch(main,'hevc: true, h264: true','hevc: false, h264: true')
    # Original HMI initialization can exceed MacPlay's 45 s window. Keep the
    # phone session while QNX boots instead of cycling the receiver mid-boot.
    main=patch(main,'settings.fps >= 90 ? 25000 : 45000','120000')
    main=patch(main,'if (!stopping && !videoReady) {\n    disconnectReason = \'连接启动超时\';',
        'if (!stopping && !videoReady && settings.wireless) {\n    disconnectReason = \'连接启动超时\';')
    main=patch(main,'const settings = JSON.parse', '''const nbt = require('./nbt_bridge.cjs');
media_1.openScreenReceiver = () => 0; // use CpStack's compressed-stream event path
media_1.closeScreenReceiver = () => {};
media_1.pollVideoReady = () => nbt.pollDecoded();
media_1.showVideoWindow = () => {};
const nativeAddon = media_1.addon;
const bridgeAddon = Object.create(nativeAddon);
Object.defineProperties(bridgeAddon, {
 mediaActivity: {value: () => nbt.mediaActivity(nativeAddon.mediaActivity())},
 macplayPumpEvents: {value: () => []},
 macplayTakeWindowAction: {value: () => 0},
 macplayCloseVideoWindow: {value: () => {}}
});
media_1.addon = bridgeAddon;
nbt.onDecoded(() => media_1.onVideo?.());
const settings = JSON.parse''')
    main=patch(main,'const stack = new cpStack_1.CpStack(config);', '''const stack = new cpStack_1.CpStack(config);
    stack.on('video-codec', codec => nbt.setCodec(codec));
    stack.on('video-config', data => nbt.setConfiguration(data));
    stack.on('video-frame', data => nbt.receiveFrame(data));
    nbt.onKeyframe(() => active?.forceMainKeyframe());''')
    main=patch(main,'sessionReady = true;', 'sessionReady = true; nbt.setStack(stack, phoneInfo?.name, socket.remoteAddress);')
    main=patch(main,"stack.on('session-ended', () => {", "stack.on('session-ended', () => { nbt.clearStack(stack);")
    main=patch(main,"stack.on('connection-closed', () => {", "stack.on('connection-closed', () => { nbt.clearStack(stack);")
    main=patch(main,"stopping = true; discovery?.destroy();", "stopping = true; nbt.close(); discovery?.destroy();")
    main=main.replace('首帧已解码，CarPlay画面窗口已打开','首帧已由QNX解码，打开NBT网页查看')
    main=main.replace('已接收CarPlay视频，画面窗口已打开','CarPlay压缩视频已送入QNX')
    (ENGINE/'main.js').write_text(main)
    (ROOT/'UPSTREAM-LICENSE').write_bytes(Path('/Applications/MacPlay.app/Contents/Resources/LICENSE').read_bytes())
    report={'source':'Roylyl/MacPlay 1.2.4','source_main_sha256':hashlib.sha256((SOURCE/'main.js').read_bytes()).hexdigest(),
            'preparer_sha256':preparer_hash,
            'adapted_main_sha256':hashlib.sha256(main.encode()).hexdigest(),'installed_app_modified':False,
            'protocol':'MacPlay on Mac','video_decode':'QNX','hid_encode':'QNX','audio':'Mac'}
    (ROOT/'engine-manifest.json').write_text(json.dumps(report,indent=2));return report
if __name__=='__main__':print(json.dumps(prepare()))
