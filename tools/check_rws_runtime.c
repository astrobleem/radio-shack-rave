/* Host probe of the production RWS1 loader and DOS PSG/PIT owner. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#define _cdecl
#include "RAVEMID.H"
#include "DOSSND.H"

static FILE *out;
static unsigned port61, half, low;
static unsigned long writes;
static unsigned char psgLog[512];
static unsigned psgCount,irqSaves,irqRestores,irqEnabled=1;
int SessionPermit(void){return 1;}
unsigned ReadPort(unsigned port){return port==0x61?port61:0;}
void WritePort(unsigned port,unsigned value){
    if(port==0x61){port61=value;if(out)fprintf(out,"G%02X ",value&255);}
    else if(port==0xc0){if(out)fprintf(out,"P%02X ",value&255);
        if(psgCount<sizeof(psgLog))psgLog[psgCount++]=(unsigned char)value;}
    else if(port==0x43){half=0;if(out)fprintf(out,"C%02X ",value&255);}
    else if(port==0x42){if(!half){low=value;half=1;if(out)fprintf(out,"L%02X ",value&255);}
        else {half=0;if(out)fprintf(out,"H%02X ",value&255);}}
    writes++;
}
unsigned SaveIRQ(void){unsigned old=irqEnabled;irqSaves++;irqEnabled=0;return old;}
void RestoreIRQ(unsigned flags){irqRestores++;irqEnabled=flags;}

static int no_output(unsigned expected,unsigned beforeWrites,unsigned beforeSaves,
                     unsigned beforeRestores,unsigned ifBefore){
    return expected==psgCount && beforeWrites==writes && beforeSaves==irqSaves &&
           beforeRestores==irqRestores && ifBefore==irqEnabled;
}
static int batch_contract(void){
    unsigned char bytes[12];unsigned i,n,beforeS,beforeR,ifBefore;
    unsigned long beforeW;
    for(i=0;i<12;i++)bytes[i]=(unsigned char)(0x80+i);
    psgCount=0;beforeW=writes;beforeS=irqSaves;beforeR=irqRestores;ifBefore=irqEnabled;
    if(DosSoundPsgBytes(bytes,1)!=DOS_SOUND_OWNER ||
       !no_output(0,beforeW,beforeS,beforeR,ifBefore))return 20;
    if(DosSoundAcquire(DS_PIT))return 21;
    beforeW=writes;beforeS=irqSaves;beforeR=irqRestores;ifBefore=irqEnabled;
    if(DosSoundPsgBytes(bytes,1)!=DOS_SOUND_CAPABILITY ||
       !no_output(0,beforeW,beforeS,beforeR,ifBefore))return 22;
    DosSoundRelease();
    if(DosSoundAcquire(DS_PSG|DS_PWM))return 23;
    for(n=0;n<=12;n+=12){
        beforeW=writes;beforeS=irqSaves;beforeR=irqRestores;ifBefore=irqEnabled;
        if(DosSoundPsgBytes(bytes,n)!=DOS_SOUND_CAPABILITY ||
           !no_output(0,beforeW,beforeS,beforeR,ifBefore))return 24;
    }
    beforeW=writes;beforeS=irqSaves;beforeR=irqRestores;ifBefore=irqEnabled;
    if(DosSoundPsgBytes(0,1)!=DOS_SOUND_CAPABILITY ||
       !no_output(0,beforeW,beforeS,beforeR,ifBefore))return 25;
    for(n=1;n<=11;n++){
        psgCount=0;beforeW=writes;beforeS=irqSaves;beforeR=irqRestores;
        irqEnabled=n&1; ifBefore=irqEnabled;
        if(DosSoundPsgBytes(bytes,n) || psgCount!=n || writes-beforeW!=n ||
           irqSaves!=beforeS || irqRestores!=beforeR || irqEnabled!=ifBefore ||
           memcmp(psgLog,bytes,n))return 26;
    }
    /* Existing byte path must still preserve incoming IF via its own hooks. */
    beforeS=irqSaves;beforeR=irqRestores;irqEnabled=1;
    if(DosSoundPsgByte(0xfe) || irqSaves!=beforeS+1 ||
       irqRestores!=beforeR+1 || irqEnabled!=1)return 27;
    DosSoundPwmBegin();
    psgCount=0;beforeW=writes;beforeS=irqSaves;beforeR=irqRestores;ifBefore=irqEnabled;
    if(DosSoundPsgBytes(bytes,1)!=DOS_SOUND_SPEECH ||
       !no_output(0,beforeW,beforeS,beforeR,ifBefore))return 28;
    DosSoundPwmEnd();
    psgCount=0;beforeW=writes;beforeS=irqSaves;beforeR=irqRestores;ifBefore=irqEnabled;
    if(DosSoundPsgBytes(bytes,11) || psgCount!=11 || writes-beforeW!=11 ||
       memcmp(psgLog,bytes,11) || irqSaves!=beforeS ||
       irqRestores!=beforeR || irqEnabled!=ifBefore)return 29;
    DosSoundRelease();return 0;
}

