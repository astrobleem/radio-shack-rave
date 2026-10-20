"""Portable regressions for MIDI SFX ownership and MIDI VU drawing."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract_function(source: str, name: str) -> str:
    """Return a current static function body from a production header/source."""
    match = re.search(r"(?m)^static[ \t]+[^\n{};]*\b" + re.escape(name) + r"[ \t]*\([^;{}]*\)[ \t\r\n]*\{", source)
    if not match:
        raise AssertionError(f"production function not found: {name}")
    brace = source.find("{", match.start())
    if brace < 0:
        raise AssertionError(f"function has no body: {name}")
    depth = 0
    for pos in range(brace, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():pos + 1]
    raise AssertionError(f"unterminated function: {name}")


def compile_and_run(source: str, folder: Path, name: str) -> str:
    cc = os.environ.get("RAVE_TEST_CC", "gcc")
    source_path = folder / (name + ".c")
    binary_path = folder / (name + ".exe")
    source_path.write_text(source, encoding="utf-8")
    command = [cc, "-std=c89", "-Wall", "-Wextra", "-Werror",
               "-I", str(ROOT / "src"), str(source_path), "-o", str(binary_path)]
    result = subprocess.run(command, cwd=folder, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    run = subprocess.run([str(binary_path)], cwd=folder, capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    return run.stdout


class SoundUiTests(unittest.TestCase):
    def test_sfx_phase_gate_uses_current_production_predicate(self):
        beat = (ROOT / "src/BEAT.C").read_text(encoding="utf-8")
        predicate = extract_function(beat, "soundtrack_owns_psg")
        if not re.search(r"return\s+gameplay_active\s*&&\s*RaveMidiActive\(\)\s*;", predicate):
            self.fail(f"SFX fixture expectations need review for predicate: {predicate}")
        template = (ROOT / "tests/fixtures/sound_ui_sfx.c.in").read_text(encoding="utf-8")
        self.assertEqual(template.count("@ACTUAL_PREDICATE@"), 1)
        harness = template.replace("@ACTUAL_PREDICATE@", predicate + "\n")
        with tempfile.TemporaryDirectory(prefix="rave-sfx-phase-") as td:
            out = compile_and_run(harness, Path(td), "sfx_gate")
        self.assertIn("checks=16 failures=0", out)

    def test_meter_rows_match_reference_over_full_tandy_frame(self):
        gfx = (ROOT / "src/GFX.H").read_text(encoding="utf-8")
        play = (ROOT / "src/PLAY.H").read_text(encoding="utf-8")
        actual = "\n".join(extract_function(gfx, name)
                             for name in ("gfx_init", "px", "span", "fill"))
        actual += "\n" + extract_function(play, "midi_meter_rows")
        actual += "\n" + extract_function(play, "midi_meter_draw")
        harness = r'''#include <stdio.h>
#include <string.h>
#define far
#define SCR_W 320
#define SCR_H 200
#define NO_COLOR 255
#define _fmemset memset
static unsigned char oldmem[32768],newmem[32768];
static unsigned char *video;
static unsigned row_ofs[SCR_H];
static unsigned long vram_bytes;
''' + actual + r'''
int main(void)
{
 unsigned l,s,lit,i,checks,bad,x,y,c;
 gfx_init();checks=bad=0;
 for(l=0;l<4;l++)for(s=0;s<12;s++)for(lit=0;lit<2;lit++) {
  for(i=0;i<32768;i++)oldmem[i]=newmem[i]=(unsigned char)(0x5aU+(i&3U));
  x=244U+l*18U;y=136U-s*4U;video=oldmem;
  if(lit) {c=s<7?10U:(s<10?14U:12U);fill((int)x,(int)y,14,3,c);}
  else {fill((int)x,(int)y,14,3,0);span((int)x,(int)(y+1),14,8);}
  video=newmem;midi_meter_draw(l,s,lit);checks++;
  for(i=0;i<32768;i++)if(oldmem[i]!=newmem[i]){bad++;break;}
 }
 printf("meter segment equivalence checks=%u failures=%u\n",checks,bad);
 return bad?1:0;
}
'''
        with tempfile.TemporaryDirectory(prefix="rave-meter-pixels-") as td:
            out = compile_and_run(harness, Path(td), "meter_pixels")
        self.assertIn("checks=96 failures=0", out)


if __name__ == "__main__":
    unittest.main()
