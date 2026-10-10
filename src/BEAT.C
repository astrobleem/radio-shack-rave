/* Radio Shack Rave v6: small-model C89 for MSC6 /G0 /AS, real-mode 8088 DOS.
 * One translation unit; the headers below hold static code in layers:
 * FX/CORE (judgment, host tested), SPLASH (bitmap format), GFX (drawing),
 * CLOCK (fine time), SFX (PSG), PLAY (playfield), SHOW (splash/title).
 */
#include <dos.h>
#include <conio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <malloc.h>
#include "DOSSND.H"
static void lead_output(int now,unsigned divisor,unsigned attenuation);
#define RAVE_FAR_TABLES
#include "FX.H"
#include "CORE.H"
#include "SPLASH.H"
#include "GFX.H"
#include "CLOCK.H"
#include "SFX.H"
#include "SONGS.H"

#define MAX_STATES 4096
#define MAX_SEGS 64
#define MAX_DRUMS 4096
#define BACK_MAX 1024
typedef struct {
    unsigned tick, divisor[3];
    unsigned char attenuation[3], reserved;
} State;
typedef struct { unsigned long start,period;unsigned first,count; } Seg;
typedef struct { unsigned tick;unsigned char kind,level; } Drum;
/* Song tables live in far memory, grown to the largest song loaded so far:
   a long song costs memory only once one is played. */
static State far *music;
static Drum far *drums;
static unsigned cap_states,cap_taps,cap_drums,ndrums,load_nomem;
static Seg segs[MAX_SEGS];
static unsigned states, duration, next_state, prev_div[3], prev_att[3], nsegs;
static unsigned difficulty=255;
static char song_title[26];
static unsigned old_mode, frames, late_frames, worst_ticks;
static unsigned worst_fine, music_updates, restart_count, last_music_tick;
static unsigned max_input_wait;
static unsigned long fine_sum;
static volatile unsigned irq_count,key_makes,key_breaks,key_repeats;
static int reduced, owned, keyboard_owned, video_owned, no_fx, no_logo;
static int demo_mode, tour_mode;
static int songs_mode, song_ready, exit_reason;
static unsigned demo_runs, splash_runs;
static unsigned long idle_since;
static volatile unsigned char down[128], queue[32];
static volatile unsigned queue_tick[32];
static volatile unsigned qread, qwrite, overflow;
static void (interrupt far *old_keyboard)(void);
static int auto_mode, test_mode, dump_done, shot_mode;
static unsigned long origin;
#define MAX_AUDIO 1100
typedef struct { int tick;unsigned divisor,attenuation; } AudioEvent;
typedef struct { unsigned tick,d1,d2;unsigned char a1,a2; } BackEvent;
static AudioEvent audio_trace[MAX_AUDIO];
static BackEvent back_trace[BACK_MAX];
static unsigned audio_count,back_count,audio_overflow;
static unsigned long backing_checksum;
static void lead_output(int now,unsigned divisor,unsigned attenuation)
{
    if(audio_count<MAX_AUDIO) {
        audio_trace[audio_count].tick=now;
        audio_trace[audio_count].divisor=divisor;
        audio_trace[audio_count++].attenuation=attenuation;
    } else audio_overflow++;
    if(!owned)return;
    /* Genuine channel-A gate/period writes: no automatic lead is mixed in. */
    psg(0x9f);
    if(divisor) {
        psg(0x80+(divisor&15));
        psg(divisor>>4);
        psg(0x90+attenuation);
    }
}
#define DRUM_TRACE 512
typedef struct { unsigned tick;unsigned char kind,level; } DrumEvent;
static DrumEvent drum_trace[DRUM_TRACE];
static unsigned drum_count,drum_hits;
static unsigned long drum_checksum;
static void trace_save(const char *name)
{
    FILE *f;unsigned i;
    f=fopen(name,"w");if(!f)return;
    /* Drum lines exist only for songs with a drum table, so traces of
       drumless songs are unchanged. */
    for(i=0;i<audio_count;i++)fprintf(f,"L %d %u %u\n",
        audio_trace[i].tick,audio_trace[i].divisor,audio_trace[i].attenuation);
    for(i=0;i<back_count;i++)fprintf(f,"B %u %u %u %u %u\n",
        back_trace[i].tick,back_trace[i].d1,back_trace[i].a1,
        back_trace[i].d2,back_trace[i].a2);
    for(i=0;i<drum_count;i++)fprintf(f,"D %u %u %u\n",
        drum_trace[i].tick,drum_trace[i].kind,drum_trace[i].level);
    fclose(f);
}
/* Song time in 1/256 ticks; whole ticks are its floor. The ready period is
   36 ticks before zero. */