static unsigned rd16(const unsigned char *p){return (unsigned)p[0]|((unsigned)p[1]<<8);}
static uint32_t rd32(const unsigned char *p){return (uint32_t)rd16(p)|((uint32_t)rd16(p+2)<<16);}
static int replay(const char *path,const char *trace,int pass){
    FILE *f;unsigned char head[32],r[18];uint32_t n,i;int okay=1;
    f=fopen(path,"rb");if(!f)return 2;
    if(fread(head,1,32,f)!=32){fclose(f);return 2;}
    n=rd32(head+8);out=fopen(trace,pass?"wb":"ab");if(!out){fclose(f);return 2;}
    if(!pass)fprintf(out,"REPLAY\n");
    for(i=0;i<n;i++){
        if(fread(r,1,18,f)!=18){okay=0;break;}
        fprintf(out,"%lu %lu ",(unsigned long)i,(unsigned long)rd32(r));
        RaveMidiPollFine(rd32(r));fputc('\n',out);
    }
    fclose(f);fclose(out);out=0;
    if(!RaveMidiEnded() || RaveMidiDelivered()!=RaveMidiEvents() ||
       RaveMidiErrors()!=0 || RaveMidiEvents()!=rd16(head+16))okay=0;
    return okay?0:3;
}
int main(int argc,char **argv){int rc;
    if(argc>=2 && !strcmp(argv[1],"batch"))return batch_contract();
    if(argc<3)return 2;
    /* A failed load must leave the owner available for another attempt. */
    if(DosSoundAcquire(DS_PSG|DS_PIT))return 3;
    rc=RaveMidiOpen(argv[2]);
    if(!strcmp(argv[1],"reject")){
        if(rc){RaveMidiClose();DosSoundRelease();return 4;}
        DosSoundRelease();return 0;
    }
    if(!rc || !RaveMidiPrepared() || RaveMidiEvents()!=17578U ||
       RaveMidiDuration()!=200083UL){DosSoundRelease();return 5;}
    if(!strcmp(argv[1],"accept")){RaveMidiClose();DosSoundRelease();return 0;}
    if(argc!=4 || strcmp(argv[1],"trace")){RaveMidiClose();DosSoundRelease();return 2;}
    RaveMidiRewind();rc=replay(argv[2],argv[3],1);
    if(!rc){RaveMidiRewind();rc=replay(argv[2],argv[3],0);}
    if(!rc){
        FILE *fixture=fopen(argv[2],"rb");unsigned char sample[4];
        if(!fixture || fseek(fixture,32L+500L*18L,SEEK_SET) ||
           fread(sample,1,4,fixture)!=4)rc=7;
        if(fixture)fclose(fixture);
        if(!rc){
            RaveMidiRewind();RaveMidiPollFine(rd32(sample));
            RaveMidiSilence();RaveMidiSilence();
            if((port61&3)!=0 || RaveMidiErrors()!=0)rc=8;
        }
    }
    if(!rc){RaveMidiRewind();rc=replay(argv[2],argv[3],0);}
    /* Silence after replay must mute all PSG channels and gate PIT2. */
    if(!rc){RaveMidiSilence();if((port61&3)!=0){
        fprintf(stderr,"silence retained PIT gate=%u delivered=%u errors=%u\n",
                port61,RaveMidiDelivered(),RaveMidiErrors());rc=6;}}
    RaveMidiClose();DosSoundRelease();return rc;
}
