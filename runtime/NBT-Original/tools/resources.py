"""Validated resource settings; 1 GiB requires further QNX boot-layout work."""
import json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def config():
 p=R/'vm/resources.json';m=json.loads(p.read_text()) if p.exists() else {'ram_mib':512,'vcpus':1}
 if m.get('ram_mib')!=512 or m.get('vcpus')!=1:raise ValueError('Only the validated 512 MiB / 1 vCPU configuration is currently enabled')
 return m
def image_for_ram(source):return source
