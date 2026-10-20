/* Independent output oracle: compile actual frozen TIMECLK.C frame() and
   actual PITLEASE.H LeaseFast, with only Win16/port access stubbed. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#define TC_HOST 1
#ifndef RAVE_TIMECLK_SOURCE
#define RAVE_TIMECLK_SOURCE "../deps/libwintandy/sound/TIMECLK.C"
#endif
#include RAVE_TIMECLK_SOURCE
#define SAPI
static unsigned running,pitActive,port61,half;
static FILE *out;
WORD PitRead(void){return (WORD)port61;}
void PitGate(WORD bits){port61=bits;if(out)fprintf(out,"G%02X ",bits&255);}
void PitProgram(WORD divisor){if(out)fprintf(out,"C%02X L%02X H%02X ",0xb6,divisor&255,divisor>>8);}
#ifndef RAVE_PITLEASE_SOURCE
#define RAVE_PITLEASE_SOURCE "../deps/libwintandy/sound/DRIVER/PITLEASE.H"
#endif
#include RAVE_PITLEASE_SOURCE
void PsgByte(WORD value){if(out)fprintf(out,"P%02X ",value&255);}
WORD SaveIRQ(void){return 0;}
void RestoreIRQ(WORD v){(void)v;}
HTASK GetCurrentTask(void){return 1;}
HMODULE GetModuleHandle(const char *s){(void)s;return 0;}
WORD GetModuleFileName(HMODULE h,char *s,WORD n){(void)h;(void)s;(void)n;return 0;}
HMODULE LoadLibrary(const char *s){(void)s;return 0;}
WORD FreeLibrary(HMODULE h){(void)h;return 0;}
FARPROC GetProcAddress(HMODULE h,LPSTR s){(void)h;(void)s;return 0;}
WORD GetWinFlags(void){return 0;}
int OpenSound(void){return 0;}
void CloseSound(void){}
void StopSound(void){}
void Yield(void){}
WORD CreateSystemTimer(WORD n,FARPROC f){(void)n;(void)f;return 0;}
void KillSystemTimer(WORD n){(void)n;}
void TimerEntry(void){}
void NullEntry(void){}
WORD HiInstall(WORD n){(void)n;return 0;}
WORD HiStop(void){return 0;}
DWORD HiRead(void){return 0;}
WORD HiStatus(void){return 0;}
WORD HiMetric(WORD n){(void)n;return 0;}
WORD HiRestart(void){return 0;}
WORD HiDetach(void){return 0;}
WORD HiPeriod(void){return 0;}
void HiPrepare(WORD n){(void)n;}
void HiProgram(WORD n){(void)n;}
void HiAudio(WORD n){(void)n;}
DWORD ReadStamp(void){return 0;}
static unsigned rd16(const unsigned char *p){return (unsigned)p[0]|((unsigned)p[1]<<8);}
static uint32_t rd32(const unsigned char *p){return (uint32_t)rd16(p)|((uint32_t)rd16(p+2)<<16);}
int main(int argc,char **argv){FILE *f;unsigned char h[32],r[18];uint32_t n,i;int pass;
    if(argc!=3)return 2;f=fopen(argv[1],"rb");if(!f)return 2;
    if(fread(h,1,32,f)!=32){fclose(f);return 2;}n=rd32(h+8);
    out=fopen(argv[2],"wb");if(!out){fclose(f);return 2;}
    for(pass=0;pass<3;pass++){
        if(pass){fprintf(out,"REPLAY\n");fseek(f,32,SEEK_SET);}
        frameNoiseValid=0;leaseToken=1;bassLease.token=1;bassLease.fast=LeaseFast;
        bassMode=2;bassEnabled=1;bassSuspended=0;leaseActive=leaseDivisor=0;
        port61=0;
        for(i=0;i<n;i++){
            TCFRAME state;
            if(fread(r,1,18,f)!=18){fclose(f);fclose(out);return 3;}
            memset(&state,0,sizeof(state));state.at=rd32(r)*256UL;
            state.p[0]=rd16(r+4);state.p[1]=rd16(r+6);state.p[2]=rd16(r+8);
            state.volume=rd16(r+10);state.noise=r[12];
            state.mask=15|TCN_STATE_BIT|(r[13]?TCN_RETRIGGER_BIT:0);
            fprintf(out,"%lu %lu ",(unsigned long)i,(unsigned long)rd32(r));
            frame(&state);bassOutput(rd16(r+14));fputc('\n',out);
        }
    }
    fclose(f);fclose(out);return 0;
}
