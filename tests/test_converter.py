import unittest,sys,json,hashlib
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
  for text in ['t255o4c64',','.join(['c4']*9),'t120o4l8'+'c'*513]:
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
if __name__=='__main__':unittest.main()
