"""Prepare an RWS1 stream with the frozen Tandy MIDI engine."""
from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

RAVE = Path(__file__).resolve().parents[1]
HEADER = struct.Struct("<4sHHIIHHHHII")
RECORD = struct.Struct("<IHHHHBBHH")


def sound_dir(env_name: str, dep_name: str) -> Path:
    explicit = os.environ.get(env_name)
    if explicit:
        root = Path(explicit).expanduser().resolve()
        return root if root.name.lower() == "sound" else root / "sound"
    root = RAVE / "deps" / dep_name
    if (root / "sound").is_dir():
        return root / "sound"
    return root


CORE = sound_dir("LIBTANDY", "libtandy")
WIN = sound_dir("LIBWINTANDY", "libwintandy")
STUB = RAVE / "tools/prep-windows"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compiler_args(value: str | None) -> list[str]:
    selected = value or os.environ.get("CC")
    if selected:
        args = shlex.split(selected, posix=os.name != "nt")
        if not args:
            raise RuntimeError("compiler selection is empty")
        return args
    if os.name == "nt":
        candidate = Path(os.environ.get("SystemDrive", "C:") + "/msys64/ucrt64/bin/gcc.exe")
        if candidate.is_file():
            return [str(candidate)]
        raise RuntimeError("UCRT64 GCC was not found; pass --cc or set CC")
    candidate = shutil.which("cc") or shutil.which("gcc")
    if not candidate:
        raise RuntimeError("C compiler was not found; pass --cc or set CC")
    return [candidate]


@contextmanager
def quiet_windows_errors():
    if os.name != "nt":
        yield
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    old = kernel.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    try:
        yield
    finally:
        kernel.SetErrorMode(old)


def creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def verify(song: Path, output: Path, trace: Path) -> dict:
    data = output.read_bytes()
    if len(data) < HEADER.size:
        raise ValueError("short RWS1 header")
    magic, hdr, rec, count, duration, messages, flags, speaker, reserved, checksum, tag = HEADER.unpack_from(data)
    if (magic, hdr, rec, flags, speaker, reserved, tag) != (b"RWS1", 32, 18, 3, 1, 0, 0x3954504F):
        raise ValueError("RWS1 header mismatch")
    payload = data[hdr:]
    if not 0 < count <= 18000 or len(payload) != count * rec or (sum(payload) & 0xFFFFFFFF) != checksum:
        raise ValueError("RWS1 payload length or byte-sum mismatch")
    counted = 0
    last_fine = -1
    for i in range(count):
        at, p0, p1, p2, volume, noise, retrigger, pit, frame_messages = RECORD.unpack_from(payload, i * rec)
        if at <= last_fine or any(p > 1023 for p in (p0, p1, p2)) or noise > 7:
            raise ValueError(f"invalid or unordered RWS1 frame {i}")
        if retrigger > 1 or (pit and pit < 152):
            raise ValueError(f"invalid output field in frame {i}")
        last_fine, counted = at, counted + frame_messages
    if counted != messages or volume != 65535 or pit != 0:
        raise ValueError("message accounting or sealed mute mismatch")
    with trace.open(newline="") as f:
        reader = csv.DictReader(f)
        prev_cycle = -1
        rows = 0
        min_gap = None
        max_rounding = 0
        nonzero_pit = 0
        min_pit = None
        noise_retriggers = 0
        for row in reader:
            at_cycle = int(row["at_cycles"])
            at_fine = int(row["at_fine"])
            if at_cycle <= prev_cycle or at_fine != (at_cycle + 255) // 256:
                raise ValueError(f"exact-cycle trace mismatch at frame {rows}")
            state = RECORD.unpack_from(payload, rows * rec)
            reference = tuple(int(row[key]) for key in ("at_fine", "p0", "p1", "p2", "volume", "noise", "retrigger", "pit_divisor", "frame_messages"))
            if state != reference:
                raise ValueError(f"RWS1/trace mismatch at frame {rows}")
            if prev_cycle >= 0:
                gap = at_cycle - prev_cycle
                min_gap = gap if min_gap is None else min(min_gap, gap)
            max_rounding = max(max_rounding, at_fine * 256 - at_cycle)
            if state[7]:
                nonzero_pit += 1
                min_pit = state[7] if min_pit is None else min(min_pit, state[7])
            noise_retriggers += state[6]
            prev_cycle, rows = at_cycle, rows + 1
    if rows != count:
        raise ValueError("trace count mismatch")
    return {
        "format": "RWS1", "song": str(song), "song_sha256": sha(song), "rws": str(output),
        "rws_sha256": sha(output), "rws_bytes": len(data), "exact_cycle_trace": str(trace),
        "trace_sha256": sha(trace), "frames": count, "original_channel_messages": messages,
        "accounted_frame_messages": counted, "duration_ms": duration, "final_at_fine": last_fine,
        "final_at_cycles": prev_cycle, "max_rounding_cycles_observed": max_rounding,
        "max_rounding_cycles_bound": 255, "minimum_frame_spacing_cycles": min_gap,
        "nonzero_pit_frames": nonzero_pit, "minimum_nonzero_pit_divisor": min_pit,
        "noise_retrigger_frames": noise_retriggers, "payload_byte_sum": checksum,
        "voice_flags": flags, "speaker_mode": speaker, "engine_tag": f"0x{tag:08x}",
        "frozen_source_sha256": {"MIDICLK.C": sha(WIN / "MIDICLK.C"), "SMF.C": sha(CORE / "SMF.C"),
                                 "MIDISYN.C": sha(CORE / "MIDISYN.C"), "INSTR.C": sha(CORE / "INSTR.C")},
        "limits": "Host generation verifies frozen frame scheduling and record accounting; target replay timing requires separate qualification.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare a portable RWS1 stream from a MIDI song.")
    ap.add_argument("--song", type=Path, default=RAVE / "music/DEMO.MID")
    ap.add_argument("--out", type=Path, default=RAVE / "runtime/DEMO.RWS")
    ap.add_argument("--trace", type=Path, help="optional exact-cycle trace CSV destination")
    ap.add_argument("--cc", help="C compiler command (defaults to CC, then platform default)")
    ap.add_argument("--evidence", type=Path, help="optional JSON evidence destination")
    args = ap.parse_args()
    song, output = args.song.resolve(), args.out.resolve()
    if not song.is_file():
        raise FileNotFoundError(f"MIDI input not found: {song}")
    for root, files in ((CORE, ("SMF.C", "MIDISYN.C", "INSTR.C")), (WIN, ("MIDICLK.C",))):
        missing = [name for name in files if not (root / name).is_file()]
        if missing:
            raise FileNotFoundError(f"sound dependency files missing under {root}: {', '.join(missing)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    cc = compiler_args(args.cc)
    with tempfile.TemporaryDirectory(prefix="rave-rws-") as td:
        temp = Path(td)
        exe = temp / ("rave_prepare.exe" if os.name == "nt" else "rave_prepare")
        trace = args.trace.resolve() if args.trace else temp / "cycles.csv"
        trace.parent.mkdir(parents=True, exist_ok=True)
        cmd = [*cc, "-x", "c", "-std=c99", "-O2", "-DSYNTH_HOST",
               '-DRAVE_MIDICLK_SOURCE="' + (WIN / "MIDICLK.C").as_posix() + '"',
               "-I", str(STUB), "-I", str(CORE), str(Path(__file__).with_suffix(".c")),
               str(CORE / "SMF.C"), str(CORE / "MIDISYN.C"), str(CORE / "INSTR.C"), "-o", str(exe)]
        env = os.environ.copy()
        if os.name == "nt":
            compiler_home = Path(cc[0]).resolve().parent
            clean_path = [p for p in env.get("PATH", "").split(os.pathsep)
                          if p and "msys64" not in p.lower().replace("/", "\\")]
            env["PATH"] = os.pathsep.join([str(compiler_home), *clean_path])
        with quiet_windows_errors():
            built = subprocess.run(cmd, cwd=RAVE, env=env, text=True, capture_output=True, creationflags=creation_flags())
            if built.returncode:
                raise RuntimeError(f"compiler failed ({built.returncode}):\n{built.stdout}\n{built.stderr}")
            run = subprocess.run([str(exe), str(song), str(output), str(trace)], cwd=RAVE, env=env,
                                 text=True, capture_output=True, creationflags=creation_flags())
            if run.returncode:
                raise RuntimeError(f"frozen host producer failed ({run.returncode}):\n{run.stderr}")
        print(run.stdout.strip())
        result = verify(song, output, trace)
    if args.evidence:
        evidence = args.evidence.resolve()
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"verified {result['frames']} frames / {result['original_channel_messages']} messages; {result['rws_bytes']} bytes")


if __name__ == "__main__":
    main()
