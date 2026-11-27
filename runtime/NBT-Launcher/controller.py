#!/opt/homebrew/bin/python3.13
"""Local lifecycle controller. Never emits receiver tokens or pairing secrets."""
import argparse, contextlib, fcntl, io, json, os, signal, subprocess, sys, time
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
NBT = BASE / 'NBT-Original'
NATIVE = BASE / 'CarPlay-QNX-Native'
WIRELESS = BASE / 'CarPlay-Wireless'
os.environ['PATH'] = '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'
for folder in [NBT / 'tools', NATIVE / 'tools', WIRELESS, BASE/'MacPlay-NBT/tools']:
    sys.path.insert(0, str(folder))
import nbt_vm, native_video, nbt_guest, native_hid
try:import wireless
except ImportError:
    from types import SimpleNamespace
    def legacy_unavailable():raise RuntimeError('旧版 PlayPort 接收端未安装，请使用 MacPlay 模式。')
    wireless=SimpleNamespace(running=lambda:None,stop=lambda:None,start=legacy_unavailable,url=legacy_unavailable)
import macplay_nbt

def macplay_backend():
    try:return json.loads((ROOT/'backend.json').read_text()).get('backend') in ['macplay-usb','macplay-wireless']
    except (OSError,ValueError):return False

def emit(**value):
    if globals().get('RECORD_EVENTS'):
        with (ROOT/'launcher-events.jsonl').open('a') as log:
            log.write(json.dumps(dict(time=time.strftime('%Y-%m-%dT%H:%M:%S%z'), **value), ensure_ascii=False)+'\n')
    try:
        print(json.dumps(value, ensure_ascii=False), flush=True)
    except BrokenPipeError:
        pass

def quiet(fn):
    # Existing management utilities print authenticated URLs; keep them private.
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()

def http_json(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError):
        return {}

def status():
    vm = nbt_vm.status()
    receiver_pid = macplay_nbt.running() if macplay_backend() else wireless.running()
    receiver = http_json('http://127.0.0.1:8878/api/status') if receiver_pid else {}
    controls = http_json('http://127.0.0.1:8877/status')
    result = dict(vm_running=vm.get('qemu') == 'running',
                  viewer_running=vm.get('viewer_running', False),
                  renderer_running=vm.get('renderer_running', False),
                  receiver_running=bool(receiver_pid),
                  receiver_ready=bool(receiver),
                  video_bridge_running=bool(receiver_pid) if macplay_backend() else bool(native_video.running()),
                  controls_running=bool(controls.get('running')) if macplay_backend() else bool(nbt_vm.owned_pid('carplay-input')),
                  controls_ready=controls.get('ready', False),
                  native_hid_ready=controls.get('native_hid_ready', False),
                  metrics_running=bool(nbt_vm.owned_pid('video-metrics')),
                  phone_connected=bool(receiver.get('sessionActive')),
                  controller_ready=vm.get('controller_ready', False))
    result['supervisor_running']=bool(macplay_nbt.supervisor_running()) if macplay_backend() else False
    guest=(http_json('http://127.0.0.1:8876/metrics').get('guest') or {}) if vm.get('language_profile')=='zh-CN-carplay-native' else None
    result['hmi_running']=(bool(guest.get('hmi_threads',0)>0) if guest.get('age_seconds',999)<5 else None) if guest is not None else result['controller_ready']
    result['hmi_health']='unknown' if result['hmi_running'] is None else ('running' if result['hmi_running'] else 'stopped')
    result['controller_ready']=result['controller_ready'] and result['hmi_running'] is not False
    result['services_running'] = all(result[k] for k in [
        'vm_running', 'viewer_running', 'renderer_running', 'receiver_ready',
        'video_bridge_running', 'controls_running', 'native_hid_ready', 'metrics_running']) and result['hmi_running'] is not False
    result['backend']=('MacPlay '+macplay_nbt.selected_mode()+' -> QNX') if macplay_backend() else 'PlayPort wireless -> QNX'
    return result

