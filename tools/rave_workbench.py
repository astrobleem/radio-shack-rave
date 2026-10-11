"""Rave Workbench: a small Tk window to download a MIDI, pick tracks, choose a bar range,
listen to a square-wave preview and save MML / RBG files for Radio Shack Rave.

Python 3 standard library only (Tk comes with python.org installers for Windows and macOS).

  python tools/rave_workbench.py [SONG.mid]

Flow: download or open a MIDI -> select a track in the list and press "<- selected" on a voice
row -> pick the bar range (click the overview: left = first bar, right = last bar) -> Arrange ->
Play -> Save MML / Save RBG. Voice 1 is the lead (it becomes the chart). Everything the
converter changes is listed in the report box; nothing is clamped silently.

Downloads go to midi-local/ and saves to SONGS/ by default; both are git-ignored. These are
third-party files: check you may use them, and do not commit what you make from them.
The window code is tiny; the logic lives in plain functions at the top of this file.
"""
import array
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_midi_list as fetch  # noqa: E402
import midi_to_mml as m2m  # noqa: E402
from midi_to_mml import MidiError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ['piano', 'chromatic perc', 'organ', 'guitar', 'bass', 'strings', 'ensemble', 'brass',
            'reed', 'pipe', 'synth lead', 'synth pad', 'synth fx', 'ethnic', 'percussive', 'sound fx']
SEARCH_URL = 'https://bitmidi.com/search?q='
GRIDS = ('1', '2', '4', '8', '16')
VOICE_COLORS = ('#ff5a5a', '#4aa3ff', '#5ad37a')


