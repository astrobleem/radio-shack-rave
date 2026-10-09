import unittest,sys,struct,json,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from import_score import convert
from chart_policy import seconds_to_beat,select_required
from mml import ScoreError
from fractions import Fraction as F
def payload(b):
 _,_,end,ns,nt=struct.unpack_from('<4sHHHH',b)
 return end,b[40:40+ns*12],[struct.unpack_from('<3H4B',b,40+ns*12+i*10) for i in range(nt)]
class ChartPolicy(unittest.TestCase):
 def test_native_window_contract(self):
  core=(Path(__file__).resolve().parents[1]/'src/CORE.H').read_text()
  self.assertRegex(core,r'#define WINDOW 3\b')
 def test_short_tones_remain_automatic(self):
  text='t120o4c4d16e16f4g16a16b4'
  b,report,_=convert(text,lead='1',chart_policy='metrical',difficulty='normal')
  notes=payload(b)[2];self.assertTrue(any(n[-1] for n in notes if n[1]-n[0]<=3))
  self.assertTrue(all(n[1]-n[0]>3 for n in notes if not n[-1]))
  self.assertEqual(json.loads(report)['settings']['audible_late_window_ticks'],3)
 def test_all_short_easy_chart_rejects_explicitly(self):
  with self.assertRaisesRegex(ScoreError,'no lead onset survives'):
   convert('t180o4l8cdef',chart_policy='metrical',difficulty='easy')
  # Explicit full still retains every required onset and its documented risk.
  b,_,_=convert('t180o4l8cdef',chart_policy='metrical',difficulty='full')
  self.assertTrue(all(not n[-1] for n in payload(b)[2]))
 def test_ties_rests_and_tempo_preserve_every_audio_event(self):
  text='t120o4c4&c8r8d8d8t90e4r4f4,t120o3g2g4t90a2a2'
  a=payload(convert(text,lead='1',chart_policy='elapsed')[0]);b=payload(convert(text,lead='1',chart_policy='metrical')[0])
  self.assertEqual(a[:2],b[:2]);self.assertEqual([n[:-1] for n in a[2]],[n[:-1] for n in b[2]])
  self.assertEqual(seconds_to_beat([(F(0),120),(F(2),90)],F(5,3)),3)
 def test_metrical_selection_is_deterministic_and_bounded(self):
  notes=[dict(start=F(i,8),end=F(i+1,8)) for i in range(32)]
  picks=select_required(notes,[(F(0),120)],280)
  self.assertEqual(picks,set(range(0,32,4))|{31})
  self.assertEqual(picks,select_required(notes,[(F(0),120)],280))
  self.assertTrue(all(notes[b]['start']-notes[a]['start']>=F(280,1000) for a,b in zip(sorted(picks),sorted(picks)[1:])))
if __name__=='__main__':unittest.main()
