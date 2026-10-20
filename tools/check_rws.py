"""Portable host integration checks for an RWS1 stream."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

RAVE = Path(__file__).resolve().parents[1]
HEADER_SIZE, RECORD_SIZE = 32, 18


def sound_dir(env_name: str, dep_name: str) -> Path:
    explicit = os.environ.get(env_name)
    if explicit:
        root = Path(explicit).expanduser().resolve()
        return root if root.name.lower() == "sound" else root / "sound"
    root = RAVE / "deps" / dep_name
    return root / "sound" if (root / "sound").is_dir() else root


CORE = sound_dir("LIBTANDY", "libtandy")
WIN = sound_dir("LIBWINTANDY", "libwintandy")
TOOLS = RAVE / "tools"
STUB = TOOLS / "prep-windows"


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


def command(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=RAVE, env=env, text=True, capture_output=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)


def compile_probe(cc: list[str], src: Path, exe: Path, sources: list[Path], includes: list[Path],
                  env: dict[str, str], extra: list[str]) -> None:
    args = [*cc, "-x", "c", "-std=c99", "-O2", *extra]
    for inc in includes:
        args += ["-I", str(inc)]
    args += [str(src), *(str(s) for s in sources), "-o", str(exe)]
    result = command(args, env)
    if result.returncode:
        raise RuntimeError(f"compile {src.name} ({result.returncode}):\n{result.stdout}\n{result.stderr}")


def mutate(data: bytes, edits: list[tuple[int, bytes]], fix_sum: bool = True) -> bytes:
    b = bytearray(data)
    for at, value in edits:
        b[at:at + len(value)] = value
    if fix_sum:
        struct.pack_into("<I", b, 24, sum(b[32:]) & 0xFFFFFFFF)
    return bytes(b)


def main() -> None:
    ap = argparse.ArgumentParser(description="Check RWS1 loading, rewinds, silence, and port traces.")
    ap.add_argument("--stream", type=Path, default=RAVE / "runtime/DEMO.RWS")
    ap.add_argument("--evidence", type=Path, help="optional JSON evidence destination")
    ap.add_argument("--cc", help="C compiler command (defaults to CC, then platform default)")
    args = ap.parse_args()
    stream = args.stream.resolve()
    raw = stream.read_bytes()
    if len(raw) < HEADER_SIZE:
        raise ValueError("short RWS1 stream")
    magic, hdr, rec, count, duration, messages, flags, speaker, reserved, checksum, tag = struct.unpack_from("<4sHHIIHHHHII", raw)
    if (magic, hdr, rec, flags, speaker, reserved, tag) != (b"RWS1", 32, 18, 3, 1, 0, 0x3954504F):
        raise ValueError("unsupported RWS1 header")
    if count < 1 or len(raw) != hdr + count * rec or (sum(raw[hdr:]) & 0xFFFFFFFF) != checksum:
        raise ValueError("RWS1 count, size, or payload checksum mismatch")
    if not (CORE / "SMF.C").is_file() or not (WIN / "TIMECLK.C").is_file():
        raise FileNotFoundError("pinned sound dependencies are missing; run tools/fetch_sound_deps.py")
    cc = compiler_args(args.cc)
    env = os.environ.copy()
    if os.name == "nt":
        compiler_home = Path(cc[0]).resolve().parent
        clean_path = [p for p in env.get("PATH", "").split(os.pathsep)
                      if p and "msys64" not in p.lower().replace("/", "\\")]
        env["PATH"] = os.pathsep.join([str(compiler_home), *clean_path])
    with quiet_windows_errors(), tempfile.TemporaryDirectory(prefix="rws-check-") as folder:
        td = Path(folder)
        runtime, reference = td / ("runtime.exe" if os.name == "nt" else "runtime"), td / ("reference.exe" if os.name == "nt" else "reference")
        runtime_source = (TOOLS / "check_rws_runtime.c").read_text(encoding="utf-8")
        replacements = {
            r"RaveMidiEvents\(\)!=17578U": f"RaveMidiEvents()!={messages}U",
            r"RaveMidiDuration\(\)!=200083UL": f"RaveMidiDuration()!={duration}UL",
            r"32L\+500L\*18L": f"32L+{max(0, count // 2)}L*18L",
        }
        for pattern, replacement in replacements.items():
            runtime_source, n = re.subn(pattern, replacement, runtime_source)
            if n != 1:
                raise RuntimeError(f"could not adapt runtime probe expectation: {pattern}")
        runtime_c = td / "check_rws_runtime.c"
        runtime_c.write_text(runtime_source, encoding="utf-8")
        compile_probe(cc, runtime_c, runtime,
                      [RAVE / "src/RAVEMID.C", RAVE / "src/DOSSND.C", CORE / "SMF.C", CORE / "MIDISYN.C", CORE / "INSTR.C"],
                      [RAVE / "src", CORE], env,
                      ["-DSYNTH_HOST", "-DDOS_SOUND_TEST", "-Dfar=", "-D_cdecl=", "-D_fmalloc=malloc", "-D_ffree=free", "-D_fmemcpy=memcpy"])
        compile_probe(cc, TOOLS / "check_rws_reference.c", reference, [], [STUB, WIN], env,
                      ['-DRAVE_TIMECLK_SOURCE="' + (WIN / "TIMECLK.C").as_posix() + '"',
                       '-DRAVE_PITLEASE_SOURCE="' + (WIN / "DRIVER/PITLEASE.H").as_posix() + '"',
                       "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections"])
        batch_check = command([str(runtime), "batch"], env)
        if batch_check.returncode:
            raise AssertionError(f"bounded PSG batch contract failed ({batch_check.returncode}): {batch_check.stderr}")
        runtime_trace, reference_trace = td / "runtime.txt", td / "reference.txt"
        for cmd in ([str(runtime), "trace", str(stream), str(runtime_trace)],
                    [str(reference), str(stream), str(reference_trace)]):
            result = command(list(cmd), env)
            if result.returncode:
                raise RuntimeError(f"probe {Path(cmd[0]).name} ({result.returncode}):\n{result.stderr}")
        actual, expected = runtime_trace.read_bytes(), reference_trace.read_bytes()
        a, e = actual.splitlines(), expected.splitlines()
        if len(a) != len(e):
            raise AssertionError(f"trace line count {len(a)} != {len(e)}")
        mismatches = [(i, x, y) for i, (x, y) in enumerate(zip(a, e)) if x != y]
        def canonical(line: bytes) -> bytes:
            while b"G00 G00 " in line:
                line = line.replace(b"G00 G00 ", b"G00 ")
            return line
        structural = [(i, x, y) for i, x, y in mismatches if canonical(x) != canonical(y)]
        if structural:
            idx, x, y = structural[0]
            raise AssertionError(f"PSG/divisor/ordering mismatch line {idx}:\n{x}\n{y}")
        tests = {
            "good": (raw, True), "truncated": (raw[:-1], False),
            "header_size": (mutate(raw, [(4, b"\x1f\x00")]), False),
            "record_size": (mutate(raw, [(6, b"\x11\x00")]), False),
            "voice_flags": (mutate(raw, [(18, b"\x02\x00")]), False),
            "speaker_mode": (mutate(raw, [(20, b"\x00\x00")]), False),
            "engine_tag": (mutate(raw, [(28, b"BAD!")]), False),
            "bad_sum": (mutate(raw, [(32 + 18, b"\xff")], False), False),
            "bad_period": (mutate(raw, [(32 + 4, b"\x00\x04")]), False),
            "bad_noise": (mutate(raw, [(32 + 12, b"\x08")]), False),
            "bad_retrigger": (mutate(raw, [(32 + 13, b"\x02")]), False),
            "bad_pit": (mutate(raw, [(32 + 14, b"\x01\x00")]), False),
            "backward_time": (mutate(raw, [(32 + min(100, count - 1) * 18, b"\x00\x00\x00\x00")]), False),
            "bad_final_mute": (mutate(raw, [(32 + (count - 1) * 18 + 10, b"\x00\x00")]), False),
            "bad_message_total": (mutate(raw, [(16, b"\x01\x00")]), False),
        }
        for name, (data, accepts) in tests.items():
            path = td / f"{name}.rws"
            path.write_bytes(data)
            result = command([str(runtime), "accept" if accepts else "reject", str(path)], env)
            if result.returncode:
                raise AssertionError(f"loader {name} returned {result.returncode}: {result.stderr}")
        lines = actual.splitlines()
        assert len(lines) == count * 3 + 2
        assert lines[count] == lines[count * 2 + 1] == b"REPLAY"
        assert lines[:count] == lines[count + 1:count * 2 + 1]
        assert lines[:count] == lines[count * 2 + 2:]
        result = {
            "result": "PASS" if not mismatches else "PORT_TRACE_DIFF", "stream": str(stream),
            "stream_sha256": hashlib.sha256(raw).hexdigest(), "frames_per_pass": count, "duration_ms": duration,
            "original_channel_messages": messages, "passes": 3, "compared_frame_lines": count * 3,
            "far_block_frames": 900, "far_block_max_bytes": 900 * RECORD_SIZE,
            "far_blocks_required": (count + 899) // 900, "far_block_limit": 20,
            "runtime_trace_sha256": hashlib.sha256(actual).hexdigest(),
            "reference_trace_sha256": hashlib.sha256(expected).hexdigest(),
            "exact_port_trace_mismatches": len(mismatches), "structural_psg_or_divisor_mismatches": len(structural),
            "negative_loader_cases": sorted(name for name in tests if name != "good"),
            "negative_loader_count": len(tests) - 1,
            "rewind_and_silence": "three identical complete replay traces; mid-song silences followed by rewind and final silence gate PIT2",
            "reference": "independent frozen TIMECLK.C frame() and PITLEASE.H LeaseFast()",
            "runtime": "RAVEMID.C/RVSTREAM.H and DOSSND.C host-compiled",
            "limits": "Host trace equality excludes 8088 instruction timing, IRQ deadline behavior, and physical device response.",
        }
        if args.evidence:
            evidence = args.evidence.resolve()
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"CHECK {count} frames x3, {len(tests)-1} negative loads, {len(mismatches)} exact port mismatches, {len(structural)} PSG/divisor mismatches")


if __name__ == "__main__":
    main()
