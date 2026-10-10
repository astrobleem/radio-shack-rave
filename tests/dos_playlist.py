"""Fresh CI runtime + original synthetic charts; actual DOS catalog and IRQ tests.
No physical timing claims. Compile with the workflow's existing pinned Watcom.
"""
from pathlib import Path
import argparse,os,subprocess,sys,tempfile,shutil,json,hashlib
from playlist_fixtures import populate
root=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--keep',type=Path);p.add_argument('--prepare-only',type=Path)
    a=p.parse_args();work=a.prepare_only or Path(tempfile.mkdtemp(prefix='rave-playlist-'))
    populate(work,a.runtime);(work/'EV').mkdir(exist_ok=True)
    src=(root/'src/BEAT.C').read_text()
    (work/'VALIDATOR.H').write_text(src[src.index('static int title_char'):src.index('static void music_step')])
    shutil.copy2(root/'tests/playlist_catalog.c',work/'CATQA.C')
    wc=Path(os.environ['WATCOM']);bindir=wc/('binnt' if os.name=='nt' else 'binl64')
    if not (bindir/('wcl.exe' if os.name=='nt' else 'wcl')).exists():bindir=wc/'binl'
    env=dict(os.environ,INCLUDE=str(wc/'h'));env['PATH']=str(bindir)+os.pathsep+env['PATH']
    cc=bindir/('wcl.exe' if os.name=='nt' else 'wcl')
    subprocess.run([str(cc),'-q','-bt=dos','-ms','-0','-ox','-i='+str(root/'src'),
                    '-fe=CATQA.EXE','CATQA.C'],cwd=work,env=env,check=True,capture_output=True)
    sys.path.insert(0,str(root/'tools'));from cap_dos_memory import cap
    b,_=cap((work/'CATQA.EXE').read_bytes());(work/'CATQA.EXE').write_bytes(b)
    batch=['@echo off','CATQA > EV\\CATQA.TXT','if errorlevel 1 goto failed']
    for mode in ['AUTO','MISS']:
        batch += [f'RSRAVE LONG.RBG /{mode} /SHOT','if errorlevel 1 goto failed',
                  f'copy RUNLOG.TXT EV\\{mode}.LOG > nul',f'copy AUDIO.TXT EV\\{mode}.TXT > nul',
                  f'copy FRAME.RAW EV\\{mode}.RAW > nul']
    # Escape in the demo returns to the title; a second Escape there exits.
    # DEMO waits past the first demo, which now returns to the splash.
    for folder,wait in [('EMPTY',3),('INVALID',3),('DEMO',12)]:
        batch += ['cd '+folder,f'AUTOTYPE -w {wait} -p 2 esc esc','..\\RSRAVE /DEMO',
                  f'copy RUNLOG.TXT ..\\EV\\{folder}.LOG > nul','cd ..']
    # AUTOTYPE Start joins the previous worker. A comma-only zero-delay sequence
    # touches no key events and lets the Escape break finish before shutdown.
    batch += ['AUTOTYPE -w 0 -p 0 ,','echo DONE > EV\\DONE.TXT','goto end',
              ':failed','cd \\','echo FAILED > EV\\DONE.TXT',':end']
    (work/'CHECK.BAT').write_text('\n'.join(batch)+'\n')
    if a.prepare_only:print('Prepared synthetic fixtures and native catalog; no emulator launched.');return
    conf=work/'PLAYLIST.CNF'
    conf.write_text('[sdl]\noutput=surface\n[dosbox]\nmachine=tandy\nmemsize=1\nquit warning=false\n'
                    '[cpu]\ncore=normal\ncputype=8086_prefetch\ncycles=fixed 12000\n'
                    '[mixer]\nnosound=true\n[autoexec]\nmount c '+str(work)+'\nc:\ncall CHECK.BAT\nexit\n')
    run=subprocess.run(['dosbox-x','-conf',str(conf),'-nopromptfolder','-fastlaunch'],
                       env=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy'),
                       capture_output=True,timeout=120)
    ev=work/'EV';(ev/'HOST-STDOUT.txt').write_bytes(run.stdout);(ev/'HOST-STDERR.txt').write_bytes(run.stderr)
    if a.keep:shutil.copytree(ev,a.keep,dirs_exist_ok=True)
    assert run.returncode==0,'DOSBox-X host failure: '+str(run.returncode)
    assert (ev/'DONE.TXT').read_text().strip()=='DONE'
    assert 'PASS native DOS enumeration' in (ev/'CATQA.TXT').read_text()
    logs={}
    for mode in ['AUTO','MISS','EMPTY','INVALID','DEMO']:
        f=dict(t.split('=',1) for t in (ev/(mode+'.LOG')).read_text().split() if '=' in t);logs[mode]=f
        for k,v in [('restore_video',1),('restore_keyboard',1),('cleanup_owned',0),('keyboard_owned',0),
                    ('video_owned',0),('speaker_low',0),('overflow',0),('queue_overflow',0),('silent_hits',0)]:
            assert f[k]==str(v),(mode,k,f[k])
        if mode in ['AUTO','MISS']:
            assert f['hits']==('22' if mode=='AUTO' else '0') and f['misses']==('0' if mode=='AUTO' else '22')
            assert f['state_cursor']=='2/2' and f['final_tick']=='240/240'
            assert len((ev/(mode+'.RAW')).read_bytes())==32000
            expected=[]
            if mode=='AUTO':
                for t in range(10,230,10):expected += [f'L {t} 200 3',f'L {t+5} 0 15']
            expected += ['B 0 300 3 400 4','B 240 0 15 0 15']
            assert (ev/(mode+'.TXT')).read_text().splitlines()==expected,mode
        else:
            assert f['reason']=='1' and int(f['IRQ1'])>0 and int(f['makes'])>0
            if mode in ['EMPTY','INVALID']:assert f['title']=='ORIGINAL'
            else:
                assert int(f['music_updates'])>=2 and f['hits']=='1' and f['lead_attacks']=='1'
                assert f['demos']=='1' and int(f['splashes'])>=1,(f['demos'],f['splashes'])
    report={'result':'PASS original synthetic native playlist/word fixtures',
            'runtime_sha256':hashlib.sha256(a.runtime.read_bytes()).hexdigest(),'cases':logs,
            'physical':'Not tested; emulator cycles are not physical speed evidence'}
    if a.keep:(a.keep/'QUALIFICATION.json').write_text(json.dumps(report,indent=2)+'\n')
    shutil.rmtree(work);print(report['result'])

if __name__=='__main__':main()
