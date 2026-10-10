"""Standard MIDI file -> bounded Radio Shack Rave MML (three monophonic voices).

Python 3 standard library only. This is a conversion aid for MIDI files you are
entitled to use; it ships no music and the repository does not accept
copyrighted song files.

  python tools/midi_to_mml.py SONG.mid --list
  python tools/midi_to_mml.py SONG.mid -o SONG.mml --from-bar 9 --to-bar 25 \
      --voice 4:top --voice 7:bottom --voice 6:top --title "MY SONG" --check

A voice spec is TRACK[.CHANNEL][+TRACK[.CHANNEL]...]:top|bottom. Track and
channel numbers are the ones --list prints (channels are 1-16). `top` keeps the
highest sounding pitch of that source at every instant, `bottom` the lowest.
The first voice is the lead (the one that becomes the chart).

Everything lossy is reported, never silent: notes snap to a 1/GRID-beat grid,
polyphony is reduced to one pitch, notes that begin before the excerpt are
skipped, and notes that end after it are cut. Pitches that do not fit the PSG
range (MIDI 45..96) need an explicit whole-octave shift per voice, printed as
the --voice-transpose argument import_score.py must receive; nothing is clamped
unless you pass --fold, which moves single out-of-range notes by octaves and
counts them.
"""
import argparse
import re
import sys
from fractions import Fraction as F
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mml import parse, ScoreError  # noqa: E402

LOW, HIGH = 45, 96
MAX_BYTES = 8192
MAX_LEAD_EVENTS = 512
SHARP = ['c', 'c+', 'd', 'd+', 'e', 'f', 'f+', 'g', 'g+', 'a', 'a+', 'b']
VOLUMES = (100, 78, 65)


class MidiError(ValueError):
    pass


# ---------------------------------------------------------------- SMF reader
def _vlq(data, i):
    value = 0
    while True:
        if i >= len(data):
            raise MidiError('truncated variable-length quantity')
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i


def read_smf(data):
    """Return (ppq, tracks, tempos, timesigs). Notes are (start, end, pitch, channel)."""
    if data[:4] != b'MThd' or len(data) < 14:
        raise MidiError('not a Standard MIDI File')
    hlen = int.from_bytes(data[4:8], 'big')
    fmt = int.from_bytes(data[8:10], 'big')
    ntrk = int.from_bytes(data[10:12], 'big')
    div = int.from_bytes(data[12:14], 'big')
    if div & 0x8000:
        raise MidiError('SMPTE time division is not supported')
    if fmt not in (0, 1):
        raise MidiError(f'MIDI format {fmt} is not supported')
    pos = 8 + hlen
    tracks, tempos, sigs = [], [], []
    for index in range(ntrk):
        if data[pos:pos + 4] != b'MTrk':
            raise MidiError(f'track {index} header missing')
        size = int.from_bytes(data[pos + 4:pos + 8], 'big')
        body = data[pos + 8:pos + 8 + size]
        pos += 8 + size
        i, now, status = 0, 0, 0
        name, programs = '', {}
        open_, notes = {}, []
        while i < len(body):
            delta, i = _vlq(body, i)
            now += delta
            if i >= len(body):
                break
            b = body[i]
            if b == 0xFF:
                mtype = body[i + 1]
                length, i = _vlq(body, i + 2)
                payload = body[i:i + length]
                i += length
                if mtype == 0x03 and not name:
                    name = payload.decode('latin-1', 'replace')
                elif mtype == 0x51 and length == 3:
                    tempos.append((now, int.from_bytes(payload, 'big')))
                elif mtype == 0x58 and length >= 2:
                    sigs.append((now, payload[0], 1 << payload[1]))
                continue
            if b in (0xF0, 0xF7):
                length, i = _vlq(body, i + 1)
                i += length
                continue
            if b & 0x80:
                status = b
                i += 1
            elif not status:
                raise MidiError('data byte without status')
            kind, ch = status & 0xF0, status & 0x0F
            if kind in (0xC0, 0xD0):
                arg = body[i]
                i += 1
                if kind == 0xC0:
                    programs.setdefault(ch, arg)
                continue
            a, c = body[i], body[i + 1]
            i += 2
            if kind == 0x90 and c > 0:
                open_.setdefault((ch, a), []).append(now)
            elif kind in (0x80, 0x90):
                stack = open_.get((ch, a))
                if stack:
                    notes.append((stack.pop(0), now, a, ch))
        for (ch, a), starts in open_.items():
            notes.extend((s, now, a, ch) for s in starts)
        tracks.append(dict(index=index, name=name, notes=sorted(notes), programs=programs))
    return div, tracks, sorted(tempos), sorted(sigs)


