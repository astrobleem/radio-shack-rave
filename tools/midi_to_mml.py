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
from import_score import MAX_LEAD

LOW, HIGH = 45, 96
MAX_BYTES = 131072
MAX_LEAD_EVENTS = MAX_LEAD
MAX_MIDI_BYTES = 8 * 1024 * 1024
MAX_CELLS = 50000
MAX_CELL_WORK = 5000000
SHARP = ['c', 'c+', 'd', 'd+', 'e', 'f', 'f+', 'g', 'g+', 'a', 'a+', 'b']
VOLUMES = (100, 78, 65)


class MidiError(ValueError):
    pass


# ---------------------------------------------------------------- SMF reader
def _vlq(data, i):
    value = 0
    for _ in range(4):
        if i >= len(data):
            raise MidiError('truncated variable-length quantity')
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i
    raise MidiError('variable-length quantity exceeds four bytes')


def read_smf(data):
    """Return (ppq, tracks, tempos, timesigs). Notes are (start, end, pitch, channel)."""
    if data[:4] != b'MThd' or len(data) < 14:
        raise MidiError('not a Standard MIDI File')
    hlen = int.from_bytes(data[4:8], 'big')
    fmt = int.from_bytes(data[8:10], 'big')
    ntrk = int.from_bytes(data[10:12], 'big')
    div = int.from_bytes(data[12:14], 'big')
    if hlen < 6 or 8 + hlen > len(data):
        raise MidiError('invalid or truncated MIDI header')
    if not div:
        raise MidiError('zero PPQ time division')
    if not 1 <= ntrk <= 256 or (fmt == 0 and ntrk != 1):
        raise MidiError('invalid track count (maximum 256)')
    if div & 0x8000:
        raise MidiError('SMPTE time division is not supported')
    if fmt not in (0, 1):
        raise MidiError(f'MIDI format {fmt} is not supported')
    pos = 8 + hlen
    tracks, tempos, sigs = [], [], []
    for index in range(ntrk):
        if pos + 8 > len(data) or data[pos:pos + 4] != b'MTrk':
            raise MidiError(f'track {index} header missing')
        size = int.from_bytes(data[pos + 4:pos + 8], 'big')
        if pos + 8 + size > len(data):
            raise MidiError(f'track {index} payload truncated')
        body = data[pos + 8:pos + 8 + size]
        pos += 8 + size
        i, now, status = 0, 0, 0
        name, programs = '', {}
        open_, notes = {}, []
        while i < len(body):
            delta, i = _vlq(body, i)
            now += delta
            if i >= len(body):
                raise MidiError(f'track {index} event missing after delta')
            b = body[i]
            if b == 0xFF:
                if i + 1 >= len(body):
                    raise MidiError('truncated meta event')
                mtype = body[i + 1]
                length, i = _vlq(body, i + 2)
                if i + length > len(body):
                    raise MidiError('truncated meta payload')
                payload = body[i:i + length]
                i += length
                if mtype == 0x03 and not name:
                    name = payload.decode('latin-1', 'replace')
                elif mtype == 0x51 and length == 3:
                    tempo = int.from_bytes(payload, 'big')
                    if not tempo:
                        raise MidiError('zero microseconds-per-quarter tempo')
                    tempos.append((now, tempo))
                elif mtype == 0x58 and length >= 2:
                    if not payload[0] or payload[1] > 6:
                        raise MidiError('invalid time signature')
                    sigs.append((now, payload[0], 1 << payload[1]))
                continue
            if b in (0xF0, 0xF7):
                length, i = _vlq(body, i + 1)
                if i + length > len(body):
                    raise MidiError('truncated system-exclusive payload')
                i += length
                status = 0
                continue
            if b & 0x80:
                status = b
                i += 1
            elif not status:
                raise MidiError('data byte without status')
            kind, ch = status & 0xF0, status & 0x0F
            if kind not in (0x80, 0x90, 0xA0, 0xB0, 0xC0, 0xD0, 0xE0):
                raise MidiError(f'unsupported MIDI status 0x{status:02x}')
            count = 1 if kind in (0xC0, 0xD0) else 2
            if i + count > len(body) or any(v & 0x80 for v in body[i:i + count]):
                raise MidiError('truncated or invalid channel-event data')
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
    ticks = ppq * 4 * n
    if ticks % d or not ticks:
        raise MidiError('time signature cannot be expressed in this PPQ')
    return ticks // d


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
    m = re.fullmatch(r'(\d+(?:\.\d+)?(?:\+\d+(?:\.\d+)?)*)\:(top|bottom)', spec)
    if not m:
        raise MidiError(f'bad voice spec {spec!r}; use TRACK[.CHANNEL][+...]:top|bottom')
    notes = []
    for part in m.group(1).split('+'):
        if '.' in part:
            t, c = part.split('.')
            t, c = int(t), int(c) - 1
            if not 0 <= c <= 15:
                raise MidiError('voice channel must be in 1..16')
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
    if not 1 <= ncell <= MAX_CELLS:
        raise MidiError(f'excerpt exceeds {MAX_CELLS} grid cells; use a shorter excerpt')
    cells = [None] * ncell
    stats = dict(skipped_before=0, cut_after=0, snapped_short=0)
    pick = max if mode == 'top' else min
    work = 0
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
        work += max(0, min(ec, ncell) - sc)
        if work > MAX_CELL_WORK:
            raise MidiError('polyphonic reduction exceeds bounded work; narrow the excerpt or source')
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
def build(args):
    if args.output and Path(args.output).resolve() == Path(args.midi).resolve():
        raise MidiError('output must differ from the input MIDI file')
    if Path(args.midi).stat().st_size > MAX_MIDI_BYTES:
        raise MidiError(f'MIDI input exceeds {MAX_MIDI_BYTES} bytes')
    if args.from_bar < 1 or args.to_bar < 0:
        raise MidiError('bar numbers must be positive (to-bar 0 means end)')
    if any(not 0 <= v <= 127 for v in args.volume):
        raise MidiError('volume must be in 0..127')
    data = Path(args.midi).read_bytes()
    ppq, tracks, tempos, sigs = read_smf(data)
    if args.list:
        list_tracks(ppq, tracks, tempos, sigs)
        return 0
    if not args.voice or not 1 <= len(args.voice) <= 3:
        raise MidiError('give 1..3 --voice specs (the first is the lead)')
    if args.grid not in (1, 2, 4, 8, 16):
        raise MidiError('--grid must be 1, 2, 4, 8 or 16 subdivisions per quarter note')
    bt = bar_ticks(ppq, sigs)
    end_all = max((n[1] for tr in tracks for n in tr['notes']), default=0)
    if not end_all:
        raise MidiError('MIDI contains no positive-duration notes')
    t0 = (args.from_bar - 1) * bt
    t1 = min((args.to_bar - 1) * bt, -(-end_all // bt) * bt) if args.to_bar else -(-end_all // bt) * bt
    if t1 <= t0:
        raise MidiError('empty excerpt')
    in_range = [u for t, u in tempos if t < t1] or [500000]
    at_start = [u for t, u in tempos if t <= t0]
    start_tempo = at_start[-1] if at_start else (tempos[0][1] if tempos else 500000)
    inside = {u for t, u in tempos if t0 < t < t1}
    bpm = args.tempo if args.tempo is not None else round(60e6 / start_tempo)
    if inside and not args.tempo and max(abs(60e6 / u - bpm) for u in inside) > 0.6:
        raise MidiError(f'tempo changes inside the excerpt ({sorted(round(60e6 / u, 1) for u in inside)} BPM); '
                        'pick a constant-tempo span or pass --tempo to flatten it explicitly')
    if not 32 <= bpm <= 255:
        raise MidiError(f'tempo {bpm} BPM is outside 32..255; pass --tempo with an explicit half- or double-time value')
    if F(t1 - t0, ppq) * 60 / bpm > 600:
        raise MidiError('excerpt exceeds the 600-second runtime limit')
    unit = ppq / args.grid
    voices, shifts, report = [], {}, []
    for vi, spec in enumerate(args.voice):
        notes, mode = parse_voice(spec, tracks)
        runs, stats = reduce_voice(notes, mode, t0, t1, unit)
        pitches = [p for _, p, _, _ in runs if p is not None]
        if not pitches:
            raise MidiError(f'voice {vi + 1} ({spec}) has no notes in bars {args.from_bar}..{args.to_bar or "end"}')
        shift = octave_shift(pitches, args.fold)
        folded = 0
        if shift is None:
            raise MidiError(f'voice {vi + 1} ({spec}) spans {min(pitches)}..{max(pitches)}, wider than the PSG range '
                            f'{LOW}..{HIGH}; narrow the source or pass --fold to octave-fold single notes')
        if args.fold:
            fixed = []
            for nid, p, s, c in runs:
                if p is not None:
                    p2, f = fold_pitch(p, shift)
                    folded += bool(f)
                    p = p2
                fixed.append((nid, p, s, c))
            runs = fixed
        voices.append((spec, runs, shift, stats, folded))
        shifts[vi + 1] = shift
    total_cells = (t1 - t0) // unit
    parts = []
    for vi, (spec, runs, shift, stats, folded) in enumerate(voices):
        vol = args.volume[vi] if vi < len(args.volume) else VOLUMES[vi]
        parts.append(emit_voice(runs, args.grid, vol, bpm if vi == 0 else None))
    text = 'MML@' + ','.join(parts) + ';'
    if len(text) > MAX_BYTES:
        sizes = [len(p) for p in parts]
        raise MidiError(f'{len(text)} bytes exceeds the {MAX_BYTES}-byte source limit (voices: {sizes}); '
                        'use a shorter excerpt, a coarser --grid, or fewer notes')
    # Verify the text means exactly what was quantized.
    parsed, tmap, duration = parse(text, parts_only=True)
    for vi, (spec, runs, shift, _, _) in enumerate(voices):
        want = expected_notes(runs, args.grid)
        got = [(n['start'] * bpm / 60, n['end'] * bpm / 60, n['note']) for n in parsed[vi] if n['note']]
        if got != want:
            raise MidiError(f'internal check failed: voice {vi + 1} text differs from the quantized notes')
    bars = (t1 - t0) // bt
    print(f'excerpt bars {args.from_bar}..{args.from_bar + bars} ({bars} bars), tempo {bpm} BPM, grid 1/{args.grid * 4} note, '
          f'{len(text)} bytes ({MAX_BYTES} max), {float(duration):.1f} s')
    for vi, (spec, runs, shift, stats, folded) in enumerate(voices):
        notes = [r for r in runs if r[1] is not None]
        pitches = [r[1] for r in notes]
        role = 'lead' if vi == 0 else 'backing'
        print(f' voice {vi + 1} ({role}) {spec}: {len(notes)} notes, source pitch {min(pitches)}..{max(pitches)}, '
              f'shift {shift:+d} -> {min(pitches) + shift}..{max(pitches) + shift}; '
              f'skipped carry-in {stats["skipped_before"]}, cut at end {stats["cut_after"]}, '
              f'lengthened to one cell {stats["snapped_short"]}' + (f', octave-folded {folded}' if folded else ''))
    title = args.title or Path(args.midi).stem
    vt = ' '.join(f'--voice-transpose {k}:{v:+d}' for k, v in shifts.items() if v)
    print(f'import: python tools/import_score.py {args.output or "SONG.mml"} OUT.RBG --lead 1 '
          f'--difficulty {args.difficulty} --title "{title}" {vt}'.rstrip())
    if args.check:
        from import_score import convert, clean_title
        title = clean_title(title)
        try:
            blob, rep, _ = convert(text, lead='1', parts=list(range(1, len(voices) + 1)), difficulty=args.difficulty,
                                   title=title, voice_transpose={k: v for k, v in shifts.items() if v})
        except ScoreError as e:
            raise MidiError(f'import_score rejected the arrangement: {e}')
        import json
        r = json.loads(rep)
        print(f'check: import_score accepts it: {r["lead_events"]} lead events ({MAX_LEAD_EVENTS} max), '
              f'{r["chart_taps"]} taps, {r["automatic_lead_events"]} automatic, {r["states"]} PSG states, '
              f'{r["seconds"]} s')
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='ascii')
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
    except (MidiError, ScoreError, OSError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
