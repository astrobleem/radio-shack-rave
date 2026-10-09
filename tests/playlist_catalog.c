
#include <dos.h>
#include <direct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
static void lead_output(int n,unsigned d,unsigned a){(void)n;(void)d;(void)a;}
#include "CORE.H"
#include "SONGS.H"
#define MAX_STATES 1024
#define MAX_SEGS 64
typedef struct {unsigned tick,divisor[3];unsigned char attenuation[3],reserved;} State;
typedef struct {unsigned long start,period;unsigned first,count;} Seg;
static State music[MAX_STATES];static Seg segs[MAX_SEGS];
static unsigned states,duration,nsegs,difficulty;
static char song_title[26];
#include "VALIDATOR.H"
static unsigned loads;
static int counted(const char *p){loads++;return load_score(p);}
int main(void){unsigned i,j,prev=SONG_MAX,seen[SONG_MAX];char path[19];
 assert(sizeof(State)==12 && sizeof(Tap)==10 && sizeof(Seg)==12);
 assert(!_chdir("EMPTY"));songs_reset(17);songs_discover();
 assert(!song_count && !songs_next(counted));assert(load_score("ORIGINAL.RBG"));assert(!_chdir(".."));
 assert(!_chdir("INVALID"));songs_reset(17);songs_discover();
 assert(song_count==3 && !songs_next(counted));assert(load_score("ORIGINAL.RBG"));assert(!_chdir(".."));
 assert(!_chdir("MIX"));songs_reset(17);songs_discover();assert(song_count==6);
 for(j=0;j<3;j++){memset(seen,0,sizeof(seen));for(i=0;i<3;i++){
 assert(songs_next(counted));assert(song_last!=prev && !seen[song_last]++);prev=song_last;
 printf("cycle=%u title=%s\n",j,song_title);}}
 for(i=0;i<song_count;i++){song_path(path,song_names[i]);assert(!remove(path));}
 assert(!songs_next(counted));loads=0;assert(!songs_next(counted) && !loads);assert(!_chdir(".."));
 assert(!_chdir("MANY"));songs_reset(17);songs_discover();assert(song_count==64);
 for(j=0;j<2;j++){memset(seen,0,sizeof(seen));for(i=0;i<64;i++){
 assert(songs_next(counted));assert(!seen[song_last]++);if(i==0 && j)assert(song_last!=prev);prev=song_last;}}
 assert(!_chdir(".."));
 puts("PASS native DOS enumeration RBG2/3/4 malformed empty directory 64-candidate bound shuffle disappearance fallback");return 0;}
