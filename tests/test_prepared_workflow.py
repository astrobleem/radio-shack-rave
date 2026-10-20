"""Portable checks for the original demo and prepared-stream workflow."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAVE = Path(__file__).resolve().parents[1]


def run(args: list[str]) -> None:
    result = subprocess.run(args, cwd=RAVE, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stdout}\n{result.stderr}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="run native RWS preparation and loader/replay checks")
    parser.add_argument("--cc", help="compiler command passed to preparation and runtime checks")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rave-demo-test-") as folder:
        td = Path(folder)
        midi, mml, chart = td / "DEMO.MID", td / "DEMO.MML", td / "DEMO.RBG"
        run([sys.executable, "tools/generate_demo_midi.py", "--out", str(midi), "--mml-out", str(mml)])
        if midi.read_bytes() != (RAVE / "music/DEMO.MID").read_bytes():
            raise AssertionError("checked-in demo MIDI differs from deterministic generator output")
        if mml.read_bytes() != (RAVE / "music/DEMO.MML").read_bytes():
            raise AssertionError("checked-in demo MML differs from deterministic generator output")
        run([sys.executable, "tools/import_score.py", str(mml), str(chart), "--difficulty", "normal", "--title", "CIRCUIT"])
        if chart.read_bytes() != (RAVE / "runtime/DEMO.RBG").read_bytes():
            raise AssertionError("checked-in demo chart differs from its original MML source")
        if args.full:
            stream = td / "DEMO.RWS"
            command = [sys.executable, "tools/rave_prepare.py", "--song", str(midi), "--out", str(stream)]
            if args.cc:
                command += ["--cc", args.cc]
            run(command)
            command = [sys.executable, "tools/check_rws.py", "--stream", str(stream)]
            if args.cc:
                command += ["--cc", args.cc]
            run(command)
    print("PASS original MIDI, MML-to-chart reproducibility" + (", prepared stream and runtime replay" if args.full else ""))


if __name__ == "__main__":
    main()
