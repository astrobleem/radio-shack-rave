/* Offline RWS1 compiler. Includes the frozen Win16 producer verbatim; the
 * host stubs only replace Windows loading, RAWCLK queueing, and wall time. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "windows.h"
#ifndef RAVE_MIDICLK_SOURCE
#define RAVE_MIDICLK_SOURCE "../deps/libwintandy/sound/MIDICLK.C"
#endif
#include RAVE_MIDICLK_SOURCE
#include "SMF.H"

#define FRAME_LIMIT 18000U /* Same 20 x 900-frame bound as the DOS loader. */
typedef struct { TCXFRAME state; WORD noiseEvent, messages; } CAPTURE;
static CAPTURE captured[FRAME_LIMIT];
static unsigned pushed, deliveredRaw;
static WORD rawEnd, rawStart, rawOpen;
static DWORD virtualCycles;
static WORD midHandle, have, feedEof, feedEnded;
static DWORD feedCommitted;
static SMF_EVENT event;
static MDINFO snapshot;

HTASK GetCurrentTask(void){return 1;}
HMODULE GetModuleHandle(const char *name){return !strcmp(name,"MIDICLK")?33:34;}
WORD GetModuleFileName(HMODULE h,char *out,WORD cap){
 const char *p=h==34?"C:\\MMLAB\\RAWCLK.DLL":"C:\\MMLAB\\MIDICLK.DLL";
 (void)cap;strcpy(out,p);return (WORD)strlen(out);
}
HMODULE LoadLibrary(const char *path){return strstr(path,"RAWCLK")?34:33;}
WORD FreeLibrary(HMODULE h){(void)h;return 0;}
static WORD rawOpenFn(void){rawOpen=1;pushed=deliveredRaw=rawEnd=rawStart=0;return 0;}
static WORD rawCloseFn(void){rawOpen=0;return 0;}
static WORD rawStartFn(void){rawStart=1;return 0;}
static WORD rawEndFn(void){rawEnd=1;return 0;}
static WORD rawZero(void){return 0;}
static WORD rawStatusFn(WORD q){switch(q){
 case 1:return rawStart;
 case 2:return (WORD)deliveredRaw;
 case 6:return 0;
 case 7:return rawEnd&&deliveredRaw==pushed;
 case 20:return 1;
 }return 0;}
static DWORD rawClockFn(void){return virtualCycles;}
static WORD rawPushFn(TCFRAME *f){(void)f;return 1;}
static WORD noiseCapsFn(WORD v,TCNINFO *c,WORD n){
 if(v!=TCN_VERSION||n!=sizeof(*c))return 3;
 c->size=n;c->version=v;c->features=TCN_EXPLICIT_NOISE;
 c->frameBytes=sizeof(TCXFRAME);c->eventMask=TCN_RETRIGGER;c->reserved=0;return 0;
}
static WORD speakerCapsFn(WORD v,TCXINFO *c,WORD n){
 if(v!=TCX_VERSION||n!=sizeof(*c))return 3;
 memset(c,0,sizeof(*c));c->size=n;c->version=v;c->status=TCX_AVAILABLE;
 c->minDivisor=152;c->maxDivisor=65535;return 0;
}
static WORD noisePushFn(TCXFRAME *f,WORD flags){
 if(pushed-deliveredRaw>=1024U)return 2;
 if(pushed>=FRAME_LIMIT)return 1;
 captured[pushed].state=*f;captured[pushed].noiseEvent=flags;
 captured[pushed].messages=frameN;pushed++;return 0;
}
FARPROC GetProcAddress(HMODULE h,LPSTR p){uintptr_t q=(uintptr_t)p;(void)h;
 switch(q){
 case 2:return (FARPROC)rawPushFn;
 case 3:return (FARPROC)rawStartFn;
 case 4:return (FARPROC)rawEndFn;
 case 5:return (FARPROC)rawCloseFn;
 case 6:return (FARPROC)rawStatusFn;
 case 11:return (FARPROC)rawZero;
 case 12:return (FARPROC)rawClockFn;
 case 13:return (FARPROC)rawOpenFn;
 case 14:case 15:case 16:case 17:case 18:case 19:return (FARPROC)rawZero;
 case 24:return (FARPROC)speakerCapsFn;
 case 28:return (FARPROC)rawZero; /* TCX_AVAILABLE */
 case 29:return (FARPROC)rawZero; /* configure PIT lease */
 case 30:return (FARPROC)rawZero;
 case 31:return (FARPROC)noiseCapsFn;
 case 32:return (FARPROC)noisePushFn;
 case 33:return (FARPROC)rawZero;
 }return 0;
}

