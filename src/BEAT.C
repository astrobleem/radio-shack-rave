/* Radio Shack Rave: small-model MSC6 /G0, real-mode 8088 DOS. */
#include <dos.h>
#include <conio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "DOSSND.H"
static void lead_output(int now,unsigned divisor,unsigned attenuation);
#include "FX.H"
#include "CORE.H"
#include "SPLASH.H"

#define MAX_STATES 1024
#define RINGS 4
typedef struct {
    unsigned tick, divisor[3];
    unsigned char attenuation[3], reserved;
} State;
static State music[MAX_STATES];
static unsigned states, duration, next_state, prev_div[3], prev_att[3];
static unsigned old_mode, frames, late_frames, worst_ticks;
static unsigned writes, worst_writes, ring_phase, old_ring[RINGS];
static unsigned no_fx,fx_updates,fx_deferred,fx_max_writes,fx_word_max;
static unsigned fx_slow_frames;
static unsigned fx_old_mode;
static int fx_old_star[8][2];
static unsigned music_updates, restart_count, last_music_tick;
static unsigned worst_pit_counts,max_input_wait;
static volatile unsigned irq_count,key_makes,key_breaks,key_repeats;
static unsigned char far *video=(unsigned char far *)0xb8000000UL;
static int old_y[MAX_NOTES], reduced, owned, keyboard_owned, video_owned;
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
static BackEvent back_trace[MAX_STATES];
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
    DosSoundPsgByte(0x9f);
    if(divisor) {
        DosSoundPsgByte(0x80+(divisor&15));
        DosSoundPsgByte(divisor>>4);
        DosSoundPsgByte(0x90+attenuation);
    }
}
static void trace_save(const char *name)
{
    FILE *f;unsigned i;
    f=fopen(name,"w");if(!f)return;
    for(i=0;i<audio_count;i++)fprintf(f,"L %d %u %u\n",
        audio_trace[i].tick,audio_trace[i].divisor,audio_trace[i].attenuation);
    for(i=0;i<back_count;i++)fprintf(f,"B %u %u %u %u %u\n",
        back_trace[i].tick,back_trace[i].d1,back_trace[i].a1,
        back_trace[i].d2,back_trace[i].a2);
    fclose(f);
}
static unsigned long elapsed(void)
{
    unsigned flags;unsigned long ticks;
    _asm pushf
    _asm pop flags
    _asm cli
    ticks=*(unsigned long far *)0x0040006cUL;
    _asm push flags
    _asm popf
    /* Preserve BIOS midnight flag; INT1A/00 would clear it repeatedly. */
    return ticks;
}
static unsigned pit_count(void)
{
    unsigned lo,hi,flags;
    _asm pushf
    _asm pop flags
    _asm cli
    /* Counter latch only: mode, divisor and IRQ cadence remain unchanged. */
    outp(0x43,0);lo=inp(0x40);hi=inp(0x40);
    _asm push flags
    _asm popf
    return lo|(hi<<8);
}
static int song_time(void)
{
    unsigned long now=elapsed(), age;
    age=now>=origin?now-origin:now+0x1800b0UL-origin;
    if(age>30000UL)age=30000UL;
    return (int)age-36;
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
static unsigned key_take(void)
{
    unsigned key,wait;
    if(qread==qwrite)return 0;
    key=queue[qread];
    wait=*(unsigned far *)0x0040006cUL-queue_tick[qread];
    if(wait>max_input_wait)max_input_wait=wait;
    qread=(qread+1)&31;return key;
}
static void mode(unsigned m)
{
    union REGS r;r.x.ax=m;int86(0x10,&r,&r);
}
static void cleanup(void)
{
    if(owned)lead_cancel(song_time());
    if(keyboard_owned){_dos_setvect(9,old_keyboard);keyboard_owned=0;}
    if(owned){DosSoundRelease();owned=0;}
    if(video_owned){mode(old_mode);video_owned=0;}
}
static int load_score(const char *name)
{
    FILE *f;char magic[4];unsigned version,i,k;int ok=1;
    f=fopen(name,"rb");if(!f)return 0;
    if(fread(magic,1,4,f)!=4)ok=0;
    if(fread(&version,2,1,f)!=1 ||
        !((version==3 && !memcmp(magic,"RBG3",4)) ||
          (version==2 && !memcmp(magic,"RBG2",4))))ok=0;
    if(fread(&duration,2,1,f)!=1 || !duration || duration>10924)ok=0;
    if(fread(&states,2,1,f)!=1 || states<2 || states>MAX_STATES)ok=0;
    if(fread(&taps,2,1,f)!=1 || !taps || taps>MAX_NOTES)ok=0;
    if(!ok){fclose(f);return 0;}
    if(fread(music,sizeof(State),states,f)!=states)ok=0;
    if(fread(chart,sizeof(Tap),taps,f)!=taps)ok=0;
    if(fgetc(f)!=EOF)ok=0;
    fclose(f);
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
           chart[i].reserved>(version==3?1:0))ok=0;
        if(!chart[i].reserved)required_taps++;
        if(chart[i].end_tick<=chart[i].tick || chart[i].end_tick>duration ||
           !chart[i].divisor || chart[i].divisor>1023 ||
           chart[i].attenuation>14 || chart[i].note<45 || chart[i].note>96)ok=0;
        if(i && chart[i].tick<=chart[i-1].tick)ok=0;
        if(i && chart[i].tick<chart[i-1].end_tick)ok=0;
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
            DosSoundPsgByte(0x80+(k<<5)+(d&15));
            DosSoundPsgByte(d>>4);
        }
        if(a!=prev_att[k])DosSoundPsgByte(0x90+(k<<5)+a);
        prev_div[k]=d;prev_att[k]=a;
    }
    last_music_tick=music[chosen].tick;
    if(back_count<MAX_STATES) {
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
static void pixel(int x,int y,unsigned color)
{
    unsigned pos;unsigned char v;
    if(x<0 || x>319 || y<0 || y>199)return;
    pos=(y&3)*8192+(y>>2)*160+(x>>1);v=video[pos];
    video[pos]=(unsigned char)((x&1)?(v&240)|color:(v&15)|(color<<4));
    writes++;
}
static void rect(int x,int y,int w,int h,unsigned color)
{
    int yy,xx;unsigned pos;unsigned char packed;
    if(x<0 || x+w>320 || y<0 || y+h>200)return;
    packed=(unsigned char)(color|(color<<4));
    for(yy=y;yy<y+h;yy++) {
        pos=(yy&3)*8192+(yy>>2)*160+(x>>1);
        for(xx=0;xx<w/2;xx++){video[pos++]=packed;writes++;}
    }
}
static void box(int x,int y,int w,int h,unsigned color)
{
    int yy;unsigned pos,right;unsigned char high;
    /* Every caller has even x/width. Pack horizontal edges two pixels per
       byte; calculate each vertical row address once, without pixel calls. */
    rect(x,y,w,1,color);rect(x,y+h-1,w,1,color);
    right=(w>>1)-1;high=(unsigned char)(color<<4);
    for(yy=y+1;yy<y+h-1;yy++) {
        pos=(yy&3)*8192+(yy>>2)*160+(x>>1);
        video[pos]=(unsigned char)((video[pos]&15)|high);
        video[pos+right]=(unsigned char)((video[pos+right]&240)|color);
        writes+=2;
    }
}
/* 3x5 glyphs, left-to-right rows, digits then uppercase letters. */
static const unsigned char font[36][5]={
 {7,5,5,5,7},{2,6,2,2,7},{7,1,7,4,7},{7,1,7,1,7},
 {5,5,7,1,1},{7,4,7,1,7},{7,4,7,5,7},{7,1,1,1,1},
 {7,5,7,5,7},{7,5,7,1,7},{2,5,7,5,5},{6,5,6,5,6},
 {7,4,4,4,7},{6,5,5,5,6},{7,4,6,4,7},{7,4,6,4,4},
 {7,4,5,5,7},{5,5,7,5,5},{7,2,2,2,7},{1,1,1,5,7},
 {5,5,6,5,5},{4,4,4,4,7},{5,7,7,5,5},{5,7,7,7,5},
 {7,5,5,5,7},{7,5,7,4,4},{7,5,5,7,1},{6,5,6,5,5},
 {7,4,7,1,7},{7,2,2,2,2},{5,5,5,5,7},{5,5,5,5,2},
 {5,5,7,7,5},{5,5,2,5,5},{5,5,2,2,2},{7,1,2,4,7}
};
static void text(int x,int y,const char *s,unsigned color)
{
    int ix,row,col;unsigned bits;
    while(*s) {
        ix=*s>='0'&&*s<='9'?*s-'0':
            (*s>='A'&&*s<='Z'?*s-'A'+10:-1);
        if(ix>=0)for(row=0;row<5;row++) {
            bits=font[ix][row];
            for(col=0;col<3;col++)if(bits&(4>>col))pixel(x+col,y+row,color);
        }
        if(*s=='\'')pixel(x+1,y,color);
        if(*s=='.')pixel(x+1,y+4,color);
        if(*s=='!'){pixel(x+1,y,color);pixel(x+1,y+1,color);
            pixel(x+1,y+2,color);pixel(x+1,y+4,color);}
        x+=5;s++;
    }
}
static void text2(int x,int y,const char *s,unsigned color)
{
    int ix,row,col;unsigned bits;
    while(*s) {
        ix=*s>='A'&&*s<='Z'?*s-'A'+10:-1;
        if(ix>=0)for(row=0;row<5;row++) {
            bits=font[ix][row];
            for(col=0;col<3;col++)if(bits&(4>>col))
                rect(x+col*2,y+row*2,2,2,color);
        }
        if(*s=='!'){rect(x+2,y,2,6,color);rect(x+2,y+8,2,2,color);}
        x+=10;s++;
    }
}
static void side_shape(unsigned kind,unsigned r,unsigned color)
{
    int dx,dy;
    if(kind==1)for(dx=-(int)r;dx<=(int)r;dx++) {
        dy=(int)r-(dx<0?-dx:dx);
        pixel(52+dx,100-dy,color);pixel(52+dx,100+dy,color);
    }
    else if(kind==2)box(52-r,100-r/2,r*2,r,color);
    else box(52-r,100-r,r*2,r*2,color);
}
static int feedback(int now)
{
    unsigned visible,before;
    visible=now<fx_until?fx_kind:0;
    if(visible==fx_shown)return 0;
    before=writes;rect(228,150,84,10,0);
    if(visible==2)text2(232,150,"AWESOME!",11);
    else if(visible==1)text2(250,150,"NICE!",10);
    else if(visible==3)text2(250,150,"MISS!",6);
    fx_shown=visible;fx_changes++;
    if(writes-before>fx_word_max)fx_word_max=writes-before;
    return 1;
}
static void sides(int now,int word_changed)
{
    static const unsigned sizes[8]={6,10,14,20,26,32,38,44};
    static const unsigned char palettes[4][2]={{1,3},{3,5},{5,1},{6,3}};
    static const signed char points[8][2]={
        {-24,-30},{-12,-42},{12,-42},{24,-30},
        {24,22},{12,38},{-12,38},{-24,22}};
    unsigned phase,kind,pal,i,r,before;int x,y;
    if(now<fx_slow_until)fx_slow_frames++;
    phase=reduced?0:(unsigned)(now<0?0:now)>>(now<fx_slow_until?4:3);
    if(phase==ring_phase)return;
    if(word_changed){fx_deferred++;return;}
    before=writes;
    for(i=0;i<2;i++)if(old_ring[i])side_shape(fx_old_mode,old_ring[i],0);
    for(i=0;i<8;i++)if(fx_old_star[i][0]>=0)
        pixel(fx_old_star[i][0],fx_old_star[i][1],0);
    kind=reduced?0:((combo>>3)+(lead_cursor>>4))%3;
    pal=reduced?0:((combo>>3)+(lead_cursor>>5))&3;
    for(i=0;i<2;i++) {
        r=sizes[(phase+i*4+(reduced?0:lead_cursor&1))&7];
        old_ring[i]=r;side_shape(kind,r,palettes[pal][i]);
    }
    for(i=0;i<8;i++) {
        if(kind==1){x=270+points[i][0];y=92+points[i][1];}
        else if(kind==2){x=238+i*10;y=55+((phase+i*3)&7)*10;}
        else {x=270+points[i][0]/2;y=92+points[i][1];}
        fx_old_star[i][0]=x;fx_old_star[i][1]=y;
        pixel(x,y,palettes[pal][i&1]);
    }
    fx_old_mode=kind;ring_phase=phase;fx_updates++;
    if(writes-before>fx_max_writes)fx_max_writes=writes-before;
}
static void scene(void)
{
    unsigned i;
    mode(9);video_owned=1;
    text(120,6,"RADIO SHACK RAVE",11);
    for(i=0;i<3;i++)box(104+i*36,27,32,150,8);
    rect(106,166,100,2,11);
    text(116,182,"Z",10);text(152,182,"X",13);text(188,182,"C",14);
    text(5,193,"ESC EXIT  R RETRY  M CALM",7);
    for(i=0;i<taps;i++)old_y[i]=-1;
    for(i=0;i<RINGS;i++)old_ring[i]=0;
    for(i=0;i<8;i++)fx_old_star[i][0]=-1;
    fx_old_mode=0;fx_shown=0;
    ring_phase=65535;
}
static void visuals(int now)
{
    unsigned i,phase,r;int y,lane,word_changed;char hud[64];
    static const unsigned sizes[8]={6,10,14,20,26,32,38,44};
    static const unsigned colors[3]={10,13,14};
    /* Dirty note rectangles, leaving lane borders intact. */
    for(i=0;i<taps;i++)if(old_y[i]>=0) {
        rect(110+chart[i].lane*36,old_y[i],20,4,0);old_y[i]=-1;
    }
    for(i=0;i<taps;i++) {
        if((int)chart[i].tick>now+45)break;
        if(judged[i] || chart[i].reserved)continue;
        y=166-((int)chart[i].tick-now)*3;
        if(y>=29 && y<=172) {
            lane=chart[i].lane;rect(110+lane*36,y,20,4,colors[lane]);old_y[i]=y;
        }
    }
    rect(106,166,100,2,11);
    for(i=0;i<3;i++) {
        r=now<flash_until[i]?((flash_kind[i]==1)?colors[i]:4):0;
        rect(110+i*36,170,20,5,r);
    }
    /* Integer tunnel rectangles, slow phases and stable low-intensity color.
       Reduced motion freezes tunnel and stars, notes remain playable. */
    word_changed=0;
    if(!no_fx){word_changed=feedback(now);sides(now,word_changed);}
    phase=reduced?0:(unsigned)(now<0?0:now)/4;
    if(no_fx && phase!=ring_phase) {
        for(i=0;i<RINGS;i++)if(old_ring[i]) {
            r=old_ring[i];box(52-r,100-r,r*2,r*2,0);
            pixel(269+r/2,57+r,0);pixel(267-r/2,142-r,0);
        }
        for(i=0;i<RINGS;i++) {
            r=sizes[(phase+i*2)&7];old_ring[i]=r;
            box(52-r,100-r,r*2,r*2,(i&1)?3:1);
            pixel(269+r/2,57+r,3);pixel(267-r/2,142-r,1);
        }
        ring_phase=phase;
    }
    if((frames&3)==0) {
        rect(4,18,212,6,0);
        sprintf(hud,"SCORE %lu  COMBO %u  BEST %u",score,combo,best);
        text(10,18,hud,7);
        rect(222,164,96,6,0);rect(222,174,96,6,0);
        sprintf(hud,"HIT %u",hits);text(224,166,hud,10);
        sprintf(hud,"MISS %u",misses);text(224,176,hud,7);
    }
    if(now<0){rect(222,86,96,6,0);text(230,86,"GET READY",11);}
    else if(now<2)rect(222,86,96,6,0);
    if(now>(int)duration+WINDOW) {
        rect(110,81,96,28,0);text(118,85,"SONG CLEAR",11);
        text(116,99,"R TO RETRY",7);
    }
}
static void dump_frame(const char *name)
{
    FILE *f;unsigned y,pos,x;unsigned char row[160];
    f=fopen(name,"wb");if(!f)return;
    for(y=0;y<200;y++) {
        pos=(y&3)*8192+(y>>2)*160;
        for(x=0;x<160;x++)row[x]=video[pos+x];
        fwrite(row,1,160,f);
    }
    fclose(f);
}
static void restart(void)
{
    unsigned k;
    for(k=0;k<4;k++)DosSoundPsgByte(0x9f+(k<<5));
    for(k=0;k<3;k++){prev_div[k]=65535;prev_att[k]=65535;}
    next_state=0;last_music_tick=0;reset_game();scene();origin=elapsed();
    audio_count=back_count=audio_overflow=0;backing_checksum=0;
}
static int plain_title(void)
{
    unsigned k;
    mode(9);video_owned=1;
    box(34,44,252,110,3);
    text(120,65,"RADIO SHACK RAVE",11);
    text(60,86,"YOU'VE GOT QUESTIONS.",7);
    text(166,86,"WE'VE GOT BANGERS.",7);
    text(95,108,"SPACE PLAY   Z X C",10);
    text(70,126,"M REDUCED MOTION  ESC EXIT",7);
    text(70,146,"UNCHARTED NOTES KEEP PLAYING",11);
    text(65,171,"MISS A TAP  MISS ITS TONE",8);
    if(auto_mode && auto_mode<10){dump_frame("TITLE.RAW");return 1;}
    if(auto_mode>=10){dump_frame("FALLBACK.RAW");return 0;}
    for(;;) {
        k=key_take();
        if(k==1)return 0;
        if(k==57)return 1;
        if(k==50){reduced=!reduced;text(105,140,reduced?"CALM ON ":"CALM OFF",11);}
    }
}
/* Status: -2 bad/missing bitmap, -1 Escape, 0 continue, 1 Space. */
static int splash_input(void)
{
    unsigned k;
    while((k=key_take())!=0) {
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
        pos=((y+row)&3)*8192+((y+row)>>2)*160+x/2;
        for(i=0;i<w/2;i++)video[pos+i]=buffer[i];
    }
    if(ok && fgetc(f)!=EOF)ok=0;
    fclose(f);return ok?0:-2;
}
static int splash_wait(unsigned ticks)
{
    unsigned long start=elapsed();int action;
    do {
        action=splash_input();if(action)return action;
    } while(splash_age(elapsed(),start)<ticks);
    return 0;
}
static int title_screen(void)
{
    unsigned k;int action;
    for(k=0;k<4;k++)DosSoundPsgByte(0x9f+(k<<5));
    if(auto_mode && auto_mode<10)return plain_title();
    mode(9);video_owned=1;
    if(auto_mode==11)key_event(57);
    if(auto_mode==12)key_event(1);
    if(auto_mode==13)key_event(50);
    action=splash_bitmap("CARD.BIN");
    if(action==-2)return plain_title();
    if(action)return action>0;
    if(auto_mode>=10)dump_frame("STAGE0.RAW");
    action=splash_wait(SPLASH_ORIGINAL_TICKS);
    if(action)return action>0;
    /* Only the original word answers changes. The slogan/period stay. */
    rect(166,100,84,18,0);text2(170,102,"BANGERS",15);
    if(auto_mode>=10)dump_frame("STAGE1.RAW");
    action=splash_wait(SPLASH_BANGERS_TICKS);
    if(action)return action>0;
    mode(9);
    action=splash_bitmap("LOGO.BIN");
    if(action==-2)return plain_title();
    if(action)return action>0;
    text2(140,153,"RAVE",11);
    text(95,174,"SPACE PLAY   Z X C",10);
    text(80,188,"M CALM   ESC EXIT",7);
    if(auto_mode>=10){dump_frame("STAGE2.RAW");return 0;}
    for(;;) {
        action=splash_input();if(action)return action>0;
    }
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
    reset_game();audio_count=0;
    chart[0].end_tick=12;if(hit(0,13) || audio_count)bad++;
    chart[0].end_tick=14;
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
    chart[1].tick=16;chart[1].lane=1;reset_game();
    memset((void *)down,0,sizeof(down));qread=qwrite=overflow=0;
    audio_count=0;
    for(i=0;i<1000;i++)key_event(44);
    if(key_take()!=44)bad++;
    hit(0,10);
    if(key_take() || audio_count!=1 || lead_attacks!=1)bad++;
    key_event(172);key_event(44);
    if(key_take()!=44 || key_take())bad++;
    hit(0,10);if(audio_count!=1)bad++;
    for(i=1;i<100;i++)key_event(i);
    if(!overflow)bad++;
    memset((void *)down,0,sizeof(down));qread=qwrite=overflow=0;
    next_state=0;music_step(duration);
    if(next_state!=states || last_music_tick!=duration)bad++;
    taps=save;f=fopen("COREQA.TXT","w");
    if(f){fprintf(f,"agency early/late/expired/miss/reset/nearest/repeat/catch-up: %s\n",bad?"FAIL":"PASS");fclose(f);}
    return bad;
}
static int simulate(int play)
{
    int now;unsigned i;FILE *f;
    reset_game();audio_count=back_count=audio_overflow=0;next_state=0;
    for(i=0;i<3;i++){prev_div[i]=65535;prev_att[i]=65535;}
    for(now=-3;now<=(int)duration+4;now++) {
        lead_step(now);automatic_step(now);music_step(now);expire(now);
        if(play && !reference_mode)for(i=0;i<taps;i++)if(!chart[i].reserved && (int)chart[i].tick==now)
            hit(chart[i].lane,now);
    }
    trace_save(reference_mode?"SIMR.TXT":(play?"SIMH.TXT":"SIMM.TXT"));
    f=fopen(reference_mode?"SIMR.LOG":(play?"SIMH.LOG":"SIMM.LOG"),"w");
    if(f){fprintf(f,"hits=%u misses=%u attacks=%u releases=%u events=%u overflow=%u backing=%lu\n",
        hits,misses,lead_attacks,lead_releases,audio_count,audio_overflow,backing_checksum);fclose(f);}
    return audio_overflow || lead_div || (reference_mode?0:(play?hits!=required_taps:misses!=required_taps));
}
int main(int argc,char **argv)
{
    union REGS r;int now,key,last=-32767,exit_now=0,reason=0,title_result;
    unsigned i,frame_cost,pc_before,pc_delta;
    unsigned long before,after;FILE *log;
    const char *file="ORIGINAL.RBG";
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
        else file=argv[i];
    }
    if(!load_score(file)){puts("Invalid bounded RBG2/RBG3 score; no hardware changed.");return 2;}
    if(test_mode==1)return selftest();
    if(test_mode>=2)return simulate(test_mode==2);
    r.h.ah=15;int86(0x10,&r,&r);old_mode=r.h.al;
    if(DosSoundAcquire(DS_PSG)) {
        puts("Sound owner refused: requires exclusive plain Tandy DOS.");return 3;
    }
    owned=1;atexit(cleanup);key_install();
    title_result=title_screen();
    if(auto_mode>=10) {
        cleanup();r.h.ah=15;int86(0x10,&r,&r);
        log=fopen("SPLASH.LOG","w");
        if(log) {
            fprintf(log,"mode=%d result=%d calm=%d audio_events=%u\n",
                auto_mode,title_result,reduced,audio_count);
            fprintf(log,"restore_video=%d restore_keyboard=%d sound_owned=%d keyboard_owned=%d video_owned=%d speaker_low=%u\n",
                (unsigned)r.h.al==old_mode,_dos_getvect(9)==old_keyboard,
                owned,keyboard_owned,video_owned,inp(0x61)&3);
            fclose(log);
        }
        return 0;
    }
    if(!title_result){cleanup();return 0;}
    restart();
    while(!exit_now) {
        now=song_time();lead_step(now);automatic_step(now);music_step(now);expire(now);
        if(auto_mode==5 && now!=last) {
            for(i=0;i<100;i++)key_event(44);
            if((now&7)==0)key_event(172);
        }
        while((key=key_take())!=0) {
            now=song_time();lead_step(now);automatic_step(now);
            if(key==1){reason=1;exit_now=1;break;}
            if(key==19){restart_count++;restart();last=-32767;now=song_time();}
            if(key==50){reduced=!reduced;ring_phase=65535;}
            if(key==44 || key==45 || key==46)hit(key-44,now);
        }
        if(auto_mode==1 || auto_mode==3 || auto_mode==7 || auto_mode==9)for(i=0;i<taps;i++) {
            if(!chart[i].reserved && !judged[i] &&
               (int)chart[i].tick==now+(auto_mode==9?2:0))hit(chart[i].lane,now);
        }
        if(auto_mode==3 && now>140 && !restart_count) {
            restart_count++;restart();last=-32767;continue;
        }
        if(auto_mode==4 && now>60){reason=1;exit_now=1;}
        if(auto_mode==7 && now>=60 && lead_div){reason=1;exit_now=1;}
        if(now!=last) {
            if(last!=-32767 && now-last>1)late_frames++;
            if(last!=-32767 && now-last>1)fx_slow_until=now+36;
            last=now;writes=0;before=elapsed();pc_before=pit_count();
            visuals(now);pc_delta=pc_before-pit_count();after=elapsed();
            if(pc_delta>worst_pit_counts)worst_pit_counts=pc_delta;
            frame_cost=(unsigned)(after-before);
            if(frame_cost>worst_ticks)worst_ticks=frame_cost;
            if(frame_cost)fx_slow_until=now+36;
            if(writes>worst_writes)worst_writes=writes;
            frames++;
              if(auto_mode && shot_mode && !dump_done &&
                 (now>180 || (!no_fx && now>0 && fx_shown))) {
                  dump_frame("FRAME.RAW");dump_done=1;
              }
        }
        if(auto_mode && now>(int)duration+10)exit_now=1;
    }
    cleanup();
    trace_save("AUDIO.TXT");
    r.h.ah=15;int86(0x10,&r,&r);
    log=fopen("RUNLOG.TXT","w");
    if(log) {
        fprintf(log,"mode=%d reason=%d restore_video=%d restore_keyboard=%d\n",
            auto_mode,reason,(unsigned)r.h.al==old_mode,
            _dos_getvect(9)==old_keyboard);
        fprintf(log,"score=%lu hits=%u misses=%u best=%u ghosts=%u restart=%u\n",
            score,hits,misses,best,ghosts,restart_count);
        fprintf(log,"lead_attacks=%u lead_releases=%u audio_events=%u overflow=%u backing_checksum=%lu\n",
            lead_attacks,lead_releases,audio_count,audio_overflow,backing_checksum);
        fprintf(log,"required=%u total_lead=%u automatic=%u reference=%u auto_skipped=%u\n",
            required_taps,taps,automatic_attacks,reference_attacks,automatic_skipped);
        fprintf(log,"frames=%u skipped_intervals=%u worst_draw_ticks=%u max_vram_bytes=%u\n",
            frames,late_frames,worst_ticks,worst_writes);
        fprintf(log,"fx_updates=%u fx_deferred=%u fx_max_writes=%u word_changes=%u word_max_writes=%u judgments=%u\n",
              fx_updates,fx_deferred,fx_max_writes,fx_changes,fx_word_max,fx_seen);
        fprintf(log,"fx_slow_frames=%u\n",fx_slow_frames);
        fprintf(log,"worst_modulo_pit_counts=%u input_wait_ticks=%u IRQ1=%u makes=%u breaks=%u repeats=%u\n",
            worst_pit_counts,max_input_wait,irq_count,key_makes,key_breaks,key_repeats);
        fprintf(log,"state_cursor=%u/%u final_tick=%u/%u music_updates=%u queue_overflow=%u\n",
            next_state,states,last_music_tick,duration,music_updates,overflow);
        fprintf(log,"memory states=%u chart=%u judged=%u old_y=%u keyboard=%u; PIT0 unchanged\n",
            sizeof(music),sizeof(chart),sizeof(judged),sizeof(old_y),
            sizeof(down)+sizeof(queue)+sizeof(queue_tick));
        fprintf(log,"cleanup_owned=%d keyboard_owned=%d video_owned=%d speaker_low=%u\n",
            owned,keyboard_owned,video_owned,inp(0x61)&3);
        fclose(log);
    }
    printf("Radio Shack Rave: %u hits, %u misses, score %lu.\n",hits,misses,score);
    return 0;
}
