#!/opt/homebrew/bin/python3.13
"""Manage MacPlay USB/wireless transport adapted to the NBT QNX guest."""
from pathlib import Path
import argparse,contextlib,fcntl,functools,hashlib,io,json,os,plistlib,signal,stat,subprocess,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent
RES=Path('/Applications/MacPlay.app/Contents/Resources')
EXEC=RES/'runtime/MacPlayReceiver.app/Contents/MacOS/MacPlayReceiver'
ENTRY=ROOT/'engine/main.js'
PID=ROOT/'receiver.pid'
FIFO=ROOT/'commands.fifo'
TRANSPORT=ROOT/'transport.json'
INTENT=ROOT/'service-intent.json'
SUPERVISOR=ROOT/'tools/supervisor.py'
sys.path[:0]=[str(BASE/'CarPlay-QNX-Native/tools'),str(BASE/'NBT-Original/tools')]
import nbt_guest,native_hid,nbt_vm
import video_profile
import wireless_profile
from prepare_engine import prepare

def command(pid):
    return subprocess.run(['/bin/ps','-p',str(pid),'-o','args='],capture_output=True,text=True).stdout
def running():
    try:
        pid=int(PID.read_text());args=command(pid)
        return pid if str(EXEC) in args and str(ENTRY) in args else None
    except (OSError,ValueError):return None
def supervisor_running():
    try:
        pid=int((ROOT/'supervisor.pid').read_text())
        return pid if str(SUPERVISOR) in command(pid) else None
    except (OSError,ValueError):return None
def write_intent(enabled):
    p=INTENT.with_suffix('.tmp');p.write_text(json.dumps({'enabled':enabled,'mode':selected_mode(),'updated_at':time.time()}));p.chmod(0o600);p.replace(INTENT)
