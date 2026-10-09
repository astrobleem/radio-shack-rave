"""Actual production loader with explicit DOS-width storage on a host compiler.
The body is extracted unchanged except its 2-byte version variable; native DOS
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
#define MAX_NOTES 512
#define MAX_STATES 1024
#define MAX_SEGS 64
#pragma pack(push,1)
typedef struct { uint16_t tick,divisor[3];unsigned char attenuation[3],reserved; } State;
typedef struct { uint16_t tick,end_tick,divisor;unsigned char lane,attenuation,note,reserved; } Tap;
typedef struct { uint32_t start,period;uint16_t first,count; } Seg;
#pragma pack(pop)
static State music[MAX_STATES];static Tap chart[MAX_NOTES];static Seg segs[MAX_SEGS];
static uint16_t states,duration,taps,nsegs,difficulty,required_taps;
static char song_title[26];
'''+body+'''
int main(int argc,char **argv) {
 if(sizeof(State)!=12 || sizeof(Tap)!=10 || sizeof(Seg)!=12 || argc!=2)return 3;
 if(!load_score(argv[1]))return 2;
 printf("duration=%u states=%u lead=%u required=%u segments=%u\\n",
  (unsigned)duration,(unsigned)states,(unsigned)taps,(unsigned)required_taps,(unsigned)nsegs);
 return 0;
}
'''
