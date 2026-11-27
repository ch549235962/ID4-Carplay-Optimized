#!/opt/homebrew/bin/python3.13
"""Observe a local wireless/USB session past the stock HMI watchdog window.

Does not restart services or open a browser. Optional balanced rotary input
periodically checks the control path without selecting anything.
"""
import argparse,json,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'CarPlay-QNX-Native/tools'))
from verify_frame_rate import get,rotate
import nbt_guest

def watchdog():
    result=nbt_guest.run('sloginfo',timeout=10);result.check_returncode()
    text=result.stdout.decode(errors='replace') if isinstance(result.stdout,bytes) else result.stdout
    return sum('Missed CB' in line and 'SvcDSI' in line for line in text.splitlines())

def snapshot(start):
    controls=get(8877,'/status');metrics=get(8876,'/metrics')
    guest=metrics.get('guest') or {};renderer=metrics.get('renderer') or {}
    return dict(elapsed=round(time.monotonic()-start,3),
        receiver_pid=controls.get('pid'),session_active=controls.get('session_active'),
        controls_ready=controls.get('ready'),recoveries=controls.get('decoder_recoveries'),
        guest_ns=guest.get('guest_ns'),guest_age=guest.get('age_seconds',999),
        hmi_pid=guest.get('hmi_pid'),hmi_threads=guest.get('hmi_threads'),
        decoded=renderer.get('decoded_frames'),displayed=renderer.get('presented_frames'),
        decode_errors=renderer.get('decode_errors'),display_errors=renderer.get('display_errors'))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=float,default=300)
    parser.add_argument('--guest-seconds',type=float,default=240)
    parser.add_argument('--timeout',type=float,default=1200)
    parser.add_argument('--drive',action='store_true')
    args=parser.parse_args()
    if not 10<=args.seconds<=1800 or not 0<=args.guest_seconds<=600 or not args.seconds<=args.timeout<=2400:
        parser.error('Invalid observation duration')
    start=time.monotonic();first=snapshot(start)
    if not (first['controls_ready'] and first['hmi_threads'] and first['guest_age']<5):
        raise RuntimeError('Start with a ready phone session and fresh running HMI')
    vm=(ROOT.parent/'NBT-Original/vm/pid').read_text();missed=watchdog()
    report=dict(passed=False,samples=[first],rotary_actions=0,initial_watchdog_misses=missed)
    last_fresh=start;next_drive=start;next_note=start;failure=None
    try:
        while True:
            now=time.monotonic();s=snapshot(start);report['samples'].append(s)
            if (ROOT.parent/'NBT-Original/vm/pid').read_text()!=vm:raise RuntimeError('VM restarted')
            if s['receiver_pid']!=first['receiver_pid'] or not s['session_active']:raise RuntimeError('Phone session changed')
            if s['recoveries']!=first['recoveries']:raise RuntimeError('Decoder recovered during observation')
            if s['guest_age']<5:
                last_fresh=now
                if not s['hmi_threads'] or s['hmi_pid']!=first['hmi_pid']:raise RuntimeError('HMI exited or changed')
            if now-last_fresh>30:raise RuntimeError('HMI telemetry remained stale for 30 seconds')
            for key in ['decode_errors','display_errors']:
                if s[key] is not None and s[key]!=first[key]:raise RuntimeError('Video error count changed')
            if args.drive and now>=next_drive:
                rotate(1);report['rotary_actions']+=1
                try:time.sleep(.5)
                finally:rotate(-1);report['rotary_actions']+=1
                next_drive=now+15
            if now>=next_note:print(json.dumps(s),flush=True);next_note=now+30
            guest_seconds=(s['guest_ns']-first['guest_ns'])/1e9 if s['guest_ns'] is not None else 0
            if s['elapsed']>=args.seconds and guest_seconds>=args.guest_seconds and s['guest_age']<5:break
            if s['elapsed']>=args.timeout:raise RuntimeError('Observation deadline exceeded')
            time.sleep(2)
        report['final_watchdog_misses']=watchdog()
        if report['final_watchdog_misses']!=missed:raise RuntimeError('Stock HMI missed a heartbeat')
        if s['displayed']<=first['displayed']:raise RuntimeError('No display progress')
        report.update(passed=True,observed_seconds=s['elapsed'],observed_guest_seconds=round(guest_seconds,3),
                      telemetry_delayed_samples=sum(x['guest_age']>=5 for x in report['samples']))
    except Exception as error:
        failure=error;report['failure_type']=type(error).__name__
        report['failure']=str(error) if isinstance(error,RuntimeError) else 'Observation interrupted; inspect local services'
    finally:
        path=ROOT/'logs/startup-stability-soak.json'
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2));path.chmod(0o600)
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},ensure_ascii=False),flush=True)
    if failure:raise SystemExit(1)

if __name__=='__main__':main()
