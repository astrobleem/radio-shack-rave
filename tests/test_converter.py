import unittest,sys,json,hashlib,struct
from fractions import Fraction as F
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from import_score import convert
from mml import ScoreError
class Converter(unittest.TestCase):
 def test_case_accidentals_dots_and_rests(self):
  _,_,n=convert('mMl@T120O4L8V127C#D-E+R.;')
  v=json.loads(n)['voices'][0]
  self.assertEqual([x['note'] for x in v],[61,61,65,0]);self.assertEqual(v[-1]['end'],'9/8')
 def test_tie_merges_attack_and_interval(self):
  _,r,n=convert('t120o4c4&c8r8d4',lead=1)
  v=json.loads(n)['voices'][0]
  self.assertEqual(v[0]['end'],'3/4');self.assertEqual(json.loads(r)['lead_events'],2)
 def test_unsupported_syntax_location(self):
  with self.assertRaisesRegex(ScoreError,'voice 2, line 2, column 1: unsupported syntax'):convert('c4,\n@p2d4')
 def test_tempo_conflict_rejected(self):
  with self.assertRaises(ScoreError):convert('t120c4,t90e4')
 def test_transposition_is_explicit(self):
  with self.assertRaisesRegex(ScoreError,'explicit transpose'):convert('o2c4')
  _,r,_=convert('o2c4',transpose=12)
  self.assertEqual(json.loads(r)['transpositions'][0]['output_range'],[48,48])
 def test_resolution_and_storage_bounds(self):
  for text in ['t255o4c64',','.join(['c4']*9),'t120o4l8'+'c'*2049]:
   with self.subTest(text=text[:30]):
    with self.assertRaises(ScoreError):convert(text)
 def test_original_golden_outputs(self):
  root=Path(__file__).resolve().parents[1]
  result=convert((root/'music/ORIGINAL.MML').read_text(),lead='1',parts=[1,2,3],difficulty='normal',title='CIRCUIT AFTER HOURS')
  for data,name in zip(result,['ORIGINAL.RBG','ORIGINAL.json','ORIGINAL.events.json']):self.assertEqual(data,(root/'runtime'/name).read_bytes())
  r=json.loads(result[1]);self.assertEqual((r['source_lead_onsets'],r['chart_taps'],r['automatic_lead_events']),(128,64,64))
  self.assertEqual(r['seconds'],'32/1');self.assertFalse(r['dropped_voices'])
  self.assertEqual((r['title'],r['beat_grid']['segments'],r['beat_grid']['beats']),('CIRCUIT AFTER HOURS',1,64))
 def test_title_rules(self):
  b=convert('c4',title='')[0];self.assertEqual(b[12:16],bytes([1,0,1,0]));self.assertEqual(b[16:40],bytes(24))
  with self.assertRaisesRegex(ScoreError,'title'):convert('c4',title='lower case')
  with self.assertRaisesRegex(ScoreError,'title'):convert('c4',title='X'*25)
 def test_long_song_fits_far_tables(self):
  # About five minutes: more lead notes and backing changes than the old
  # 512/1024 caps (the reason long songs had to be split), within the new.
  lead='t150o4l8'+'cdefgfed'*190
  back='t150o3l16'+'cegc'*760
  b,r,_=convert(lead+','+back,lead=1,difficulty='normal')
  r=json.loads(r);self.assertEqual(r['lead_events'],1520);self.assertGreater(r['states'],1024)
  self.assertGreater(float(sum(F(x) for x in [r['seconds']])),300)
 def test_drum_voice_writes_rbg5(self):
  mml='t120o4l8cdefgfed,t120o3l2cg,t120l8o2c f+ d f+ c a+ d >c+'
  b,r,_=convert(mml,lead=1,parts=[1,2],drums=3)
  self.assertEqual(b[:4],b'RBG5');n,zero=struct.unpack_from('<HH',b,40);self.assertEqual((n,zero),(8,0))
  ns,nt=struct.unpack_from('<HH',b,8);segs=struct.unpack_from('<H',b,12)[0]
  base=44+ns*12+nt*10+segs*12;self.assertEqual(len(b),base+n*4)
  hits=[struct.unpack_from('<HBB',b,base+i*4) for i in range(n)]
  self.assertEqual([h[1] for h in hits],[0,2,1,2,0,3,1,4])   # kick hat snare hat kick ohat snare crash
  self.assertEqual(json.loads(r)['drums']['by_kind']['closed_hat'],2)
  self.assertEqual(convert('t120o4c4,t120o3c4',lead=1)[0][:4],b'RBG4')
 def test_drum_voice_rules(self):
  with self.assertRaisesRegex(ScoreError,'General MIDI'):convert('t120o4c4,t120o1c4',lead=1,parts=[1],drums=2)
  with self.assertRaisesRegex(ScoreError,'leave it out of parts'):convert('t120o4c4,t120o2c4',lead=1,parts=[1,2],drums=2)
  with self.assertRaisesRegex(ScoreError,'cannot also be the lead'):convert('t120o4c4,t120o2c4',lead=2,drums=2)
  b,r,_=convert('t120o4c4,t120o3c4,t120l4o2c',lead='auto',drums=3)
  self.assertNotIn(3,json.loads(r)['psg_voices'])
if __name__=='__main__':unittest.main()
