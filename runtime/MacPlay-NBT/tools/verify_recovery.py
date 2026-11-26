#!/opt/homebrew/bin/python3.13
"""Fault injection on owned local processes; keeps the QNX VM running."""
import json,os,signal,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'NBT-Launcher'));import controller

def state():
    with urllib.request.urlopen('http://127.0.0.1:8877/status',timeout=2) as f:return json.load(f)
def stream():return json.loads((ROOT.parent/'CarPlay-QNX-Native/logs/live-qnx-video.json').read_text())
def wait(fn,seconds=30):
    start=time.monotonic()
    while time.monotonic()-start<seconds:
        try:
            if fn():return round(time.monotonic()-start,3)
        except (OSError,ValueError,KeyError):pass
        time.sleep(.25)
    raise RuntimeError('Recovery readiness timed out')

def main():
    initial=state();assert initial['ready'] and initial['session_active']
    vm=int((ROOT.parent/'NBT-Original/vm/pid').read_text());receiver=controller.macplay_nbt.running();decoder=stream()['decoder_ssh_pid']
    command=controller.macplay_nbt.command(decoder)
    assert 'nbt-native' in command and 'native_decoder' in command
    os.kill(decoder,signal.SIGTERM)
    decoder_seconds=wait(lambda:stream()['decoder_ssh_pid'] not in [None,decoder] and state()['decoder_transport_ready'] and state()['decoded_frames']>5)
    assert controller.macplay_nbt.running()==receiver and int((ROOT.parent/'NBT-Original/vm/pid').read_text())==vm
    print('Decoder-only recovery',decoder_seconds,flush=True)
    os.kill(receiver,signal.SIGTERM)
    receiver_seconds=wait(lambda:controller.macplay_nbt.running() not in [None,receiver] and state()['ready'] and state()['session_active'] and state()['decoded_frames']>5,35)
    assert int((ROOT.parent/'NBT-Original/vm/pid').read_text())==vm
    result={'decoder_recovery_seconds':decoder_seconds,'decoder_failure_preserved_phone_session':True,'receiver_recovery_seconds':receiver_seconds,'vm_pid_preserved':True,'supervisor_running':bool(controller.macplay_nbt.supervisor_running()),'phone_reconnected':True}
    (ROOT/'logs/startup-stability-recovery.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':main()