/* Same bounded lookahead/commit rule and 4096/32 budgets as MCIPSG.C. */
static int feed(unsigned budget){int r;WORD result;DWORD through;
 while(budget--&&!feedEof){
  if(!have){r=smf_step(&event);if(r<0){fprintf(stderr,"SMF step: %s\n",smf_error());return 1;}
   if(r==2)continue;if(!r){feedEof=1;break;}have=1;}
  if(!budget)break;
  result=MDPush(midHandle,snapshot.generation,event.ms,(DWORD)event.status|
    ((DWORD)event.data1<<8)|((DWORD)event.data2<<16));
  if(result==MD_FULL)break;
  if(result){fprintf(stderr,"MDPush=%u at=%lu\n",result,(unsigned long)event.ms);return 1;}
  have=0;
 }
 if(feedEnded)return 0;
 if(feedEof){result=MDCommit(midHandle,snapshot.generation,smf_duration_ms(),MD_EOF);
  if(result){fprintf(stderr,"EOF commit=%u\n",result);return 1;}feedEnded=1;return 0;}
 if(!have)return 0;
 if(event.ms){through=event.ms-1;
  if(through>=feedCommitted){result=MDCommit(midHandle,snapshot.generation,through,0);
   if(result){fprintf(stderr,"commit=%u at=%lu\n",result,(unsigned long)through);return 1;}
   feedCommitted=through;}}
 return 0;
}
static void byte(FILE *f,unsigned v,uint32_t *sum){fputc(v&255,f);*sum+=v&255;}
static void word(FILE *f,unsigned v,uint32_t *sum){byte(f,v,sum);byte(f,v>>8,sum);}
static void dword(FILE *f,uint32_t v,uint32_t *sum){word(f,v&65535U,sum);word(f,v>>16,sum);}
static void header(FILE *f,uint32_t duration,unsigned messages,uint32_t sum){uint32_t ignore=0;
 fwrite("RWS1",1,4,f);word(f,32,&ignore);word(f,18,&ignore);
 dword(f,pushed,&ignore);dword(f,duration,&ignore);word(f,messages,&ignore);
 word(f,3,&ignore);word(f,1,&ignore);word(f,0,&ignore);
 dword(f,sum,&ignore);dword(f,0x3954504fU,&ignore);
}
static int write_results(const char *output,const char *trace,DWORD duration,unsigned messages){
 FILE *f,*t;unsigned i;DWORD lastAt=0,lastFine=0;uint32_t sum=0,totalMessages=0;
 if(!pushed||pushed>FRAME_LIMIT)return 1;
 if(captured[pushed-1].state.frame.volume!=65535U||
    captured[pushed-1].state.pitDivisor!=0)return 1;
 f=fopen(output,"wb");if(!f)return 1;
 t=fopen(trace,"w");if(!t){fclose(f);return 1;}
 header(f,duration,messages,0);
 fprintf(t,"frame,at_cycles,at_fine,p0,p1,p2,volume,noise,retrigger,pit_divisor,frame_messages\n");
 for(i=0;i<pushed;i++){
  CAPTURE *c=&captured[i];TCFRAME *v=&c->state.frame;
  DWORD fine=(v->at>>8)+((v->at&255U)!=0);
  unsigned retrigger=(c->noiseEvent&TCN_RETRIGGER)?1U:0U;
  if((i&&v->at<=lastAt)||(i&&fine<=lastFine)||v->mask!=15||v->noise>7||
      (c->noiseEvent&~TCN_RETRIGGER)||
      (c->state.pitDivisor&&c->state.pitDivisor<152)){
   fprintf(stderr,"invalid frame %u\n",i);fclose(t);fclose(f);return 1;}
  lastAt=v->at;lastFine=fine;totalMessages+=c->messages;
  dword(f,fine,&sum);word(f,v->p[0],&sum);word(f,v->p[1],&sum);
  word(f,v->p[2],&sum);word(f,v->volume,&sum);byte(f,v->noise,&sum);
  byte(f,retrigger,&sum);word(f,c->state.pitDivisor,&sum);
  word(f,c->messages,&sum);
  fprintf(t,"%u,%lu,%lu,%u,%u,%u,%u,%u,%u,%u,%u\n",i,
    (unsigned long)v->at,(unsigned long)fine,v->p[0],v->p[1],v->p[2],
    v->volume,v->noise,retrigger,c->state.pitDivisor,c->messages);
 }
 if(totalMessages!=messages){fprintf(stderr,"frame messages=%lu expected=%u\n",(unsigned long)totalMessages,messages);
  fclose(t);fclose(f);return 1;}
 if(fseek(f,0,SEEK_SET)){fclose(t);fclose(f);return 1;}
 header(f,duration,messages,sum);
 if(fclose(t)||fclose(f))return 1;
 fprintf(stdout,"frames=%u messages=%lu duration=%lu payload_sum=%lu end_cycle=%lu end_fine=%lu\n",
   pushed,(unsigned long)totalMessages,(unsigned long)duration,(unsigned long)sum,
   (unsigned long)lastAt,(unsigned long)lastFine);
 return 0;
}
int main(int argc,char **argv){FILE *src;unsigned char *song;long size;DWORD nowMs,duration;WORD messages;MDINFO current;
 if(argc!=4){fprintf(stderr,"usage: rave_prepare input.mid output.rws exact_cycles.csv\n");return 2;}
 src=fopen(argv[1],"rb");if(!src){perror(argv[1]);return 2;}
 if(fseek(src,0,SEEK_END)){fclose(src);return 2;}size=ftell(src);rewind(src);
 if(size<=0||size>SMF_MAX_FILE){fclose(src);return 2;}
 song=(unsigned char *)malloc((size_t)size);if(!song){fclose(src);return 2;}
 if(fread(song,1,(size_t)size,src)!=(size_t)size){fclose(src);free(song);return 2;}
 fclose(src);
 if(!smf_open(song,(unsigned)size)||!smf_rewind()){fprintf(stderr,"SMF: %s\n",smf_error());free(song);return 1;}
 duration=smf_duration_ms();messages=smf_event_count();
 if(MDOpen(&midHandle)||MDVoiceMode(midHandle,3)||MDTiming(midHandle,1)||
    MDSpeakerMode(midHandle,1)||MDStatus(midHandle,&snapshot,sizeof(snapshot))){fprintf(stderr,"MD open/config failed\n");return 1;}
 if(renderSpeakerMode!=1||!extendedFrame){fprintf(stderr,"speaker assist unavailable\n");return 1;}
 if(feed(4096)||MDStart(midHandle)){fprintf(stderr,"MD start failed\n");return 1;}
 for(nowMs=0;nowMs<=duration+2000UL;nowMs+=55UL){
  virtualCycles=MSCycles(nowMs);
  while(deliveredRaw<pushed&&captured[deliveredRaw].state.frame.at<=virtualCycles)deliveredRaw++;
  if(MDPump(midHandle)||MDStatus(midHandle,&current,sizeof(current))){fprintf(stderr,"MD pump failed at %lu ms\n",(unsigned long)nowMs);return 1;}
  snapshot=current;
  if(current.state==MD_FAILED){fprintf(stderr,"MD failed at %lu ms error=%u\n",(unsigned long)nowMs,current.error);return 1;}
  if(current.state==MD_DONE)break;
  if(feed(32)){fprintf(stderr,"feed failed at %lu ms\n",(unsigned long)nowMs);return 1;}
 }
 if(info.state!=MD_DONE||info.accepted!=messages||info.delivered!=messages||
    !rawEnd||deliveredRaw!=pushed||!feedEnded){
  fprintf(stderr,"incomplete state=%u accepted=%lu delivered=%lu frames=%u/%u eof=%u\n",
    info.state,(unsigned long)info.accepted,(unsigned long)info.delivered,
    deliveredRaw,pushed,feedEnded);return 1;}
 if(write_results(argv[2],argv[3],duration,messages))return 1;
 if(MDClose(midHandle)){fprintf(stderr,"close failed\n");return 1;}
 smf_close();free(song);return 0;
}
