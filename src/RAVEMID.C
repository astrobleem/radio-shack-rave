/* Optional full-song SMF sidecar. The RBG remains the gameplay chart.
   Shared parser/synth objects are linked from LIBTANDY; no engine fork. */
#include <stdio.h>
#include <malloc.h>
#include <string.h>
#include "RAVEMID.H"
#include "SMF.H"
#include "MIDISYN.H"
#include "DOSSND.H"

static unsigned char far *midiFile;
static unsigned midiSize;
static int active, started, failed;
static unsigned delivered,errors,maxPollGap,maxLateness;
static unsigned openedEvents;
static unsigned long openedDuration;
static unsigned long previousPoll;
static int pollSeen,ended;
static MSYN synth;
static SMF_EVENT nextEvent;
static int haveEvent;
static unsigned oldPeriod[3],oldVolume[4],oldNoise;
static unsigned oldSpeaker,oldSpeakerAttacks;
static unsigned emittedPackedVolume=65535U;
static void midi_volume_emitted(unsigned channel,unsigned attenuation)
{
    unsigned shift=channel*4U;
    emittedPackedVolume=(emittedPackedVolume&~(15U<<shift))|((attenuation&15U)<<shift);
}
static unsigned char noiseAttack;
#include "RVSTREAM.H"