# ------------------------------------------------------------------ helpers
def bar_ticks(ppq, sigs):
    """Ticks per bar from the first time signature (constant meter only)."""
    if len({(n, d) for _, n, d in sigs}) > 1:
        raise MidiError('meter changes inside the file; choose a constant-meter excerpt by tick or split it')
    n, d = (sigs[0][1], sigs[0][2]) if sigs else (4, 4)
    return ppq * 4 * n // d


def polyphony(notes):
    events = sorted([(s, 1) for s, _, _, _ in notes] + [(e, -1) for _, e, _, _ in notes],
                    key=lambda x: (x[0], x[1]))
    cur = best = 0
    for _, delta in events:
        cur += delta
        best = max(best, cur)
    return best


def list_tracks(ppq, tracks, tempos, sigs):
    bt = bar_ticks(ppq, sigs)
    print(f'ppq {ppq}, {bt // ppq if bt % ppq == 0 else bt / ppq:g} beats per bar, '
          f'tempo events {[(t, round(60e6 / u, 2)) for t, u in tempos[:6]]}')
    print('track.ch  program  notes  pitch    poly  bars(first-last)  name')
    for tr in tracks:
        for ch in sorted({c for *_, c in tr['notes']}):
            ns = [n for n in tr['notes'] if n[3] == ch]
            lo, hi = min(n[2] for n in ns), max(n[2] for n in ns)
            first, last = ns[0][0] // bt + 1, max(n[1] for n in ns) // bt + 1
            tag = ' (drums)' if ch == 9 else ''
            prog = tr['programs'].get(ch, '-')
            print(f'{tr["index"]:>3}.{ch + 1:<3} {str(prog):>7} {len(ns):>6}  {lo:>3}-{hi:<3} '
                  f'{polyphony(ns):>5}  {first:>5}-{last:<5}      {tr["name"][:24]}{tag}')


def parse_voice(spec, tracks):
    m = re.fullmatch(r'([0-9.+]+):(top|bottom)', spec)
    if not m:
        raise MidiError(f'bad voice spec {spec!r}; use TRACK[.CHANNEL][+...]:top|bottom')
    notes = []
    for part in m.group(1).split('+'):
        if '.' in part:
            t, c = part.split('.')
            t, c = int(t), int(c) - 1
        else:
            t, c = int(part), None
        if not 0 <= t < len(tracks):
            raise MidiError(f'track {t} does not exist')
        picked = [n for n in tracks[t]['notes'] if c is None or n[3] == c]
        if not picked:
            raise MidiError(f'no notes in {part}')
        notes.extend(picked)
    return sorted(notes), m.group(2)


def reduce_voice(notes, mode, t0, t1, unit):
    """Monophonic runs on a grid: list of (note_id, pitch, start_cell, cells)."""
    ncell = round((t1 - t0) / unit)
    cells = [None] * ncell
    stats = dict(skipped_before=0, cut_after=0, snapped_short=0)
    pick = max if mode == 'top' else min
    for nid, (s, e, p, _) in enumerate(notes):
        if e <= t0 or s >= t1:
            continue
        if s < t0 - unit / 2:
            stats['skipped_before'] += 1
            continue
        sc = max(0, round((s - t0) / unit))
        ec = round((min(e, t1) - t0) / unit)
        if e > t1:
            stats['cut_after'] += 1
        if ec <= sc:
            ec = sc + 1
            stats['snapped_short'] += 1
        for c in range(sc, min(ec, ncell)):
            cur = cells[c]
            if cur is None or pick(p, cur[1]) == p and p != cur[1]:
                cells[c] = (nid, p)
    runs, c = [], 0
    while c < ncell:
        if cells[c] is None:
            runs.append((None, None, c, 1))
            while c + 1 < ncell and cells[c + 1] is None:
                runs[-1] = (None, None, runs[-1][2], runs[-1][3] + 1)
                c += 1
        else:
            nid, p = cells[c]
            start = c
            while c + 1 < ncell and cells[c + 1] == (nid, p):
                c += 1
            runs.append((nid, p, start, c - start + 1))
        c += 1
    while runs and runs[-1][1] is None:
        runs.pop()  # trailing rests add nothing; the voice simply ends
    return runs, stats