static long song_fine(void)
{
    unsigned long age=clk_fine()-origin;
    if(age>30000UL*256)age=30000UL*256;
    return (long)age-36L*256;
}
static int fine_tick(long f)
{
    return f>=0?(int)(f>>8):-(int)((255-f)>>8);
}
static int song_time(void)
{
    return fine_tick(song_fine());
}
static void key_event(unsigned scan)
{
    unsigned code,next;
    code=scan&127;
    if(scan!=0xe0 && scan!=0xe1) {
        if(scan&128){down[code]=0;key_breaks++;}
        else if(!down[code]) {
            down[code]=1;key_makes++;next=(qwrite+1)&31;
            if(next!=qread){
                queue[qwrite]=(unsigned char)code;
                queue_tick[qwrite]=*(unsigned far *)0x0040006cUL;
                qwrite=next;
            }
            else overflow++;
        } else key_repeats++;
    }
}
static void interrupt far keyboard(void)
{
    unsigned ack;
    irq_count++;key_event(inp(0x60));
    ack=inp(0x61);outp(0x61,ack|0x80);outp(0x61,ack);
    outp(0x20,0x20);
}
static void key_install(void)
{
    memset((void *)down,0,sizeof(down));qread=qwrite=overflow=0;
    old_keyboard=_dos_getvect(9);_dos_setvect(9,keyboard);
    keyboard_owned=1;
}
/* Next queued key press, with how many ticks ago it was pressed. */
static unsigned key_take(unsigned *ago)
{
    unsigned key,wait;
    if(qread==qwrite)return 0;
    key=queue[qread];
    wait=*(unsigned far *)0x0040006cUL-queue_tick[qread];
    if(wait>36)wait=0;
    if(wait>max_input_wait)max_input_wait=wait;
    if(ago)*ago=clk_virtual?0:wait;
    qread=(qread+1)&31;return key;
}
static void mode(unsigned m)
{
    union REGS r;r.x.ax=m;int86(0x10,&r,&r);
    pal_identity();
}
static void cleanup(void)
{
    if(owned)lead_cancel(song_time());
    if(keyboard_owned){_dos_setvect(9,old_keyboard);keyboard_owned=0;}
    if(owned){DosSoundRelease();owned=0;}
    if(video_owned){mode(old_mode);video_owned=0;}
    if(psg_log){fclose(psg_log);psg_log=0;}
    if(pal_log){fclose(pal_log);pal_log=0;}
}
static int title_char(int c)
{
    return (c>='A' && c<='Z') || (c>='0' && c<='9') || (c && strchr(" !?'.,-:&/+",c)!=0);
}
static void title_from_name(const char *name)
{
    const char *p=name,*q;unsigned n=0;
    for(q=name;*q;q++)if(*q=='\\' || *q=='/' || *q==':')p=q+1;
    for(;*p && *p!='.' && n<24;p++) {
        song_title[n]=(char)((*p>='a' && *p<='z')?*p-32:*p);
        if(!title_char(song_title[n]))song_title[n]=' ';
        n++;
    }
    song_title[n]=0;
}
static int tables_fit(unsigned ns,unsigned nt,unsigned nd)
{
    if(ns<2)ns=2;
    if(nt<8)nt=8;
    if(nd<1)nd=1;
    load_nomem=1;
    if(ns>cap_states) {
        if(music)_ffree(music);
        cap_states=0;music=(State far *)_fmalloc(ns*sizeof(State));
        if(!music)return 0;
        cap_states=ns;
    }
    if(nt>cap_taps) {
        if(chart)_ffree(chart);
        if(judged)_ffree(judged);
        cap_taps=0;chart=(Tap far *)_fmalloc(nt*sizeof(Tap));
        judged=(unsigned char far *)_fmalloc(nt);
        if(!chart || !judged)return 0;
        cap_taps=nt;
    }
    if(nd>cap_drums) {
        if(drums)_ffree(drums);
        cap_drums=0;drums=(Drum far *)_fmalloc(nd*sizeof(Drum));
        if(!drums)return 0;
        cap_drums=nd;
    }
    load_nomem=0;
    return 1;
}
/* Small model: stdio reads near buffers only, so far tables are filled
   through a bounce buffer. */
