#!/opt/homebrew/bin/python3.13
"""Measure startup phases; --cold explicitly stops and restarts this local VM."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'NBT-Launcher'))
import controller

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cold',action='store_true');args=parser.parse_args()
    if args.cold:
        controller.stop();time.sleep(2)
        assert not controller.macplay_nbt.running() and not controller.macplay_nbt.supervisor_running()
        assert controller.nbt_vm.status()['qemu']=='stopped'
    before=controller.macplay_nbt.running();start=time.monotonic();controller.start();marks={'service_start_return':round(time.monotonic()-start,3)}
    last_note=0
    while time.monotonic()-start<120:
        state=controller.status();metrics=controller.http_json('http://127.0.0.1:8876/metrics');video=metrics.get('renderer') or {}
        for name,ready in [('receiver_ready',state['receiver_ready']),('phone_connected',state['phone_connected']),('native_hid_ready',state['native_hid_ready']),('first_qnx_decoded',video.get('decoded_frames',0)>0),('first_qnx_displayed',video.get('presented_frames',0)>0),('idrive_ready',state['controller_ready'])]:
            if ready and name not in marks:marks[name]=round(time.monotonic()-start,3);print(name,marks[name],flush=True)
        if all(k in marks for k in ['phone_connected','native_hid_ready','first_qnx_displayed','idrive_ready']):
            result={'cold':args.cold,'phase_seconds':marks,'builtin_tools_used':controller.macplay_nbt.builtin_tools_available(),'supervisor_running':bool(controller.macplay_nbt.supervisor_running()),'manual_stop_stayed_stopped':args.cold,'configuration':metrics.get('configuration'),'phone_session_active':state['phone_connected']}
            (ROOT/'logs'/('startup-stability-cold.json' if args.cold else 'startup-stability-warm.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False),flush=True);return
        if time.monotonic()-start-last_note>=10:last_note=time.monotonic()-start;print('Boot elapsed',round(last_note,1),flush=True)
        time.sleep(.3)
    raise RuntimeError('Startup readiness timed out; inspect local logs')
if __name__=='__main__':main()