def octave_shift(pitches, fold):
    """Whole-octave shift that fits every pitch in 45..96, else None."""
    lo, hi = min(pitches), max(pitches)
    for k in sorted(range(-6, 7), key=abs):
        if lo + 12 * k >= LOW and hi + 12 * k <= HIGH:
            return 12 * k
    if not fold:
        return None
    mid = (lo + hi) // 2
    return 12 * round((70 - mid) / 12)


def fold_pitch(p, shift):
    q = p + shift
    folded = 0
    while q < LOW:
        q += 12
        folded += 1
    while q > HIGH:
        q -= 12
        folded += 1
    return q - shift, folded


def pieces(units, grid):
    """Greedy legal MML durations (units of 1/grid beat) as (units, code, dots)."""
    table = []
    for code in (1, 2, 4, 8, 16, 32, 64):
        base = F(4 * grid, code)
        if base < 1:
            continue
        for dots, mult in ((0, F(1)), (1, F(3, 2)), (2, F(7, 4)), (3, F(15, 8))):
            u = base * mult
            if u.denominator == 1:
                table.append((int(u), code, dots))
    table.sort(reverse=True)
    out = []
    while units:
        for u, code, dots in table:
            if u <= units:
                out.append((u, code, dots))
                units -= u
                break
        else:
            raise MidiError('internal: cannot express duration')
    return out


def emit_voice(runs, grid, volume, tempo=None):
    """MML text for one voice plus its expected (start_beat, end_beat, pitch) notes."""
    seq = []  # (kind, pitch, code, dots, tie)
    for nid, p, start, cells in runs:
        for k, (u, code, dots) in enumerate(pieces(cells, grid)):
            seq.append(('n' if p is not None else 'r', p, code, dots, k > 0 and p is not None))
    uses = {}
    for _, _, code, _, _ in seq:
        uses[code] = uses.get(code, 0) + 1
    default = max(uses, key=uses.get) if uses else 4
    first = next((p for _, p, *_ in seq if p is not None), 60)
    octave = first // 12 - 1
    head = ''.join(([f't{tempo}'] if tempo else []) + [f'o{octave}', f'l{default}', f'v{volume}'])
    out, bar = [head], []
    unit_in_bar = 0
    pos = 0
    for kind, p, code, dots, tie in seq:
        tok = ''
        if kind == 'n':
            if not tie:
                o = p // 12 - 1
                if o == octave + 1:
                    tok += '>'
                elif o == octave - 1:
                    tok += '<'
                elif o != octave:
                    tok += f'o{o}'
                octave = o
            tok = ('&' if tie else tok) + SHARP[p % 12]
        else:
            tok = 'r'
        tok += '' if code == default else str(code)
        tok += '.' * dots
        bar.append(tok)
    out.append(''.join(bar))
    return ' '.join(out)


def expected_notes(runs, grid):
    return [(F(start, grid), F(start + cells, grid), p) for _, p, start, cells in runs if p is not None]