static int fread_far(void far *dst,unsigned size,unsigned count,FILE *f)
{
    static unsigned char bounce[512];
    unsigned long left=(unsigned long)size*count;unsigned n;
    unsigned char far *p=(unsigned char far *)dst;
    while(left) {
        n=left>512UL?512:(unsigned)left;
        if(fread(bounce,1,n,f)!=n)return 0;
        _fmemcpy(p,(void far *)bounce,n);p+=n;left-=n;
    }
    return 1;
}
static int load_score(const char *name)
{
    FILE *f;char magic[4]={0,0,0,0};unsigned version=0,i,k;int ok=1;
    unsigned char extra[28]={0},ext5[4]={0,0,0,0};
    f=fopen(name,"rb");if(!f)return 0;
    duration=states=taps=0;ndrums=0;load_nomem=0;
    if(fread(magic,1,4,f)!=4)ok=0;
    if(fread(&version,2,1,f)!=1 ||
        !((version==5 && !memcmp(magic,"RBG5",4)) ||
          (version==4 && !memcmp(magic,"RBG4",4)) ||
          (version==3 && !memcmp(magic,"RBG3",4)) ||
          (version==2 && !memcmp(magic,"RBG2",4))))ok=0;
    if(fread(&duration,2,1,f)!=1 || !duration || duration>10924)ok=0;
    if(fread(&states,2,1,f)!=1 || states<2 || states>MAX_STATES)ok=0;
    if(fread(&taps,2,1,f)!=1 || !taps || taps>MAX_NOTES)ok=0;
    nsegs=0;difficulty=255;title_from_name(name);
    if(ok && version>=4) {
        if(fread(extra,1,28,f)!=28)ok=0;
        nsegs=extra[0]|(extra[1]<<8);difficulty=extra[2];
        if(nsegs>MAX_SEGS || (difficulty>3 && difficulty!=255) || extra[3])ok=0;
        for(i=0;i<24 && extra[4+i];i++)if(!title_char(extra[4+i]))ok=0;
        for(k=i;k<24;k++)if(extra[4+k])ok=0;
        if(ok){memcpy(song_title,extra+4,i);song_title[i]=0;}
    }
    /* RBG5 adds a drum table: u16 count, u16 zero. */
    if(ok && version==5) {
        if(fread(ext5,1,4,f)!=4)ok=0;
        ndrums=ext5[0]|(ext5[1]<<8);
        if(!ndrums || ndrums>MAX_DRUMS || ext5[2] || ext5[3])ok=0;
    }
    if(ok && !tables_fit(states,taps,ndrums))ok=0;
    if(!ok){fclose(f);return 0;}
    if(!fread_far(music,sizeof(State),states,f))ok=0;
    if(ok && !fread_far(chart,sizeof(Tap),taps,f))ok=0;
    if(ok && nsegs && fread(segs,sizeof(Seg),nsegs,f)!=nsegs)ok=0;
    if(ok && ndrums && !fread_far(drums,sizeof(Drum),ndrums,f))ok=0;
    if(fgetc(f)!=EOF)ok=0;
    fclose(f);
    if(!ok)return 0;
    for(i=0;i<states;i++) {
        if(music[i].divisor[0] || music[i].attenuation[0]!=15)ok=0;
        if(music[i].tick>duration || music[i].reserved)ok=0;
        if(i && music[i].tick<=music[i-1].tick)ok=0;
        for(k=0;k<3;k++) {
            if(music[i].divisor[k]>1023 ||
               music[i].attenuation[k]>15 ||
               (!music[i].divisor[k] && music[i].attenuation[k]!=15))ok=0;
        }
    }
    if(music[0].tick || music[states-1].tick!=duration)ok=0;
    for(k=0;k<3;k++)if(music[states-1].divisor[k] ||
        music[states-1].attenuation[k]!=15)ok=0;
    required_taps=0;
    for(i=0;i<taps;i++) {
        if(chart[i].tick>=duration || chart[i].lane>2 ||
           chart[i].reserved>(unsigned char)(version>=3?1:0))ok=0;
        if(!chart[i].reserved)required_taps++;
        if(chart[i].end_tick<=chart[i].tick || chart[i].end_tick>duration ||
           !chart[i].divisor || chart[i].divisor>1023 ||
           chart[i].attenuation>14 || chart[i].note<45 || chart[i].note>96)ok=0;
        if(i && chart[i].tick<=chart[i-1].tick)ok=0;
        if(i && chart[i].tick<chart[i-1].end_tick)ok=0;
    }
    for(i=0;i<nsegs;i++) {
        if(!segs[i].count || (segs[i].count>1 && !segs[i].period) ||
           (segs[i].start>>16)>=duration)ok=0;
        if(i && (segs[i].start<=segs[i-1].start ||
           segs[i].first!=segs[i-1].first+segs[i-1].count))ok=0;
    }
    if(nsegs && segs[0].first)ok=0;
    for(i=0;i<ndrums;i++) {
        if(drums[i].tick>=duration || drums[i].kind>6 || drums[i].level>15)ok=0;
        if(i && drums[i].tick<=drums[i-1].tick)ok=0;
    }
    if(!required_taps)ok=0;
    return ok;
}
static void music_step(int now)
{
    unsigned chosen,k,d,a;
    if(now<0 || next_state>=states)return;
    chosen=next_state;
    if(music[chosen].tick>(unsigned)now)return;
    /* Consume due states, apply only present state; no expired attack burst. */
    while(chosen+1<states && music[chosen+1].tick<=(unsigned)now)chosen++;
    for(k=1;k<3;k++) {
        d=music[chosen].divisor[k];a=music[chosen].attenuation[k];
        if(d!=prev_div[k] && d) {
            psg(0x80+(k<<5)+(d&15));
            psg(d>>4);
        }
        if(a!=prev_att[k])psg(0x90+(k<<5)+a);
        prev_div[k]=d;prev_att[k]=a;
    }
    last_music_tick=music[chosen].tick;
    if(back_count<BACK_MAX) {
        back_trace[back_count].tick=music[chosen].tick;
        back_trace[back_count].d1=music[chosen].divisor[1];
        back_trace[back_count].d2=music[chosen].divisor[2];
        back_trace[back_count].a1=music[chosen].attenuation[1];
        back_trace[back_count++].a2=music[chosen].attenuation[2];
    }
    backing_checksum=backing_checksum*33UL+music[chosen].tick;
    for(k=1;k<3;k++)backing_checksum=backing_checksum*33UL+
        music[chosen].divisor[k]*16UL+music[chosen].attenuation[k];
    next_state=chosen+1;music_updates++;
}
/* Drum channel: the SN76496 noise generator. A hit writes the noise
   control (periodic or white, shift rate), which also restarts the shift
   register for a clean attack, then decays linearly to silence in fine
   time, finer than the 55 ms tick. Several hits due at once (a slow frame)
   play only the latest, and a hit already past its length is skipped,
   like music_step. Kinds: kick, snare, closed hat, open hat, crash,
   low tom, high tom. */