def auxiliaries():
    for name, command in [
        ('video-metrics', ['/opt/homebrew/bin/python3.13', str(NBT/'tools/video_metrics.py')]),
        ('carplay-input', ['/opt/homebrew/bin/node', str(NBT/'tools/carplay_input.mjs')])]:
        if name=='carplay-input' and macplay_backend():continue
        if not nbt_vm.owned_pid(name):
            with (NBT/'logs'/f'{name}.log').open('ab') as log:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                         stderr=log, start_new_session=True)
            (NBT/'vm'/f'{name}.pid').write_text(str(child.pid))

def stop_video():
    pid = native_video.running()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(60):
            if not native_video.running():
                break
            time.sleep(.1)
        if native_video.running():
            raise RuntimeError('视频桥接未能停止，请查看日志。')

def start():
    began=time.monotonic()
    emit(message='正在启动 NBT 虚拟机…')
    current = nbt_vm.status()
    if macplay_backend() and current.get('qemu')=='running':
        guest=http_json('http://127.0.0.1:8876/metrics').get('guest') or {}
        fresh=guest.get('age_seconds',999)<5
        hmi_stopped=fresh and guest.get('guest_ns',0)>60_000_000_000 and guest.get('hmi_threads')==0
        low_memory=fresh and not macplay_nbt.running() and guest.get('ram_valid') and guest.get('ram_free_bytes',0)<32*1024*1024
        if hmi_stopped or low_memory:
            emit(message='HMI 已退出，正在恢复本地虚拟机…' if hmi_stopped else 'QNX 可用内存不足，正在按原配置重启虚拟机…')
            macplay_nbt.stop()
            stop_video();quiet(nbt_vm.stop);current=nbt_vm.status()
    if not all([current.get('qemu') == 'running', current.get('renderer_running'), current.get('viewer_running')]):
        stop_video()
    quiet(nbt_vm.start)
    auxiliaries()
    if macplay_backend():
        emit(message='正在准备 MacPlay '+('无线' if macplay_nbt.selected_mode()=='wireless' else 'USB')+' → QNX 连接…')
        builtin=macplay_nbt.builtin_tools_available()
        if not builtin and not macplay_nbt.running():
            deadline=time.monotonic()+100
            while True:
                try:
                    check=nbt_guest.run('/boot/native/native_video_ctl',timeout=7)
                    if check.returncode==0 and 'ready' in json.loads(check.stdout):break
                except (OSError,ValueError,subprocess.TimeoutExpired):pass
                if time.monotonic()>deadline:raise RuntimeError('QNX 启动超时，可稍后重新开启。')
                time.sleep(1)
        if wireless.running():quiet(wireless.stop)
        macplay_nbt.start()
        state=status()
        if not state['receiver_ready']:raise RuntimeError('MacPlay/QNX 部分服务尚未就绪。')
        emit(message='接收服务已启动，QNX 将继续初始化画面和旋钮。' if not state['controller_ready'] else '服务已就绪。',elapsed_seconds=round(time.monotonic()-began,2))
        return state
    emit(message='正在启动无线 CarPlay 接收服务…')
    quiet(wireless.start)
    if not http_json('http://127.0.0.1:8878/api/status'):
        raise RuntimeError('CarPlay 接收服务尚未就绪，请查看日志后重试。')
    emit(message='正在等待 QNX 就绪并连接视频通道…')
    deadline = time.monotonic() + 100
    while True:
        try:
            check = nbt_guest.run('/boot/native/native_video_ctl', timeout=7)
            # Shared video memory appears only after the first phone frame.
            # A valid ctl response proves SSH/QNX readiness even without a phone.
            if check.returncode == 0 and 'ready' in json.loads(check.stdout):
                break
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('QNX 启动超时；服务已保留，可稍后再点开启。')
        time.sleep(1)
    emit(message='正在准备 QNX 原生旋钮与触控编码器…')
    native_hid.ensure()
    if native_video.running():
        check = nbt_guest.run('test -x /var/tmp/nbt-native/native_decoder', timeout=8)
        if check.returncode:
            nbt_guest.upload(NATIVE/'build/native_decoder', '/var/tmp/nbt-native/native_decoder')
            nbt_guest.run('chmod 700 /var/tmp/nbt-native/native_decoder', timeout=8).check_returncode()
    quiet(native_video.start)
    for _ in range(20):
        if http_json('http://127.0.0.1:8877/status').get('native_hid_ready'):
            break
        time.sleep(.5)
    state = status()
    if not state['services_running']:
        raise RuntimeError('部分服务未就绪；请查看日志后重试开启。')
    return state

