#!/opt/homebrew/bin/python3.13
"""Measure incoming, QNX decoded and presented frames using host wall time.

Optional balanced rotary input keeps the UI active without selecting anything.
No screenshot, browser launch, system reset or duplicate-frame generation.
"""
import argparse,json,time,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def get(port,path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=4) as response:return json.load(response)

def rotate(step):
    request=urllib.request.Request('http://127.0.0.1:8877/action',
        data=json.dumps({'action':'rotate','steps':step}).encode(),
        headers={'Origin':'http://127.0.0.1:8876','Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)

def sample():
    controls=get(8877,'/status');metrics=get(8876,'/metrics')
    keys=['pid','connection','session_active','ready','received_frames','forwarded_frames','decoded_frames',
          'displayed_frames','decoder_recoveries','messages_sent','last_error']
    return {'controls':{k:controls.get(k) for k in keys},'renderer':metrics.get('renderer'),
        'guest':metrics.get('guest'),'guest_time_ratio':metrics.get('guest_time_ratio'),
        'processes':metrics.get('processes'),'configuration':metrics.get('configuration')}

def direct_counters():
    # The QNX collector sleeps in guest time, which may run slower than wall
    # time. Read shared counters directly at the endpoints of a benchmark.
    import nbt_guest
    before=time.monotonic();result=nbt_guest.run('/boot/native/native_video_ctl',timeout=6)
    result.check_returncode()
    return (before+time.monotonic())/2,json.loads(result.stdout)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=15)
    parser.add_argument('--drive',action='store_true');parser.add_argument('--label',default='video-rate')
    parser.add_argument('--drive-interval',type=float,default=.5)
    args=parser.parse_args()
    if not 3<=args.seconds<=60 or not args.label.replace('-','').replace('_','').isalnum():parser.error('Invalid duration or label')
    if not .1<=args.drive_interval<=5:parser.error('Drive interval must be between 0.1 and 5 seconds')
    first=sample();initial=first['controls']
    if not initial['ready'] or not initial['session_active']:raise RuntimeError('Phone session is not ready')
    first_at,first_qnx=direct_counters()
    start=time.monotonic();next_action=start;next_sample=start;actions=0;samples=[]
    try:
        while time.monotonic()-start<args.seconds:
            now=time.monotonic()
            if args.drive and now>=next_action:
                rotate(1 if actions%2==0 else -1);actions+=1;next_action=now+args.drive_interval
            if now>=next_sample:
                current=sample();state=current['controls']
                if state['pid']!=initial['pid'] or not state['session_active']:raise RuntimeError('Receiver/session changed during measurement')
                current['elapsed']=round(now-start,3);samples.append(current);next_sample=now+.5
            time.sleep(.01)
    finally:
        if actions%2:rotate(-1);actions+=1
    last=sample();elapsed=time.monotonic()-start
    last_at,last_qnx=direct_counters();qnx_elapsed=last_at-first_at
    rates={k:round((last['controls'][k]-initial[k])/elapsed,2)
           for k in ['received_frames','forwarded_frames','decoded_frames','displayed_frames']}
    rates['decoded_frames']=round((last_qnx['decoded']-first_qnx['decoded'])/qnx_elapsed,2)
    rates['displayed_frames']=round((last_qnx['rendered']-first_qnx['rendered'])/qnx_elapsed,2)
    report={'label':args.label,'measured_seconds':round(elapsed,3),'connection':initial['connection'],
            'requested_fps':get(8878,'/api/status')['display']['fps'],'rates':rates,
            'balanced_rotary_actions':actions,'session_preserved':True,
            'decoder_recoveries':last['controls']['decoder_recoveries']-initial['decoder_recoveries'],
            'guest_time_ratio':last['guest_time_ratio'],'configuration':last['configuration'],
            'qnx_counter_basis':'direct shared-memory counters; host monotonic time',
            'qnx_window_seconds':round(qnx_elapsed,3),
            'renderer_errors':{k:(last['renderer'] or {}).get(k) for k in ['decode_errors','display_errors']},
            'samples':samples}
    report['session_preserved']=last['controls']['pid']==initial['pid'] and bool(last['controls']['session_active'])
    report['hmi_running']=all((s.get('guest') or {}).get('hmi_threads',0)>0 and (s.get('guest') or {}).get('age_seconds',999)<5 for s in [first,*samples,last])
    report['qnx_counters']={'first':first_qnx,'last':last_qnx}
    report['counter_errors']={key:last_qnx[key]-first_qnx[key] for key in ['errors','render_errors']}
    report['measurement_valid']=report['session_preserved'] and report['decoder_recoveries']==0 and all(rate>=0 for rate in rates.values()) and rates['displayed_frames']>0 and report['hmi_running'] and all(value==0 for value in report['counter_errors'].values())
    if not report['measurement_valid']:
        report['diagnostic_rates']=rates
        report['rates']=None
        report['invalid_reason']='Session/counters changed, errors occurred, HMI health was absent/stale, or presentation did not advance; no successful display-FPS result.'
    folder=ROOT/'logs';folder.mkdir(exist_ok=True)
    file=folder/(args.label+'.json');file.write_text(json.dumps(report,ensure_ascii=False,indent=2));file.chmod(0o600)
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