# ------------------------------------------------------------------ pure logic
def track_rows(smf):
    """One row per (track, channel) that has notes, keyed 'T.C' with C 1-based like --list."""
    ppq, tracks, tempos, sigs = smf
    bt = m2m.bar_ticks(ppq, sigs)
    rows = []
    for tr in tracks:
        for ch in sorted({n[3] for n in tr['notes']}):
            ns = [n for n in tr['notes'] if n[3] == ch]
            prog = tr['programs'].get(ch)
            rows.append(dict(
                key=f'{tr["index"]}.{ch + 1}', notes=len(ns), lo=min(n[2] for n in ns), hi=max(n[2] for n in ns),
                poly=m2m.polyphony(ns), first=ns[0][0] // bt + 1, last=max(n[1] for n in ns) // bt + 1,
                drums=ch == 9, program=prog,
                family='drums' if ch == 9 else ('?' if prog is None else FAMILIES[prog // 8]),
                name=tr['name'].strip(), mean=sum(n[2] for n in ns) / len(ns)))
    return rows


def song_info(smf):
    ppq, tracks, tempos, sigs = smf
    bt = m2m.bar_ticks(ppq, sigs)
    end = max((n[1] for tr in tracks for n in tr['notes']), default=0)
    bars = -(-end // bt) if end else 0
    bpm = round(60e6 / tempos[0][1]) if tempos else 120
    return dict(bars=bars, bpm=bpm, tempo_changes=len({u for _, u in tempos}) > 1,
                beats=bt / ppq)


def bar_density(smf):
    """Note onsets per bar over all pitched tracks (for the overview strip)."""
    ppq, tracks, tempos, sigs = smf
    bt = m2m.bar_ticks(ppq, sigs)
    bars = song_info(smf)['bars']
    counts = [0] * bars
    for tr in tracks:
        for s, e, p, ch in tr['notes']:
            if ch != 9 and s // bt < bars:
                counts[s // bt] += 1
    return counts


def suggest_voices(rows):
    """A guess, not a verdict: busiest single-line pitched track as lead (top), lowest as bass
    (bottom), next busiest as voice 3. Always check by ear."""
    ok = [r for r in rows if not r['drums'] and r['family'] != 'sound fx' and r['notes'] >= 8
          and r['hi'] - r['lo'] <= m2m.HIGH - m2m.LOW]  # must fit the PSG range without folding
    mono = [r for r in ok if r['poly'] <= 1]
    pool = mono or ok
    if not pool:
        return []
    lead_pool = [r for r in pool if r['mean'] >= 55] or pool
    lead = max(lead_pool, key=lambda r: r['notes'])
    rest = [r for r in pool if r is not lead and r['notes'] * 4 >= lead['notes']]
    out = [(lead['key'], 'top')]
    bass = min(rest, key=lambda r: r['mean'], default=None)
    if bass and bass['mean'] < lead['mean'] - 7:
        out.append((bass['key'], 'bottom'))
        rest = [r for r in rest if r is not bass]
    if rest:
        out.append((max(rest, key=lambda r: r['notes'])['key'], 'top'))
    return out


def _int(text, label, default=None, lo=None, hi=None):
    text = str(text).strip()
    if not text:
        if default is None:
            raise MidiError(f'{label} is required')
        return default
    try:
        v = int(text)
    except ValueError:
        raise MidiError(f'{label} must be a whole number, not {text!r}')
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise MidiError(f'{label} must be {lo}..{hi}')
    return v


def gui_params(v):
    """Form values (all strings/bools) -> (specs, arrange kwargs). Raises MidiError."""
    specs = []
    for i in (1, 2, 3):
        src = v.get(f'src{i}', '').strip().replace(' ', '')
        if src:
            specs.append(f'{src}:{v.get(f"mode{i}", "top")}')
        elif i == 1:
            raise MidiError('voice 1 (the lead) needs a track: select one in the list and press "<- selected"')
        elif any(v.get(f'src{j}', '').strip() for j in range(i + 1, 4)):
            raise MidiError(f'voice {i} is empty but a later voice is set; fill voices in order')
    last = _int(v.get('last_bar', ''), 'last bar', 0, 1)
    vols = []
    for i in (1, 2, 3):
        vols.append(_int(v.get(f'vol{i}', ''), f'voice {i} volume', m2m.VOLUMES[i - 1], 0, 127))
    kw = dict(from_bar=_int(v.get('first_bar', ''), 'first bar', 1, 1), to_bar=last + 1 if last else 0,
              grid=_int(v.get('grid', '4'), 'grid', 4), volumes=tuple(vols), fold=bool(v.get('fold')),
              difficulty=v.get('difficulty', 'normal'), title=v.get('title', '').strip(),
              tempo=_int(v.get('tempo', ''), 'tempo', 0, 32, 255) or None, check=True)
    kw['chart_policy']='metrical'
    return specs, kw


def safe_name(title):
    name = re.sub(r'[^A-Za-z0-9_-]+', '_', title.strip()).strip('_')[:40] or 'song'
    return 'song_' + name if fetch.reserved_name(name) else name


def list_local(root):
    root = Path(root)
    return sorted(p for p in root.glob('*/*.mid')) + sorted(p for p in root.glob('*.mid')) if root.is_dir() else []


def note_freq(pitch):
    return 440.0 * 2 ** ((pitch - 69) / 12)


def render_wav(result, path, *, rate=22050, max_seconds=120):
    """Square-wave preview (what the PSG roughly sounds like), shifted as the game will play it."""
    from midi_preview import render_game
    return render_game(result,path,rate,max_seconds)



def player_command(path, platform=None, which=shutil.which):
    """Argv list that plays a WAV on this OS, or None (the caller then offers Save WAV)."""
    platform = platform or sys.platform
    path = str(path)
    if platform == 'darwin' and which('afplay'):
        return ['afplay', path]
    for exe, extra in (('paplay', []), ('aplay', ['-q']), ('ffplay', ['-nodisp', '-autoexit', '-loglevel', 'quiet']),
                       ('play', ['-q'])):
        if which(exe):
            return [exe, *extra, path]
    return None


def piano_roll_rects(result, width, height):
    """(voice_index, x0, y0, x1, y1) boxes for the game-pitch piano roll; y spans PSG 45..96."""
    cells = max(1, max((r[2] + r[3] for v in result['voices'] for r in v['runs']), default=1))
    rows = m2m.HIGH - m2m.LOW + 1
    rects = []
    for vi, v in enumerate(result['voices']):
        for _, p, start, n in v['runs']:
            if p is None:
                continue
            q = p + v['shift']
            y = (m2m.HIGH - q) / rows * height
            rects.append((vi, start / cells * width, y, max(1.0, (start + n) / cells * width), y + height / rows))
    return rects


def save_outputs(result, out_dir, name):
    """Write NAME.mml and the game score NAME.RBG (+ .json report, .events.json). Returns paths."""
    import json
    from midi_arrangement import convert_arrangement
    if safe_name(name) != name:
        raise MidiError('unsafe output name')
    blob, report, events = convert_arrangement(result['arrangement'])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mml = out_dir / f'{name}.mml'
    mml.write_text(result['text'] + '\n', encoding='ascii')
    mml.with_suffix('.arrangement.json').write_bytes((json.dumps(result['arrangement'],indent=2)+'\n').encode())
    rbg = out_dir / f'{name}.RBG'
    rbg.write_bytes(blob)
    rbg.with_suffix('.json').write_bytes(report)
    rbg.with_suffix('.events.json').write_bytes(events)
    return mml, rbg


def limits_line(result):
    r = result['import_check'] or {}
    if not r:
        return f'{result["bytes"]}/{m2m.MAX_BYTES} bytes'
    return (f'{result["bytes"]}/{m2m.MAX_BYTES} bytes   {r["lead_events"]}/{m2m.MAX_LEAD_EVENTS} lead events   '
            f'{r["chart_taps"]} taps   {r["states"]} states   {r["seconds"]} s')


# ------------------------------------------------------------------------- GUI
def run(initial=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title('Rave Workbench')
    root.geometry('1200x800')
    S = dict(smf=None, rows=[], dens=[], info=None, result=None, path=None, proc=None, wav=None)
    q = queue.Queue()
    var = {k: tk.StringVar() for k in ('url', 'status', 'first_bar', 'last_bar', 'tempo', 'title', 'grid',
                                         'difficulty', 'src1', 'src2', 'src3', 'mode1', 'mode2', 'mode3',
                                         'vol1', 'vol2', 'vol3', 'local')}
    fold = tk.BooleanVar(value=False)
    var['grid'].set('4')
    var['difficulty'].set('normal')
    for i in (1, 2, 3):
        var[f'mode{i}'].set('bottom' if i == 2 else 'top')
        var[f'vol{i}'].set(str(m2m.VOLUMES[i - 1]))

    def say(text):
        var['status'].set(text)

    # --- source
    top = ttk.LabelFrame(root, text='1  Get a MIDI')
    top.pack(fill='x', padx=8, pady=4)
    ttk.Entry(top, textvariable=var['url'], width=60).grid(row=0, column=0, padx=4, pady=3, sticky='we')
    ttk.Button(top, text='Download URL', command=lambda: start_download()).grid(row=0, column=1, padx=2)
    ttk.Button(top, text='Open file...', command=lambda: open_dialog()).grid(row=0, column=2, padx=2)
    ttk.Button(top, text='Fetch the 4 defaults', command=lambda: start_defaults()).grid(row=0, column=3, padx=2)
    ttk.Button(top, text='Search BitMidi in browser', command=lambda: webbrowser.open(
        SEARCH_URL + (var['title'].get() or 'stayin alive').replace(' ', '+'))).grid(row=0, column=4, padx=2)
    local = ttk.Combobox(top, textvariable=var['local'], width=50, state='readonly')
    local.grid(row=1, column=0, padx=4, pady=3, sticky='we')
    ttk.Button(top, text='Load selected', command=lambda: load_path(Path(var['local'].get()))
               if var['local'].get() else None).grid(row=1, column=1, padx=2)
    ttk.Label(top, text='Paste a direct .mid link or a BitMidi song page link.  Files: midi-local/ (git-ignored)').grid(
        row=1, column=2, columnspan=3, sticky='w')
    top.columnconfigure(0, weight=1)

    # --- tracks + overview
    mid = ttk.LabelFrame(root, text='2  Tracks (select one, then use "<- selected" on a voice)')
    mid.pack(fill='both', expand=True, padx=8, pady=4)
    cols = ('key', 'family', 'notes', 'range', 'poly', 'bars', 'name')
    tree = ttk.Treeview(mid, columns=cols, show='headings', height=8, selectmode='extended')
    for c, w in zip(cols, (60, 110, 60, 80, 50, 90, 360)):
        tree.heading(c, text={'key': 'track.ch', 'family': 'instrument', 'range': 'pitch'}.get(c, c))
        tree.column(c, width=w, anchor='w')
    tree.pack(side='left', fill='both', expand=True)
    sb = ttk.Scrollbar(mid, command=tree.yview)
    sb.pack(side='left', fill='y')
    tree.configure(yscrollcommand=sb.set)

    over = tk.Canvas(root, height=54, bg='#15151c', highlightthickness=0)
    over.pack(fill='x', padx=8)
    ttk.Label(root, text='Overview: note density per bar.  Left-click = first bar, right-click = last bar.').pack(anchor='w', padx=10)

    # --- voices + excerpt
    ctl = ttk.LabelFrame(root, text='3  Voices and excerpt')
    ctl.pack(fill='x', padx=8, pady=4)
    for i, name in enumerate(('Lead (chart)', 'Voice 2', 'Voice 3'), 1):
        ttk.Label(ctl, text=name, foreground=VOICE_COLORS[i - 1]).grid(row=i - 1, column=0, sticky='w', padx=4)
        ttk.Entry(ctl, textvariable=var[f'src{i}'], width=18).grid(row=i - 1, column=1, padx=2, pady=1)
        ttk.Button(ctl, text='<- selected', command=lambda i=i: pick(i)).grid(row=i - 1, column=2, padx=2)
        ttk.Combobox(ctl, textvariable=var[f'mode{i}'], values=('top', 'bottom'), width=7, state='readonly').grid(row=i - 1, column=3, padx=2)
        ttk.Label(ctl, text='vol').grid(row=i - 1, column=4)
        ttk.Entry(ctl, textvariable=var[f'vol{i}'], width=4).grid(row=i - 1, column=5, padx=2)
    ttk.Button(ctl, text='Suggest voices (a guess)', command=lambda: suggest()).grid(row=0, column=6, padx=10)
    ttk.Button(ctl, text='Clear', command=lambda: [var[f'src{i}'].set('') for i in (1, 2, 3)]).grid(row=1, column=6)
    x = 7
    for label, key, w in (('first bar', 'first_bar', 5), ('last bar', 'last_bar', 5), ('tempo', 'tempo', 5), ('title', 'title', 24)):
        ttk.Label(ctl, text=label).grid(row=0, column=x, padx=(10, 2))
        ttk.Entry(ctl, textvariable=var[key], width=w).grid(row=0, column=x + 1)
        x += 2
    ttk.Label(ctl, text='grid').grid(row=1, column=7, padx=(10, 2))
    ttk.Combobox(ctl, textvariable=var['grid'], values=GRIDS, width=4, state='readonly').grid(row=1, column=8)
    ttk.Label(ctl, text='difficulty').grid(row=1, column=9, padx=(10, 2))
    ttk.Combobox(ctl, textvariable=var['difficulty'], values=('easy', 'normal', 'hard', 'full'), width=7,
                 state='readonly').grid(row=1, column=10)
    ttk.Checkbutton(ctl, text='fold stray octaves', variable=fold).grid(row=1, column=11, columnspan=2, padx=8)

    # --- actions
    act = ttk.Frame(root)
    act.pack(fill='x', padx=8)
    for text, cmd in (('Arrange', lambda: arrange()), ('Play', lambda: play()), ('Stop', lambda: stop()),
                      ('Save WAV...', lambda: save_wav()), ('Save MML', lambda: save('mml')), ('Save MML + RBG', lambda: save('rbg'))):
        ttk.Button(act, text=text, command=cmd).pack(side='left', padx=2, pady=3)
    ttk.Label(act, textvariable=var['status']).pack(side='left', padx=10)

    roll = tk.Canvas(root, height=190, bg='#101018', highlightthickness=0)
    roll.pack(fill='x', padx=8, pady=2)
    report = tk.Text(root, height=8, wrap='word', font=('Consolas', 9) if os.name == 'nt' else ('Courier', 9))
    report.pack(fill='both', padx=8, pady=4)

    # --- behaviour
    def refresh_local():
        files = [str(p) for p in list_local(ROOT / 'midi-local')]
        local['values'] = files
        if files and not var['local'].get():
            var['local'].set(files[0])

    def load_path(path):
        try:
            if Path(path).stat().st_size > m2m.MAX_MIDI_BYTES:
                raise MidiError('MIDI input exceeds 8 MiB')
            data = Path(path).read_bytes()
            smf = m2m.read_smf(data)
            rows, info, dens = track_rows(smf), song_info(smf), bar_density(smf)
        except (OSError, MidiError) as e:
            messagebox.showerror('Cannot read MIDI', str(e))
            return
        import hashlib
        source=dict(path=str(Path(path).resolve()),bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                    licensing='Not established; private use only')
        S.update(smf=smf, rows=rows, info=info, dens=dens, path=Path(path), result=None,source=source)
        tree.delete(*tree.get_children())
        for r in rows:
            tree.insert('', 'end', iid=r['key'], values=(
                r['key'], r['family'] + (f' ({r["program"]})' if r['program'] is not None and not r['drums'] else ''),
                r['notes'], f'{r["lo"]}-{r["hi"]}', r['poly'], f'{r["first"]}-{r["last"]}', r['name']))
        var['title'].set(re.sub(r'[_-]+', ' ', Path(path).stem).upper()[:24])
        var['first_bar'].set('1')
        var['last_bar'].set(str(info['bars']))
        var['tempo'].set('')
        draw_overview()
        roll.delete('all')
        note = ' - tempo changes preserved in arrangement sidecar' if info['tempo_changes'] else ''
        hits=sum(d['channel']==9 for tr in smf[1] for d in tr.get('attacks',[]))
        say(f'{Path(path).name}: {info["bars"]} bars, {info["bpm"]} BPM, {hits} drum attacks (automatic noise import){note}')

    def draw_overview():
        over.delete('all')
        d = S['dens']
        w = max(over.winfo_width(), 400)
        if not d:
            return
        peak = max(d) or 1
        bw = w / len(d)
        try:
            a, b = int(var['first_bar'].get() or 1), int(var['last_bar'].get() or len(d))
        except ValueError:
            a, b = 1, len(d)
        for i, c in enumerate(d):
            h = 4 + 44 * c / peak
            on = a <= i + 1 <= b
            over.create_rectangle(i * bw, 52 - h, (i + 1) * bw - 0.5, 52, fill='#ffb454' if on else '#4a4a5a', width=0)

    def bar_at(ev):
        n = len(S['dens'])
        return max(1, min(n, int(ev.x / max(over.winfo_width(), 1) * n) + 1)) if n else 1

    over.bind('<Button-1>', lambda e: (var['first_bar'].set(str(bar_at(e))), draw_overview()))
    over.bind('<Button-3>', lambda e: (var['last_bar'].set(str(bar_at(e))), draw_overview()))
    over.bind('<Button-2>', lambda e: (var['last_bar'].set(str(bar_at(e))), draw_overview()))
    over.bind('<Configure>', lambda e: draw_overview())

    def pick(i):
        sel = tree.selection()
        if sel:
            var[f'src{i}'].set('+'.join(sel))

    def suggest():
        for i in (1, 2, 3):
            var[f'src{i}'].set('')
        for i, (key, mode) in enumerate(suggest_voices(S['rows']), 1):
            var[f'src{i}'].set(key)
            var[f'mode{i}'].set(mode)
        say('suggested voices are a guess from track shape only: listen and change them')

    def form():
        v = {k: x.get() for k, x in var.items()}
        v['fold'] = fold.get()
        return v

    def arrange():
        if not S['smf']:
            say('load a MIDI first')
            return
        try:
            specs, kw = gui_params(form())
            res = m2m.arrange(S['smf'], specs, source=S['source'], **kw)
        except MidiError as e:
            S['result'] = None
            report.delete('1.0', 'end')
            report.insert('end', f'NOT ARRANGED: {e}')
            say('arrangement rejected, see the message below')
            return
        S['result'] = res
        report.delete('1.0', 'end')
        report.insert('end', '\n'.join(m2m.describe(res)) + '\n\nimport: ' + m2m.import_command(res, 'SONG.mml', 'OUT.RBG'))
        say(limits_line(res))
        draw_roll()
        draw_overview()

    def draw_roll():
        roll.delete('all')
        if not S['result']:
            return
        w, h = max(roll.winfo_width(), 400), roll.winfo_height()
        for vi, x0, y0, x1, y1 in piano_roll_rects(S['result'], w, h):
            roll.create_rectangle(x0, y0, x1, y1, fill=VOICE_COLORS[vi], width=0)

    def stop():
        if sys.platform.startswith('win'):
            import winsound
            winsound.PlaySound(None, 0)
        p = S['proc']
        if p and p.poll() is None:
            p.terminate()
        S['proc'] = None

    def play():
        if not S['result']:
            arrange()
        if not S['result']:
            return
        stop()
        if S['wav']:
            Path(S['wav']).unlink(missing_ok=True)
        handle, preview = tempfile.mkstemp(prefix='rave-preview-', suffix='.wav')
        os.close(handle)
        path = Path(preview)
        S['wav'] = path
        secs = render_wav(S['result'], path)
        if sys.platform.startswith('win'):
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            cmd = player_command(path)
            if not cmd:
                say(f'no audio player found; use Save WAV ({secs:.0f} s rendered)')
                return
            S['proc'] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        say(f'playing PSG + noise approximation ({secs:.0f} s; all reported drum reductions applied)')

    def out_name():
        return safe_name(var['title'].get() or (S['path'].stem if S['path'] else 'song'))[:8]

    def save_wav():
        if not S['result']:
            arrange()
        if S['result']:
            f = filedialog.asksaveasfilename(defaultextension='.wav', initialfile=out_name() + '.wav')
            if f:
                render_wav(S['result'], f)
                say(f'saved {f}')

    def save(kind):
        if not S['result']:
            arrange()
        res = S['result']
        if not res:
            return
        try:
            if kind == 'mml':
                d = ROOT / 'SONGS'
                d.mkdir(exist_ok=True)
                import json
                (d / f'{out_name()}.mml').write_text(res['text'] + '\n', encoding='ascii')
                (d / f'{out_name()}.arrangement.json').write_text(json.dumps(res['arrangement'],indent=2)+'\n')
                say(f'saved MML + arrangement sidecar (tempo and drums) for {out_name()}')
            else:
                paths = save_outputs(res, ROOT / 'SONGS', out_name())
                say('saved ' + ', '.join(p.name for p in paths) + ' in SONGS/')
        except Exception as e:  # ScoreError, OSError: show it, keep the window alive
            messagebox.showerror('Save failed', str(e))

    def open_dialog():
        f = filedialog.askopenfilename(filetypes=[('MIDI', '*.mid *.midi'), ('all', '*.*')])
        if f:
            load_path(Path(f))

    # --- downloads run in a thread; results come back through the queue
    def worker(items):
        for name, url in items:
            try:
                target = fetch.fetch_one(name, url, ROOT / 'midi-local', 2048 * 1024)
                q.put(('ok', target))
            except (OSError, ValueError) as e:
                q.put(('err', f'{name}: {e}'))
        q.put(('done', None))

    def start(items):
        if S.get('fetching'):
            say('a download is already running')
            return
        S['fetching']=True
        say('downloading...')
        threading.Thread(target=worker, args=(items,), daemon=True).start()

    def start_download():
        url = var['url'].get().strip()
        try:
            name = safe_name(Path(url.split('?')[0].rstrip('/')).stem or 'download')
            fetch.parse_pair(f'{name}={url}')
        except ValueError as e:
            say(str(e))
            return
        start([(name, url)])

    def start_defaults():
        start(list(fetch.DEFAULTS))

    last = {}

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == 'ok':
                    last['p'] = val
                    var['local'].set(str(val))
                elif kind == 'err':
                    say('download failed: ' + val)
                elif kind == 'done':
                    S['fetching']=False
                    refresh_local()
                    if last.get('p'):
                        load_path(last.pop('p'))
        except queue.Empty:
            pass
        root.after(200, poll)

    def on_close():
        stop()
        if S['wav']:
            Path(S['wav']).unlink(missing_ok=True)
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', on_close)
    refresh_local()
    poll()
    if initial:
        root.after(100, lambda: load_path(Path(initial)))
    say('Download or open a MIDI to begin.')
    root.rave_form=var
    root.rave_arrange=arrange
    root.rave_result=lambda:S['result']
    return root


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        run(argv[0] if argv else None).mainloop()
    except ImportError as e:
        print(f'Tk is not available in this Python ({e}). Install the python.org build or python3-tk.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
