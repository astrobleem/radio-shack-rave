"""Exercise production catalog/loader and game transitions without DOS hardware."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from loader_source import generate

ROOT = Path(__file__).resolve().parents[1]
CATALOG = r'''
#include <stdlib.h>
#include <assert.h>
#define _A_NORMAL 0
#define _A_SUBDIR 16
#define _A_VOLID 8
struct find_t { unsigned attrib;char name[13]; };
static unsigned enumerated, entries, fake_attr;
static const char *fake_name;
unsigned _dos_findfirst(const char *p,unsigned a,struct find_t *f) {
 assert(!strcmp(p,"SONGS\\*.RBG") && !a);enumerated=0;
 if(!entries)return 1;
 strcpy(f->name,fake_name);f->attrib=fake_attr;enumerated++;return 0;
}
unsigned _dos_findnext(struct find_t *f) {
 if(enumerated>=entries)return 1;
 strcpy(f->name,fake_name);f->attrib=fake_attr;enumerated++;return 0;
}
#include "SONGS.H"
static unsigned calls, accepts;
static int stub_load(const char *p) {
 calls++;assert(!strncmp(p,"SONGS\\",6));return accepts;
}
int main(int argc,char **argv) {
 unsigned i,j,previous=SONG_MAX,seen[SONG_MAX],snapshot[192];
 char name[13];unsigned long rng;
 assert(argc==2);
 if(!strcmp(argv[1],"catalog")) {
  songs_reset(17);assert(!songs_next(stub_load));assert(!calls);
  assert(!song_name_ok("") && !song_name_ok("A.") && !song_name_ok("A.R"));
  assert(!song_name_ok("LONGNAME9.RBG") && !song_name_ok("../A.RBG"));
  assert(!song_name_ok("A.EXE") && !song_name_ok("A.RBG.EXE"));
  assert(song_name_ok("A.RBG") && song_name_ok("a1234567.rbg"));
  accepts=0;assert(songs_add("BAD.RBG"));assert(song_count==1 && !calls);
  assert(!songs_next(stub_load));assert(calls==1);
  songs_reset(17);calls=0;
  accepts=1;
  for(i=0;i<SONG_MAX+10;i++) {sprintf(name,"S%u.RBG",i);songs_add(name);}
  assert(song_count==SONG_MAX && calls==0);
  assert(!songs_add("S0.RBG"));
  for(j=0;j<3;j++) {
   memset(seen,0,sizeof(seen));
   for(i=0;i<SONG_MAX;i++) {
    assert(songs_next(stub_load));assert(song_last!=previous);
    previous=song_last;assert(!seen[previous]++);snapshot[j*SONG_MAX+i]=previous;
   }
  }
  songs_reset(17);
  for(i=0;i<SONG_MAX;i++){sprintf(name,"S%u.RBG",i);songs_add(name);}
  for(i=0;i<192;i++){assert(songs_next(stub_load));assert(song_last==snapshot[i]);}
  rng=song_rng;assert(!songs_add("MISSING.EXE"));assert(song_rng==rng);
  songs_reset(0);songs_add("ONLY.RBG");
  for(i=0;i<10;i++)assert(songs_next(stub_load) && song_last==0);
  accepts=0;calls=0;assert(!songs_next(stub_load));assert(calls==1);
  calls=0;assert(!songs_next(stub_load));assert(!calls);
  songs_reset(9);entries=2000;fake_name="BAD.RBG";fake_attr=0;
  songs_discover();assert(enumerated==SONG_SCAN_MAX && song_count==1 && !calls);
  assert(!songs_next(stub_load));assert(calls==1);
  songs_reset(9);
  accepts=1;entries=3;fake_attr=_A_SUBDIR;calls=0;
  songs_discover();assert(!calls && !song_count);
  fake_attr=_A_VOLID;songs_discover();assert(!calls);
  entries=0;songs_discover();assert(!song_count);
 } else {
  songs_reset(3);
  assert(songs_add("BAD.RBG"));
  assert(songs_add("EMPTY.RBG"));
  assert(songs_add("SHORT.RBG"));
  assert(songs_add("META.RBG"));
  assert(songs_add("MISSING.RBG"));
  assert(songs_add("ONE.RBG"));assert(songs_add("TWO.RBG"));
  previous=SONG_MAX;
  for(i=0;i<12;i++) {
   assert(songs_next(load_score));assert(duration && required_taps);
   assert(song_last!=previous);previous=song_last;
  }
  assert(!remove("SONGS/ONE.RBG"));assert(!remove("SONGS/TWO.RBG"));
  assert(!songs_next(load_score));assert(!songs_next(load_score));
 }
 puts("PASS catalog/loader");return 0;
}
'''

GAME = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define A_EXIT 0
#define A_PLAY 1
#define A_TITLE 2
#define A_DEMO 3
#define A_SPLASH 4
#define WINDOW 3
typedef struct { unsigned tick,lane,reserved; } Tap;
static Tap chart[2];
static unsigned duration=10,taps=0,live_from,judged[2],down[128],flash_kind[3];
static int flash_until[3],key_lit[3],results_step;
static int songs_mode,song_ready,demo_mode,tour_mode,auto_mode,reduced,exit_reason;
static unsigned restart_count,late_frames,frame_cost,worst_fine,worst_ticks,frames;
static unsigned shot_mode,dump_done,lead_div;
static unsigned long idle_since,fine_sum,clock_tick,origin;
static unsigned resets,stops,cancels,loads,key_once,key_at;
static int load_result=1,next_result=1;
static int owned,keyboard_owned,video_owned;
static unsigned old_mode=3,restored_mode,releases,vectors;
static void (*old_keyboard)(void);
static FILE *psg_log;
static void _dos_setvect(unsigned n,void (*v)(void)){assert(n==9 && v==old_keyboard);vectors++;}
static void DosSoundRelease(void){releases++;}
static void mode(unsigned n){restored_mode=n;}
static void lead_step(int n){(void)n;}
static void automatic_step(int n){(void)n;}
static void music_step(int n){(void)n;}
static int song_time(void){return (int)(clock_tick-origin)-36;}
static long song_fine(void){return (long)song_time()*256;}
static int fine_tick(long n){return (int)(n/256);}
static unsigned long clk_ticks(void){return clock_tick;}
static unsigned long clk_fine(void){return clock_tick*256;}
static void restart(void){resets++;origin=clock_tick;lead_div=0;}
static void lead_cancel(int n){(void)n;cancels++;lead_div=0;}
static void sfx_stop(void){stops++;}
static int load_score(const char *p){assert(!strcmp(p,"ORIGINAL.RBG"));loads++;return load_result;}
static int songs_next(int (*f)(const char *)){(void)f;loads++;return next_result;}
static int autoplays(void){return 0;}
static void key_event(unsigned k){(void)k;}
static unsigned key_take(unsigned *ago) {
 *ago=0;if(key_once && clock_tick>=key_at){unsigned k=key_once;key_once=0;return k;}return 0;
}
static void hit(unsigned l,int n){(void)l;(void)n;}
static void expire(int n){(void)n;}
static void playfield_frame(long f,int n){(void)f;(void)n;}
static void results_frame(int n){(void)n;}
static void sfx_step(void){}
static void dump_frame(const char *p){(void)p;}
static void frame_end(void){clock_tick++;assert(clock_tick<10000);}
'''
GAME_MAIN = r'''
int main(void) {
 unsigned n;
 songs_mode=1;song_ready=0;lead_div=1;
 assert(song_prepare());assert(cancels==1 && stops==1 && loads==1 && !lead_div);
 assert(song_prepare());assert(loads==1);
 assert(game_run(1)==A_DEMO);assert(resets==1 && !song_ready && clock_tick>=153);
 assert(song_prepare());assert(loads==2 && cancels==2 && stops==2);
 key_once=57;key_at=clock_tick;assert(game_run(1)==A_PLAY);assert(song_ready);
 assert(song_prepare());assert(loads==2); /* Space retains demo song. */
 key_once=1;key_at=clock_tick;assert(game_run(1)==A_EXIT);assert(exit_reason==1);
 song_ready=0;next_result=0;assert(song_prepare());assert(!songs_mode && loads==4);
 songs_mode=1;song_ready=0;load_result=0;assert(!song_prepare());assert(!songs_mode);
 /* After any game the next song is chosen when the title is entered, so the
    marquee names it and Space/idle demo play that same song. */
 songs_mode=1;next_result=1;load_result=1;song_ready=0;n=loads;
 assert(action_ready(A_TITLE));assert(loads==n+1 && song_ready);
 assert(action_ready(A_PLAY) && action_ready(A_DEMO));assert(loads==n+1);
 assert(action_ready(A_SPLASH) && action_ready(A_EXIT));assert(loads==n+1);
 songs_mode=0;key_once=0;assert(game_run(1)==A_SPLASH);
 tour_mode=1;assert(game_run(1)==A_EXIT);
 n=resets;auto_mode=4;key_once=19;key_at=clock_tick;
 assert(game_run(0)==A_EXIT);assert(resets==n+2); /* R retries current song. */
 owned=keyboard_owned=video_owned=1;lead_div=1;psg_log=tmpfile();assert(psg_log);
 cleanup();assert(!owned && !keyboard_owned && !video_owned && !lead_div && !psg_log);
 assert(releases==1 && vectors==1 && restored_mode==3);
 cleanup();assert(releases==1 && vectors==1); /* Idempotent final cleanup. */
 puts("PASS production demo/end/Space/Escape/fallback/mute/reset/title-names-next");return 0;
}
'''


class SongsTests(unittest.TestCase):
    def compile(self, text, folder, name):
        source = folder / (name + '.c')
        source.write_text(text)
        exe = folder / (name + '.exe')
        cc = os.environ.get('RAVE_TEST_CC', 'gcc')
        if 'wcl386' in cc.lower():
            cmd = [cc, '-q', '-bt=nt', '-w4', '-i=' + str(ROOT/'src'),
                   '-fe=' + exe.name, str(source)]
        else:
            cmd = [cc, '-std=c89', '-Wall', '-Wextra', '-I', str(ROOT/'src'),
                   str(source), '-o', str(exe)]
        result = subprocess.run(cmd, cwd=folder, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return exe

    def test_catalog_and_real_loader(self):
        with tempfile.TemporaryDirectory(prefix='rave-songs-') as td:
            folder = Path(td)
            loader = generate(ROOT).split('int main(')[0]
            # Production DOS paths are valid on Windows. Translate separators
            # only at the host-test file boundary for POSIX CI; body stays DOS.
            shim = r'''
static FILE *host_fopen(const char *name,const char *mode) {
 char path[260];unsigned i;
 if(strlen(name)>=sizeof(path))return 0;
 strcpy(path,name);
 for(i=0;path[i];i++)if(path[i]=='\\')path[i]='/';
 return fopen(path,mode);
}
'''
            loader = loader.replace('static int title_char(', shim+'static int title_char(', 1)
            loader = loader.replace('f=fopen(name,"rb")', 'f=host_fopen(name,"rb")')
            exe = self.compile(loader + CATALOG, folder, 'catalog')
            subprocess.run([str(exe), 'catalog'], cwd=folder, check=True)
            songs = folder / 'SONGS'; songs.mkdir()
            for name in ['ONE', 'TWO']:
                shutil.copyfile(ROOT/'runtime/ORIGINAL.RBG', songs/(name+'.RBG'))
            (songs/'BAD.RBG').write_bytes(b'garbage')
            (songs/'EMPTY.RBG').write_bytes(b'')
            (songs/'SHORT.RBG').write_bytes(b'RBG4\x04')
            (songs/'META.RBG').write_bytes(b'RBG4'+struct.pack('<HHHH',4,10,2,1)+b'\x01')
            subprocess.run([str(exe), 'files'], cwd=folder, check=True)

    def test_actual_demo_loop_and_prepare(self):
        src = (ROOT/'src/BEAT.C').read_text()
        prepare = src[src.index('static int song_prepare('):src.index('static int autoplays(')]
        game = src[src.index('static int game_run('):src.index('static int run_show(')]
        cleanup = src[src.index('static void cleanup('):src.index('static int title_char(')]
        with tempfile.TemporaryDirectory(prefix='rave-transitions-') as td:
            exe = self.compile(GAME + cleanup + prepare + game + GAME_MAIN, Path(td), 'game')
            subprocess.run([str(exe)], cwd=td, check=True)


if __name__ == '__main__':
    unittest.main()