#define DRUM_KINDS 7
static const unsigned char drum_ctl[DRUM_KINDS]={2,5,4,4,4,1,0};
static const unsigned char drum_att0[DRUM_KINDS]={0,1,5,4,2,1,1};
static const unsigned drum_len[DRUM_KINDS]={560,840,230,1400,4200,1160,930};
static unsigned next_drum,drum_kind=255,drum_lvl,drum_att=15,drum_shown=15;
static long drum_t0;
static void drums_reset(void)
{
    next_drum=0;drum_kind=255;drum_att=15;drum_shown=15;
}
static void drums_step(long nowf)
{
    unsigned i,k,att;long at,age;
    if(nowf<0 || !drums)return;
    i=next_drum;
    if(i<ndrums && (long)drums[i].tick*256L<=nowf) {
        while(i+1<ndrums && (long)drums[i+1].tick*256L<=nowf)i++;
        next_drum=i+1;k=drums[i].kind;at=(long)drums[i].tick*256L;
        /* A hit noticed late (a slow frame) still plays in full from now,
           up to one tick late; older than that it is skipped. */
        if(nowf-at<256L) {
            drum_kind=k;drum_t0=nowf-at<(long)drum_len[k]?at:nowf;
            drum_lvl=drums[i].level;drum_shown=255;
            psg(0xe0|drum_ctl[k]);drum_hits++;
            if(drum_count<DRUM_TRACE) {
                drum_trace[drum_count].tick=drums[i].tick;
                drum_trace[drum_count].kind=(unsigned char)k;
                drum_trace[drum_count++].level=(unsigned char)drum_lvl;
            }
            drum_checksum=drum_checksum*33UL+drums[i].tick*8UL+k;
        }
    }
    if(drum_kind==255)return;
    age=nowf-drum_t0;k=drum_kind;
    if(age>=(long)drum_len[k]){att=15;drum_kind=255;}
    else {
        att=drum_att0[k]+drum_lvl+(unsigned)((long)(15-drum_att0[k])*age/(long)drum_len[k]);
        if(att>15)att=15;
    }
    drum_att=att;
    if(att!=drum_shown){psg(0xf0|att);drum_shown=att;}
}
/* User-supplied full-screen art (RSPL), shown before the splash if present.
   Status: -2 bad/missing bitmap, -1 Escape, 0 continue, 1 Space. */
static int splash_input(void)
{
    unsigned k;
    while((k=key_take(0))!=0) {
        if(k==1)return -1;
        if(k==57)return 1;
        if(k==50)reduced=!reduced;
    }
    return 0;
}
static int splash_bitmap(const char *name)
{
    FILE *f;unsigned w,h,x,y,row,pos,i;int action,ok=1;
    unsigned char header[12];static unsigned char buffer[SPLASH_ROW];
    action=splash_input();if(action)return action;
    f=fopen(name,"rb");if(!f)return -2;
    if(fread(header,1,12,f)!=12 || !splash_header(header)) {
        fclose(f);return -2;
    }
    w=splash_u16(header+4);h=splash_u16(header+6);
    x=splash_u16(header+8);y=splash_u16(header+10);
    for(row=0;row<h;row++) {
        action=splash_input();if(action){fclose(f);return action;}
        if(fread(buffer,1,w/2,f)!=w/2){ok=0;break;}
        pos=row_ofs[y+row]+x/2;
        for(i=0;i<w/2;i++)video[pos+i]=buffer[i];
    }
    if(ok && fgetc(f)!=EOF)ok=0;
    fclose(f);return ok?0:-2;
}
/* Audio stepping, also called between the playfield's drawing stages so a
   slow frame does not hold back lead, backing or drums for its whole
   length. Judgment is unaffected: it uses key timestamps. */
