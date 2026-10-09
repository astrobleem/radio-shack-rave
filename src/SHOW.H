/* Presentation: the attract splash, the title screen and the kiosk loop.
 * Screens are frame loops: draw what changed, step sound effects, read keys,
 * present. Calm mode keeps every screen still apart from text appearing.
 */
#define A_EXIT 0
#define A_PLAY 1
#define A_TITLE 2
#define A_DEMO 3
#define A_SPLASH 4
#define ATTRACT_TICKS 364
static unsigned frame_no;
static void dump_frame(const char *name)
{
    FILE *f;unsigned y,x;unsigned char row[160];unsigned char far *p;
    f=fopen(name,"wb");if(!f)return;
    for(y=0;y<SCR_H;y++) {
        p=video+row_ofs[y];
        for(x=0;x<160;x++)row[x]=p[x];
        fwrite(row,1,160,f);
    }
    fclose(f);
}
/* End of a frame: real time waits for the next vertical retrace so drawing
   starts as the beam leaves the screen; render mode saves the frame and
   advances the virtual clock by half a tick. */
static unsigned frame_cost;
static void frame_end(void)
{
    char name[16];
    if(clk_virtual) {
        sprintf(name,"F%05u.RAW",frame_no++);dump_frame(name);
        clk_vtime+=RENDER_STEP;
    } else if(frame_cost<64)vsync_wait();
    /* A frame that took over a quarter tick (14 ms) does not also wait out
       a retrace: on slow machines tearing costs less than lost frames. */
}
static void calm_badge(void)
{
    text(266,2,reduced?"CALM ON ":"CALM OFF",reduced?11:8,0);
}
/* Splash keys: Space plays, Escape exits, M toggles calm, anything else
   skips ahead to the title. 0 means keep going. */
static int show_keys(int other)
{
    unsigned k;
    while((k=key_take(0))!=0) {
        idle_since=clk_ticks();
        if(k==1)return A_EXIT+100;
        if(k==57)return A_PLAY+100;
        if(k==50){reduced=!reduced;calm_badge();}
        else if(other)return other+100;
    }
    return 0;
}
static int logo_show(void)
{
    int action;unsigned long t0;
    clear_screen();
    action=splash_bitmap("LOGO.BIN");
    if(action==-2)return 0;
    if(action)return action>0?A_PLAY+100:A_EXIT+100;
    sfx_chord(84,79,76,4,2,20);sfx_note(3,NOISE_WHITE(1),6,1,6);
    t0=clk_ticks();
    while(clk_ticks()-t0<46) {
        sfx_step();
        if((action=show_keys(A_TITLE))!=0)return action;
        frame_end();
    }
    clear_screen();
    return 0;
}
static void starburst(int step,int steps)
{
    int i,k,x,y,dx,dy,len,r0,r1;
    static const signed char ray[24][2]={
        {64,0},{62,17},{55,32},{45,45},{32,55},{17,62},{0,64},{-17,62},{-32,55},
        {-45,45},{-55,32},{-62,17},{-64,0},{-62,-17},{-55,-32},{-45,-45},
        {-32,-55},{-17,-62},{0,-64},{17,-62},{32,-55},{45,-45},{55,-32},{62,-17}};
    r0=24+step*200/steps;r1=24+(step+1)*200/steps;
    for(i=0;i<24;i++) {
        dx=ray[i][0];dy=ray[i][1];
        for(len=r0;len<r1;len++)for(k=-1;k<=1;k++) {
            x=160+dx*len/64+k*(dy!=0);y=132+dy*len/80+k*(dy==0);
            if(y<100 || x<0 || x>=SCR_W || y>=SCR_H)continue;
            if(((x+y)&1)==0)px(x,y,(i&1)?1:5);
        }
    }
}
static const char splash_q[]="YOU'VE GOT QUESTIONS?";
static const unsigned char blip_notes[]={72,74,76,79,81,84,86,88};
static int splash_run(void)
{
    unsigned long t0,t;int stage=0,action,i;Style st,big,sub;char one[2];
    static const int last_char=sizeof(splash_q)-2;
    sfx_stop();
    if(!no_logo && (action=logo_show())!=0)return action-100;
    clear_screen();calm_badge();
    t0=clk_ticks();one[1]=0;
    style(&st,2,15,NO_COLOR,1,NO_COLOR);
    style(&big,5,15,4,0,NO_COLOR);big.rows=rows_gold;big.nrows=12;
    style(&sub,1,15,NO_COLOR,1,0);sub.letters=rainbow;sub.nletters=6;
    for(;;) {
        t=clk_ticks()-t0;
        /* Stages: 0..20 letters, 21 WE'VE GOT, 22..27 rays, 28 BANGERS,
           29 second stab, 30 lift, 31 subtitle, 32 done. */
        for(;;) {
            if(stage<=last_char && t>=(unsigned long)(4+stage*2)) {
                one[0]=splash_q[stage];
                fancy(32+stage*12,46,one,&st);
                if(one[0]!=' ')sfx_blip(blip_notes[stage%8]);
            } else if(stage==21 && t>=52) {
                fancy(center_x("WE'VE GOT",2),78,"WE'VE GOT",&st);
                sfx_note(2,45,2,2,12);sfx_note(3,NOISE_WHITE(2),4,1,4);
            } else if(stage>=22 && stage<=27 && t>=(unsigned long)(62+(stage-22))) {
                if(!reduced)starburst(stage-22,6);
                else if(stage==27){for(i=0;i<6;i++)starburst(i,6);}
            } else if(stage==28 && t>=70) {
                fancy(center_x("BANGERS",5),112,"BANGERS",&big);
                /* Rays may have crossed the upper lines: redraw them. */
                fancy(32,46,splash_q,&st);
                fancy(center_x("WE'VE GOT",2),78,"WE'VE GOT",&st);
                sfx_chord(72,67,48,1,2,10);sfx_note(3,NOISE_WHITE(0),0,2,32);
            } else if(stage==29 && t>=74) {
                sfx_chord(72,67,48,2,2,6);
            } else if(stage==30 && t>=80) {
                sfx_chord(77,72,53,1,3,40);
            } else if(stage==31 && t>=86) {
                fancy(center_x("RADIO SHACK RAVE",1),164,"RADIO SHACK RAVE",&sub);
                text(center_x("PRESS SPACE",1),180,"PRESS SPACE",8,0);
            } else if(stage==32 && t>=160) {
                return A_TITLE;
            } else break;
            stage++;
            if(auto_mode>=10 && stage==31)dump_frame("SPLASH.RAW");
        }
        sfx_step();
        if((action=show_keys(A_TITLE))!=0){sfx_stop();return action-100;}
        frame_end();
    }
}

