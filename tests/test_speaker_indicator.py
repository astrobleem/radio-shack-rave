"""Public regressions for the fifth speaker gate LED and emitted PIT-state cache."""
from __future__ import annotations

import ctypes
import os
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SHARED = Path(os.environ.get("LIBTANDY", ROOT / "deps" / "libtandy"))
SOUND = SHARED if SHARED.name.lower() == "sound" else SHARED / "sound"


def cc_command() -> list[str]:
    raw = os.environ.get("RAVE_TEST_CC") or os.environ.get("CC") or "gcc"
    command = shlex.split(raw, posix=(os.name != "nt"))
    if os.name == "nt" and not shutil.which(command[0], path=os.environ.get("PATH")):
        fallback = Path("C:/msys64/ucrt64/bin/gcc.exe")
        if fallback.is_file():
            return [str(fallback)]
    return command


def run_compiler(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        compiler = shutil.which(command[0], path=env.get("PATH"))
        if compiler:
            home = str(Path(compiler).resolve().parent)
            clean = [p for p in env.get("PATH", "").split(os.pathsep)
                     if p and "msys64" not in p.lower().replace("/", "\\")]
            env["PATH"] = os.pathsep.join([home, *clean])
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    return subprocess.run(command, cwd=cwd, env=env, text=True,
                          capture_output=True, timeout=30, creationflags=flags)


def synthetic_rws(path: Path) -> None:
    """Small authored fixture: one message, off/on/change/off/on/off PIT gates."""
    states = [(0, 0), (40, 500), (80, 450), (120, 0), (160, 620), (200, 0)]
    records = []
    for i, (at, pit) in enumerate(states):
        records.append(struct.pack("<IHHHHBBHH", at, 0, 0, 0, 0xFFFF,
                                   0, 0, pit, 1 if i == 0 else 0))
    payload = b"".join(records)
    checksum = sum(payload) & 0xFFFFFFFF
    header = struct.pack("<4sHHIIHHHHII", b"RWS1", 32, 18, len(states),
                         1000, 1, 3, 1, 0, checksum, 0x3954504F)
    assert len(header) == 32 and len(payload) == 18 * len(states)
    path.write_bytes(header + payload)


def compile_host(source: str, folder: Path, name: str) -> Path:
    source_path = folder / f"{name}.c"
    output = folder / (name + (".exe" if os.name == "nt" else ""))
    source_path.write_text(source, encoding="ascii")
    cc = cc_command()
    if Path(cc[0]).name.lower().startswith("wcl"):
        command = [*cc, "-q", "-bt=nt", "-fe=" + output.name,
                   str(source_path), str(SOUND / "SMF.C"),
                   str(SOUND / "MIDISYN.C"), str(SOUND / "INSTR.C"),
                   "-I" + str(ROOT), "-I" + str(SOUND), "-I" + str(folder)]
    else:
        command = [*cc, "-x", "c", "-std=c89", "-Wall", "-Wextra",
                   "-I", str(ROOT), "-I", str(SOUND), "-I", str(folder),
                   str(source_path), str(SOUND / "SMF.C"),
                   str(SOUND / "MIDISYN.C"), str(SOUND / "INSTR.C"),
                   "-lm", "-o", str(output)]
    result = run_compiler(command, folder)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return output


class SpeakerIndicatorTests(unittest.TestCase):
    def test_emitted_pit_gate_live_prepared_and_failure_cache(self):
        header = (ROOT / "src" / "RAVEMID.H").read_text(encoding="latin1")
        self.assertIn("RaveMidiPitGate", header)
        with tempfile.TemporaryDirectory(prefix="rave-speaker-rws-") as td:
            folder = Path(td)
            stream = folder / "SYNTH.RWS"
            synthetic_rws(stream)
            # GCC on Linux has no DOS malloc.h; this host-only compatibility
            # header provides the memory aliases already used by the core.
            (folder / "malloc.h").write_text(
                "#include <stdlib.h>\n#include <string.h>\n"
                "#define _fmalloc malloc\n#define _ffree free\n"
                "#define _fmemcpy memcpy\n#define _fmemset memset\n",
                encoding="ascii")
            binary = compile_host((TESTS / "speaker_gate.c").read_text(encoding="ascii"),
                                  folder, "speaker_gate")
            result = run_compiler([str(binary), str(stream)], folder)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS synthetic prepared RWS", result.stdout)

    def test_fifth_led_and_four_psg_meters_match_public_reference(self):
        play_path = ROOT / "src" / "PLAY.H"
        play = play_path.read_text(encoding="latin1")
        start = play.index("static void midi_meter_rows(")
        end = play.index("/* At most two HUD items redraw per frame", start)
        current = play[start:end]
        current = current.replace("midi_meter_draw(l,midiMeterSegment,lit);",
                                  "draws++;midi_meter_draw(l,midiMeterSegment,lit);")
        source = r'''#include <stdio.h>
#include <string.h>
#define far
#define _fmemset memset
#define SCR_W 320
#define SCR_H 200
static unsigned char memory[32768],baseline[32768];
static unsigned char *video=memory;
static unsigned row_ofs[SCR_H],meter_lvl[4],meter_shown[4];
static unsigned midiMeterChannel,midiMeterSegment,midiMeterWant[5],midiMeterShown[5],midiMeterDirty[5];
static unsigned char midiMeterValid[5];
static int gameplay_active,animations,midiActive=1;
static unsigned packedVolume=0xffffU,pitGate,draws;
static unsigned RaveMidiPackedVolume(void){return packedVolume;}
static unsigned RaveMidiPitGate(void){return pitGate;}
static int RaveMidiActive(void){return midiActive;}
static void midi_service(void){}
static void midi_meter_draw(unsigned,unsigned,unsigned);
static void midi_meter_frame(void);
static void legacy_meter_draw(unsigned,unsigned,unsigned);
static unsigned px(unsigned char *m,unsigned x,unsigned y){unsigned char b=m[row_ofs[y]+(x>>1)];return (x&1U)?(b&15U):(b>>4);}
static void putpx(unsigned x,unsigned y,unsigned c){unsigned char *p=video+row_ofs[y]+(x>>1);if(x&1U)*p=(unsigned char)((*p&0xf0U)|(c&15U));else *p=(unsigned char)((*p&15U)|((c&15U)<<4));}
/* Accepted-four-meter reference: same positions, colors, and off-cell fill
   used by test_sound_ui.py's pre-speaker whole-frame equivalence oracle. */
static void legacy_meter_draw(unsigned ch,unsigned seg,unsigned lit){unsigned x=244U+ch*18U,y=136U-seg*4U,xx,yy,c=lit?(seg<7?10U:(seg<10?14U:12U)):0U;for(yy=0;yy<3;yy++)for(xx=0;xx<14;xx++)putpx(x+xx,y+yy,(!lit&&yy==1)?8U:c);}
static unsigned frame(void){draws=0;midi_meter_frame();if(draws>4){fprintf(stderr,"redraw overflow=%u gate=%u dirty=%u/%u/%u/%u/%u\\n",draws,pitGate,midiMeterDirty[0],midiMeterDirty[1],midiMeterDirty[2],midiMeterDirty[3],midiMeterDirty[4]);return 999;}return draws;}
static int only_led_delta(unsigned char *a,unsigned char *b){unsigned x,y;for(y=0;y<200;y++)for(x=0;x<320;x++)if(px(a,x,y)!=px(b,x,y)&&!(x>=224&&x<238&&y>=93&&y<96))return 0;return 1;}
static void reset(void){unsigned i,y;memset(memory,0,sizeof(memory));memset(baseline,0,sizeof(baseline));for(y=0;y<200;y++)row_ofs[y]=(y&3U)*8192U+(y>>2)*160U;for(i=0;i<4;i++)meter_lvl[i]=meter_shown[i]=0;for(i=0;i<5;i++){midiMeterWant[i]=midiMeterShown[i]=0;midiMeterDirty[i]=0xfffU;midiMeterValid[i]=0;}midiMeterDirty[0]=0;midiMeterValid[0]=1;midiMeterChannel=midiMeterSegment=0;video=memory;midi_meter_draw(0,0,0);}
static int settled_psg(void){unsigned i;for(i=0;i<40;i++){if(frame()>4)return 0;if(!midiMeterDirty[1]&&!midiMeterDirty[2]&&!midiMeterDirty[3]&&!midiMeterDirty[4])return 1;}return 0;}
static int compare_psg(void){unsigned c,s,x,y,bit;video=baseline;for(c=0;c<4;c++)for(s=0;s<12;s++){bit=1U<<s;legacy_meter_draw(c,s,(midiMeterShown[c+1]&bit)!=0);}video=memory;for(y=92;y<140;y++)for(x=244;x<314;x++)if(px(memory,x,y)!=px(baseline,x,y))return 0;return 1;}
int main(void){unsigned mode,atten,c,s,expected,frames=0,waited,max_settle=0;static const unsigned char levels[16]={12,12,11,10,9,8,8,7,6,5,4,4,3,2,1,0};static const unsigned masks[13]={0,1,3,7,15,31,63,127,255,511,1023,2047,4095};
for(mode=0;mode<2;mode++){animations=(int)mode;for(atten=0;atten<16;atten++){reset();packedVolume=0;for(c=0;c<4;c++)packedVolume|=(atten&15U)<<(c*4U);if(frame()>4)return 9;expected=masks[levels[atten]];for(c=0;c<4;c++)if(midiMeterWant[c+1]!=expected)return 10;if(!settled_psg()||!compare_psg())return 11;}}
/* Mixed simultaneously non-muted values. */
reset();packedVolume=(0U)|(4U<<4)|(8U<<8)|(12U<<12);if(frame()>4)return 9;if(midiMeterWant[1]!=4095U||midiMeterWant[2]!=511U||midiMeterWant[3]!=63U||midiMeterWant[4]!=7U)return 12;if(!settled_psg()||!compare_psg())return 13;
/* Gate target converges while all four PSG columns are still dirty, in both modes. */
for(mode=0;mode<2;mode++){animations=(int)mode;reset();packedVolume=0;pitGate=1;waited=0;while(midiMeterShown[0]!=1U&&waited<40){waited++;if(frame()>4)return 14;frames=draws;}if(midiMeterShown[0]!=1U||waited>40||midiMeterShown[0]!=midiMeterWant[0])return 15;if(!midiMeterDirty[1]&&!midiMeterDirty[2]&&!midiMeterDirty[3]&&!midiMeterDirty[4])return 16;if(waited>max_settle)max_settle=waited;if(!settled_psg())return 17;}
/* Once PSG is steady, gate on/off must change only the reserved LED rectangle. */
if(!settled_psg())return 16;memcpy(baseline,memory,sizeof(memory));pitGate=0;waited=0;while(midiMeterShown[0]&&waited<40){waited++;if(frame()>4)return 17;}if(midiMeterShown[0]!=0||!only_led_delta(baseline,memory))return 18;memcpy(baseline,memory,sizeof(memory));pitGate=1;waited=0;while(!midiMeterShown[0]&&waited<40){waited++;if(frame()>4)return 19;}if(midiMeterShown[0]!=1U||!only_led_delta(baseline,memory))return 20;
/* Fixed-amplitude LED uses exactly one binary bit: no decay or partial height. */
if(midiMeterShown[0]!=1U||midiMeterWant[0]!=1U)return 19;
printf("PASS pixel checks: 16 attenuations x 4 PSG meters x 2 render modes, mixed levels, binary SPK, isolated LED delta; max SPK settle=%u frame(s) with four dirty PSG columns; max dirty writes/frame<=4; extra=%u\n",max_settle,frames);return 0;}
''' + current
        with tempfile.TemporaryDirectory(prefix="rave-speaker-pixels-") as td:
            folder = Path(td)
            binary = compile_host(source, folder, "speaker_pixels")
            result = run_compiler([str(binary)], folder)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("16 attenuations x 4 PSG meters", result.stdout)
            self.assertIn("max SPK settle=1 frame(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
