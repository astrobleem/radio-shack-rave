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
if __name__=='__main__':unittest.main()