static void audio_poll(void)
{
    long f=song_fine();int n=fine_tick(f);
    lead_step(n);automatic_step(n);music_step(n);drums_step(f);
}
#include "PLAY.H"
#include "HISCORE.H"
#include "SHOW.H"

static void restart(void)
{
    unsigned k;
    sfx_stop();
    for(k=0;k<3;k++){prev_div[k]=65535;prev_att[k]=65535;}
    next_state=0;last_music_tick=0;reset_game();
    vis_from=0;beat_reset(&grid_cur);beat_reset(&pulse_cur);
    scene_draw();
    audio_count=back_count=audio_overflow=0;backing_checksum=0;
    drums_reset();drum_count=drum_hits=0;drum_checksum=0;
    origin=clk_fine();
    fx_reset(song_fine());
    for(k=0;k<3;k++)key_lit[k]=0;
}
static int selftest(void)
{
    FILE *f;int bad=0;unsigned save=taps,i;
    taps=3;chart[0].tick=10;chart[0].lane=0;
    chart[1].tick=16;chart[1].lane=1;chart[2].tick=22;chart[2].lane=2;
    reference_mode=0;
    for(i=0;i<3;i++){chart[i].end_tick=chart[i].tick+4;chart[i].reserved=0;
        chart[i].divisor=400+i*20;chart[i].attenuation=3;}
    reset_game();audio_count=0;
    if(!hit(0,7) || lead_until!=11 || audio_count!=1)bad++;
    lead_step(10);if(!lead_div)bad++;
    lead_step(11);if(lead_div || audio_count!=2)bad++;
    if(hit(0,10))bad++;
    reset_game();audio_count=0;
    if(!hit(1,19) || lead_until!=20)bad++;
    lead_step(20);if(lead_div)bad++;
    /* A late hit after the tone's authored end still scores, silently. */
    reset_game();audio_count=0;
    chart[0].end_tick=12;if(!hit(0,13) || audio_count || silent_hits!=1)bad++;
    chart[0].end_tick=14;
    reset_game();audio_count=0;
    for(i=0;i<30;i++)expire(i);
    if(audio_count || misses!=3)bad++;
    reset_game();audio_count=0;
    hit(0,10);reset_game();if(lead_div || audio_count!=2)bad++;
    reset_game();if(!hit(0,7)||hit(0,10)||!hit(1,19))bad++;
    expire(25);if(misses)bad++;
    expire(26);if(misses!=1 || combo || hits!=2 || best!=2)bad++;
    reset_game();if(hits || misses || score || judged[2])bad++;
    if(hit(2,100)||ghosts!=1)bad++;
    chart[1].tick=14;chart[1].lane=0;reset_game();
    if(!hit(0,13) || judged[0] || judged[1]!=1)bad++;
    /* A late press after a newer automatic note took the lead. */
    chart[1].tick=12;chart[1].lane=1;chart[1].reserved=1;chart[1].end_tick=14;
    chart[0].end_tick=12;reset_game();audio_count=0;
    automatic_step(12);
    if(!hit(0,13) || judged[0]!=1 || misses || lead_owner!=1)bad++;
    chart[0].end_tick=14;chart[1].reserved=0;
    chart[1].tick=16;chart[1].lane=1;chart[1].end_tick=20;reset_game();
    memset((void *)down,0,sizeof(down));qread=qwrite=overflow=0;
    audio_count=0;
    for(i=0;i<1000;i++)key_event(44);
    if(key_take(0)!=44)bad++;
    hit(0,10);
    if(key_take(0) || audio_count!=1 || lead_attacks!=1)bad++;
    key_event(172);key_event(44);
    if(key_take(0)!=44 || key_take(0))bad++;
    hit(0,10);if(audio_count!=1)bad++;
    for(i=1;i<100;i++)key_event(i);
    if(!overflow)bad++;
    memset((void *)down,0,sizeof(down));qread=qwrite=overflow=0;
    next_state=0;music_step(duration);
    if(next_state!=states || last_music_tick!=duration)bad++;
    taps=save;f=fopen("COREQA.TXT","w");
    if(f){fprintf(f,"agency early/late/expired/miss/reset/nearest/repeat/catch-up/late-window: %s\n",bad?"FAIL":"PASS");fclose(f);}
    return bad;
}
static int simulate(int play)
{
    int now;unsigned i;FILE *f;
    reset_game();audio_count=back_count=audio_overflow=0;next_state=0;
    drums_reset();drum_count=drum_hits=0;drum_checksum=0;
    for(i=0;i<3;i++){prev_div[i]=65535;prev_att[i]=65535;}
    for(now=-3;now<=(int)duration+4;now++) {
        lead_step(now);automatic_step(now);music_step(now);expire(now);
        drums_step((long)now*256L);
        if(play && !reference_mode)for(i=0;i<taps;i++)if(!chart[i].reserved && (int)chart[i].tick==now)
            hit(chart[i].lane,now);
    }
    trace_save(reference_mode?"SIMR.TXT":(play?"SIMH.TXT":"SIMM.TXT"));
    f=fopen(reference_mode?"SIMR.LOG":(play?"SIMH.LOG":"SIMM.LOG"),"w");
    if(f){fprintf(f,"hits=%u misses=%u attacks=%u releases=%u events=%u overflow=%u backing=%lu\n",
        hits,misses,lead_attacks,lead_releases,audio_count,audio_overflow,backing_checksum);
        if(ndrums)fprintf(f,"drums=%u drum_hits=%u drum_checksum=%lu\n",ndrums,drum_hits,drum_checksum);
        fclose(f);}
    return audio_overflow || lead_div || (reference_mode?0:(play?hits!=required_taps:misses!=required_taps));
}
/* Called only between games; mute the old track before loading the next. */
static int song_prepare(void)
{
    if(!songs_mode || song_ready)return 1;
    lead_cancel(song_time());sfx_stop();
    if(!songs_next(load_score)) {
        songs_mode=0;
        if(!load_score("ORIGINAL.RBG"))return 0;
    }
    song_ready=1;return 1;
}
/* Screens that name or start the next song settle it first, so the title
   marquee always names the song that Space (or the idle demo) will play. */
