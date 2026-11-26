"""Bounded SSH access to the two plugin directories and our transaction area."""
from __future__ import annotations
import base64,hashlib,ipaddress,json,os,re,shlex,socket,time,uuid
from pathlib import Path,PurePosixPath
import paramiko
from .payload import RT,PLUGIN,RW,CONTROL,InstallError

def quote(value):return shlex.quote(str(value))
def fingerprint(key):return 'SHA256:'+base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
def writable(path):
    if path in (RT,PLUGIN,CONTROL):return True
    return any(path.startswith(root+'/') for root in (RT,PLUGIN,CONTROL)) and '..' not in PurePosixPath(path).parts

def private_json(file:Path,value):
    file.parent.mkdir(parents=True,exist_ok=True)
    if os.name!='nt':file.parent.chmod(0o700)
    temp=file.with_name(file.name+'.tmp-'+uuid.uuid4().hex)
    try:
        with os.fdopen(os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w',encoding='utf-8') as out:
            json.dump(value,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
        temp.replace(file)
    finally:temp.unlink(missing_ok=True)

class PinnedKey(paramiko.MissingHostKeyPolicy):
    def __init__(self,expected):self.expected=expected
    def missing_host_key(self,client,hostname,key):
        actual=fingerprint(key)
        if self.expected and actual!=self.expected:raise InstallError('车机 SSH 身份与上次不同。请核对车辆；换车请在高级设置清除已记住的车机身份。')
        client.get_host_keys().add(hostname,key.get_name(),key)

class Remote:
    def __init__(self,host,password,expected=None,port=22):
        try:host=str(ipaddress.IPv4Address(host));port=int(port)
        except (ValueError,TypeError):raise InstallError('车机地址必须是有效的 IPv4 地址。')
        if not 1<=port<=65535:raise InstallError('SSH 端口无效。')
        self.host=host;self.port=port;self.client=paramiko.SSHClient();self.client.set_missing_host_key_policy(PinnedKey(expected))
        try:
            self.client.connect(host,port=port,username='root',password=password,look_for_keys=False,allow_agent=False,
                timeout=8,banner_timeout=15,auth_timeout=15)
        except InstallError:self.client.close();raise
        except paramiko.AuthenticationException:
            self.client.close();raise InstallError('root 密码不正确，或车机尚未允许 root SSH 登录。')
        except (OSError,paramiko.SSHException) as error:
            self.client.close();raise InstallError('无法连接车机。请检查 ENET 网线、车机地址、车辆供电和 SSH 是否已开通。') from error
        self.fingerprint=fingerprint(self.client.get_transport().get_remote_server_key());self.client.get_transport().set_keepalive(10)
    def close(self):self.client.close()
    def run(self,command,data=b'',timeout=60,max_output=16*1024*1024,check=True):
        channel=None
        try:
            channel=self.client.get_transport().open_session(timeout=10);channel.settimeout(timeout);channel.exec_command(command)
            for offset in range(0,len(data),32768):channel.sendall(data[offset:offset+32768])
            channel.shutdown_write();out=bytearray();err=bytearray();deadline=time.monotonic()+timeout
            while True:
                if channel.recv_ready():out.extend(channel.recv(65536))
                if channel.recv_stderr_ready():err.extend(channel.recv_stderr(65536))
                if len(out)+len(err)>max_output:raise InstallError('车机返回的数据超过允许大小，操作已停止。')
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():break
                if time.monotonic()>deadline:raise InstallError('车机响应超时，请保持供电和 ENET 连接。')
                time.sleep(.005)
            code=channel.recv_exit_status()
            if check and code:raise InstallError('车机操作未完成：'+(err or out).decode('utf-8','replace')[:300])
            return code,bytes(out),bytes(err)
        except InstallError:raise
        except (OSError,EOFError,paramiko.SSHException,AttributeError) as error:raise InstallError('与车机的连接中断。保留本地备份，恢复连接后检查上次安装。') from error
        finally:
            if channel:channel.close()
    def exists(self,path):return self.run('test -e '+quote(path),check=False)[0]==0
    def is_dir(self,path):return self.run('test -d '+quote(path),check=False)[0]==0
    def read(self,path,max_bytes=16*1024*1024):return self.run('cat '+quote(path),max_output=max_bytes)[1]
    def mkdir(self,path):
        if not writable(path):raise InstallError('拒绝创建非插件目录。')
        self.run('mkdir -p '+quote(path)+' && chmod 700 '+quote(path))
    def put(self,data,target,mode=0o600):
        if not writable(target) or not isinstance(mode,int) or not 0<=mode<=0o777:raise InstallError('拒绝写入非插件目录或异常权限。')
        temp=target+'.id4-tmp'
        self.run('cat > '+quote(temp),data)
        if self.read(temp,max(len(data)+1024,8192))!=data:
            self.run('rm -f '+quote(temp),check=False);raise InstallError('车机文件回读不一致，未替换原文件。')
        self.run('chmod '+oct(mode)[2:]+' '+quote(temp)+' && mv '+quote(temp)+' '+quote(target))
    def walk(self,root):
        if root not in (RT,PLUGIN):raise InstallError('备份目录无效。')
        if not self.exists(root):return []
        if self.run('test -L '+quote(root),check=False)[0]==0:raise InstallError('插件目录是符号链接，未继续操作。')
        if not self.is_dir(root):raise InstallError('插件目录被其他文件占用。')
        # Shell glob includes hidden entries and does not follow links.
        command='''walk(){ for p in "$1"/* "$1"/.[!.]* "$1"/..?*; do
 test -e "$p" || test -L "$p" || continue
 if test -L "$p"; then echo "L $p"
 elif test -d "$p"; then echo "D $p"; walk "$p"
 elif test -f "$p"; then echo "F $p"
 else echo "X $p"; fi
done; }; walk '''+quote(root)
        rows=self.run(command,max_output=1024*1024)[1].decode('utf-8','strict').splitlines();files=[]
        if len(rows)>3000:raise InstallError('插件目录文件过多，无法安全备份。')
        for line in rows:
            kind,sep,path=line.partition(' ')
            if not sep or not path.startswith(root+'/') or '..' in PurePosixPath(path).parts or any(ord(c)<32 for c in path):raise InstallError('备份目录含无法识别的文件名。')
            if kind in ('L','X'):raise InstallError('插件目录含符号链接或特殊文件，请先人工检查。')
            if kind=='D':continue
            if kind!='F':raise InstallError('备份目录返回格式异常。')
            permissions=self.run('ls -ld '+quote(path),max_output=8192)[1].decode('utf-8','replace').split()[0]
            if len(permissions)<10 or permissions[0]!='-':raise InstallError('无法读取备份文件权限。')
            mode=0
            for i,char in enumerate(permissions[1:10]):
                if char in 'rwx':mode|=1<<(8-i)
                elif char!='-':raise InstallError('备份目录含特殊权限，请先人工检查。')
            files.append((path,mode))
        return files
    def free_bytes(self):
        text=self.run('df -k '+quote(RW),max_output=32768)[1].decode('ascii','replace')
        for line in reversed(text.splitlines()):
            parts=line.split()
            for i,item in enumerate(parts):
                if item.endswith('%') and i and parts[i-1].isdigit():return int(parts[i-1])*1024
        raise InstallError('无法确认车机剩余空间，未写入安装文件。')
    def identity(self):
        info=self.run('uname -s; uname -m; uname -r; id -u',max_output=4096)[1].decode('ascii','replace').split()
        if len(info)!=4 or info[0]!='QNX' or info[1].lower() not in ('x86','x86pc','i386','i486','i586','i686') or not info[2].startswith('6.5'):
            raise InstallError('当前主机不符合原始 NBT / QNX 6.5 x86 要求。CIC、NBT Evo、ID5/ID6 不支持此安装器。')
        if info[3]!='0':raise InstallError('需要 root SSH 权限。')
        for path in (RW, RW+'/Plugins', RT, PLUGIN, CONTROL):
            if self.run('test -L '+quote(path),check=False)[0]==0:
                raise InstallError('车机数据或插件目录存在符号链接，未继续写入。')
        required=[('test -d '+quote(RW),'NBT HMI 数据目录'),
            ('test -x /opt/mm/bin/NmeCmdLine','原始 NBT 视频组件'),
            ('test -f /opt/mm/lib/cinemo/cinemo_classes.xml','原始 NBT Cinemo 配置'),
            ('test -e /dev/i2c/i2c_0/acp','原车 Apple 认证芯片接口')]
        for command,label in required:
            if self.run(command,check=False)[0]:raise InstallError('未找到'+label+'，未写入车辆。')
        if self.run('test -d /opt/hmi/ID5 -o -d /var/opt/hmi/data/rw/Plugins/NbtAad',check=False)[0]==0:
            raise InstallError('检测到 NBT Evo 或另一套 Android Auto 插件，请先确认主机并处理冲突。')
        return {'system':info[0],'architecture':info[1],'qnx_version':info[2],'model':'原始 HU_NBT','fingerprint':self.fingerprint}
    def quiet_services(self):
        # Only this project's processes; never stop HmiMain3D, io-nme or stock services.
        for name in ['native_service','nbt_carplay','nbt_decoder','nbt_cluster','nbt_knob','nbt_aa_wms','nbt_aa_ipod','nbt_ipod_tap','nbt_a2i_play']:
            self.run('slay -f -Q -s TERM '+name,check=False,max_output=8192)
        time.sleep(1)
    def clone(self,source,target):
        if source not in (RT,PLUGIN) or not writable(target) or not target.startswith(CONTROL+'/'):raise InstallError('暂存路径无效。')
        self.mkdir(target)
        if self.exists(source):self.run('cp -Rp '+quote(source+'/.')+' '+quote(target+'/'),timeout=120)
    def acquire(self,token):
        if not re.fullmatch('[0-9a-f]{32}',token):raise InstallError('事务标识无效。')
        self.mkdir(CONTROL)
        code,_,_=self.run('mkdir '+quote(CONTROL+'/lock')+' && printf %s '+quote(token)+' > '+quote(CONTROL+'/lock/owner'),check=False)
        if code:raise InstallError('检测到另一项安装或上次未完成的操作。请勿重复安装，使用“检查/恢复上次操作”。')
    def release(self,token):
        if self.exists(CONTROL+'/lock/owner') and self.read(CONTROL+'/lock/owner').decode()==token:
            self.run('rm -f '+quote(CONTROL+'/lock/owner')+'; rmdir '+quote(CONTROL+'/lock'),check=False)
    def exec_script(self,path):
        if not path.startswith(CONTROL+'/') or not writable(path):raise InstallError('事务脚本路径无效。')
        return self.run('sh '+quote(path),timeout=120)
