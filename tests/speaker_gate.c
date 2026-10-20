#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int failPit, failedPitCalls, pitCalls;
static unsigned lastDivisor;
int DosSoundPsgByte(unsigned v){(void)v;return 0;}
int DosSoundPsgBytes(const unsigned char *b,unsigned n){(void)b;(void)n;return 0;}
int DosSoundPitDivisor(unsigned d,unsigned a){(void)a;pitCalls++;lastDivisor=d;if(failPit){failPit=0;failedPitCalls++;return -9;}return 0;}
#define far
#define _cdecl
#define _fmalloc malloc
#define _ffree free
#define _fmemcpy memcpy
#define _fmemset memset
#include "src/RAVEMID.C"
#define REQUIRE(test,code,msg) do {if(!(test)){fprintf(stderr,"FAIL %s\n",msg);return code;}} while(0)
static void poll(unsigned long at){RaveMidiPollFine(at);}
int main(int argc,char **argv){unsigned before;
 if(argc!=2)return 2;
 /* Live path must report confirmed writes, not intended state. */
 MSReset(&synth);emittedPitGate=0;oldSpeaker=oldSpeakerAttacks=65535U;
 synth.speakerDivisor=500;synth.speakerAttacks=1;midi_psg();
 REQUIRE(RaveMidiPitGate()==1,10,"live successful on not reflected");
 synth.speakerDivisor=0;failPit=1;midi_psg();
 REQUIRE(failedPitCalls&&lastDivisor==0&&RaveMidiPitGate()==1,11,"failed live mute changed confirmed gate");
 midi_psg();REQUIRE(RaveMidiPitGate()==0,12,"successful live mute did not clear gate");
 synth.speakerDivisor=500;synth.speakerAttacks=2;midi_psg();
 REQUIRE(RaveMidiPitGate()==1,13,"live re-on not reflected");
 /* Opening/predecoding must not fabricate an emitted gate write. */
 before=pitCalls;REQUIRE(RaveMidiOpen(argv[1])&&RaveMidiPrepared(),14,"synthetic RWS not accepted");
 REQUIRE(rvPit==0&&pitCalls==before&&RaveMidiPitGate()==1,15,"prefetch changed emitted gate");
 RaveMidiRewind();REQUIRE(RaveMidiPitGate()==0,16,"rewind did not confirm silence");
 poll(0);REQUIRE(RaveMidiPitGate()==0,17,"initial off frame wrong");
 failPit=1;poll(40);REQUIRE(failedPitCalls&&lastDivisor==500&&RaveMidiPitGate()==0,18,"failed prepared on changed gate");
 poll(80);REQUIRE(RaveMidiPitGate()==1&&lastDivisor==450,19,"prepared nonzero divisor change failed");
 failPit=1;poll(120);REQUIRE(failedPitCalls&&lastDivisor==0&&RaveMidiPitGate()==1,20,"failed prepared off changed gate");
 poll(160);REQUIRE(RaveMidiPitGate()==1&&lastDivisor==620,21,"prepared re-on change failed");
 poll(200);REQUIRE(RaveMidiPitGate()==0&&lastDivisor==0,22,"prepared final off failed");
 /* A failed explicit silence leaves the last successful gate cached. */
 RaveMidiRewind();poll(0);poll(40);REQUIRE(RaveMidiPitGate()==1,23,"setup for failed silence");
 failPit=1;before=RaveMidiPitGate();RaveMidiSilence();
 REQUIRE(failedPitCalls&&lastDivisor==0&&RaveMidiPitGate()==before,24,"failed silence corrupted cache");
 RaveMidiSilence();REQUIRE(RaveMidiPitGate()==0,25,"successful silence did not clear cache");
 /* Close failure retains the state; successful close and rewind clear it. */
 RaveMidiRewind();poll(0);poll(40);REQUIRE(RaveMidiPitGate()==1,26,"setup for close mute");
 failPit=1;RaveMidiClose();REQUIRE(failedPitCalls&&lastDivisor==0&&RaveMidiPitGate()==1,27,"failed close mute corrupted cache");
 REQUIRE(RaveMidiOpen(argv[1])&&RaveMidiPrepared(),28,"reopen synthetic RWS");RaveMidiRewind();
 REQUIRE(RaveMidiPitGate()==0,29,"rewind after reopen did not clear gate");poll(0);poll(40);
 REQUIRE(RaveMidiPitGate()==1,30,"replay gate-on failed");RaveMidiClose();
 REQUIRE(RaveMidiPitGate()==0,31,"successful close did not clear gate");
 printf("PASS synthetic prepared RWS live/prepared gate transitions, decoded prefetch, injected failed on/off/silence/close writes, rewind/reopen; PIT calls=%u injected failures=%u final gate=%u\n",(unsigned)pitCalls,(unsigned)failedPitCalls,RaveMidiPitGate());
 return 0;
}
