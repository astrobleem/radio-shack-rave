import unittest,sys,json,tempfile,io,contextlib
from fractions import Fraction as F
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import midi_to_mml as m2m
from mml import parse
from import_score import convert

def vlq(n):
 out=[n&0x7F]
 n>>=7
 while n:out.append((n&0x7F)|0x80);n>>=7
 return bytes(reversed(out))
def smf(tracks,ppq=96,bpm=120,sig=(4,4)):
 """Minimal stdlib SMF writer. tracks: list of (channel, [(start_tick,end_tick,pitch)])."""
 def chunk(tag,body):return tag+len(body).to_bytes(4,'big')+body
 conductor=b'\x00\xff\x51\x03'+(60000000//bpm).to_bytes(3,'big')+b'\x00\xff\x58\x04'+bytes([sig[0],{4:2,8:3,2:1}[sig[1]],24,8])+b'\x00\xff\x2f\x00'
 out=[chunk(b'MTrk',conductor)]
 for ch,notes in tracks:
  ev=[]
  for s,e,p in notes:ev+=[(s,1,0x90|ch,p,90),(e,0,0x80|ch,p,0)]
  ev.sort(key=lambda x:(x[0],x[1]))
  body=b'';last=0
  for t,_,st,p,v in ev:body+=vlq(t-last)+bytes([st,p,v]);last=t
  out.append(chunk(b'MTrk',body+b'\x00\xff\x2f\x00'))
 return chunk(b'MThd',(1).to_bytes(2,'big')+len(out).to_bytes(2,'big')+ppq.to_bytes(2,'big'))+b''.join(out)

def midi_from_original():
 text=(ROOT/'music/ORIGINAL.MML').read_text()
 voices,tempo_map,_=parse(text,parts_only=True)
 tracks=[]
 for ch,ns in enumerate(voices):
  tracks.append((ch,[(round(n['start']*2*96),round(n['end']*2*96),n['note']) for n in ns if n['note']]))
 return smf(tracks),text

class MidiToMml(unittest.TestCase):
 def run_tool(self,data,*argv):
  with tempfile.TemporaryDirectory() as d:
   src=Path(d)/'in.mid';src.write_bytes(data);out=Path(d)/'out.mml'
   buf,err=io.StringIO(),io.StringIO()
   with contextlib.redirect_stdout(buf),contextlib.redirect_stderr(err):
    code=m2m.main([str(src),'-o',str(out),*argv])
   return code,buf.getvalue(),err.getvalue(),(out.read_text() if out.exists() else '')
 def test_original_roundtrip_is_note_exact_and_chart_identical(self):
  data,original=midi_from_original()
  code,out,err,text=self.run_tool(data,'--voice','1:top','--voice','2:bottom','--voice','3:top','--title','CIRCUIT AFTER HOURS','--check')
  self.assertEqual(code,0,err)
  a,_,_=parse(original,parts_only=True);b,_,_=parse(text.strip(),parts_only=True)
  key=lambda v:[(n['start'],n['end'],n['note']) for n in v if n['note']]
  for x,y in zip(a,b):self.assertEqual(key(x),key(y))
  blob_a=convert(original,lead='1',parts=[1,2,3],difficulty='normal',title='CIRCUIT AFTER HOURS')[0]
  blob_b=convert(text.strip(),lead='1',parts=[1,2,3],difficulty='normal',title='CIRCUIT AFTER HOURS')[0]
  self.assertEqual(blob_a,blob_b)
 def test_excerpt_bars_and_report(self):
  data,_=midi_from_original()
  code,out,err,text=self.run_tool(data,'--voice','1:top','--from-bar','2','--to-bar','4')
  self.assertEqual(code,0,err);self.assertIn('2 bars',out)
  v,_,duration=parse(text.strip(),parts_only=True);self.assertEqual(duration,F(4))
 def test_monophonic_reduction_top_and_bottom(self):
  chord=[(0,96,60),(0,96,64),(0,96,67),(96,192,62),(96,192,65)]
  data=smf([(0,chord)])
  for mode,expect in (('top',[67,65]),('bottom',[60,62])):
   code,_,err,text=self.run_tool(data,'--voice',f'1:{mode}')
   self.assertEqual(code,0,err)
   v,_,_=parse(text.strip(),parts_only=True);self.assertEqual([n['note'] for n in v[0] if n['note']],expect)
 def test_explicit_shift_reported_and_never_clamped(self):
  data=smf([(0,[(0,96,33),(96,192,40)])])
  code,out,err,text=self.run_tool(data,'--voice','1:top','--title','LOW')
  self.assertEqual(code,0,err);self.assertIn('shift +12',out);self.assertIn('--voice-transpose 1:+12',out)
  wide=smf([(0,[(0,96,30),(96,192,100)])])
  code,_,err,_=self.run_tool(wide,'--voice','1:top')
  self.assertEqual(code,1);self.assertIn('wider than the PSG range',err)
  code,out,err,_=self.run_tool(wide,'--voice','1:top','--fold')
  self.assertEqual(code,0,err);self.assertIn('octave-folded',out)
 def test_ties_and_dotted_lengths_round_trip(self):
  data=smf([(0,[(0,24*7,60),(24*8,24*8+24*5,62)])])
  code,_,err,text=self.run_tool(data,'--voice','1:top')
  self.assertEqual(code,0,err)
  v,_,_=parse(text.strip(),parts_only=True);n=[x for x in v[0] if x['note']]
  self.assertEqual([(x['end']-x['start'])*2 for x in n],[F(7,4),F(5,4)])
 def test_source_limit_and_tempo_guards(self):
  long=[(i*24,i*24+24,60+(i*7%13)+12*(i%2)) for i in range(9000)]
  code,_,err,_=self.run_tool(smf([(0,long)]),'--voice','1:top')
  self.assertEqual(code,1);self.assertIn('exceeds the 8192-byte',err)
  code,_,err,_=self.run_tool(smf([(0,[(0,96,60)])],bpm=20),'--voice','1:top')
  self.assertEqual(code,1);self.assertIn('outside 32..255',err)
 def test_reader_rejects_non_midi(self):
  with self.assertRaises(m2m.MidiError):m2m.read_smf(b'not midi at all')
if __name__=='__main__':unittest.main()
