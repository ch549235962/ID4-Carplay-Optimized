#!/opt/homebrew/bin/python3.13
"""Measure real QNX presentations and delivered frames; never open a browser.
Uses balanced rotary steps throughout the measurement on the connected phone, then verifies switching
to the original NBT menu and back without restarting the receiver.
"""
import hashlib,json,time,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VIEW="http://127.0.0.1:8876"
CONTROL="http://127.0.0.1:8877"
def get(path):
    with urllib.request.urlopen(VIEW+path,timeout=4) as f:return json.load(f)
def control(path="/status",data=None):
    r=urllib.request.Request(CONTROL+path,headers={"Origin":VIEW,"Content-Type":"application/json"},data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(r,timeout=8) as f:return json.load(f)
def frame(tag=""):
    r=urllib.request.Request(VIEW+"/frame",headers={"If-None-Match":tag})
    try:
        with urllib.request.urlopen(r,timeout=4) as f:
            data=f.read();assert data.startswith(b"P6\n1280 480\n255\n") and len(data)==1280*480*3+16
            return f.headers["ETag"],hashlib.sha256(data).hexdigest()
    except urllib.error.HTTPError as e:
        if e.code==304:return tag,None
        raise

def main():
    began=time.monotonic();last_note=-10
    while time.monotonic()-began<150:
        try:s=get("/status");v=get("/metrics").get("renderer") or {};c=control()
        except (OSError,ValueError):time.sleep(1);continue
        if s.get("controller_ready") and c.get("session_active") and v.get("presented_frames",0)>0:break
        if time.monotonic()-began-last_note>=10:
            last_note=time.monotonic()-began;print(json.dumps({"waiting_s":round(last_note),"idrive":s.get("controller_ready"),"decoded":v.get("decoded_frames"),"display_fps":(v.get("fps") or {}).get("displayed")}),flush=True)
        time.sleep(1)
    else:raise RuntimeError("Display/input startup did not become ready")
    print("Display and iDrive ready; allowing 15 seconds for startup to settle",flush=True);time.sleep(15)
    initial=control();start=time.monotonic();first=get("/metrics");samples=[];tag="";hashes=set();unique=0;actions=0;next_sample=start;next_action=start
    while time.monotonic()-start<24:
        now=time.monotonic()
        if now>=next_action:
            control("/action",{"action":"rotate","steps":1 if actions%2==0 else -1});actions+=1;next_action=now+.5
        if now>=next_sample:
            m=get("/metrics");samples.append({"t":now-start,"renderer":m["renderer"],"guest":m.get("guest"),"processes":m.get("processes")});next_sample=now+.5
        new,digest=frame(tag)
        if new!=tag:unique+=1;tag=new
        if digest:hashes.add(digest)
        time.sleep(.01)
    elapsed=time.monotonic()-start;last=get("/metrics")
    if actions%2:control("/action",{"action":"rotate","steps":-1});actions+=1
    a,b=first["renderer"],last["renderer"]
    rates={key:round((b[key]-a[key])/elapsed,2) for key in ["received_frames","decoded_frames","presented_frames"]}
    (ROOT/"logs/display-performance-samples.json").write_text(json.dumps({"rates":rates,"samples":samples,"http_frames":unique,"distinct_pixels":len(hashes)},indent=2))
    assert rates["decoded_frames"]>3,rates
    assert rates["presented_frames"]>=.8*rates["decoded_frames"],rates
    assert b["decode_errors"]==a["decode_errors"]==0
    assert b["display_errors"]==a["display_errors"]==0
    assert unique/elapsed>.6*rates["presented_frames"],(unique,elapsed,rates)
    assert len(hashes)>10,len(hashes)
    print(json.dumps({"rates":rates,"http_frame_fps":round(unique/elapsed,2),"distinct_pixels":len(hashes)}),flush=True)
    old_hash=frame()[1];switch_at=time.monotonic();control("/mode",{"target":"nbt"});hidden_ack=time.monotonic()-switch_at
    request=urllib.request.Request(VIEW+"/action",data=b'{"action":"menu"}',headers={"Origin":VIEW,"Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=5) as f:json.load(f)
    while time.monotonic()-switch_at<18:
        if frame()[1]!=old_hash:break
        time.sleep(.2)
    else:raise RuntimeError("Original NBT frame did not return")
    menu_delay=time.monotonic()-switch_at;assert get("/status")["controller_ready"]
    # Require new presentations; a pre-switch metrics sample must not satisfy
    # the resume check merely because it still reports visible/high FPS.
    hidden_frames=get("/metrics")["renderer"]["presented_frames"]
    control("/mode",{"target":"carplay"});back_at=time.monotonic();back_wall=time.time()
    while time.monotonic()-back_at<18:
        v=get("/metrics")["renderer"]
        if v["visible"] and v["sampled_at"]>back_wall and v["presented_frames"]>=hidden_frames+5:break
        time.sleep(.5)
    else:raise RuntimeError("CarPlay fast presentation did not resume")
    final=control();assert final["pid"]==initial["pid"] and final["ready"] and final["session_active"]
    report={"measured_seconds":round(elapsed,2),"rates":rates,"http_distinct_frame_fps":round(unique/elapsed,2),"distinct_pixel_hashes":len(hashes),"balanced_rotary_actions":actions,"decode_errors":b["decode_errors"],"display_errors":b["display_errors"],"hide_ack_seconds":round(hidden_ack,3),"nbt_frame_return_seconds":round(menu_delay,3),"carplay_resume_seconds":round(time.monotonic()-back_at,3),"phone_session_preserved":True,"receiver_pid":final["pid"],"controller_ready":True,"samples":samples}
    (ROOT/"logs/display-performance-after.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="samples"},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
