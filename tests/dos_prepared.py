"""Exercise the redistributable prepared demo with a fresh DOS executable."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,struct,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--runtime',type=Path,required=True);ap.add_argument('--keep',type=Path);ap.add_argument('--dosbox',default='dosbox-x');args=ap.parse_args()
 with tempfile.TemporaryDirectory(prefix='rave-public-midi-') as td:
  work=Path(td);shutil.copyfile(args.runtime,work/'RSRAVE.EXE')
  for name in ['DEMO.RBG','DEMO.RWS']:shutil.copyfile(ROOT/'runtime'/name,work/name)
  (work/'EV').mkdir();lines=['@ECHO OFF','mount c '+str(work),'c:']
  for name,mode in [('AUTO','/AUTO /NOLOGO'),('RETRY','/RETRY /NOLOGO'),('SCORE','/HISCORE /NOLOGO'),('INTRO','/SPLASH')]:
   lines+=['RSRAVE DEMO.RBG /STREAM DEMO.RWS /LEAN /RENDER '+mode+' > EV\\'+name+'.OUT','IF ERRORLEVEL 1 GOTO FAIL','COPY '+('SPLASH.LOG' if name=='INTRO' else 'RUNLOG.TXT')+' EV\\'+name+'.LOG > NUL']
  # DOSBox internal shell has no batch labels in autoexec. Use a DOS batch for error exits.
  batch=['@ECHO OFF',*lines[3:],'ECHO PASS > EV\\PASS.TXT','GOTO END',':FAIL','ECHO FAIL > EV\\FAIL.TXT',':END','EXIT']
  (work/'TEST.BAT').write_text('\n'.join(batch)+'\n')
  config='[sdl]\noutput=surface\n[dosbox]\nmachine=tandy\nmemsize=1\n[cpu]\ncore=normal\ncputype=8086_prefetch\ncycles=fixed 200000\n[mixer]\nnosound=true\n[autoexec]\n@ECHO OFF\nmount c '+str(work)+'\nc:\nTEST.BAT\nexit\n'
  (work/'TEST.CNF').write_text(config)
  env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy');kw={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
  subprocess.run([args.dosbox,'-conf',str(work/'TEST.CNF'),'-nopromptfolder','-fastlaunch'],env=env,check=True,capture_output=True,timeout=180,**kw)
  evidence=work/'EV';assert (evidence/'PASS.TXT').exists() and not (evidence/'FAIL.TXT').exists(),[(p.name,p.read_text(errors='replace')) for p in evidence.glob('*.OUT')]
  expected=struct.unpack_from('<H',(ROOT/'runtime/DEMO.RWS').read_bytes(),16)[0];logs={}
  for name in ['AUTO','RETRY','SCORE']:
   text=(evidence/(name+'.LOG')).read_text();fields={k:int(v) for k,v in re.findall(r'\b([a-z_]+)=(\d+)',text)}
   assert fields['midi_delivered']==expected and fields['midi_errors']==0 and fields['midi_ended']==1,text
   assert fields['hits']==fields['required'] and fields['misses']==0,text
   assert 'restore_video=1 restore_keyboard=1' in text and 'cleanup_owned=0 keyboard_owned=0 video_owned=0 speaker_low=0' in text,text
   if name=='RETRY':assert fields['restart']==1
   if name=='SCORE':assert 'hiscore_initials=CLD' in text
   logs[name]=fields
  intro=(evidence/'INTRO.LOG').read_text();assert 'restore_video=1 restore_keyboard=1 sound_owned=0 keyboard_owned=0 video_owned=0 speaker_low=0' in intro
  report={'result':'PASS','runtime_sha256':hashlib.sha256(args.runtime.read_bytes()).hexdigest(),'source_messages':expected,'modes':['full playback','R replay','complete score tally','intro'],'runs':logs,'limits':'Virtual-clock DOSBox smoke with original redistributable music; not physical timing.'}
  if args.keep:
   args.keep.mkdir(parents=True,exist_ok=True);shutil.copytree(evidence,args.keep,dirs_exist_ok=True);(args.keep/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
  print('PASS original prepared demo: full playback, restart, tally, intro and restoration;',expected,'messages')
if __name__=='__main__':main()
