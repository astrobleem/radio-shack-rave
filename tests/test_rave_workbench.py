import unittest,sys,tempfile,wave,subprocess,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'tests'))
import rave_workbench as wb
import midi_to_mml as m2m
from test_midi_to_mml import smf,midi_from_original

def song():
 lead=[(i*96,i*96+96,60+(i*5)%12) for i in range(16)]
 bass=[(i*192,i*192+192,40+(i%3)*2) for i in range(8)]
 chords=[(i*192,i*192+192,p) for i in range(8) for p in (55,59,62)]
 return m2m.read_smf(smf([(0,lead),(1,bass),(2,chords),(9,[(0,48,36)])]))

class Workbench(unittest.TestCase):
 def test_rows_info_density(self):
  s=song();rows=wb.track_rows(s);keys=[r['key'] for r in rows]
  self.assertEqual(keys,['1.1','2.2','3.3','4.10'])
  self.assertEqual(rows[2]['poly'],3);self.assertTrue(rows[3]['drums'])
  self.assertEqual(wb.song_info(s)['bars'],4);self.assertEqual(wb.song_info(s)['bpm'],120)
  d=wb.bar_density(s);self.assertEqual(len(d),4);self.assertEqual(d[0],4+2+6)  # drums excluded
 def test_suggest_is_lead_then_bass_and_ignores_drums(self):
  rows=wb.track_rows(song())
  # make sure every candidate has enough notes for the heuristic
  for r in rows:r['notes']=max(r['notes'],8)
  got=wb.suggest_voices(rows)
  self.assertEqual(got[0],('1.1','top'));self.assertEqual(got[1],('2.2','bottom'))
  self.assertNotIn('4.10',[k for k,_ in got]);self.assertEqual(wb.suggest_voices([]),[])
 def test_form_validation(self):
  with self.assertRaisesRegex(m2m.MidiError,'voice 1'):wb.gui_params({})
  with self.assertRaisesRegex(m2m.MidiError,'in order'):wb.gui_params({'src1':'1.1','src3':'2.2'})
  with self.assertRaisesRegex(m2m.MidiError,'whole number'):wb.gui_params({'src1':'1.1','first_bar':'x'})
  with self.assertRaisesRegex(m2m.MidiError,'tempo'):wb.gui_params({'src1':'1.1','tempo':'999'})
  specs,kw=wb.gui_params({'src1':'1.1 + 3.3','mode1':'top','src2':'2.2','mode2':'bottom','first_bar':'2','last_bar':'3','grid':'8'})
  self.assertEqual(specs,['1.1+3.3:top','2.2:bottom']);self.assertEqual((kw['from_bar'],kw['to_bar'],kw['grid']),(2,4,8))
  self.assertEqual(kw['volumes'],(100,78,65));self.assertIsNone(kw['tempo'])
 def test_arrange_wav_roll_and_save(self):
  s=song();specs,kw=wb.gui_params({'src1':'1.1','src2':'2.2','mode2':'bottom','title':'Test Tune','fold':True})
  res=m2m.arrange(s,specs,**kw)
  with tempfile.TemporaryDirectory() as d:
   w=Path(d)/'p.wav';secs=wb.render_wav(res,w)
   with wave.open(str(w)) as f:self.assertEqual(f.getframerate(),22050);self.assertGreater(f.getnframes(),int(secs*22050)-5);self.assertGreater(len(f.readframes(f.getnframes())),0)
   mml,rbg=wb.save_outputs(res,Path(d)/'out',wb.safe_name(res['title']))
   self.assertEqual(rbg.name,'TEST_TUNE.RBG');self.assertTrue(mml.read_text().startswith('MML@'));self.assertTrue(rbg.read_bytes())
   self.assertTrue(rbg.with_suffix('.json').exists())
  rects=wb.piano_roll_rects(res,800,200)
  self.assertEqual({r[0] for r in rects},{0,1});self.assertTrue(all(0<=r[2]<=200 and 0<=r[1]<=800 for r in rects))
  self.assertIn('lead events',wb.limits_line(res))
 def test_original_song_through_the_same_path(self):
  data,_=midi_from_original();s=m2m.read_smf(data)
  specs,kw=wb.gui_params({'src1':'0.1','src2':'1.2','mode2':'bottom','src3':'2.3'})
  self.assertEqual(specs[0],'0.1:top')
 def test_player_and_names(self):
  none=lambda x:None
  self.assertIsNone(wb.player_command('a.wav','linux',none))
  self.assertEqual(wb.player_command('a.wav','darwin',lambda x:'/x' if x=='afplay' else None),['afplay','a.wav'])
  self.assertEqual(wb.player_command('a.wav','linux',lambda x:'/x' if x=='aplay' else None),['aplay','-q','a.wav'])
  self.assertEqual(wb.safe_name('  A/B: C?? '),'A_B_C');self.assertEqual(wb.safe_name('!!!'),'song')
 def test_window_builds_and_arranges_when_tk_and_display_exist(self):
  try:
   import tkinter;tkinter.Tk().destroy()
  except Exception:self.skipTest('no Tk/display')
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'t.mid';p.write_bytes(smf([(0,[(i*96,i*96+96,60+i%5) for i in range(16)])]))
   r=wb.run(str(p));r.withdraw();r.update();r.after(300,r.quit);r.mainloop()
   r.rave_form['src1'].set('1.1');r.rave_form['title'].set('UI TEST')
   r.rave_arrange();res=r.rave_result()
   self.assertIsNotNone(res);self.assertEqual(res['arrangement']['chart_policy'],'metrical')
   self.assertGreater(res['import_check']['chart_taps'],0)
   r.destroy()
if __name__=='__main__':unittest.main()