static int action_ready(int action)
{
    if(action==A_PLAY || action==A_DEMO || action==A_TITLE)return song_prepare();
    return 1;
}
static int autoplays(void){return auto_mode==1 || auto_mode==3 || auto_mode==7 || auto_mode==9 || auto_mode==16;}
/* One play of the song. demo: the attract-mode autoplayer, any key leaves. */
static int game_run(int demo)
{
    int now,key,last=-32767,playing=1,results_t=0,off;unsigned i,l,ago;
    long nowf;unsigned long before,cost;
    demo_mode=demo;song_ready=0;restart();
    for(;;) {
        nowf=song_fine();now=fine_tick(nowf);
        lead_step(now);automatic_step(now);music_step(now);drums_step(nowf);
        if(auto_mode==5 && now!=last) {
            for(i=0;i<100;i++)key_event(44);
            if((now&7)==0)key_event(172);
        }
        while((key=(int)key_take(&ago))!=0) {
            now=song_time();lead_step(now);automatic_step(now);
            idle_since=clk_ticks();
            if(!playing && hs_entry_key((unsigned)key))continue;
            if(demo) {
                if(key==50){reduced=!reduced;continue;}
                if(key==1)return A_TITLE;
                if(key==57){song_ready=1;return A_PLAY;}
                return A_TITLE;
            }
            if(key==1) {
                exit_reason=1;
                if(auto_mode)return A_EXIT;
                return A_TITLE;
            }
            if(key==19){restart_count++;restart();playing=1;last=-32767;now=song_time();nowf=song_fine();continue;}
            if(key==50){reduced=!reduced;continue;}
            if(key==57 && !playing)return A_TITLE;
            if(playing && key>=44 && key<=46)hit(key-44,now-(int)ago);
        }
        if(playing && (autoplays() || demo))for(i=live_from;i<taps;i++) {
            if((int)chart[i].tick>now+3)break;
            off=auto_mode==9?2:0;
            if(demo)off=(i%13==6)?2:((i%17==9)?-2:0);
            if(!chart[i].reserved && !judged[i] && (int)chart[i].tick<=now+off) {
                l=chart[i].lane;hit(l,now);
            }
        }
        if(auto_mode==3 && now>140 && !restart_count) {
            restart_count++;restart();last=-32767;continue;
        }
        if(auto_mode==4 && now>60){exit_reason=1;return A_EXIT;}
        if(auto_mode==7 && now>=60 && lead_div){exit_reason=1;return A_EXIT;}
        expire(now);
        for(l=0;l<3;l++)key_lit[l]=(unsigned char)(((!demo && !auto_mode && down[44+l]) ||
            (flash_kind[l]==1 && now<flash_until[l]-1))?1:0);
        if(playing && now>(int)duration+WINDOW+2) {
            playing=0;results_step=0;results_t=(int)clk_ticks();hs_begin(demo);
        }
        if(now!=last && last!=-32767 && now-last>1)late_frames++;
        before=clk_fine();
        if(playing)playfield_frame(nowf,now);
        else results_frame((int)clk_ticks()-results_t);
        sfx_step();
        cost=clk_fine()-before;frame_cost=cost>65535UL?65535u:(unsigned)cost;
        if(playing && now>=0) {
            frames++;fine_sum+=cost;
            if(cost>worst_fine)worst_fine=(unsigned)cost;
            if((cost>>8)>worst_ticks)worst_ticks=(unsigned)(cost>>8);
        }
        last=now;
        if(auto_mode && shot_mode && !dump_done && now>=200) {
            dump_frame("FRAME.RAW");dump_done=1;
        }
        if(auto_mode && auto_mode<10 && now>(int)duration+10)return A_EXIT;
        if(auto_mode==16 && !playing && results_step>=9 && hs_state!=HS_ENTER &&
           (int)clk_ticks()-results_t>54)return A_EXIT;
        if(!playing && demo && (int)clk_ticks()-results_t>100)
            return tour_mode?A_EXIT:A_SPLASH;
        frame_end();
    }
}
static int run_show(void)
{
    int action;
    if((auto_mode>=1 && auto_mode<=9) || auto_mode==16) {
        title_draw();dump_frame("TITLE.RAW");
        return game_run(0);
    }
    if(auto_mode==14)action=A_DEMO;
    else {splash_runs++;action=splash_run();}
    for(;;) {
        if(action==A_EXIT)return action;
        if(!action_ready(action))return A_EXIT;
        if(action==A_PLAY)action=game_run(0);
        else if(action==A_TITLE)action=title_run();
        else if(action==A_DEMO) {
            demo_runs++;action=game_run(1);
            /* Attract loop: the song's top ravers, if it has any, then the splash. */
            if(action==A_SPLASH && hs_top())action=scores_run();
        }
        else {splash_runs++;action=splash_run();}
    }
}
int main(int argc,char **argv)
{
    union REGS r;int title_result=0;unsigned i;FILE *log;
    const char *file="ORIGINAL.RBG";int explicit_file=0;
    for(i=1;i<(unsigned)argc;i++) {
        if(!strcmp(argv[i],"/AUTO"))auto_mode=1;
        else if(!strcmp(argv[i],"/MISS"))auto_mode=2;
        else if(!strcmp(argv[i],"/RETRY"))auto_mode=3;
        else if(!strcmp(argv[i],"/ESC"))auto_mode=4;
        else if(!strcmp(argv[i],"/SPAM"))auto_mode=5;
        else if(!strcmp(argv[i],"/INPUT"))auto_mode=6;
        else if(!strcmp(argv[i],"/TEST"))test_mode=1;
        else if(!strcmp(argv[i],"/SIMH"))test_mode=2;
        else if(!strcmp(argv[i],"/SIMM"))test_mode=3;
        else if(!strcmp(argv[i],"/SIMR")){test_mode=4;reference_mode=1;}
        else if(!strcmp(argv[i],"/REF")){auto_mode=8;reference_mode=1;}
        else if(!strcmp(argv[i],"/HESC"))auto_mode=7;
        else if(!strcmp(argv[i],"/CALM"))reduced=1;
        else if(!strcmp(argv[i],"/FXOFF"))no_fx=1;
        else if(!strcmp(argv[i],"/EARLY"))auto_mode=9;
        else if(!strcmp(argv[i],"/SHOT"))shot_mode=1;
        else if(!strcmp(argv[i],"/SPLASH"))auto_mode=10;
        else if(!strcmp(argv[i],"/SSKIP"))auto_mode=11;
        else if(!strcmp(argv[i],"/SESC"))auto_mode=12;
        else if(!strcmp(argv[i],"/SCALM"))auto_mode=13;
        else if(!strcmp(argv[i],"/DEMO"))auto_mode=14;
        else if(!strcmp(argv[i],"/HISCORE"))auto_mode=16;
        else if(!strcmp(argv[i],"/TOUR")){auto_mode=15;tour_mode=1;clk_virtual=1;}
        else if(!strcmp(argv[i],"/RENDER"))clk_virtual=1;
        else if(!strcmp(argv[i],"/NOLOGO"))no_logo=1;
        else if(!strcmp(argv[i],"/NOVSYNC"))vsync_on=0;
        else {file=argv[i];explicit_file=1;}
    }
    /* Keep scripted timing/QA and explicit-file launches exactly reproducible. */
    if(!explicit_file && !test_mode && (!auto_mode || auto_mode==14)) {
        songs_reset(clk_ticks());songs_discover();
        songs_mode=songs_next(load_score);song_ready=songs_mode;
    }
    if(!songs_mode && !load_score(file)) {
        puts(load_nomem?"Not enough free memory for this song; no hardware changed.":
            "Invalid bounded RBG2/RBG3/RBG4/RBG5 score; no hardware changed.");
        return 2;
    }
    if(test_mode==1)return selftest();
    if(test_mode>=2)return simulate(test_mode==2);
    hs_load();
    gfx_init();lanes_init();
    cache=(unsigned char far *)_fmalloc(CACHE_BYTES);cache_used=0;
    fx_init();rz_init();
    words_init();
    r.h.ah=15;int86(0x10,&r,&r);old_mode=r.h.al;
    if(DosSoundAcquire(DS_PSG)) {
        puts("Sound owner refused: requires exclusive plain Tandy DOS.");return 3;
    }
    owned=1;atexit(cleanup);key_install();
    if(clk_virtual){psg_log=fopen("PSG.LOG","w");pal_log=fopen("PAL.LOG","w");}
    mode(9);video_owned=1;
    psg_mute_all();
    if(auto_mode>=10 && auto_mode<=13) {
        if(auto_mode==11)key_event(57);
        if(auto_mode==12)key_event(1);
        if(auto_mode==13)key_event(50);
        title_result=splash_run();
        if(title_result==A_TITLE){title_draw();dump_frame("FALLBACK.RAW");}
        cleanup();r.h.ah=15;int86(0x10,&r,&r);
        log=fopen("SPLASH.LOG","w");
        if(log) {
            fprintf(log,"mode=%d result=%d calm=%d audio_events=%u\n",
                auto_mode,title_result==A_PLAY,reduced,audio_count);
            fprintf(log,"restore_video=%d restore_keyboard=%d sound_owned=%d keyboard_owned=%d video_owned=%d speaker_low=%u\n",
                (unsigned)r.h.al==old_mode,_dos_getvect(9)==old_keyboard,
                owned,keyboard_owned,video_owned,inp(0x61)&3);
            fclose(log);
        }
        return 0;
    }
    run_show();
    cleanup();
    if(!auto_mode && !clk_virtual) {
        printf("Radio Shack Rave: %u hits, %u misses, score %lu.\n",hits,misses,score);
        return 0;
    }
    /* Diagnostics only for scripted runs; a play from floppy writes nothing. */
    trace_save("AUDIO.TXT");
    r.h.ah=15;int86(0x10,&r,&r);
    log=fopen("RUNLOG.TXT","w");
    if(log) {
        fprintf(log,"mode=%d reason=%d restore_video=%d restore_keyboard=%d\n",
            auto_mode,exit_reason,(unsigned)r.h.al==old_mode,
            _dos_getvect(9)==old_keyboard);
        fprintf(log,"score=%lu hits=%u misses=%u best=%u ghosts=%u restart=%u silent_hits=%u\n",
            score,hits,misses,best,ghosts,restart_count,silent_hits);
        fprintf(log,"lead_attacks=%u lead_releases=%u audio_events=%u overflow=%u backing_checksum=%lu\n",
            lead_attacks,lead_releases,audio_count,audio_overflow,backing_checksum);
        fprintf(log,"required=%u total_lead=%u automatic=%u reference=%u auto_skipped=%u\n",
            required_taps,taps,automatic_attacks,reference_attacks,automatic_skipped);
        fprintf(log,"frames=%u skipped_intervals=%u worst_draw_ticks=%u worst_draw_ms=%lu avg_draw_ms10=%lu vram_bytes=%lu\n",
            frames,late_frames,worst_ticks,(unsigned long)worst_fine*55UL/256UL,
            frames?fine_sum*550UL/256UL/frames:0UL,vram_bytes);
        fprintf(log,"judgments=%u awesome=%u nice=%u missed=%u title=%s segments=%u difficulty=%u\n",
            fx_seen,fx_awesome,fx_nice,fx_missed,song_title,nsegs,difficulty);
        fprintf(log,"input_wait_ticks=%u IRQ1=%u makes=%u breaks=%u repeats=%u pit_mode=%d\n",
            max_input_wait,irq_count,key_makes,key_breaks,key_repeats,clk_mode2?2:3);
        fprintf(log,"state_cursor=%u/%u final_tick=%u/%u music_updates=%u queue_overflow=%u\n",
            next_state,states,last_music_tick,duration,music_updates,overflow);
        fprintf(log,"drums=%u drum_hits=%u drum_checksum=%lu\n",ndrums,drum_hits,drum_checksum);
        fprintf(log,"hiscore_state=%d hiscore_rank=%d hiscore_initials=%s hiscore_songs=%u\n",
            hs_state,hs_rank,hs_ini[0]?hs_ini:"-",hs_count);
        fprintf(log,"far_tables state_table=%u/%u note_table=%u/%u drum_table=%u/%u segs=%u keyboard=%u; PIT0 unchanged\n",
            states,cap_states,taps,cap_taps,ndrums,cap_drums,(unsigned)sizeof(segs),
            (unsigned)(sizeof(down)+sizeof(queue)+sizeof(queue_tick)));
        fprintf(log,"prof lanes=%lu caps=%lu hud=%lu fx=%lu rows=%u\n",prof[0]>>8,prof[1]>>8,prof[2]>>8,prof[3]>>8,rows_written);
        fprintf(log,"fx_scenes_seen=%04x fx_switches=%u fx_lite=%u fx_buffer=%d demos=%u splashes=%u\n",
            fx_seen_mask,fx_switches,fx_lite,fxbuf!=0,demo_runs,splash_runs);
        fprintf(log,"cleanup_owned=%d keyboard_owned=%d video_owned=%d speaker_low=%u\n",
            owned,keyboard_owned,video_owned,inp(0x61)&3);
        fclose(log);
    }
    return 0;
}