def ensure_supervisor():
    write_intent(True)
    if not supervisor_running():
        with (ROOT/'logs/supervisor.log').open('ab') as log:
            child=subprocess.Popen(['/opt/homebrew/bin/python3.13',str(SUPERVISOR)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        (ROOT/'supervisor.pid').write_text(str(child.pid))
def serialized(fn):
    @functools.wraps(fn)
    def wrapped(*args,**kwargs):
        ROOT.mkdir(exist_ok=True)
        with (ROOT/'receiver-operation.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('CarPlay 正在启动或停止，请稍候')
            return fn(*args,**kwargs)
    return wrapped
def builtin_tools_available():
    try:
        nbt=BASE/'NBT-Original'
        identity=json.loads((nbt/'vm/boot-identity.json').read_text())
        if identity['pid']!=int((nbt/'vm/pid').read_text()) or identity['profile']!='zh-CN-carplay-native':return False
        p=Path(identity['image']);info=p.stat()
        if info.st_size!=identity['size'] or info.st_mtime_ns!=identity['mtime_ns']:return False
        hashes=json.loads((nbt/'profiles/zh-CN-carplay-native/manifest.json').read_text())['native_tool_hashes']
        return all(hashes[name]==hashlib.sha256((BASE/'CarPlay-QNX-Native/build'/name).read_bytes()).hexdigest() for name in ['native_decoder','native_hid'])
    except (OSError,ValueError,KeyError):return False
def http(url):
    try:
        with urllib.request.urlopen(url,timeout=2) as f:return json.load(f)
    except (OSError,ValueError):return {}
def selected_mode():
    try:mode=json.loads(TRANSPORT.read_text()).get('mode','usb')
    except FileNotFoundError:mode='usb'
    if mode not in ['usb','wireless']:raise RuntimeError('Invalid MacPlay transport mode')
    return mode
def settings_for_mode(original,legacy,mode,fps=30):
    settings=dict(original)
    if type(fps)is not int or fps not in (30,60):raise RuntimeError('视频帧率只支持 30 或 60 FPS')
    settings.update(wireless=mode=='wireless',resolution='custom',width=1280,height=480,fps=fps)
    if mode=='wireless':
        if not legacy.get('bt_address') or not legacy.get('wifi_ssid'):raise RuntimeError('请先配置测试 iPhone 的蓝牙地址和 Wi-Fi 名称。')
        bt=legacy['bt_address'].replace('-',':').lower()
        settings.update(targetBluetooth=bt,targetUSB=None,selectedPhone=bt,lastPhone=bt,
            ssid=legacy['wifi_ssid'],password=legacy.get('wifi_passphrase',''),
            channel=legacy.get('wifi_channel',48),wifiInterface='en0',networkInterfaceMode='manual')
        if not settings['password']:raise RuntimeError('Saved Wi-Fi password is unavailable')
    return settings
def set_mode(mode):
    if mode not in ['usb','wireless']:raise RuntimeError('Invalid MacPlay transport mode')
    if selected_mode()!=mode and running():stop()
    for p,data in [(TRANSPORT,{'mode':mode}),
        (BASE/'NBT-Launcher/backend.json',{'backend':'macplay-'+mode}),
        (BASE/'NBT-Original/vm/carplay-backend.json',{'backend':'macplay-'+mode})]:
        tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(p)
    return {'selected_transport':mode}
def wireless_diagnostic():
    original=Path.home()/'Library/Application Support/MacPlay/settings.json'
    legacy_file=BASE/'CarPlay-Wireless/config-private.json'
    legacy=json.loads(legacy_file.read_text()) if legacy_file.exists() else {}
    settings=settings_for_mode(json.loads(original.read_text()),legacy,'wireless')
    return wireless_profile.diagnostic(settings['targetBluetooth'],settings)
def status():
    return {'receiver_running':bool(running()),'supervisor_running':bool(supervisor_running()),'receiver':http('http://127.0.0.1:8878/api/status') if running() else {},
            'controls':http('http://127.0.0.1:8877/status') if running() else {}}
def stop_standalone():
    # Stop only MacPlay's known receiver executable, not its GUI or other Node apps.
    rows=subprocess.run(['/bin/ps','-axo','pid=,uid=,args='],capture_output=True,text=True).stdout.splitlines()
    for row in rows:
        fields=row.strip().split(None,2)
        if len(fields)!=3:continue
        pid,uid,args=int(fields[0]),int(fields[1]),fields[2]
        if uid!=os.getuid() or not args.startswith(str(EXEC)+' ') or str(ENTRY) in args:continue
        os.kill(pid,signal.SIGTERM)
        for _ in range(60):
            if str(EXEC) not in command(pid):break
            time.sleep(.1)
        else:raise RuntimeError('Standalone MacPlay receiver is still stopping')
def stop_legacy_input():
    pid=nbt_vm.owned_pid('carplay-input')
    if pid:
        os.kill(pid,signal.SIGTERM)
        for _ in range(40):
            if not nbt_vm.owned_pid('carplay-input'):break
            time.sleep(.1)
        else:raise RuntimeError('Previous input relay is still stopping')
@serialized
def start(supervise=True):
    if running():
        if supervise:ensure_supervisor()
        return status()
    ROOT.mkdir(exist_ok=True);(ROOT/'logs').mkdir(exist_ok=True)
    app=plistlib.loads((RES.parent/'Info.plist').read_bytes())
    if app.get('CFBundleShortVersionString')!='1.2.4':raise RuntimeError('MacPlay version changed; adaptation requires review')
    prepare()
    builtin=builtin_tools_available()
    if not builtin:
        native_hid.ensure()
        check=nbt_guest.run('test -x /var/tmp/nbt-native/native_decoder',timeout=8)
        if check.returncode:
            nbt_guest.upload(BASE/'CarPlay-QNX-Native/build/native_decoder','/var/tmp/nbt-native/native_decoder')
            nbt_guest.run('chmod 700 /var/tmp/nbt-native/native_decoder',timeout=8).check_returncode()
    stop_legacy_input();stop_standalone()
    import native_video
    if native_video.running():
        with contextlib.redirect_stdout(io.StringIO()):native_video.stop()
    for port in [8877,8878,17000]:
        import socket
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    original=Path.home()/'Library/Application Support/MacPlay'
    legacy_file=BASE/'CarPlay-Wireless/config-private.json'
    legacy=json.loads(legacy_file.read_text()) if legacy_file.exists() else {}
    settings=settings_for_mode(json.loads((original/'settings.json').read_text()),legacy,selected_mode(),video_profile.config()['target_fps'])
    if settings['wireless']:
        settings=wireless_profile.apply(settings,wireless_profile.snapshot())
    profile=ROOT/'settings-private.json';profile.write_text(json.dumps(settings,ensure_ascii=False,indent=2));profile.chmod(0o600)
    if FIFO.exists() and not stat.S_ISFIFO(FIFO.stat().st_mode):raise RuntimeError('Unexpected command FIFO path')
    if not FIFO.exists():os.mkfifo(FIFO,0o600)
    env=os.environ.copy();env.update(MACPLAY_RESOURCES=str(RES),MACPLAY_DATA=str(original),
        MACPLAY_SETTINGS_PATH=str(profile),MACPLAY_ATTEMPT='NBT-QNX',MACPLAY_LANGUAGE='zh-Hans',
        DYLD_LIBRARY_PATH=str(RES/'gstreamer/macos-arm64/lib'),PATH='/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')
    env['NBT_QNX_BUILTIN_TOOLS']='1' if builtin else '0'
    env['NBT_QNX_DEFER_VIDEO_UNTIL_HMI']='1' if builtin and not nbt_vm.status().get('controller_ready') else '0'
    fd=os.open(FIFO,os.O_RDWR|os.O_NONBLOCK)
    try:
        with (ROOT/'logs/receiver.log').open('ab') as log:
            os.chmod(log.name,0o600)
            child=subprocess.Popen([str(EXEC),str(ENTRY)],env=env,stdin=fd,stdout=log,stderr=log,start_new_session=True)
    finally:os.close(fd)
    PID.write_text(str(child.pid))
    for _ in range(80):
        if child.poll() is not None:raise RuntimeError('MacPlay NBT engine exited; inspect MacPlay-NBT/logs/receiver.log')
        s=status()
        if s['receiver'] and (builtin or s['controls'].get('native_hid_ready')):
            if supervise:ensure_supervisor()
            return s
        time.sleep(.2)
    raise RuntimeError('MacPlay NBT input service is not ready')
@serialized
def stop():
    write_intent(False)
    supervisor=supervisor_running()
    if supervisor and supervisor!=os.getpid():os.kill(supervisor,signal.SIGTERM)
    pid=running()
    if pid:
        try:
            fd=os.open(FIFO,os.O_WRONLY|os.O_NONBLOCK)
            try:os.write(fd,b'stop\n')
            finally:os.close(fd)
        except OSError:os.kill(pid,signal.SIGTERM)
        for _ in range(60):
            if not running():break
            time.sleep(.1)
        if running():os.kill(pid,signal.SIGTERM)
        for _ in range(30):
            if not running():break
            time.sleep(.1)
        if running():raise RuntimeError('MacPlay NBT engine is still stopping')
    with contextlib.suppress(Exception):nbt_guest.run('/boot/native/native_video_ctl hide',timeout=6)
    return status()
if __name__=='__main__':
    os.umask(0o077);p=argparse.ArgumentParser();p.add_argument('action',choices=['start','stop','status','mode','wireless-check']);p.add_argument('mode',nargs='?',choices=['usb','wireless']);a=p.parse_args()
    if a.action=='mode':
        if not a.mode:p.error('mode requires usb or wireless')
        result=set_mode(a.mode)
    else:result={'start':start,'stop':stop,'status':status,'wireless-check':wireless_diagnostic}[a.action]()
    print(json.dumps(result,ensure_ascii=False,indent=2))
