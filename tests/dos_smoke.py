"""Emulated DOS checks: build with OpenWatcom, run the native diagnostic
cases in DOSBox-X (machine=tandy) headless, and compare the audio traces
with the recorded v5 native evidence.

    WATCOM=/opt/ow python tests/dos_smoke.py [--cycles 12000] [--keep DIR]

This is an emulator smoke test, not hardware timing or listening.
"""
import argparse,os,shutil,subprocess,sys,tempfile,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1]
CASES=[
 ('/TEST',[],'COREQA.TXT'),
 ('/SIMH',[],'SIMH.TXT'),('/SIMM',[],'SIMM.TXT'),('/SIMR',[],'SIMR.TXT'),
 ('/AUTO /SHOT',[('AUDIO.TXT','HIT.TXT'),('RUNLOG.TXT','HIT.LOG'),('FRAME.RAW','HIT.RAW')],None),
 ('/MISS',[('AUDIO.TXT','MISS.TXT'),('RUNLOG.TXT','MISS.LOG')],None),
 ('/AUTO /CALM',[('AUDIO.TXT','CALM.TXT'),('RUNLOG.TXT','CALM.LOG')],None),
 ('/RETRY',[('AUDIO.TXT','RETRY.TXT'),('RUNLOG.TXT','RETRY.LOG')],None),
 ('/SPAM',[('AUDIO.TXT','SPAM.TXT'),('RUNLOG.TXT','SPAM.LOG')],None),
 ('/HESC',[('RUNLOG.TXT','ESC.LOG')],None),
 ('/SPLASH',[('SPLASH.LOG','FALLBACK.LOG'),('FALLBACK.RAW','TITLE.RAW'),('SPLASH.RAW','SPLASH.RAW')],None),
 ('/SSKIP',[('SPLASH.LOG','SKIP.LOG')],None),('/SESC',[('SPLASH.LOG','SESC.LOG')],None),
 ('/SCALM',[('SPLASH.LOG','SCALM.LOG')],None)]
