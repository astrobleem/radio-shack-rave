import unittest,sys,struct,json,tempfile,subprocess,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from import_score import convert
from mml import ScoreError
root=Path(__file__).resolve().parents[1]
FIXTURES={
 'fast_repeats':'t155o5l8f+f+f+f+f+f+f+f+f+f+f+f+,t155o4l4bbbbbb',
 'ties_and_rests':'t120o4c4&c8r8d8d8e4r4f4,t120o3g2g2g2g2',
 'changing_tempo':'t120o4c8d8e8f8t90g8a8b8>c8,t120o3g2t90a2',
 'slow_sustains':'t90o5c1&c2r4d4e4f4g4,t90o4e1r1',
 'mixed_accidentals':'t180o4l8c#d-e+f#g+a-bc,t180o3l4cega',
}
def unpack(b):
 magic,v,end,ns,nt=struct.unpack_from('<4sHHHH',b)
 assert (magic,v)==(b'RBG3',3)
 return end,b[12:12+ns*12],[struct.unpack_from('<3H4B',b,12+ns*12+i*10) for i in range(nt)]
def run(b,mode):
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp)/'TEST.RBG';p.write_bytes(b)
  r=subprocess.run([os.environ['RAVE_CORE_EXE'],str(p),mode],capture_output=True,text=True,check=True)
 return r.stdout.splitlines(),r.stderr
class Retention(unittest.TestCase):
 def test_general_music_is_not_thinned(self):
  for name,s in FIXTURES.items():
   with self.subTest(song=name):
    full=convert(s,lead=1,difficulty='full')
    end,back,full_notes=unpack(full[0])
    for difficulty in ('easy','normal','hard','full'):
     a=convert(s,lead=1,difficulty=difficulty);self.assertEqual(a,convert(s,lead=1,difficulty=difficulty))
     e,b,notes=unpack(a[0]);r=json.loads(a[1])
     self.assertEqual((e,b),(end,back));self.assertEqual([n[:-1] for n in notes],[n[:-1] for n in full_notes])
     self.assertEqual(r['lead_events'],r['source_lead_onsets']);self.assertEqual(len(notes),r['lead_events'])
     self.assertEqual(r['chart_taps']+r['automatic_lead_events'],len(notes))
 def test_actual_core_all_hits_equals_reference(self):
  for name,s in FIXTURES.items():
   full_trace=None
   for difficulty in ('easy','normal','hard','full'):
    with self.subTest(song=name,difficulty=difficulty):
     b=convert(s,lead=1,difficulty=difficulty)[0]
     ref,_=run(b,'ref');hit,_=run(b,'hit');self.assertEqual(ref,hit)
     if full_trace is None:full_trace=ref
     self.assertEqual(ref,full_trace)
 def test_actual_core_misses_only_suppress_required(self):
  for name,s in FIXTURES.items():
   for difficulty in ('easy','normal','hard','full'):
    with self.subTest(song=name,difficulty=difficulty):
     b=convert(s,lead=1,difficulty=difficulty)[0];e,back,notes=unpack(b)
     miss,stats=run(b,'miss');expected=[]
     for t,off,d,l,a,n,auto in notes:
      if auto:expected.extend([f'L {t} {d} {a}',f'L {off} 0 15'])
     self.assertEqual(miss,expected)
 def test_first_repeat_is_retained_on_easy(self):
  b,r,n=convert(FIXTURES['fast_repeats'],lead=1,difficulty='easy')
  notes=unpack(b)[2];self.assertEqual(notes[1][-1],1)
  ref,_=run(b,'ref');hit,_=run(b,'hit');self.assertEqual(ref,hit)
  self.assertTrue(any(line==f'L {notes[1][0]} {notes[1][2]} {notes[1][4]}' for line in hit))
 def test_bounds_do_not_silently_drop_notes(self):
  with self.assertRaisesRegex(ScoreError,'total lead events'):
   convert('t120o4l8'+'c'*513,difficulty='easy')
if __name__=='__main__':unittest.main()
