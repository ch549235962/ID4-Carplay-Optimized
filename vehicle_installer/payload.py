"""Pinned upstream package download and validation; no bundled credentials."""
from __future__ import annotations
import hashlib,json,os,ssl,stat,sys,urllib.request,zipfile
import certifi
from dataclasses import dataclass
from pathlib import Path,PurePosixPath

RT='/var/opt/hmi/data/rw/NbtAndroidAutoRT'
PLUGIN='/var/opt/hmi/data/rw/Plugins/NbtAndroidAuto'
RW='/var/opt/hmi/data/rw'
CONTROL=RW+'/.ID4CarPlayInstaller'
class InstallError(Exception):pass

def data_directory():
    if sys.platform=='win32':root=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))
    elif sys.platform=='darwin':root=Path.home()/'Library/Application Support'
    else:root=Path.home()/'.local/share'
    path=root/'ID4CarPlayInstaller';path.mkdir(parents=True,exist_ok=True)
    if os.name!='nt':path.chmod(0o700)
    return path

def load_lock():return json.loads(Path(__file__).with_name('release-lock.json').read_text(encoding='utf-8'))
def digest(data):return hashlib.sha256(data).hexdigest()

def safe_relative(name):
    p=PurePosixPath(name)
    if p.is_absolute() or not p.parts or any(part in ('..','.') for part in p.parts) or '\\' in name or any(ord(c)<32 for c in name):
        raise InstallError('安装包包含不安全的路径。')
    return p

@dataclass(frozen=True)
class Entry:
    source:str
    target:str
    mode:int
    data:bytes

@dataclass(frozen=True)
class Package:
    version:str
    sha256:str
    entries:tuple[Entry,...]

    @classmethod
    def read(cls,file:Path,lock=None):
        lock=lock or load_lock()
        if file.stat().st_size>16*1024*1024:raise InstallError('安装包过大。请选择指定的约 2 MB 官方插件 ZIP，不要选择整车固件包。')
        with file.open('rb') as source:raw=source.read(16*1024*1024+1)
        if len(raw)>16*1024*1024 or digest(raw)!=lock['sha256']:raise InstallError('安装包校验失败，请重新下载指定的官方版本。')
        with zipfile.ZipFile(file) as archive:
            members=archive.infolist()
            if len(members)>300 or sum(m.file_size for m in members)>32*1024*1024:raise InstallError('安装包体积或文件数量异常。')
            names=set()
            for member in members:
                safe_relative(member.filename.rstrip('/'))
                if member.filename in names or stat.S_ISLNK(member.external_attr>>16):raise InstallError('安装包包含重复文件或符号链接。')
                names.add(member.filename)
            found=[m.filename for m in members if m.filename.endswith('/payload/manifest.json')]
            if len(found)!=1:raise InstallError('找不到唯一的安装清单。')
            manifest=json.loads(archive.read(found[0]));prefix=found[0][:-len('manifest.json')]
            if manifest.get('version')!=lock['version']:raise InstallError('安装包版本与已验证版本不一致。')
            expected={e['source']:e for e in lock['files']};seen=set();entries=[]
            for entry in manifest.get('files',[]):
                source=entry.get('source','');safe_relative(source)
                pinned=expected.get(source)
                if source in seen or not pinned or any(entry.get(k)!=pinned[k] for k in ['target','mode','size','sha256']):raise InstallError('安装清单与固定校验记录不一致。')
                target=entry['target']
                if not (target.startswith(RT+'/') or target.startswith(PLUGIN+'/')) or '..' in PurePosixPath(target).parts:raise InstallError('安装包试图写入非插件目录。')
                data=archive.read(prefix+source)
                if len(data)!=entry['size'] or digest(data)!=entry['sha256']:raise InstallError('安装文件校验失败：'+source)
                mode=int(entry['mode'],8)
                if mode not in (0o600,0o644,0o700,0o755):raise InstallError('安装文件权限异常。')
                entries.append(Entry(source,target,mode,data));seen.add(source)
            if seen!=set(expected):raise InstallError('安装包文件不完整。')
        return cls(manifest['version'],lock['sha256'],tuple(entries))

def obtain_package(cache:Path,progress=lambda *_:None,offline:Path|None=None):
    lock=load_lock();cache.mkdir(parents=True,exist_ok=True)
    if offline is not None:return Package.read(offline)
    file=cache/lock['asset']
    if file.exists():
        try:return Package.read(file)
        except (InstallError,zipfile.BadZipFile):file.unlink()
    part=file.with_suffix('.partial')
    request=urllib.request.Request(lock['url'],headers={'User-Agent':'ID4-CarPlay-Installer/0.2'})
    try:
        with urllib.request.urlopen(request,timeout=30,context=ssl.create_default_context(cafile=certifi.where())) as response,part.open('wb') as output:
            length=int(response.headers.get('Content-Length','0'));total=0
            while chunk:=response.read(65536):
                total+=len(chunk)
                if total>16*1024*1024:raise InstallError('官方安装包下载体积异常。')
                output.write(chunk);progress('正在下载官方安装包',total/max(length,total))
        package=Package.read(part);part.replace(file);return package
    except (OSError,zipfile.BadZipFile) as error:
        raise InstallError('无法准备官方安装包。请联网重试，或在高级设置选择已下载的官方 ZIP。') from error
    finally:part.unlink(missing_ok=True)
