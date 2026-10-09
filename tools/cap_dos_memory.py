"""Bound DOS MZ extra allocation to 4096 paragraphs (64 KiB), like MSC6 /CP.
Reject a build whose minimum allocation cannot fit; never hide that failure.
"""
import argparse,struct,json,hashlib
from pathlib import Path
def cap(data):
 b=bytearray(data)
 if len(b)<28 or b[:2]!=b'MZ':raise ValueError('not a DOS MZ executable')
 h=struct.unpack_from('<14H',b)
 if h[5]>4096:raise ValueError('minimum DOS allocation exceeds the explicit cap')
 struct.pack_into('<H',b,12,4096)
 image=(h[2]-1)*512+(h[1] or 512)-h[4]*16
 return bytes(b),dict(min_extra_paragraphs=h[5],max_extra_paragraphs=4096,
  paragraph_rounded_max_bytes=((image+15)//16+4096)*16,PSP_environment_excluded=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('exe',type=Path);a=p.parse_args()
 b,info=cap(a.exe.read_bytes());a.exe.write_bytes(b)
 print(json.dumps(dict(info,sha256=hashlib.sha256(b).hexdigest())))
