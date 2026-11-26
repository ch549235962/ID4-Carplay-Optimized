"""Read current Mac radio identity without scanning, pairing or changing settings."""
import json,re,subprocess
MAC=re.compile(r'^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$',re.I)
SWIFT='''import Foundation
import IOBluetooth
import CoreWLAN
var value:[String:Any]=[:]
if let h=IOBluetoothHostController.default(),let a=h.addressAsString(){value["bluetooth_mac"]=a}
if let w=CWWiFiClient.shared().interface(){
 value["interface"]=w.interfaceName
 value["ssid"]=w.ssid()
 value["bssid"]=w.bssid()
 if let c=w.wlanChannel(){value["channel"]=c.channelNumber}
}
let data=try JSONSerialization.data(withJSONObject:value,options:[.sortedKeys])
print(String(data:data,encoding:.utf8)!)
'''
def snapshot():
    p=subprocess.run(['/usr/bin/swift','-e',SWIFT],capture_output=True,text=True,timeout=12)
    if p.returncode:raise RuntimeError('无法读取本机无线信息')
    value=json.loads(p.stdout)
    address=value.get('bluetooth_mac','').replace('-',':').lower()
    if not MAC.fullmatch(address):raise RuntimeError('本机蓝牙地址不可用，请确认蓝牙已开启')
    value['bluetooth_mac']=address
    return value

def apply(settings,probe):
    result=dict(settings)
    result['bluetoothMAC']=probe['bluetooth_mac']
    if probe.get('interface')!=result['wifiInterface']:
        raise RuntimeError('当前 Wi-Fi 与所选无线接口不一致')
    if isinstance(probe.get('channel'),int) and 1<=probe['channel']<=196:result['channel']=probe['channel']
    if probe.get('ssid') and probe['ssid']!=result['ssid']:
        raise RuntimeError('当前 Wi-Fi 与保存的手机 Wi-Fi 不一致，请先更新无线配置')
    if probe.get('bssid') and MAC.fullmatch(probe['bssid']):result['accessPointMAC']=probe['bssid'].lower()
    return result

def diagnostic(target,settings):
    probe=snapshot();effective=apply(settings,probe)
    data=json.loads(subprocess.check_output(['/usr/sbin/system_profiler','SPBluetoothDataType','-json'],text=True,timeout=15))
    paired=False;connected=False
    for controller in data.get('SPBluetoothDataType',[]):
        for group in ['device_connected','device_not_connected']:
            for row in controller.get(group,[]):
                for device in row.values():
                    if device.get('device_address','').replace('-',':').lower()==target.lower():
                        paired=True;connected=group=='device_connected'
    return {'interface':effective['wifiInterface'],'channel':effective['channel'],'ssid':effective['ssid'],
        'local_bluetooth_identity_valid':True,'paired_phone_found':paired,'bluetooth_currently_connected':connected,
        'ssid_readable':bool(probe.get('ssid')),'wifi_password_present':bool(effective.get('password')),
        'wireless_video_verified':False,'note':'蓝牙用于发现与认证，画面和音频通过 Wi-Fi；配对记录保留。'}
