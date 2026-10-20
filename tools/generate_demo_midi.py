"""Generate first-party, deterministic MIDI and matching MML demo sources (CC0)."""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

RAVE = Path(__file__).resolve().parents[1]
TPQ = 480
QUARTER = TPQ
HALF = TPQ // 2
# First-party melody in C major, written for this demo. Each pitch is an eighth.
MELODY = [60, 64, 67, 72, 71, 67, 64, 62, 65, 69, 72, 74, 72, 69, 65, 64,
          67, 71, 74, 79, 77, 74, 71, 69, 65, 69, 72, 77, 76, 72, 69, 67,
          60, 64, 67, 72, 74, 72, 67, 64, 62, 65, 69, 74, 72, 69, 65, 62,
          67, 71, 74, 79, 76, 74, 71, 67, 65, 69, 72, 77, 74, 72, 69, 60]
CHORDS = [(48, 55, 60, 64), (45, 52, 57, 60), (41, 48, 53, 57), (43, 50, 55, 59),
          (48, 55, 60, 64), (45, 52, 57, 60), (43, 50, 55, 59), (48, 55, 60, 64)]


def vlq(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


def track(events: list[tuple[int, bytes]]) -> bytes:
    events.sort(key=lambda e: e[0])
    body = bytearray()
    previous = 0
    for tick, message in events:
        body.extend(vlq(tick - previous))
        body.extend(message)
        previous = tick
    body.extend(b"\x00\xff\x2f\x00")
    return b"MTrk" + struct.pack(">I", len(body)) + body


def midi_bytes() -> bytes:
    conductor = [(0, b"\xff\x03\x13Circuit After Hours"),
                 (0, b"\xff\x51\x03\x07\xa1\x20"),
                 (0, b"\xff\x58\x04\x04\x02\x18\x08")]
    melody: list[tuple[int, bytes]] = [(0, b"\xc0\x50"), (0, b"\xb0\x07\x64")]
    for i, note in enumerate(MELODY):
        at = i * HALF
        melody.extend(((at, bytes((0x90, note, 92))), (at + HALF - 12, bytes((0x80, note, 0)))))
    chords: list[tuple[int, bytes]] = [(0, b"\xc1\x00"), (0, b"\xb1\x07\x50")]
    bass: list[tuple[int, bytes]] = [(0, b"\xc2\x32"), (0, b"\xb2\x07\x58")]
    for bar, chord in enumerate(CHORDS):
        start = bar * 4 * QUARTER
        for note in chord:
            chords.extend(((start, bytes((0x91, note, 58))), (start + 2 * QUARTER, bytes((0x81, note, 0)))))
        root = chord[0] - 12
        for beat in range(4):
            at = start + beat * QUARTER
            bass.extend(((at, bytes((0x92, root if beat in (0, 2) else root + 7, 72))),
                         (at + QUARTER - 18, bytes((0x82, root if beat in (0, 2) else root + 7, 0)))))
    return b"MThd" + struct.pack(">IHHH", 6, 1, 4, TPQ) + b"".join(
        (track(conductor), track(melody), track(chords), track(bass)))


def mml_text() -> str:
    names = {0: "c", 1: "c+", 2: "d", 3: "d+", 4: "e", 5: "f", 6: "f+", 7: "g", 8: "g+", 9: "a", 10: "a+", 11: "b"}
    octave = 4
    tokens = ["t120"]
    for note in MELODY:
        target = note // 12 - 1
        while octave < target:
            tokens.append("<")
            octave += 1
        while octave > target:
            tokens.append(">")
            octave -= 1
        tokens.append(names[note % 12] + "8")
    # Keep the gameplay chart alive beyond the MIDI's last note-off and its
    # producer tail, so native stream duration validation accepts the pair.
    return "MML@" + " ".join(tokens) + " r1;\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=RAVE / "music/DEMO.MID")
    ap.add_argument("--mml-out", type=Path, default=RAVE / "music/DEMO.MML")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.mml_out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(midi_bytes())
    args.mml_out.write_text(mml_text(), encoding="ascii", newline="\n")
    print(f"wrote original 4-track MIDI: {args.out} and matching lead chart source: {args.mml_out}")


if __name__ == "__main__":
    main()
