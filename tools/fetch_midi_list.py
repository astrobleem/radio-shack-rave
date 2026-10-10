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
import re
import sys
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


def parse_pair(text):
    """NAME=URL -> (name, url); http(s) only, and names are safe folder names."""
    name, sep, url = text.partition('=')
    if not sep or not NAME_RE.fullmatch(name):
        raise ValueError(f'expected NAME=URL with NAME of letters, digits, - or _: {text!r}')
    if not re.match(r'https?://', url):
        raise ValueError(f'URL must start with http:// or https://: {url!r}')
    return name, url


def check_midi(data, max_bytes):
    if len(data) > max_bytes:
        raise ValueError(f'{len(data)} bytes is over the {max_bytes}-byte limit')
    if data[:4] != b'MThd':
        raise ValueError('not a Standard MIDI File (missing MThd header)')
    return data


def download(url, max_bytes, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'radio-shack-rave-fetch/1'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    return check_midi(data, max_bytes)


def show(path):
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
                data = download(url, args.max_kb * 1024)
            except (OSError, ValueError) as e:
                print(f'  download failed: {e}', file=sys.stderr)
                failures += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            print(f'  saved {target} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()})')
        elif target.exists():
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
