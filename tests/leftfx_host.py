"""Execute production left-panel code on the host against a pinned source.

Usage: python tests/leftfx_host.py --baseline ../baseline-build/src
       --out ../evidence/leftfx --cc C:/WATCOM/binnt/wcl386.exe
Clocks below model work costs to exercise scheduling; they measure no CPU.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMMON = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#define far
#define _fmalloc malloc
static unsigned char screen[32768];
static unsigned long clock_now,copy_cost,copy_bytes,heap_bytes,copies,polls;
static void *copy_count(void *dst,const void *src,unsigned n) {
    unsigned char *p=(unsigned char *)dst;
    if(p>=screen && p<screen+sizeof(screen)) {
        copy_bytes+=n;copies++;clock_now+=copy_cost;
    } else heap_bytes+=n;
    return memcpy(dst,src,n);
}
static void *set_count(void *dst,int v,unsigned n) {
    unsigned char *p=(unsigned char *)dst;
    if(p>=screen && p<screen+sizeof(screen)) {
        copy_bytes+=n;copies++;clock_now+=copy_cost;
    }
    return memset(dst,v,n);
}
#define _fmemcpy copy_count
#define _fmemset set_count
#define _fmemmove memmove
static int inp(unsigned p){(void)p;return 8;}
static int outp(unsigned p,unsigned v){(void)p;return (int)v;}
#include "GFX.H"
static int reduced,no_fx,clk_virtual=1;
static unsigned long clk_fine(void){return clock_now;}
static void audio_poll(void){polls++;}
typedef struct {unsigned long start,period;unsigned first,count;} Seg;
static unsigned nsegs;
static Seg segs[64];
'''
MAIN = r'''
static void snapshot(unsigned s,unsigned f) {
    char name[32];FILE *out;
    sprintf(name,"S%uF%u.BIN",s,f);out=fopen(name,"wb");assert(out);
    assert(fwrite(screen,1,sizeof(screen),out)==sizeof(screen));
    assert(fwrite(pal_want,1,16,out)==16);fclose(out);
}
static void sprite(unsigned s,long beat) {
    switch(fx_type[s]) {
    case FXK_CUBE:cube_frame(beat);break;
    case FXK_STARS:stars_frame(beat*9);break;
    case FXK_FLAG:flag_frame(beat);break;
    case FXK_ALFREDO:al_frame(beat);break;
    case FXK_ROTOZOOM:rz_start(beat);rz_rows(FX_H/2);break;
    }
}
#ifdef NEW_FX
static void frame(unsigned long t) {
    clock_now=t;fx_frame((long)t,0);pal_flush();
}
static void timing(void) {
    unsigned i,previous;unsigned long started;int scene;
    /* A ready frame cannot arm before song time zero. */
    fx_scene=0;fx_reset(-1000);fx_frame(-1000,0);pal_flush();
    assert(!fx_holding);frame(0);assert(fx_holding);
    /* Very fast tempo: sixteen beats finish first, eight seconds wins. */
    nsegs=1;segs[0].start=0;segs[0].period=256UL*256;
    segs[0].first=0;segs[0].count=1000;beat_reset(&pulse_cur);
    fx_hold_beat=0;fx_hold_time=0;
    frame(FX_DWELL_FINE-1);assert(fx_scene==0);
    frame(FX_DWELL_FINE);assert(fx_scene==1);
    /* Model each row taking one BIOS tick, exceeding old slot duration. */
    clk_virtual=0;copy_cost=256;fx_credit=0;
    for(i=0;fx_wipe<FX_DONE && i<400;i++) {
        previous=(unsigned)fx_wipe;
        frame(clock_now+128);assert(fx_wipe<=FX_DONE);
        assert((unsigned)fx_wipe==previous+1);
        assert(!fx_holding);
    }
    assert(fx_wipe==FX_DONE && i>=100 && i<=200);
    copy_cost=0;clk_virtual=1;
    frame(clock_now+128);assert(!fx_holding && fx_present);
    frame(clock_now+128);assert(fx_holding);
    started=fx_hold_time;scene=fx_scene;
    frame(started+FX_DWELL_FINE-1);assert(fx_scene==scene);
    frame(started+FX_DWELL_FINE);assert(fx_scene!=scene);
    /* A slow beat grid wins over the eight-second floor. */
    fx_scene=1;fx_reset(0);fx_credit=0;nsegs=1;
    segs[0].period=8000UL*256;beat_reset(&pulse_cur);
    frame(0);frame(128);assert(fx_holding);
    frame(16UL*8000-1);assert(fx_scene==1);
    frame(16UL*8000+128);assert(fx_scene!=1);
    /* Calm/FXOFF time cannot expire the freshly visible dwell. */
    fx_scene=1;fx_reset(0);frame(0);frame(128);
    reduced=1;frame(200000);assert(!fx_holding);
    reduced=0;frame(400000);assert(fx_scene==1 && fx_holding);
    no_fx=1;frame(500000);assert(!fx_holding);
    no_fx=0;frame(600000);assert(fx_scene==1 && fx_holding);
    /* Rotozoom's first partial pass cannot arm the dwell. */
    fx_scene=4;fx_reset(0);fx_credit=0;pal_flush();
    clk_virtual=0;copy_cost=0;rz_row=0;fx_present=0;
    fx_credit=-1000;frame(0);assert(!fx_present && !fx_holding);
    clk_virtual=1;fx_credit=0;frame(128);
    assert(rz_row==FX_H/2 && fx_present && !fx_holding);
    frame(256);assert(fx_holding);
    /* A palette awaiting retrace must not start visible dwell. */
    fx_scene=1;fx_reset(0);fx_present=1;pal_dirty=1;
    clock_now=0;fx_frame(0,0);assert(!fx_holding);pal_flush();
    frame(128);assert(fx_holding);
    puts("PASS ready, slow wipe, tempo bounds, calm, FXOFF, first sprite, palette");
}
#endif
int main(int argc,char **argv) {
    unsigned s,f;static const long beats[]={73,1001,2048,4095,8191};
    assert(argc==2);video=screen;gfx_init();fx_init();rz_init();
#ifdef NEW_FX
    if(!strcmp(argv[1],"timing")){timing();return 0;}
#endif
    for(s=0;s<FX_SCENES;s++) {
        memset(screen,0xaa,sizeof(screen));pal_identity();fx_scene=(int)s;
        copy_bytes=heap_bytes=copies=polls=0;star_seed=0x2a5d;
        fx_reset(-1000);snapshot(s,0);
        printf("%u %lu %lu %lu %lu\n",s,copy_bytes,heap_bytes,copies,polls);
        fx_still(s);snapshot(s,1);
        for(f=0;f<5;f++) {
            fx_pal(s,f+1);sprite(s,beats[f]);snapshot(s,f+2);
        }
    }
    return 0;
}
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_harness(src, out, cc, new):
    out.mkdir(parents=True, exist_ok=True)
    play = (src / 'PLAY.H').read_text()
    beats = play[play.index('typedef struct { unsigned seg,k;'):
                 play.index('#include "LEFT.H"')]
    code = COMMON + beats + '\n#include "LEFT.H"\n' + MAIN
    source = out / 'harness.c'
    source.write_bytes(code.replace('\n', '\r\n').encode())
    exe = out / 'harness.exe'
    if 'wcl386' in cc.lower():
        cmd = [cc, '-q', '-bt=nt', '-i='+str(src),
               '-fe='+str(exe), str(source)]
    else:
        cmd = [cc, '-std=c89', '-Wall', '-Wextra', '-I', str(src),
               str(source), '-o', str(exe)]
    if new:
        cmd.insert(1, '-DNEW_FX')
    result = subprocess.run(cmd, cwd=out, capture_output=True, text=True)
    (out / 'compile.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    return exe


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--cc', default=os.environ.get('RAVE_TEST_CC', 'gcc'))
    args = p.parse_args()
    out = args.out.resolve()
    roots = [('before', args.baseline.resolve()), ('after', ROOT/'src')]
    counts = {}
    for label, src in roots:
        exe = build_harness(src, out/label, args.cc, label == 'after')
        result = subprocess.run([str(exe), 'render'], cwd=out/label,
                                capture_output=True, text=True, check=True)
        counts[label] = [list(map(int, row.split()))
                         for row in result.stdout.splitlines()]
        if label == 'after':
            timing = subprocess.run([str(exe), 'timing'], cwd=out/label,
                                    capture_output=True, text=True)
            (out/'timing.log').write_text(timing.stdout + timing.stderr)
            assert timing.returncode == 0, timing.stdout + timing.stderr
    images = []
    for before in sorted((out/'before').glob('S*F*.BIN')):
        after = out/'after'/before.name
        assert before.read_bytes() == after.read_bytes(), before.name
        images.append(dict(file=before.name, sha256=digest(after)))
    assert len(images) == 56
    # No rendering, clock, input, tone, drum, song or launcher edits elsewhere.
    for name in ['BEAT.C', 'CLOCK.H', 'CORE.H', 'DOSSND.C', 'DOSSND.H',
                 'GFX.H', 'PLAY.H', 'SHOW.H', 'SONGS.H', 'FX.H', 'WORDS.H']:
        assert digest(roots[0][1]/name) == digest(ROOT/'src'/name), name
    result = dict(status='PASS', host_only=True, physical_speed_claim=False,
                  frame_palette_pairs_equal=56, images=images,
                  initial_work_counts=counts, timing=timing.stdout.strip(),
                  unchanged_production_paths=True)
    (out/'RESULTS.json').write_text(json.dumps(result, indent=2)+'\n')
    print('PASS 56 complete bank images/palettes, timing gates, unchanged core')


if __name__ == '__main__':
    main()
