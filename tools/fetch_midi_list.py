"""Download MIDI files into a local folder and list their tracks (no conversion).

Python 3 standard library only. With no arguments it fetches the four MIDIs
listed in DEFAULTS; pass NAME=URL pairs to fetch your own instead.

  python tools/fetch_midi_list.py                      # the four defaults
  python tools/fetch_midi_list.py --list-only          # just list what is already downloaded
  python tools/fetch_midi_list.py --only jump          # one default
  python tools/fetch_midi_list.py mytune=https://example.org/tune.mid

Files land in midi-local/NAME/NAME.mid (git-ignored). Existing files are kept
unless --force. Each download must start with the MIDI header and stay under
--max-kb, and its size and SHA-256 are printed. Then midi_to_mml.py --list
prints each track, channel, instrument, pitch range and bar span, which is what
you need to choose --voice specs and a bar range.

These are third-party files. Check you are allowed to use them, and keep
anything you make from them out of the repository; the README says no outside
songs ship with the game.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from midi_to_mml import MidiError, list_tracks, read_smf  # noqa: E402

DEFAULTS = [
    ('stayin', 'https://bitmidi.com/uploads/16633.mid'),
    ('jump', 'https://bitmidi.com/uploads/107487.mid'),
    ('sandstorm', 'https://bitmidi.com/uploads/37900.mid'),
    ('megalovania', 'https://www.vgmusic.com/music/computer/microsoft/windows/Undertale_-_Megalovania_v1_2.mid'),
]
NAME_RE = re.compile(r'[A-Za-z0-9_-]{1,40}')

def reserved_name(name):
    return name.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}

def check_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('URL must be a complete HTTP(S) address without credentials')
    return url


def parse_pair(text):
    """NAME=URL -> (name, url); http(s) only, and names are safe folder names."""
    name, sep, url = text.partition('=')
    if not sep or not NAME_RE.fullmatch(name) or reserved_name(name):
        raise ValueError(f'expected NAME=URL with NAME of letters, digits, - or _: {text!r}')
    check_url(url)
    return name, url


def check_midi(data, max_bytes):
    if not 1 <= max_bytes <= 8 * 1024 * 1024:
        raise ValueError('byte limit must be 1..8388608')
    if len(data) > max_bytes:
        raise ValueError(f'{len(data)} bytes is over the {max_bytes}-byte limit')
    if data[:4] != b'MThd':
        raise ValueError('not a Standard MIDI File (missing MThd header)')
    read_smf(data)
    return data


def midi_link_from_html(html, base):
    """First .mid link on a page (BitMidi song pages carry /uploads/N.mid), made absolute; else None."""
    m = re.search(r'href=["\']([^"\']+\.mid)["\']', html, re.I)
    return check_url(urllib.parse.urljoin(base, m.group(1))) if m else None


def resolve_midi_url(url, timeout=30):
    """Return a direct .mid URL: the URL itself, or the .mid link found on a song page."""
    check_url(url)
    if urllib.parse.urlparse(url).path.lower().endswith(('.mid', '.midi')):
        return url
    req = urllib.request.Request(url, headers={'User-Agent': 'radio-shack-rave-fetch/1'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final=check_url(resp.geturl())
        data=resp.read(2_000_001)
        if len(data)>2_000_000:raise ValueError('page exceeds 2 MB')
        html = data.decode('utf8', 'replace')
    link = midi_link_from_html(html, final)
    if not link:
        raise ValueError('no .mid link found on that page; copy the direct .mid URL instead')
    return link


def download(url, max_bytes, timeout=30, details=None):
    check_url(url)
    if not 1 <= max_bytes <= 8 * 1024 * 1024:raise ValueError('invalid byte limit')
    req = urllib.request.Request(url, headers={'User-Agent': 'radio-shack-rave-fetch/1'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final=check_url(resp.geturl())
        data = resp.read(max_bytes + 1)
    data=check_midi(data, max_bytes)
    if details is not None:details['final_download_url']=final
    return data

def fetch_one(name, url, dest, max_bytes, *, force=False):
    """Validate completely before replacing a local file; always save provenance."""
    parse_pair(f'{name}={url}')
    dest=Path(dest).resolve();folder=dest/name;target=folder/(name+'.mid')
    metadata=target.with_suffix('.source.json')
    if (folder.is_symlink() or target.is_symlink() or metadata.is_symlink()
            or folder.resolve().parent!=dest or target.resolve().parent!=folder.resolve()):
        raise ValueError('destination escapes its selected folder')
    if target.exists() and not force:
        if target.stat().st_size>max_bytes:raise ValueError('existing MIDI exceeds byte limit')
        check_midi(target.read_bytes(),max_bytes)
        return target
    direct=resolve_midi_url(url);details={};data=download(direct,max_bytes,details=details)
    folder.mkdir(parents=True,exist_ok=True)
    handle, tmp=tempfile.mkstemp(prefix='download-',suffix='.tmp',dir=str(folder))
    try:
        with os.fdopen(handle,'wb') as f:f.write(data)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    record=dict(source_url=url,resolved_midi_url=direct,**details,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                licensing='Third-party source; eligibility not established, keep private',
                validation='Full bounded SMF parse before replacement; no downloaded code executed')
    metadata.write_bytes((json.dumps(record,indent=2)+'\n').encode())
    return target


def show(path):
    if path.stat().st_size>8*1024*1024:raise MidiError('MIDI input exceeds 8 MiB')
    ppq, tracks, tempos, sigs = read_smf(path.read_bytes())
    list_tracks(ppq, tracks, tempos, sigs)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('pairs', nargs='*', metavar='NAME=URL')
    p.add_argument('--dest', type=Path, default=Path('midi-local'))
    p.add_argument('--only', action='append', default=[], metavar='NAME', help='fetch only these defaults')
    p.add_argument('--list-only', action='store_true', help='skip downloading; list files already in --dest')
    p.add_argument('--force', action='store_true', help='re-download even if the file exists')
    p.add_argument('--max-kb', type=int, default=2048)
    args = p.parse_args(argv)
    if not 1 <= args.max_kb <= 8192:
        print('error: max-kb must be 1..8192',file=sys.stderr)
        return 2
    try:
        items = [parse_pair(x) for x in args.pairs] if args.pairs else list(DEFAULTS)
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    if args.only:
        known = {n for n, _ in items}
        missing = [n for n in args.only if n not in known]
        if missing:
            print(f'error: unknown name(s): {", ".join(missing)} (have: {", ".join(sorted(known))})', file=sys.stderr)
            return 2
        items = [(n, u) for n, u in items if n in args.only]
    failures = 0
    for name, url in items:
        target = args.dest / name / f'{name}.mid'
        print(f'=== {name}')
        if not args.list_only and (args.force or not target.exists()):
            try:
                target = fetch_one(name,url,args.dest,args.max_kb*1024,force=args.force)
                data = target.read_bytes()
            except (OSError, ValueError) as e:
                print(f'  download failed: {e}', file=sys.stderr)
                failures += 1
                continue
            print(f'  saved {target} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()})')
        elif target.exists():
            if target.stat().st_size>args.max_kb*1024:
                print('  existing MIDI exceeds byte limit',file=sys.stderr)
                failures+=1
                continue
            data = target.read_bytes()
            print(f'  have {target} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()})')
        else:
            print(f'  {target} not downloaded yet', file=sys.stderr)
            failures += 1
            continue
        try:
            show(target)
        except MidiError as e:
            print(f'  cannot read it: {e}', file=sys.stderr)
            failures += 1
    print('\nNext: python tools/midi_to_mml.py midi-local/NAME/NAME.mid --voice TRACK:top ... --from-bar N --to-bar M --check -o SONGS/NAME.mml')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
