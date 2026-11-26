"""The upstream HSFZ/ZGW identification and ECU 0x63 diagnostic reset protocol."""
import ipaddress,socket,struct,time
from .payload import InstallError
IDENTIFY=bytes.fromhex('000000000011')
RESET=bytes.fromhex('000000040001f4631101')

def ipv4(value):
    try:return str(ipaddress.IPv4Address(value))
    except ValueError:raise InstallError('网关地址必须是有效的 IPv4 地址。')

def discover(host,timeout=2.0):
    probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:probe.connect((host,9));local=probe.getsockname()[0]
    except OSError:return None
    finally:probe.close()
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1);sock.bind((local,0));sock.settimeout(timeout)
        broadcast='169.254.255.255' if local.startswith('169.254.') else '255.255.255.255'
        sock.sendto(IDENTIFY,(broadcast,6811));deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            sock.settimeout(max(.1,deadline-time.monotonic()));data,sender=sock.recvfrom(1024)
            if len(data)<6 or sender[0]==host or sender[0].startswith('127.'):continue
            length,control=struct.unpack('>IH',data[:6])
            if length!=len(data)-6 or control!=0x11 or b'DIAGADR' not in data or b'BMWVIN' not in data:continue
            if local.startswith('169.254.') and not sender[0].startswith('169.254.'):continue
            return ipv4(sender[0])
    except OSError:return None
    finally:sock.close()

def receive_exact(sock,count):
    data=bytearray()
    while len(data)<count:
        part=sock.recv(count-len(data))
        if not part:raise InstallError('网关连接关闭，尚未确认重启。')
        data.extend(part)
    return bytes(data)

def reset(address,timeout=5):
    address=ipv4(address)
    try:
        with socket.create_connection((address,6801),timeout=timeout) as sock:
            sock.settimeout(timeout);sock.sendall(RESET)
            for _ in range(8):
                length,control=struct.unpack('>IH',receive_exact(sock,6))
                if not 2<=length<=256:raise InstallError('网关回应长度异常，尚未确认重启。')
                body=receive_exact(sock,length)
                if control==2:continue
                if control==1 and len(body)>=4 and body[:4]==bytes.fromhex('63f45101'):return True
                if control==1 and len(body)>=5 and body[:4]==bytes.fromhex('63f47f11'):
                    if body[4]==0x78:continue
                    raise InstallError('网关拒绝重启请求：'+body[4:5].hex())
            raise InstallError('网关未确认重启。安装内容已校验，请手动重启 iDrive。')
    except OSError as error:raise InstallError('无法通过车辆网关确认重启，请手动重启 iDrive。') from error
