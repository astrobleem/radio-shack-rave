"""Native checks for far-memory song tables and the drum channel.

Builds two original synthetic songs with the converter:
  LONG.RBG   more lead notes and backing changes than the old 512/1024 caps
  DRUMS.RBG  a drum voice on the noise channel (RBG5)
then runs them in DOSBox-X (machine=tandy) and checks every required note is
hit, every backing state applied, every drum hit played in order, and the
exit cleanup. Emulator only; no physical timing claims.

    python tests/dos_songs.py --runtime RSRAVE.EXE [--keep DIR]
"""
from pathlib import Path
import argparse, os, shutil, struct, subprocess, sys, tempfile
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from import_score import convert

LONG = ('t240o4l16' + 'cdefgfedcegc>c<gec' * 62,
        't240o3l16' + 'cgeg' * 279,
        't240o3l32r' + 'l16' + 'eaca' * 278 + 'l32r')
DRUMS = ('t120o4l8' + 'cdefgfed' * 4,
         't120o3l2' + 'cgcg' * 2,
         't120l16o2' + 'c f+ f+ f+ d f+ f+ f+ c f+ c f+ d f+ a+ f+' * 2 + ' >c+4.<')


def drum_table(blob):
    ns, nt = struct.unpack_from('<HH', blob, 8)
    segs = struct.unpack_from('<H', blob, 12)[0]
    n = struct.unpack_from('<H', blob, 40)[0]
    base = 44 + ns * 12 + nt * 10 + segs * 12
    return [struct.unpack_from('<HBB', blob, base + 4 * i) for i in range(n)]


def logdict(path):
    return dict(t.split('=', 1) for t in path.read_text().split() if '=' in t)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--keep', type=Path)
    a = p.parse_args()
    work = Path(tempfile.mkdtemp(prefix='rave-songs-'))
    shutil.copy2(a.runtime, work / 'RSRAVE.EXE')
    long_blob, long_report, _ = convert(','.join(LONG), lead=1, difficulty='normal', title='LONG FIXTURE')
    drum_blob, drum_report, _ = convert(','.join(DRUMS), lead=1, parts=[1, 2], drums=3, title='DRUM FIXTURE')
    (work / 'LONG.RBG').write_bytes(long_blob)
    (work / 'DRUMS.RBG').write_bytes(drum_blob)
    (work / 'EV').mkdir()
    batch = ['@echo off',
             'RSRAVE LONG.RBG /AUTO', 'copy RUNLOG.TXT EV\\LONG.LOG > nul',
             'RSRAVE DRUMS.RBG /SIMH', 'copy SIMH.TXT EV\\DSIM.TXT > nul', 'copy SIMH.LOG EV\\DSIM.LOG > nul',
             'RSRAVE DRUMS.RBG /AUTO', 'copy RUNLOG.TXT EV\\DRUMS.LOG > nul', 'copy AUDIO.TXT EV\\DRUMS.TXT > nul',
             'echo DONE > EV\\DONE.TXT']
    (work / 'CHECK.BAT').write_text('\r\n'.join(batch) + '\r\n')
    conf = work / 'SONGS.CNF'
    conf.write_text('[sdl]\noutput=surface\n[dosbox]\nmachine=tandy\nmemsize=1\nquit warning=false\n'
                    '[cpu]\ncore=normal\ncputype=8086_prefetch\ncycles=fixed 12000\n'
                    '[mixer]\nnosound=true\n[autoexec]\nmount c ' + str(work) + '\nc:\ncall CHECK.BAT\nexit\n')
    subprocess.run(['dosbox-x', '-conf', str(conf), '-nopromptfolder', '-fastlaunch'],
                   env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                   capture_output=True, timeout=600)
    ev = work / 'EV'
    if a.keep:
        shutil.copytree(ev, a.keep, dirs_exist_ok=True)
    bad = []

    def need(cond, msg):
        print(('PASS ' if cond else 'FAIL ') + msg)
        if not cond:
            bad.append(msg)
    need((ev / 'DONE.TXT').exists(), 'song batch completed')
    import json
    lr = json.loads(long_report)
    lg = logdict(ev / 'LONG.LOG')
    need(lr['lead_events'] > 512 and lr['states'] > 1024,
         f"long fixture exceeds the old caps ({lr['lead_events']} lead notes, {lr['states']} states)")
    need(lg['hits'] == str(lr['chart_taps']) and lg['misses'] == '0',
         f"long song: every required note hit ({lg['hits']}/{lr['chart_taps']})")
    need(lg['state_cursor'] == f"{lr['states']}/{lr['states']}" and lg['final_tick'] == f"{lr['duration_ticks']}/{lr['duration_ticks']}",
         'long song: every backing state applied through the last tick')
    need(lg['lead_attacks'] == str(lr['lead_events']), 'long song: every lead note sounded')
    need(lg['restore_video'] == '1' and lg['cleanup_owned'] == '0' and lg['speaker_low'] == '0',
         'long song: clean exit')
    table = drum_table(drum_blob)
    want = [f'D {t} {k} {lv}' for t, k, lv in table]
    got = [l for l in (ev / 'DSIM.TXT').read_text().split('\n') if l.startswith('D ')]
    need(got == want, f'drums: simulation plays all {len(want)} hits in order with kind and level')
    dg = logdict(ev / 'DRUMS.LOG')
    need(dg['drums'] == str(len(table)) and dg['drum_hits'] == str(len(table)),
         f"drums: live play triggered {dg['drum_hits']}/{len(table)} hits on the noise channel")
    live = [l for l in (ev / 'DRUMS.TXT').read_text().split('\n') if l.startswith('D ')]
    need(live == want, 'drums: live hits match the converter table exactly')
    need(dg['hits'] == json.loads(drum_report)['chart_taps'].__str__() and dg['misses'] == '0', 'drums: lead gameplay unaffected')
    need(dg['restore_video'] == '1' and dg['cleanup_owned'] == '0' and dg['speaker_low'] == '0', 'drums: clean exit')
    shutil.rmtree(work)
    print('FAIL' if bad else 'PASS: far-memory songs and drum channel')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