/* Title: sunset, chrome logotype, scrolling perspective floor, marquee. */
#define HORIZON 104
#define FLOOR_BOT 152
#define MARQ_Y 191
static unsigned char floor_shown[FLOOR_BOT-HORIZON];
static unsigned marq_shown;
static char marquee[120];
static int marq_len;
static unsigned char twinkle_x[24],twinkle_y[24];
static unsigned twinkle_n;
static void floor_row(int y,unsigned c)
{
    int k,x;
    /* Far lines are dotted so the floor fades into the horizon. */
    if(c==5){span(0,y,SCR_W,0);for(x=y&1;x<SCR_W;x+=2)px(x,y,5);}
    else span(0,y,SCR_W,c);
    for(k=-12;k<=12;k++) {
        x=160+k*40*(y-HORIZON)/48;
        if(x>=0 && x<SCR_W)px(x,y,c?15:5);
    }
}
static void floor_frame(long tf)
{
    unsigned char want[FLOOR_BOT-HORIZON];int k,y;unsigned ph;
    memset(want,0,sizeof(want));
    ph=reduced?0:255-(unsigned)((tf>>2)&255);
    for(k=5;k<=12;k++) {
        y=HORIZON+(int)(250L*256/((long)k*256+ph));
        if(y>HORIZON && y<FLOOR_BOT)want[y-HORIZON]=(unsigned char)(k<8?13:5);
    }
    for(y=1;y<FLOOR_BOT-HORIZON;y++)if(want[y]!=floor_shown[y]) {
        floor_row(HORIZON+y,want[y]);floor_shown[y]=want[y];
    }
}
static unsigned char marq_byte(unsigned vx,unsigned row)
{
    unsigned c,i,col,bits,out=0,k;
    for(k=0;k<2;k++) {
        i=((vx+k)/6)%(unsigned)marq_len;col=(vx+k)%6;
        bits=col<5?font5[glyph(marquee[i])][row]&(16>>col):0;
        c=bits?(marquee[i]=='*'?14:11):0;
        out=(out<<4)|c;
    }
    return (unsigned char)out;
}
static void marquee_frame(long tf)
{
    unsigned target,row,x;unsigned char far *p;
    if(reduced)target=marq_shown==1?0:marq_shown;
    else target=(unsigned)((tf*2)>>8)&~1u;
    if(target==marq_shown && marq_shown!=1)return;
    if(marq_shown==1 || target-marq_shown>16) {
        for(row=0;row<7;row++) {
            p=video+row_ofs[MARQ_Y+row];
            for(x=0;x<160;x++)p[x]=marq_byte(target+x*2,row);
        }
        marq_shown=target;return;
    }
    while(marq_shown!=target) {
        marq_shown+=2;
        for(row=0;row<7;row++) {
            p=video+row_ofs[MARQ_Y+row];
            _fmemmove(p,p+1,159);
            p[159]=marq_byte(marq_shown+318,row);
        }
    }
}
static void sun_draw(void)
{
    int dy,w,y,i;long rx=58,ry=48;unsigned c;
    for(dy=1;dy<=48;dy++) {
        y=HORIZON-dy;
        for(w=0;(long)w*w*ry*ry+(long)dy*dy*rx*rx<=rx*rx*ry*ry;w++);
        if(dy<24 && (dy%8)<3-dy/8)continue;
        if(dy>=36)c=14;else if(dy>=24)c=12;else if(dy>=12)c=12;else c=13;
        span(160-w,y,w*2,c);
        if(dy>=24 && dy<36)for(i=160-w+(y&1);i<160+w;i+=2)px(i,y,14);
    }
}
static void title_draw(void)
{
    Style st;unsigned i;int x,y;
    clear_screen();
    for(i=0;i<60;i++)px((int)(rnd()%320),(int)(rnd()%100),(i&3)?8:7);
    sun_draw();
    style(&st,2,15,1,NO_COLOR,NO_COLOR);st.rows=rows_chrome;st.nrows=11;
    fancy(center_x("RADIO SHACK",2),6,"RADIO SHACK",&st);
    style(&st,6,15,0,5,NO_COLOR);st.rows=rows_gold;st.nrows=12;
    fancy(center_x("RAVE",6),28,"RAVE",&st);
    span(0,HORIZON,SCR_W,13);
    memset(floor_shown,255,sizeof(floor_shown));floor_frame(0);
    text(36,158,"YOU'VE GOT QUESTIONS? WE'VE GOT",7,0);
    text(36+32*6,158,"BANGERS.",14,0);
    text(center_x("Z X C ON THE BEAT    M CALM    ESC EXIT",1),180,
        "Z X C ON THE BEAT    M CALM    ESC EXIT",8,0);
    sprintf(marquee,"   NOW PLAYING: %s  *  TANDY 1000 3-VOICE SOUND  *  "
        "16 COLORS AT 320X200  *  HIT THE NOTES, HEAR THE MELODY  *",
        song_title[0]?song_title:"UNTITLED");
    marq_len=strlen(marquee);marq_shown=1;
    twinkle_n=0;
    for(i=0;i<200 && twinkle_n<24;i++) {
        x=(int)(rnd()%320);y=(int)(rnd()%96);
        if(!getpx(x,y) && !getpx(x+1,y) && !getpx(x-1,y)) {
            twinkle_x[twinkle_n]=(unsigned char)(x>>1);twinkle_y[twinkle_n]=(unsigned char)y;
            px(x&~1,y,8);twinkle_n++;
        }
    }
    calm_badge();
}
static void title_frame(long tf,unsigned long t)
{
    static const unsigned char tw[4]={8,7,15,7};
    static unsigned blink=255;
    unsigned i,b;
    floor_frame(tf);marquee_frame(tf);
    b=(reduced || (t/9)&1)?15:7;
    if(b!=blink || t<2){blink=b;text(center_x("PRESS SPACE TO RAVE",1),169,"PRESS SPACE TO RAVE",b,0);}
    if(!reduced)for(i=(unsigned)(t%3);i<twinkle_n;i+=3)
        px(twinkle_x[i]*2,twinkle_y[i],tw[(t/3+i)&3]);
}
static int title_run(void)
{
    unsigned long t0,t;int action;
    sfx_stop();title_draw();
    t0=clk_ticks();idle_since=t0;
    for(;;) {
        t=clk_ticks();
        title_frame((long)(clk_fine()-(t0<<8)),t-t0);
        sfx_step();
        if((action=show_keys(0))!=0) {
            if(action==A_PLAY+100)sfx_chord(72,76,79,3,1,8);
            return action-100;
        }
        if(t-idle_since>=(tour_mode?120UL:(unsigned long)ATTRACT_TICKS))return A_DEMO;
        frame_end();
    }
}