def main():
    p=argparse.ArgumentParser();p.add_argument('--cycles',default='12000')
    p.add_argument('--keep',type=Path);a=p.parse_args()
    work=Path(tempfile.mkdtemp(prefix='rave-dos-'))
    subprocess.run([str(root/'tools/build_ow.sh'),str(work/'RSRAVE.EXE')],check=True,capture_output=True)
    if a.keep:
        a.keep.mkdir(parents=True,exist_ok=True)
        shutil.copy(work/'RSRAVE.EXE',a.keep/'RSRAVE.EXE')
        build={'fresh_sha256':hashlib.sha256((work/'RSRAVE.EXE').read_bytes()).hexdigest(),'pinned_sha256':hashlib.sha256((root/'runtime/RSRAVE.EXE').read_bytes()).hexdigest(),'native_tests':'PENDING until the diagnostics below complete'}
        (a.keep/'BUILD.json').write_text(json.dumps(build,indent=2)+'\n')
    assert (work/'RSRAVE.EXE').read_bytes()==(root/'runtime/RSRAVE.EXE').read_bytes(), 'Fresh CI binary differs from pinned runtime; retained build is not yet native-qualified'
    subprocess.run([sys.executable,str(root/'tests/dos_playlist.py'),'--runtime',str(work/'RSRAVE.EXE')]+(['--keep',str(a.keep/'playlist')] if a.keep else []),check=True)
    shutil.copy(root/'runtime/ORIGINAL.RBG',work);shutil.copy(root/'tests/BAD.RBG',work)
    (work/'EV').mkdir()
    auto=['mount c '+str(work),'c:','RSRAVE BAD.RBG /TEST','if errorlevel 2 echo REJECTED>EV\\BAD.TXT']
    for args,copies,single in CASES:
        auto.append('RSRAVE ORIGINAL.RBG '+args)
        for src,dst in copies:auto.append(f'copy {src} EV\\{dst} > nul')
        if single:auto.append(f'copy {single} EV\\{single} > nul')
    auto.append('exit')
    conf=work/'rave.conf'
    conf.write_text(f"""[sdl]\noutput=surface\n[dosbox]\nmachine=tandy\nmemsize=1\nquit warning=false
[cpu]\ncore=normal\ncputype=8086_prefetch\ncycles=fixed {a.cycles}\n[mixer]\nnosound=true
[autoexec]\n"""+'\n'.join(auto)+'\n')
    env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy')
    subprocess.run(['dosbox-x','-conf',str(conf),'-nopromptfolder','-fastlaunch'],env=env,
        check=True,capture_output=True,timeout=1800)
    ev=work/'EV';native=root/'evidence/NATIVE';bad=[]
    def need(cond,msg):
        print(('PASS ' if cond else 'FAIL ')+msg)
        if not cond:bad.append(msg)
    need((ev/'BAD.TXT').exists(),'invalid score rejected')
    need('PASS' in (ev/'COREQA.TXT').read_text(),'native core self-test')
    for t in ('HIT','MISS','CALM','RETRY','SPAM'):
        need((ev/f'{t}.TXT').read_bytes()==(native/f'{t}.TXT').read_bytes(),f'{t} lead/backing trace equals v5 native evidence')
    for t in ('SIMH','SIMM','SIMR'):
        need((ev/f'{t}.TXT').read_bytes()==(native/f'{t}.TXT').read_bytes(),f'{t} simulation equals v5 native evidence')
    for log in ('HIT','MISS','CALM','RETRY','SPAM','ESC'):
        text=(ev/f'{log}.LOG').read_text()
        need('restore_video=1 restore_keyboard=1' in text and 'cleanup_owned=0 keyboard_owned=0 video_owned=0 speaker_low=0' in text,f'{log} exit restores video, keyboard, sound, speaker')
    need('hits=64 misses=0' in (ev/'HIT.LOG').read_text(),'all-hit autoplay')
    # Logical colors 3, 4, 7 and 9 are palette-cycled for the left panel, so
    # nothing else on the playfield may use them.
    raw=(ev/'HIT.RAW').read_bytes();stray=0
    for y in range(200):
        row=raw[y*160:y*160+160]  # dumps are plain sequential rows
        for x in range(320):
            c=(row[x>>1]>>4) if not x&1 else (row[x>>1]&15)
            if c in (3,4,7,9) and not (4<=x<100 and 47<=y<147):stray+=1
    need(stray==0,f'cycled colors confined to the left panel ({stray} stray pixels)')
    fx=dict(t.split('=',1) for t in (ev/'HIT.LOG').read_text().split() if '=' in t)
    need(fx.get('fx_buffer')=='1' and int(fx.get('fx_switches','0'))>=4,'left panel buffer allocated and scenes rotate')
    need('hits=0 misses=64' in (ev/'MISS.LOG').read_text(),'all-miss run')
    for log,res in (('SKIP','result=1'),('SESC','result=0'),('SCALM','calm=1'),('FALLBACK','result=0')):
        text=(ev/f'{log}.LOG').read_text()
        need(res in text and 'sound_owned=0 keyboard_owned=0 video_owned=0 speaker_low=0' in text,f'splash {log} {res} and clean exit')
    if a.keep:shutil.copytree(ev,a.keep,dirs_exist_ok=True)
    print('FAIL' if bad else 'PASS: emulated DOS diagnostics')
    if a.keep and not bad:
        build['native_tests']='PASS baseline diagnostics and original synthetic playlist/word fixtures'
        build['source_head']=os.environ.get('GITHUB_SHA','local')
        (a.keep/'BUILD.json').write_text(json.dumps(build,indent=2)+'\n')
    shutil.rmtree(work)
    sys.exit(1 if bad else 0)
if __name__=='__main__':main()
