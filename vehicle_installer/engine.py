"""Installation orchestration. No firmware partitions or stock HMI files are written."""
from __future__ import annotations
import contextlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from . import gateway
from .backup import Snapshot, MARKER, latest_snapshot
from .payload import RT, PLUGIN, RW, CONTROL, InstallError, obtain_package
from .remote import Remote, private_json, quote as q
from .transaction import commit_script, rollback_script


@contextlib.contextmanager
def local_lock(root):
    file = (root / 'operation.lock').open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            file.seek(0); file.write(b'0'); file.flush(); file.seek(0)
            try: msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError: raise InstallError('另一窗口正在操作车机，请先完成该操作。')
        else:
            import fcntl
            try: fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError: raise InstallError('另一窗口正在操作车机，请先完成该操作。')
        yield
    finally:
        file.close()


class Installer:
    def __init__(self, root: Path, progress=lambda *_: None, remote_factory=Remote):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.progress = progress
        self.remote_factory = remote_factory

    def connect(self, host, password, port):
        key = f'{host}:{port}'
        known_file = self.root / 'known-headunits.json'
        known = json.loads(known_file.read_text('utf-8')) if known_file.exists() else {}
        self.progress('正在连接并识别车机', .03)
        remote = self.remote_factory(host, password, known.get(key), port)
        try:
            identity = remote.identity()
            if known.get(key) != identity['fingerprint']:
                known[key] = identity['fingerprint']; private_json(known_file, known)
            return remote, identity
        except Exception:
            remote.close(); raise

    def check(self, host, password, port=22):
        with local_lock(self.root):
            remote, identity = self.connect(host, password, port)
            try:
                free = remote.free_bytes()
                version = remote.read(RT+'/VERSION', 1024).decode('ascii', 'replace').strip() if remote.exists(RT+'/VERSION') else '尚未安装'
                pending = remote.exists(CONTROL+'/lock')
                self.progress('连接检查完成', 1)
                return {'message': f"已识别：{identity['model']} / QNX {identity['qnx_version']} {identity['architecture']}\n"
                        f"当前插件：{version}\n剩余空间：{free//1048576} MB\n"
                        + ('存在未完成操作，请使用“恢复上次安装前备份”。' if pending else 'SSH、视频组件和 Apple 认证接口检查通过。'),
                        'identity': identity}
            finally: remote.close()

    def operate(self, host, password, port=22, gateway_ip='', offline=None, restore=False):
        if gateway_ip: gateway_ip = gateway.ipv4(gateway_ip)
        with local_lock(self.root):
            # Download before opening a vehicle connection; errors here never write to the vehicle.
            package = None if restore else obtain_package(self.root/'cache', self.progress, offline)
            remote, identity = self.connect(host, password, port)
            try:
                source = latest_snapshot(self.root/'backups', identity['fingerprint']) if restore else None
                if remote.exists(CONTROL+'/lock'):
                    if not restore: raise InstallError('有上次未完成的操作。请先使用“恢复上次安装前备份”，不要重复安装。')
                    source = self.pending_snapshot(remote, identity)
                existing = {root: remote.exists(root) for root in (RT, PLUGIN)}
                # Enumerate first to reject symbolic links or special files before any mutation.
                listing = [item for root in (RT, PLUGIN) for item in remote.walk(root)]
                old_size = sum(len(remote.read(path)) for path, _ in listing)
                new_size = sum(len(e.data) for e in package.entries) if package else sum(len(v[0]) for v in source.files.values())
                if remote.free_bytes() < old_size+new_size+16*1024*1024:
                    raise InstallError('车机空间不足：需要容纳暂存文件并保留至少 16 MB 余量，未开始安装。')
                token = uuid.uuid4().hex
                self.progress('正在创建安装前备份', .12)
                backup = Snapshot.create(remote, self.root/'backups', identity, token,
                    lambda title, fraction: self.progress(title, .12+.12*fraction))
                if restore and remote.exists(CONTROL+'/lock'):
                    # pending_snapshot already proved ownership, inactivity, and a complete matching backup.
                    remote.release(source.metadata['transaction'])
                tx = CONTROL+'/'+token
                wanted = source.metadata['existing'] if restore else {RT: True, PLUGIN: True}
                state = {'schema': 1, 'token': token, 'identity': identity, 'backup': str(backup.directory),
                         'existing': existing, 'wanted': wanted, 'phase': 'staging', 'created_at': time.time()}
                local_state = self.root/'operations'/(token+'.json')
                activation_started = False
                safe_to_unlock = False
                acquired = False
                try:
                    remote.mkdir(tx)
                    self.state(remote, tx, state, local_state)
                    remote.acquire(token)
                    acquired = True
                    remote.quiet_services()
                    remote.run('test -d '+q(RW+'/Plugins')+' || mkdir '+q(RW+'/Plugins'))
                    self.progress('正在暂存完整插件', .27)
                    for label, root in [('r', RT), ('p', PLUGIN)]:
                        if not wanted[root]: continue
                        stage = tx+'/new-'+label
                        if restore: remote.mkdir(stage)
                        else: remote.clone(root, stage)
                        remote.run('chmod '+('700' if root == RT else '755')+' '+q(stage))
                    if restore:
                        files = source.files
                    else:
                        files = {e.target: (e.data, e.mode) for e in package.entries}
                    for i, (target, (data, mode)) in enumerate(files.items()):
                        stage_target = self.stage_path(tx, target)
                        remote.mkdir(stage_target.rsplit('/', 1)[0])
                        remote.put(data, stage_target, mode)
                        self.progress('正在传输并回读校验：'+target.rsplit('/', 1)[1], .28+.38*(i+1)/max(1,len(files)))
                    # mkdir above is private by default; the HMI plugin root must stay traversable.
                    if wanted[PLUGIN]: remote.run('chmod 755 '+q(tx+'/new-p'))
                    if not restore:
                        stage = tx+'/new-r'
                        remote.put((package.version+'\n').encode(), stage+'/VERSION', 0o644)
                        if not remote.exists(stage+'/vid.dpi'): remote.put(b'100\n', stage+'/vid.dpi', 0o644)
                        if not remote.exists(RT+'/nbt_decoder') and not remote.exists(stage+'/decoder.hw') and not remote.exists(stage+'/decoder.off'):
                            remote.put(b'', stage+'/decoder.hw', 0o644)
                        remote.run('rm -f '+q(stage+'/disabled'))
                        if not gateway_ip and remote.exists(stage+'/gateway'):
                            try: gateway_ip = gateway.ipv4(remote.read(stage+'/gateway',1024).decode('ascii').strip())
                            except (InstallError, UnicodeError): pass
                        if not gateway_ip:
                            self.progress('正在查找车辆重启网关', .68)
                            gateway_ip = gateway.discover(host) or ''
                        if gateway_ip: remote.put((gateway_ip+'\n').encode(), stage+'/gateway', 0o644)
                    for label, root in [('r', RT), ('p', PLUGIN)]:
                        if wanted[root]: remote.put(token.encode(), tx+'/new-'+label+'/'+MARKER)
                    remote.put(commit_script(tx, existing, wanted), tx+'/activate.sh', 0o700)
                    self.progress('正在激活已校验的插件，请保持连接', .74)
                    state['phase'] = 'activating'; self.state(remote, tx, state, local_state)
                    activation_started = True
                    remote.exec_script(tx+'/activate.sh')
                    self.progress('正在核对安装结果', .82)
                    try:
                        for target, (data, _) in files.items():
                            if remote.read(target, max(len(data)+1024,8192)) != data:
                                raise InstallError('激活后的文件校验失败。')
                        for root in (RT, PLUGIN):
                            if wanted[root]:
                                if remote.read(root+'/'+MARKER,1024).decode() != token: raise InstallError('安装目录标识不一致。')
                            elif remote.exists(root): raise InstallError('恢复后的目录状态不一致。')
                    except Exception:
                        remote.put(rollback_script(tx, existing, wanted, token), tx+'/rollback.sh', 0o700)
                        remote.exec_script(tx+'/rollback.sh')
                        raise InstallError('安装结果校验失败，已恢复原插件。保持供电，重启 iDrive 后可重试。')
                    state['phase'] = 'verified'; self.state(remote, tx, state, local_state)
                    safe_to_unlock = True
                except Exception as error:
                    if not activation_started:
                        safe_to_unlock = True
                        state['phase'] = 'staging-failed'
                    else:
                        try:
                            phase = remote.read(tx+'/phase', 1024).decode().strip()
                            safe_to_unlock = phase == 'rolled-back'
                        except Exception: pass
                        state['phase'] = 'rolled-back' if safe_to_unlock else 'recovery-required'
                    private_json(local_state, state)
                    if activation_started and not safe_to_unlock:
                        raise InstallError('连接中断或激活未完成，不能确认车机状态。请保持车辆供电，重新连接后使用“恢复上次安装前备份”。\n备份：'+str(backup.directory)) from error
                    raise
                finally:
                    if safe_to_unlock and acquired: remote.release(token)
                self.progress('文件安装已完成，正在请求车辆网关重启', .93)
                message = '已恢复安装前备份。' if restore else f'已安装 JayJay CarPlay {package.version}，全部文件回读校验通过。'
                if restore and not gateway_ip and remote.exists(RT+'/gateway'):
                    try: gateway_ip = gateway.ipv4(remote.read(RT+'/gateway',1024).decode('ascii').strip())
                    except (InstallError, UnicodeError): pass
                if not gateway_ip: gateway_ip = gateway.discover(host) or ''
                if gateway_ip:
                    try:
                        gateway.reset(gateway_ip)
                        message += '\n车辆网关已接受重启请求。请等待 iDrive 重新启动；尚未确认手机连接效果。'
                    except InstallError as error: message += '\n'+str(error)
                else:
                    message += '\n未找到重启网关。请在车辆允许的条件下，长按音量旋钮约 30 秒重启 iDrive。'
                message += '\n本次操作前备份：'+str(backup.directory)
                self.progress('操作完成', 1)
                return {'message': message, 'backup': str(backup.directory), 'identity': identity}
            finally: remote.close()

    @staticmethod
    def stage_path(tx, target):
        for label, root in [('r', RT), ('p', PLUGIN)]:
            if target.startswith(root+'/'): return tx+'/new-'+label+target[len(root):]
        raise InstallError('文件不属于受管理的插件目录。')

    @staticmethod
    def state(remote, tx, state, local_state):
        private_json(local_state, state)
        remote.put(json.dumps(state, ensure_ascii=False).encode(), tx+'/state.json')

    def pending_snapshot(self, remote, identity):
        token = remote.read(CONTROL+'/lock/owner', 1024).decode()
        if not re.fullmatch('[0-9a-f]{32}', token): raise InstallError('上次安装锁格式异常，请保留现状并导出日志。')
        tx = CONTROL+'/'+token
        state = json.loads(remote.read(tx+'/state.json', 32768))
        if state.get('identity',{}).get('fingerprint') != identity['fingerprint'] or state.get('token') != token:
            raise InstallError('上次事务身份不匹配，未恢复。')
        if remote.exists(tx+'/pid'):
            pid = remote.read(tx+'/pid', 1024).decode().strip()
            if not pid.isdigit() or remote.run('kill -0 '+pid, check=False)[0] == 0:
                raise InstallError('车机上的安装脚本仍在运行。请等待完成后再恢复，勿重复写入。')
        for folder in (self.root/'backups').iterdir():
            try:
                backup = Snapshot.read(folder, identity['fingerprint'])
                if backup.metadata['transaction'] == token: return backup
            except (OSError, ValueError, KeyError, InstallError): continue
        raise InstallError('当前电脑没有上次事务对应的完整备份，不能自动恢复。请使用原安装电脑。')