def stop():
    # Continue cleanup if one component fails; never touch system Bluetooth.
    failures = []
    for message, function in [
        ('正在停止视频通道…', macplay_nbt.stop if macplay_backend() else stop_video),
        ('正在停止 CarPlay 接收服务…', lambda: quiet(wireless.stop)),
        ('正在关闭 NBT 虚拟机…', lambda: quiet(nbt_vm.stop))]:
        emit(message=message)
        try:
            function()
        except (Exception, SystemExit) as exc:
            failures.append(str(exc))
    state = status()
    if any(state[k] for k in ['vm_running', 'viewer_running', 'renderer_running',
                              'receiver_running', 'video_bridge_running', 'controls_running', 'metrics_running']):
        failures.append('仍有项目服务运行')
    if failures:
        raise RuntimeError('；'.join(failures))
    return state

def open_pages(target='both'):
    if target not in ['nbt','carplay','both']:raise RuntimeError('无效网页目标')
    urls=[]
    if target in ['nbt','both']:urls.append('http://127.0.0.1:8876/')
    if target in ['carplay','both']:urls.append('http://127.0.0.1:8878/' if macplay_backend() else wireless.url())
    chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    if chrome.exists():
        # Explicit --new-window also works when Chrome has no existing window;
        # LaunchServices URL dispatch on this Mac otherwise returns without one.
        with (ROOT/'browser-open.log').open('ab') as log:
            subprocess.Popen([str(chrome), '--new-window', *urls],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)
    else:
        subprocess.run(['/usr/bin/open', *urls], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    emit(message={'nbt':'已打开 NBT 网页。','carplay':'已打开 CarPlay 状态页。','both':'已打开 NBT 和 CarPlay 两个网页。'}[target])

def main():
    global RECORD_EVENTS
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'reconnect', 'status', 'open', 'open-nbt', 'open-carplay','usb','wireless'])
    args = parser.parse_args()
    RECORD_EVENTS = args.action != 'status'
    if args.action == 'status':
        emit(ok=True, state=status()); return
    with (ROOT/'operation.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit(ok=False, error='另一项启动或停止操作正在进行，请稍候。'); return
        if args.action == 'start':
            state = start()
        elif args.action == 'stop':
            state = stop()
        elif args.action == 'reconnect':
            emit(message='正在重新连接 CarPlay，保留蓝牙配对…')
            if macplay_backend():macplay_nbt.stop()
            else:quiet(wireless.stop)
            state = start()
        elif args.action in ['usb','wireless']:
            if args.action=='wireless':
                report=macplay_nbt.wireless_diagnostic()
                if not report['paired_phone_found']:raise RuntimeError('未找到保存的 iPhone 配对记录，请先配对手机。')
                emit(message='正在切换无线测试；请拔下 iPhone 的 USB 数据线，保持 Wi-Fi 和蓝牙开启。')
            macplay_nbt.set_mode(args.action)
            state=start()
        else:
            state = status()
        if args.action in ['open','open-nbt','open-carplay']:
            open_pages({'open':'both','open-nbt':'nbt','open-carplay':'carplay'}[args.action])
        emit(ok=True, state=state)

if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (Exception, SystemExit) as exc:
        # Avoid subprocess command strings, which could contain credentials.
        message = str(exc) if isinstance(exc, RuntimeError) else '操作失败（'+type(exc).__name__+'），请查看服务日志。'
        emit(ok=False, error=message)
        sys.exit(1)
