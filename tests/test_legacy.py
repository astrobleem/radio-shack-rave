"""Synthetic RBG2/3/4 interchange and actual production-loader conformance."""
import unittest,sys,struct,tempfile,subprocess,os,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from import_score import convert
def legacy(blob,version):
 magic,v,end,ns,nt=struct.unpack_from('<4sHHHH',blob)
 payload=blob[40:40+ns*12+nt*10]
 assert version in (2,3)
 if version==2:
  payload=bytearray(payload)
  for i in range(nt):payload[ns*12+i*10+9]=0
 return struct.pack('<4sHHHH',('RBG'+str(version)).encode(),version,end,ns,nt)+payload
def run(blob,mode=None,loader=False):
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp)/'SCORE.RBG';p.write_bytes(blob)
  args=[os.environ['RAVE_LOADER_EXE'] if loader else os.environ['RAVE_CORE_EXE'],str(p)]
  if mode:args.append(mode)
  return subprocess.run(args,capture_output=True)
class Legacy(unittest.TestCase):
 def test_rbg3_and_rbg4_sound_and_score_identity(self):
  new=convert('t120o4l8cdefgab>c,t120o3l4cegr',lead=1,difficulty='normal')[0]
  old=legacy(new,3)
  for mode in ['hit','ref','miss']:
   a,b=run(old,mode),run(new,mode)
   self.assertEqual((a.returncode,a.stdout,a.stderr),(b.returncode,b.stdout,b.stderr))
  for b in [old,new]:self.assertEqual(run(b,loader=True).returncode,0)
 def test_rbg2_all_required_is_supported(self):
  new=convert('t120o4l8cdefgab>c,t120o3l4cegr',lead=1,difficulty='full')[0]
  old=legacy(new,2)
  for mode in ['hit','ref','miss']:
   a,b=run(old,mode),run(new,mode)
   self.assertEqual((a.returncode,a.stdout,a.stderr),(b.returncode,b.stdout,b.stderr))
  self.assertEqual(run(old,loader=True).returncode,0)
 def test_loader_rejects_malformed_all_versions(self):
  new=convert('t120o4c4d4,t120o3g2',lead=1)[0]
  for good in [legacy(new,2),legacy(new,3),new]:
   for bad in [good[:4],good[:-1],good+b'x',b'NOPE'+good[4:]]:
    self.assertEqual(run(bad,loader=True).returncode,2)
 def test_rbg4_metadata_does_not_change_legacy_payload(self):
  a=convert('t120o4c4d4,t120o3g2',lead=1,title='FIRST')[0]
  b=convert('t120o4c4d4,t120o3g2',lead=1,title='SECOND')[0]
  self.assertEqual(legacy(a,3),legacy(b,3))
 def test_loader_long_song_and_drums(self):
  long=convert('t150o4l8'+'cdefgfed'*190+',t150o3l16'+'cegc'*760,lead=1)[0]
  out=run(long,loader=True);self.assertEqual(out.returncode,0,out.stdout)
  self.assertIn(b'lead=1520',out.stdout)
  drum=convert('t120o4l8cdefgfed,t120o3l2cg,t120l8o2c f+ d f+ c a+ d >c+',lead=1,parts=[1,2],drums=3)[0]
  out=run(drum,loader=True);self.assertEqual(out.returncode,0);self.assertIn(b'drums=8',out.stdout)
  for mode in ['hit','ref','miss']:self.assertEqual(run(drum,mode).returncode,0)
  ns,nt=struct.unpack_from('<HH',drum,8);segs=struct.unpack_from('<H',drum,12)[0];base=44+ns*12+nt*10+segs*12
  bad=[drum[:42]+b'\x01'+drum[43:],                       # reserved word nonzero
       drum[:40]+b'\x00\x00'+drum[42:],                    # zero drums in RBG5
       drum[:base+2]+b'\x07'+drum[base+3:],                 # unknown kind
       drum[:base+3]+b'\x10'+drum[base+4:],                 # level above 15
       drum[:base+4]+drum[base:base+2]+drum[base+6:],        # ticks not increasing
       drum[:base]+struct.pack('<H',9999)+drum[base+2:],     # hit after the end
       drum+b'\x00']
  for b in bad:self.assertEqual(run(b,loader=True).returncode,2)
if __name__=='__main__':unittest.main()
