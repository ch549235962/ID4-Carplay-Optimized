#!/usr/bin/env python3
"""Compact a separate IFS while verifying every file and retaining startup instructions."""
import hashlib,json,struct,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];SRC=R.parent/'NBT-Dev/src/BMW-NBT-Emulator';sys.path.insert(0,str(SRC/'tools'))
from inspect_nbt_ifs import find_imagefs
from repack_nbt_ifs import checksum32
def compact(source,output):
 source=Path(source);output=Path(output);assert source.resolve()!=output.resolve() and not output.exists()
 data=source.read_bytes();inv=find_imagefs(data);base=inv['header_offset'];end=base+inv['image_size'];startup=struct.unpack_from('<I',data,32)[0];assert base==startup and not checksum32(data,0,base) and not checksum32(data,base,end)
 # Retain the complete fixed image header and its NUL-terminated mountpoint.
 first=base+88;header_end=data.index(0,first)+1;built=bytearray(data[:header_end]);offsets={};payloads={};hashes={};dedup=0
 for e in sorted((x for x in inv['entries'] if x['type']=='file'),key=lambda e:e['absolute_offset']):
  payload=data[e['absolute_offset']:e['absolute_offset']+e['size']];digest=hashlib.sha256(payload).hexdigest();hashes[e['path']]=digest;alignment=e['absolute_offset']%4096;key=(digest,e['size'],alignment)
  if key in payloads:offsets[e['path']]=payloads[key];dedup+=e['size'];continue
  built.extend(bytes((alignment-len(built))%4096));offsets[e['path']]=len(built)-base;payloads[key]=offsets[e['path']];built.extend(payload)
 built.extend(bytes((-len(built))%4));directory=len(built);pos=base+inv['dir_offset'];bypos={e['dirent_offset']:e for e in inv['entries']}
 while pos+2<=base+inv['hdr_dir_size']:
  size=struct.unpack_from('<H',data,pos)[0]
  if not size:break
  rec=bytearray(data[pos:pos+size]);e=bypos.get(pos)
  if e and e['type']=='file':struct.pack_into('<I',rec,24,offsets[e['path']])
  built.extend(rec);pos+=size
 built.extend(bytes(4));hdrsize=len(built)-base;fssize=hdrsize+4;stored=base+fssize;oldram=struct.unpack_from('<I',data,28)[0]
 struct.pack_into('<3I',built,base+8,fssize,hdrsize,directory-base);struct.pack_into('<I',built,28,oldram+stored-end);struct.pack_into('<I',built,36,stored);struct.pack_into('<I',built,44,fssize)
 struct.pack_into('<I',built,base-4,0);struct.pack_into('<I',built,base-4,(-checksum32(built,0,base))&0xffffffff);built.extend(struct.pack('<I',(-checksum32(built,base,len(built)))&0xffffffff));built.extend(data[end:]);updated=find_imagefs(built)
 assert len(inv['entries'])==len(updated['entries']);assert data[256:base-4]==built[256:base-4]
 for e in updated['entries']:
  if e['type']=='file':assert hashlib.sha256(built[e['absolute_offset']:e['absolute_offset']+e['size']]).hexdigest()==hashes[e['path']],e['path']
 assert not checksum32(built,0,base) and not checksum32(built,base,base+updated['image_size'])
 output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(built);report={'source':str(source),'output':str(output),'source_bytes':len(data),'output_bytes':len(built),'bytes_reclaimed':len(data)-len(built),'deduplicated_bytes':dedup,'files_verified':len(hashes),'startup_instructions_preserved':True,'all_file_payloads_identical':True,'output_sha256':hashlib.sha256(built).hexdigest()};output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n');return report
if __name__=='__main__':print(json.dumps(compact(sys.argv[1],sys.argv[2])))
