"""Checksummed, local-only backups bound to the head unit SSH identity."""
from __future__ import annotations
import hashlib,json,os,time,uuid,zipfile
from dataclasses import dataclass
from pathlib import Path,PurePosixPath
from .payload import RT,PLUGIN,InstallError
from .remote import private_json
MARKER='.id4-installer-token'
MAX_BACKUP=128*1024*1024

def validate_target(target):
    if not isinstance(target,str) or '..' in PurePosixPath(target).parts or any(ord(c)<32 for c in target):return False
    return target.startswith(RT+'/') or target.startswith(PLUGIN+'/')
def member_for(target):return ('rt'+target[len(RT):]) if target.startswith(RT+'/') else ('plugin'+target[len(PLUGIN):])

@dataclass
class Snapshot:
    directory:Path
    metadata:dict
    files:dict

    @classmethod
    def create(cls,remote,root:Path,identity:dict,token:str,progress=lambda *_:None):
        folder=root/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
        if os.name!='nt':folder.chmod(0o700)
        existing={RT:remote.exists(RT),PLUGIN:remote.exists(PLUGIN)}
        listing=[item for directory in (RT,PLUGIN) for item in remote.walk(directory) if PurePosixPath(item[0]).name!=MARKER]
        data_files={};records=[];total=0
        archive=folder/'backup.zip'
        with os.fdopen(os.open(archive,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as output:
            with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
                for i,(target,mode) in enumerate(listing):
                    if not validate_target(target):raise InstallError('备份文件超出插件目录。')
                    data=remote.read(target);total+=len(data)
                    if total>MAX_BACKUP:raise InstallError('插件及日志备份超过 128 MB，请先导出并清理旧日志。')
                    name=member_for(target);z.writestr(name,data)
                    records.append({'target':target,'member':name,'mode':mode,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()});data_files[target]=(data,mode)
                    progress('正在备份已有插件', (i+1)/max(1,len(listing)))
            output.flush();os.fsync(output.fileno())
        metadata={'schema':1,'complete':True,'transaction':token,'created_at':time.time(),'identity':identity,'existing':existing,'files':records}
        private_json(folder/'backup.json',metadata)
        return cls(folder,metadata,data_files)

    @classmethod
    def read(cls,folder:Path,expected_fingerprint:str):
        if (folder/'backup.json').stat().st_size>2*1024*1024:raise InstallError('备份清单过大。')
        meta=json.loads((folder/'backup.json').read_text(encoding='utf-8'))
        if meta.get('schema')!=1 or meta.get('complete') is not True or meta.get('identity',{}).get('fingerprint')!=expected_fingerprint:
            raise InstallError('备份不完整或不属于当前车机，未恢复。')
        if set(meta.get('existing',{}))!={RT,PLUGIN} or any(type(v)is not bool for v in meta['existing'].values()):raise InstallError('备份目录记录异常。')
        if len(meta.get('files',[]))>3000:raise InstallError('备份文件数量异常。')
        data_files={};total=0
        with zipfile.ZipFile(folder/'backup.zip') as z:
            members=z.infolist()
            if len(members)>3000 or sum(m.file_size for m in members)>MAX_BACKUP:raise InstallError('备份体积异常。')
            if len({m.filename for m in members})!=len(members) or {m.filename for m in members}!={e['member'] for e in meta['files']}:
                raise InstallError('备份文件清单不一致。')
            for entry in meta['files']:
                target=entry['target'];mode=entry['mode']
                if not validate_target(target) or target in data_files or entry['member']!=member_for(target) or type(mode)is not int or not 0<=mode<=0o777:
                    raise InstallError('备份目标或权限无效。')
                data=z.read(entry['member']);total+=len(data)
                if total>MAX_BACKUP or len(data)!=entry['size'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise InstallError('备份校验失败，未恢复。')
                data_files[target]=(data,mode)
        return cls(folder,meta,data_files)

def latest_snapshot(root:Path,fingerprint:str):
    if root.exists():
        for folder in sorted(root.iterdir(),reverse=True):
            if not (folder/'backup.json').is_file():continue
            try:return Snapshot.read(folder,fingerprint)
            except (InstallError,ValueError,KeyError,OSError,zipfile.BadZipFile):continue
    raise InstallError('本机没有属于当前车机的完整备份。请使用之前安装时的电脑或备份目录。')