# --------------------------------------------------------------------- main
def arrange(smf, specs, *, from_bar=1, to_bar=0, grid=4, tempo=None, volumes=(), fold=False,
            title='', difficulty='normal', check=False):
    """Reduce a parsed MIDI (read_smf result) to bounded Rave MML; return a result dict.

    Raises MidiError with an explanatory message for anything that cannot be represented.
    """
    ppq, tracks, tempos, sigs = smf
    if not specs or not 1 <= len(specs) <= 3:
        raise MidiError('give 1..3 voice specs (the first is the lead)')
    if grid not in (1, 2, 4, 8, 16):
        raise MidiError('grid must be 1, 2, 4, 8 or 16 subdivisions per quarter note')
    if from_bar < 1:
        raise MidiError('from-bar must be at least 1')
    bt = bar_ticks(ppq, sigs)
    end_all = max((n[1] for tr in tracks for n in tr['notes']), default=0)
    if not end_all:
        raise MidiError('the file contains no notes')
    t0 = (from_bar - 1) * bt
    t_end = -(-end_all // bt) * bt
    t1 = min((to_bar - 1) * bt, t_end) if to_bar else t_end
    if t1 <= t0:
        raise MidiError('empty excerpt: to-bar must be after from-bar and inside the song')
    at_start = [u for t, u in tempos if t <= t0]
    start_tempo = at_start[-1] if at_start else (tempos[0][1] if tempos else 500000)
    inside = {u for t, u in tempos if t0 < t < t1}
    bpm = tempo or round(60e6 / start_tempo)
    if inside and not tempo and max(abs(60e6 / u - bpm) for u in inside) > 0.6:
        raise MidiError(f'tempo changes inside the excerpt ({sorted(round(60e6 / u, 1) for u in inside)} BPM); '
                        'pick a constant-tempo span or give an explicit tempo to flatten it')
    if not 32 <= bpm <= 255:
        raise MidiError(f'tempo {bpm} BPM is outside 32..255; give an explicit half- or double-time tempo')
    unit = ppq / grid
    voices, shifts = [], {}
    for vi, spec in enumerate(specs):
        notes, mode = parse_voice(spec, tracks)
        runs, stats = reduce_voice(notes, mode, t0, t1, unit)
        pitches = [p for _, p, _, _ in runs if p is not None]
        if not pitches:
            raise MidiError(f'voice {vi + 1} ({spec}) has no notes in bars {from_bar}..{to_bar or "end"}')
        shift = octave_shift(pitches, fold)
        folded = 0
        if shift is None:
            raise MidiError(f'voice {vi + 1} ({spec}) spans {min(pitches)}..{max(pitches)}, wider than the PSG range '
                            f'{LOW}..{HIGH}; narrow the source or allow octave folding of single notes')
        if fold:
            fixed = []
            for nid, p, s, c in runs:
                if p is not None:
                    p2, f = fold_pitch(p, shift)
                    folded += bool(f)
                    p = p2
                fixed.append((nid, p, s, c))
            runs = fixed
            pitches = [p for _, p, _, _ in runs if p is not None]
        vol = volumes[vi] if vi < len(volumes) else VOLUMES[vi]
        voices.append(dict(spec=spec, runs=runs, shift=shift, stats=stats, folded=folded, volume=vol,
                           notes=len(pitches) and sum(1 for r in runs if r[1] is not None),
                           lo=min(pitches), hi=max(pitches)))
        shifts[vi + 1] = shift
    parts = [emit_voice(v['runs'], grid, v['volume'], bpm if i == 0 else None) for i, v in enumerate(voices)]
    text = 'MML@' + ','.join(parts) + ';'
    if len(text) > MAX_BYTES:
        raise MidiError(f'{len(text)} bytes exceeds the {MAX_BYTES}-byte source limit '
                        f'(voices: {[len(x) for x in parts]}); use a shorter excerpt, a coarser grid, or fewer notes')
    parsed, _, duration = parse(text, parts_only=True)
    for vi, v in enumerate(voices):
        want = expected_notes(v['runs'], grid)
        got = [(n['start'] * bpm / 60, n['end'] * bpm / 60, n['note']) for n in parsed[vi] if n['note']]
        if got != want:
            raise MidiError(f'internal check failed: voice {vi + 1} text differs from the quantized notes')
    bars = (t1 - t0) // bt
    result = dict(text=text, bytes=len(text), bpm=bpm, grid=grid, from_bar=from_bar, bars=bars,
                  seconds=float(duration), voices=voices, shifts=shifts, difficulty=difficulty,
                  title=title, import_check=None)
    if check:
        from import_score import convert, clean_title
        import json
        result['title'] = clean_title(title or 'SONG')
        try:
            _, rep, _ = convert(text, lead='1', parts=list(range(1, len(voices) + 1)), difficulty=difficulty,
                                title=result['title'], voice_transpose={k: v for k, v in shifts.items() if v})
        except ScoreError as e:
            raise MidiError(f'import_score rejected the arrangement: {e}')
        result['import_check'] = json.loads(rep)
    return result


def import_command(result, mml_name='SONG.mml', rbg_name='OUT.RBG'):
    vt = ' '.join(f'--voice-transpose {k}:{v:+d}' for k, v in result['shifts'].items() if v)
    return (f'python tools/import_score.py {mml_name} {rbg_name} --lead 1 --difficulty {result["difficulty"]} '
            f'--title "{result["title"]}" {vt}').rstrip()


def describe(result):
    """Human-readable report lines shared by the CLI and the GUI."""
    lines = [f'excerpt bars {result["from_bar"]}..{result["from_bar"] + result["bars"]} ({result["bars"]} bars), '
             f'tempo {result["bpm"]} BPM, grid 1/{result["grid"] * 4} note, '
             f'{result["bytes"]} bytes ({MAX_BYTES} max), {result["seconds"]:.1f} s']
    for vi, v in enumerate(result['voices']):
        st = v['stats']
        lines.append(f' voice {vi + 1} ({"lead" if vi == 0 else "backing"}) {v["spec"]}: {v["notes"]} notes, '
                     f'source pitch {v["lo"]}..{v["hi"]}, shift {v["shift"]:+d} -> {v["lo"] + v["shift"]}..{v["hi"] + v["shift"]}; '
                     f'skipped carry-in {st["skipped_before"]}, cut at end {st["cut_after"]}, '
                     f'lengthened to one cell {st["snapped_short"]}' + (f', octave-folded {v["folded"]}' if v['folded'] else ''))
    r = result['import_check']
    if r:
        lines.append(f'check: import_score accepts it: {r["lead_events"]} lead events ({MAX_LEAD_EVENTS} max), '
                     f'{r["chart_taps"]} taps, {r["automatic_lead_events"]} automatic, {r["states"]} PSG states, {r["seconds"]} s')
    return lines


def build(args):
    ppq, tracks, tempos, sigs = read_smf(Path(args.midi).read_bytes())
    if args.list:
        list_tracks(ppq, tracks, tempos, sigs)
        return 0
    result = arrange((ppq, tracks, tempos, sigs), args.voice, from_bar=args.from_bar, to_bar=args.to_bar,
                     grid=args.grid, tempo=args.tempo, volumes=args.volume, fold=args.fold,
                     title=args.title or Path(args.midi).stem, difficulty=args.difficulty, check=args.check)
    if args.output:
        Path(args.output).write_text(result['text'] + '\n', encoding='ascii')
    print('\n'.join(l for l in describe(result) if not l.startswith('check:')))
    print('import: ' + import_command(result, args.output or 'SONG.mml'))
    if result['import_check']:
        print(next(l for l in describe(result) if l.startswith('check:')))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('midi', type=Path)
    p.add_argument('-o', '--output', type=Path)
    p.add_argument('--list', action='store_true', help='print tracks, channels, ranges and bar spans, then exit')
    p.add_argument('--voice', action='append', default=[], metavar='SPEC')
    p.add_argument('--from-bar', type=int, default=1, help='first bar, 1-based (default 1)')
    p.add_argument('--to-bar', type=int, default=0, help='bar after the last one (exclusive; default end of file)')
    p.add_argument('--grid', type=int, default=4, help='subdivisions per quarter note: 1,2,4,8,16 (default 4 = 16ths)')
    p.add_argument('--tempo', type=int, help='explicit quarter-note BPM (default: the file tempo)')
    p.add_argument('--volume', type=int, action='append', default=[], help='per voice 0..127 (default 100/78/65)')
    p.add_argument('--fold', action='store_true', help='octave-fold single out-of-range notes (counted, never silent)')
    p.add_argument('--difficulty', choices=('easy', 'normal', 'hard', 'full'), default='normal')
    p.add_argument('--title')
    p.add_argument('--check', action='store_true', help='also run the arrangement through import_score.convert')
    args = p.parse_args(argv)
    try:
        return build(args)
    except (MidiError, ScoreError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
