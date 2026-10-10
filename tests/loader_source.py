"""Actual production loader with explicit DOS-width storage on a host compiler.
The body is extracted unchanged except its 2-byte version variable; far
pointers and far allocation map to their host equivalents. Native DOS
CI remains the ABI/compiler check. This does not replace native qualification.
"""
from pathlib import Path
def generate(root):
 src=(root/'src/BEAT.C').read_text()
 body=src[src.index('static int title_char('):src.index('static void music_step(')]
 body=body.replace('unsigned version,i,k;', 'uint16_t version;unsigned i,k;')
 return '''#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#define far
#define _fmalloc malloc
#define _ffree free
#define _fmemcpy memcpy
#define MAX_NOTES 2048
#define MAX_STATES 4096
#define MAX_SEGS 64
#define MAX_DRUMS 4096
#pragma pack(push,1)
typedef struct { uint16_t tick,divisor[3];unsigned char attenuation[3],reserved; } State;
typedef struct { uint16_t tick,end_tick,divisor;unsigned char lane,attenuation,note,reserved; } Tap;
typedef struct { uint32_t start,period;uint16_t first,count; } Seg;
typedef struct { uint16_t tick;unsigned char kind,level; } Drum;
#pragma pack(pop)
static State *music;static Tap *chart;static unsigned char *judged;static Drum *drums;
static Seg segs[MAX_SEGS];
static unsigned cap_states,cap_taps,cap_drums,load_nomem;
static uint16_t states,duration,taps,nsegs,difficulty,required_taps,ndrums;
static char song_title[26];
'''+body+'''
int main(int argc,char **argv) {
 if(sizeof(State)!=12 || sizeof(Tap)!=10 || sizeof(Seg)!=12 || sizeof(Drum)!=4 || argc!=2)return 3;
 if(!load_score(argv[1]))return 2;
 printf("duration=%u states=%u lead=%u required=%u segments=%u drums=%u\\n",
  (unsigned)duration,(unsigned)states,(unsigned)taps,(unsigned)required_taps,(unsigned)nsegs,(unsigned)ndrums);
 return 0;
}
'''