static int midi_load(const char *path)
{
    FILE *f;long size;static unsigned char bounce[512];unsigned n,offset=0;
    f=fopen(path,"rb");if(!f)return 0;
    if(fseek(f,0L,SEEK_END)){fclose(f);return 0;}
    size=ftell(f);
    if(size<=0 || size>SMF_MAX_FILE || fseek(f,0L,SEEK_SET)) {fclose(f);return 0;}
    midiSize=(unsigned)size;midiFile=(unsigned char far *)_fmalloc(midiSize);
    if(!midiFile){fclose(f);return 0;}
    while(offset<midiSize) {
        n=midiSize-offset;if(n>sizeof(bounce))n=sizeof(bounce);
        if(fread(bounce,1,n,f)!=n){fclose(f);_ffree(midiFile);midiFile=0;return 0;}
        _fmemcpy(midiFile+offset,bounce,n);offset+=n;
    }
    fclose(f);return 1;
}
static void midi_psg(void)
{
    unsigned i,p,v,noise;
    for(i=0;i<3;i++) {
        p=synth.note[i]?synth.p[i]:0;v=synth.volume[i];
        if(p!=oldPeriod[i]) {
            if(p) {
                if(DosSoundPsgByte(0x80+(i<<5)+(p&15)) ||
                   DosSoundPsgByte(p>>4)) errors++;
                else oldPeriod[i]=p;
            } else oldPeriod[i]=0;
        }
        if(v!=oldVolume[i]) {
            if(DosSoundPsgByte(0x90+(i<<5)+v)) errors++;
            else {oldVolume[i]=v;midi_volume_emitted(i,v);}
        }
    }
    noise=synth.noiseNote?synth.noise:0;
    if(noise!=oldNoise || noiseAttack) {
        if(DosSoundPsgByte(0xe0|noise)) errors++;
        else {oldNoise=noise;noiseAttack=0;}
    }
    if(synth.volume[3]!=oldVolume[3]) {
        if(DosSoundPsgByte(0xf0+synth.volume[3])) errors++;
        else {oldVolume[3]=synth.volume[3];midi_volume_emitted(3,synth.volume[3]);}
    }
    if(synth.speakerDivisor!=oldSpeaker || synth.speakerAttacks!=oldSpeakerAttacks) {
        if(DosSoundPitDivisor(synth.speakerDivisor,
            (unsigned)(synth.speakerAttacks!=oldSpeakerAttacks))) errors++;
        else {oldSpeaker=synth.speakerDivisor;oldSpeakerAttacks=synth.speakerAttacks;}
    }
}
int _cdecl RaveMidiOpen(const char *path)
{
    unsigned i;int rc;FILE *probe;char magic[4];
    RaveMidiClose();
    openedEvents=0;openedDuration=0;
    probe=fopen(path,"rb");if(!probe)return 0;
    rc=fread(magic,1,4,probe)==4 && !memcmp(magic,"RWS1",4);
    fclose(probe);
    if(rc) {
        if(!rv_load(path))return 0;
        active=started=1;failed=0;
        delivered=errors=maxPollGap=maxLateness=0;ended=0;
        return 1;
    }
    if(!midi_load(path))return 0;
    if(!smf_open(midiFile,midiSize)){smf_close();_ffree(midiFile);midiFile=0;return 0;}
    openedEvents=smf_event_count();openedDuration=smf_duration_ms();
    MSReset(&synth);MSSpeakerMode(&synth,1);
    for(i=0;i<3;i++)oldPeriod[i]=65535U;
    for(i=0;i<4;i++)oldVolume[i]=65535U;
    oldNoise=oldSpeaker=oldSpeakerAttacks=65535U;noiseAttack=0;
    rc=smf_next(&nextEvent);
    if(rc<0){smf_close();_ffree(midiFile);midiFile=0;return 0;}
    haveEvent=rc>0;started=1;active=1;failed=0;
    delivered=errors=maxPollGap=maxLateness=0;previousPoll=0;pollSeen=ended=0;
    return 1;
}
void _cdecl RaveMidiRewind(void)
{
    unsigned status,ch;int rc,messageResult;
    if(!active)return;
    delivered=errors=maxPollGap=maxLateness=0;previousPoll=0;pollSeen=ended=0;
    /* Stop latched output before clearing the timeline. This is also required
       on restart, where legacy sfx_stop is intentionally muted. */
    RaveMidiSilence();
    if(rvPrepared){rv_rewind();return;}
    smf_rewind();MSReset(&synth);MSSpeakerMode(&synth,1);
    oldSpeaker=oldSpeakerAttacks=65535U;oldNoise=65535U;noiseAttack=0;
    oldPeriod[0]=oldPeriod[1]=oldPeriod[2]=65535U;
    oldVolume[0]=oldVolume[1]=oldVolume[2]=oldVolume[3]=65535U;
    rc=smf_next(&nextEvent);haveEvent=rc>0;failed=rc<0;
    if(failed)errors++;
    /* The often-large t=0 setup group is state preparation, not playback.
       Apply it before the game starts its clock; the first poll emits it. */
    while(haveEvent && !failed && nextEvent.ms==0) {
        MSRender(&synth,0);
        do {
            status=(unsigned)nextEvent.status&240U;
            ch=(unsigned)nextEvent.status&15U;
            messageResult=MSMessageDeferred(&synth,0,
                (unsigned long)nextEvent.status|
                ((unsigned long)nextEvent.data1<<8)|
                ((unsigned long)nextEvent.data2<<16));
            delivered++;if(messageResult)errors++;
            if(!messageResult && status==0x90 && ch==9 && nextEvent.data2)
                noiseAttack=1;
            rc=smf_next(&nextEvent);haveEvent=rc>0;
            if(rc<0){haveEvent=0;failed=1;errors++;}
        } while(haveEvent && nextEvent.ms==0);
        MSRender(&synth,0);
    }
    started=1;
}
void _cdecl RaveMidiSilence(void)
{
    unsigned i;
    if(!active)return;
    for(i=0;i<4;i++) {
        if(DosSoundPsgByte(0x9f+(i<<5)))errors++;
        else midi_volume_emitted(i,15);
    }
    if(DosSoundPitDivisor(0,0))errors++;
    /* Invalidate every output cache so the next poll cannot mistake a prior
       sounding value for the now-silent hardware state. Preserve counters. */
    oldPeriod[0]=oldPeriod[1]=oldPeriod[2]=65535U;
    oldVolume[0]=oldVolume[1]=oldVolume[2]=oldVolume[3]=65535U;
    oldNoise=oldSpeaker=oldSpeakerAttacks=65535U;noiseAttack=0;
    rvNoiseValid=0;
}
void _cdecl RaveMidiPoll(unsigned long elapsedMs)
{
    unsigned long eventMs=0,gap;int rc,messageResult;
    if(!active)return;
    if(pollSeen && elapsedMs>=previousPoll) {
        gap=elapsedMs-previousPoll;if(gap>maxPollGap)maxPollGap=(unsigned)gap;
    }
    previousPoll=elapsedMs;pollSeen=1;
    if(!started)started=1;
    while(haveEvent && !failed && nextEvent.ms<=elapsedMs) {
        eventMs=nextEvent.ms;
        MSRender(&synth,eventMs);
        do {
            unsigned status=(unsigned)nextEvent.status&240U;
            unsigned ch=(unsigned)nextEvent.status&15U;
            messageResult=MSMessageDeferred(&synth,eventMs,
                (unsigned long)nextEvent.status|
                ((unsigned long)nextEvent.data1<<8)|
                ((unsigned long)nextEvent.data2<<16));
            delivered++;if(messageResult)errors++;
            if(!messageResult && status==0x90 && ch==9 && nextEvent.data2)
                noiseAttack=1;
            rc=smf_next(&nextEvent);haveEvent=rc>0;
            if(rc<0){haveEvent=0;failed=1;errors++;}
        } while(haveEvent && nextEvent.ms==eventMs);
        MSRender(&synth,eventMs);
        gap=elapsedMs-eventMs;if(gap>maxLateness)maxLateness=(unsigned)gap;
        midi_psg();
    }
    MSRender(&synth,elapsedMs);midi_psg();
    if(!haveEvent && !failed && elapsedMs>=smf_duration_ms())ended=1;
}
void _cdecl RaveMidiClose(void)
{
    if(active) {
        if(emittedPackedVolume!=65535U)RaveMidiSilence();
        else if(DosSoundPitDivisor(0,0))errors++;
    }
    active=started=haveEvent=failed=0;oldSpeaker=0;
    if(midiFile){smf_close();_ffree(midiFile);midiFile=0;}
    rv_free();
}
int _cdecl RaveMidiPrepared(void){return rvPrepared;}
unsigned _cdecl RaveMidiPackedVolume(void){return active?emittedPackedVolume:65535U;}
void _cdecl RaveMidiPollFine(unsigned long fine){if(active && rvPrepared)rv_poll(fine);}
int _cdecl RaveMidiActive(void){return active;}
unsigned _cdecl RaveMidiEvents(void){return openedEvents;}
unsigned _cdecl RaveMidiDelivered(void){return delivered;}
unsigned _cdecl RaveMidiErrors(void){return errors;}
unsigned _cdecl RaveMidiMaxPollGap(void){return maxPollGap;}
unsigned _cdecl RaveMidiMaxLateness(void){return maxLateness;}
int _cdecl RaveMidiEnded(void){return ended;}
unsigned long _cdecl RaveMidiDuration(void){return openedDuration;}
