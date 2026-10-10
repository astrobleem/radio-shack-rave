"""Native high score checks in DOSBox-X (machine=tandy).

/HISCORE autoplays a song as a real game, then types C L D Enter at the
initials prompt. Checks: ranks 1..5 fill in order with ties below; a sixth
equal score does not enter; RAVE.HI round-trips; a malformed file reads as
empty and is replaced on the next save; a RAVE.HI that cannot be written fails
without stopping the game; ordinary scripted play never creates RAVE.HI.

    python tests/dos_hiscore.py --runtime RSRAVE.EXE [--keep DIR]
"""
from pathlib import Path
import argparse, os, shutil, struct, subprocess, sys, tempfile
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from import_score import convert

SHORT = 't150o4l8cdefgfedcegc,t150o3l2cgc'


def dosbox(work, batch, name):
    (work / (name + '.BAT')).write_text('\r\n'.join(['@echo off'] + batch) + '\r\n')
    conf = work / (name + '.CNF')
    conf.write_text('[sdl]\noutput=surface\n[dosbox]\nmachine=tandy\nmemsize=1\nquit warning=false\n'
                    '[cpu]\ncore=normal\ncputype=8086_prefetch\ncycles=fixed 12000\n'
                    '[mixer]\nnosound=true\n[autoexec]\nmount c ' + str(work) + '\nc:\ncall ' + name + '.BAT\nexit\n')
    subprocess.run(['dosbox-x', '-conf', str(conf), '-nopromptfolder', '-fastlaunch'],
                   env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'),
                   capture_output=True, timeout=600)


def table(path):
    b = path.read_bytes()
    assert b[:4] == b'RHI1'
    n = struct.unpack_from('<H', b, 4)[0]
    assert len(b) == 6 + n * 54
    songs = []
    for i in range(n):
        rec = b[6 + i * 54:6 + (i + 1) * 54]
        rows = [(rec[4 + k * 10:7 + k * 10].decode(), chr(rec[7 + k * 10]),
                 struct.unpack_from('<IH', rec, 8 + k * 10)) for k in range(5)]
        songs.append(rows)
    return songs


def logdict(path):
    return dict(t.split('=', 1) for t in path.read_text().split() if '=' in t)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--keep', type=Path)
    a = p.parse_args()
    work = Path(tempfile.mkdtemp(prefix='rave-hi-'))
    shutil.copy2(a.runtime, work / 'RSRAVE.EXE')
    (work / 'SHORT.RBG').write_bytes(convert(SHORT, lead=1, title='SHORT FIXTURE')[0])
    (work / 'EV').mkdir()
    bad = []

    def need(cond, msg):
        print(('PASS ' if cond else 'FAIL ') + msg)
        if not cond:
            bad.append(msg)

    # No redirection here: DOS creates a redirected file even when "if" is false.
    batch = ['RSRAVE SHORT.RBG /AUTO', 'if exist RAVE.HI copy RAVE.HI EV\\AUTO.TXT']
    for i in range(6):
        batch += ['RSRAVE SHORT.RBG /HISCORE', f'copy RUNLOG.TXT EV\\RUN{i}.LOG > nul']
    dosbox(work, batch, 'FILL')
    need(not (work / 'EV/AUTO.TXT').exists(), 'scripted /AUTO play never writes RAVE.HI')
    for i in range(5):
        d = logdict(work / f'EV/RUN{i}.LOG')
        need(d.get('hiscore_state') == '2' and d.get('hiscore_rank') == str(i + 1) and d.get('hiscore_initials') == 'CLD',
             f'run {i + 1}: saved as CLD at rank {i + 1}')
    d = logdict(work / 'EV/RUN5.LOG')
    need(d.get('hiscore_state') == '0' and d.get('hiscore_rank') == '0', 'run 6: an equal score does not enter a full board')
    t = table(work / 'RAVE.HI')
    score = int(logdict(work / 'EV/RUN0.LOG')['score'])
    need(len(t) == 1 and all(r[0] == 'CLD' and r[2][0] == score for r in t[0]),
         f'RAVE.HI holds one song with five CLD rows at {score}')
    need(all(r[1] in 'SABCD' and 0 < r[2][1] <= 1000 for r in t[0]), 'grades and accuracy stored')

    (work / 'RAVE.HI').write_bytes(b'RHI1\xff\xffgarbage')
    dosbox(work, ['RSRAVE SHORT.RBG /HISCORE', 'copy RUNLOG.TXT EV\\CORRUPT.LOG > nul'], 'CORRUPT')
    d = logdict(work / 'EV/CORRUPT.LOG')
    need(d.get('hiscore_state') == '2' and d.get('hiscore_rank') == '1', 'malformed RAVE.HI reads as empty; next save ranks 1')
    need(len(table(work / 'RAVE.HI')) == 1, 'malformed file replaced by a valid table')

    # Unwritable save: a directory named RAVE.HI cannot be opened for writing
    # (file permissions would not stop an emulator running as root).
    saved = (work / 'RAVE.HI').read_bytes()
    (work / 'RAVE.HI').unlink()
    (work / 'RAVE.HI').mkdir()
    dosbox(work, ['RSRAVE SHORT.RBG /HISCORE', 'copy RUNLOG.TXT EV\\RO.LOG > nul'], 'READONLY')
    d = logdict(work / 'EV/RO.LOG')
    need(d.get('hiscore_state') == '3', 'unwritable RAVE.HI: save fails and is reported')
    need(d.get('restore_video') == '1' and d.get('cleanup_owned') == '0' and d.get('speaker_low') == '0',
         'unwritable RAVE.HI: game still exits cleanly')
    need((work / 'RAVE.HI').is_dir(), 'unwritable RAVE.HI left alone')
    (work / 'RAVE.HI').rmdir()
    (work / 'RAVE.HI').write_bytes(saved)

    if a.keep:
        shutil.copytree(work / 'EV', a.keep, dirs_exist_ok=True)
        shutil.copy2(work / 'RAVE.HI', a.keep / 'RAVE.HI')
    shutil.rmtree(work)
    print('FAIL' if bad else 'PASS: high score table')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
