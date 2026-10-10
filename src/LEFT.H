/* Left panel: a framed 96x100 window that cycles through effects, one new
 * scene every two bars, continuing across songs.
 *
 * Palette cycling. Logical colors 3, 4, 7 and 9 appear only inside this
 * window; the rest of the playfield never uses them. Each scene's image is
 * a precomputed map of cycle phases (tools/gen_fx.py -> FXDATA.H). Moving
 * it costs four Tandy palette register writes in vertical blank, whatever
 * the size of the effect: plasma, spiral starburst, tunnel, copper bars,
 * sky and grid floor all animate this way.
 *
 * CPU effects. A rotating wireframe cube, a starfield, a rotozoomer and a
 * waving flag draw real pixels. They run after the lanes and HUD and spend
 * a per-frame time credit, so a slow machine refreshes them less often and
 * skips the two heaviest scenes, while notes, input and audio keep their
 * priority. Judgment never reads anything drawn here.
 *
 * Calm mode and /FXOFF freeze the window: no cycling, no motion, no scene
 * changes.
 */
#include "FXDATA.H"
#define FX_X 4
#define FX_Y 47
#define FX_BW (FX_W/2)
#define FX_BYTES (FX_BW*FX_H)
#define FX_CREDIT 24
#define FX_CREDIT_MAX 72
#define FX_WIPE_ROWS 10
/* fx_wipe 0..FX_H-1 scans the old scene out to black, FX_H..FX_DONE-1
   scans the new one in; FX_DONE means idle. */
#define FX_DONE (2*FX_H)
#define FX_BEATS 8
static const unsigned char fx_cidx[4]={3,4,7,9};
static unsigned char fx_lut[256][2];
static unsigned char far *fxbuf;
static int fx_scene=-1,fx_wipe=FX_DONE,fx_ready;
static unsigned fx_base,fx_seen_mask,fx_switches,fx_lite;
static long fx_credit,fx_slot,fx_slot0;
static unsigned long fx_core_avg,fx_spent;

static void fx_init(void)
{
    unsigned b;
    for(b=0;b<256;b++) {
        fx_lut[b][0]=(unsigned char)((fx_cidx[b>>6]<<4)|fx_cidx[(b>>4)&3]);
        fx_lut[b][1]=(unsigned char)((fx_cidx[(b>>2)&3]<<4)|fx_cidx[b&3]);
    }
    fxbuf=(unsigned char far *)_fmalloc(FX_BYTES);
}
/* Decode one row of scene s into fxbuf and copy it to the screen. Rows are
   decoded top to bottom; the static runs are sorted by row, so a cursor
   walks them once per scene instead of rescanning the list every row. */
static const unsigned char far *fx_rp;
static void fx_row(unsigned s,unsigned y)
{
    static unsigned char row[FX_BW];
    const unsigned char far *m=fx_maps[s];
    const unsigned char far *r;unsigned x,i,n,a,b,c;
    if(m)for(x=0,m+=y*24;x<24;x++){row[2*x]=fx_lut[m[x]][0];row[2*x+1]=fx_lut[m[x]][1];}
    else memset(row,0,FX_BW);
    if(!y)fx_rp=fx_runs+fx_run_off[s];
    while(fx_rp[0]!=255 && fx_rp[0]<y)fx_rp+=4;
    for(r=fx_rp;r[0]==y;r+=4) {
        a=r[3]>>4;b=r[3]&15;
        for(i=r[1],n=r[2];n;n--,i++) {
            c=((i+y)&1)?b:a;
            row[i>>1]=(unsigned char)((i&1)?(row[i>>1]&0xf0)|c:(row[i>>1]&0x0f)|(c<<4));
        }
    }
    if(fxbuf)_fmemcpy(fxbuf+y*FX_BW,(void far *)row,FX_BW);
    _fmemcpy(video+row_ofs[FX_Y+y]+FX_X/2,(void far *)row,FX_BW);
}
static unsigned fx_bg(int x,int y)
{
    unsigned char v;
    if(!fxbuf)return 0;
    v=fxbuf[y*FX_BW+(x>>1)];
    return (x&1)?(v&15):(v>>4);
}
static void fx_pal(unsigned s,long t)
{
    unsigned k;
    for(k=0;k<4;k++)pal_set(fx_cidx[k],fx_grad[s][(unsigned)(t+2*k)&7]);
}
/* One step of the scene change curtain. */
static void fx_wipe_row(unsigned s)
{
    if(fx_wipe<FX_H)_fmemset(video+row_ofs[FX_Y+fx_wipe]+FX_X/2,0,FX_BW);
    else fx_row(s,(unsigned)(fx_wipe-FX_H));
    fx_wipe++;
}

/* Beat position in 1/256 beat, from the song's beat grid when present. */
static long fx_beat256(long nowf)
{
    BeatCur n;long tb,period,fr;
    if(nowf<0)return 0;
    if(!nsegs)return nowf*256L/2330L;
    for(;;) {
        n=pulse_cur;beat_next(&n);
        if(!beat_valid(&n) || beat_fine(&n)>nowf)break;
        pulse_cur=n;
    }
    tb=beat_fine(&pulse_cur);
    n=pulse_cur;beat_next(&n);
    if(beat_valid(&n))period=beat_fine(&n)-tb;
    else period=pulse_cur.k?(long)(segs[pulse_cur.seg].period>>8):2330L;
    if(period<64)period=64;
    fr=nowf<tb?0:(nowf-tb)*256L/period;
    if(fr>255)fr=255;
    return (long)beat_index(&pulse_cur)*256L+fr;
}

/* ---- sprites: restore from fxbuf, draw in window coordinates ---- */
static void fx_px(int x,int y,int c)
{
    if(x<0 || x>=FX_W || y<0 || y>=FX_H)return;
    px(FX_X+x,FX_Y+y,c<0?fx_bg(x,y):(unsigned)c);
}
static void fx_line(int x0,int y0,int x1,int y1,int c)
{
    int dx=x1>x0?x1-x0:x0-x1,dy=y1>y0?y1-y0:y0-y1;
    int sx=x0<x1?1:-1,sy=y0<y1?1:-1,e=dx-dy,e2;
    for(;;) {
        fx_px(x0,y0,c);
        if(x0==x1 && y0==y1)break;
        e2=2*e;
        if(e2>-dy){e-=dy;x0+=sx;}
        if(e2<dx){e+=dx;y0+=sy;}
    }
}
static const signed char cube_v[8][3]={
    {-1,-1,-1},{1,-1,-1},{1,1,-1},{-1,1,-1},{-1,-1,1},{1,-1,1},{1,1,1},{-1,1,1}};
static const unsigned char cube_e[12][2]={
    {0,1},{1,2},{2,3},{3,0},{4,5},{5,6},{6,7},{7,4},{0,4},{1,5},{2,6},{3,7}};
static int cube_xy[12][4],cube_on;
static void cube_erase(void)
{
    unsigned i;
    if(!cube_on)return;
    for(i=0;i<12;i++)fx_line(cube_xy[i][0],cube_xy[i][1],cube_xy[i][2],cube_xy[i][3],-1);
    cube_on=0;
}
static void cube_frame(long s256)
{
    int sx[8],sy[8],sz[8],x,y,z,x1,z1,y2,z2,ca,sa,cb,sb;unsigned i,a,b;int c;
    a=(unsigned)(s256>>3)&255;b=(unsigned)((s256*3)>>4)&255;
    ca=fx_sin[(a+64)&255];sa=fx_sin[a];cb=fx_sin[(b+64)&255];sb=fx_sin[b];
    for(i=0;i<8;i++) {
        x=cube_v[i][0]*56;y=cube_v[i][1]*56;z=cube_v[i][2]*56;
        x1=(x*ca+z*sa)/128;z1=(z*ca-x*sa)/128;
        y2=(y*cb-z1*sb)/128;z2=(y*sb+z1*cb)/128;
        sx[i]=FX_W/2+x1*92/(z2+250);sy[i]=FX_H/2+y2*92/(z2+250);sz[i]=z2;
    }
    cube_erase();
    for(i=0;i<12;i++) {
        z=sz[cube_e[i][0]]+sz[cube_e[i][1]];
        c=z<-40?15:(z<40?11:8);
        cube_xy[i][0]=sx[cube_e[i][0]];cube_xy[i][1]=sy[cube_e[i][0]];
        cube_xy[i][2]=sx[cube_e[i][1]];cube_xy[i][3]=sy[cube_e[i][1]];
        fx_line(cube_xy[i][0],cube_xy[i][1],cube_xy[i][2],cube_xy[i][3],c);
    }
    cube_on=1;
}
#define FX_STARS 20
static unsigned star_seed=0x2a5d;
static unsigned rnd(void){star_seed=star_seed*25173u+13849u;return star_seed>>4;}
static unsigned char st_a[FX_STARS],st_v[FX_STARS];
static long st_t0[FX_STARS];
static int st_xy[FX_STARS][6],st_on;
static void stars_erase(void)
{
    unsigned i;
    if(!st_on)return;
    for(i=0;i<FX_STARS;i++)if(st_xy[i][0]>=0) {
        fx_px(st_xy[i][0],st_xy[i][1],-1);fx_px(st_xy[i][2],st_xy[i][3],-1);
        fx_px(st_xy[i][4],st_xy[i][5],-1);
        st_xy[i][0]=-1;
    }
    st_on=0;
}
static void stars_frame(long nowf)
{
    unsigned i;int d,x,y,tx,ty,ca,sa;long age;
    stars_erase();
    for(i=0;i<FX_STARS;i++) {
        age=nowf-st_t0[i];
        d=age<0 || age>20000L?999:8+(int)((age*st_v[i])>>11);
        ca=fx_sin[(st_a[i]+64)&255];sa=fx_sin[st_a[i]];
        x=FX_W/2+ca*d/127;y=FX_H/2+sa*d/127;
        if(x<1 || x>=FX_W-1 || y<1 || y>=FX_H-1) {
            st_a[i]=(unsigned char)rnd();st_v[i]=(unsigned char)(16+(rnd()&63));
            st_t0[i]=nowf;st_xy[i][0]=-1;continue;
        }
        /* Three-pixel streak, lengthening as it nears the edge. */
        tx=FX_W/2+ca*(d-2-d/8)/127;ty=FX_H/2+sa*(d-2-d/8)/127;
        st_xy[i][4]=FX_W/2+ca*(d-4-d/4)/127;st_xy[i][5]=FX_H/2+sa*(d-4-d/4)/127;
        fx_px(st_xy[i][4],st_xy[i][5],12);fx_px(tx,ty,14);fx_px(x,y,15);
        st_xy[i][0]=x;st_xy[i][1]=y;st_xy[i][2]=tx;st_xy[i][3]=ty;
    }
    st_on=1;
}
static void stars_reset(long nowf)
{
    unsigned i;
    for(i=0;i<FX_STARS;i++) {
        st_a[i]=(unsigned char)rnd();st_v[i]=(unsigned char)(16+(rnd()&63));
        st_t0[i]=nowf-(long)(rnd()&4095);st_xy[i][0]=-1;
    }
    st_on=0;
}
/* Rotozoom: 4x2-pixel cells (two whole bytes on two rows), drawn a band of
   rows at a time with parameters latched for the whole pass. */
static int rz_row=0;
static unsigned rz_u0,rz_v0;
static int rz_cdu,rz_cdv,rz_rdu,rz_rdv;
static unsigned char rz_tex[1024];
static void rz_init(void)
{
    unsigned i,c;
    for(i=0;i<1024;i++) {
        c=fx_tex[i];
        if(c>=16)c=fx_cidx[c-16];
        rz_tex[i]=(unsigned char)(c*17);
    }
}
static void rz_start(long s256)
{
    unsigned a=(unsigned)(s256>>4)&255,z=(unsigned)(s256>>3)&255;
    int k=170+(fx_sin[z]*80)/127,dux,dvx;
    dux=k*fx_sin[(a+64)&255]/128;dvx=k*fx_sin[a]/128;
    rz_cdu=dux*4;rz_cdv=dvx*4;rz_rdu=-dvx*2;rz_rdv=dux*2;
    /* Window centre maps to the texture centre, drifting slowly. */
    rz_u0=(unsigned)(16*256+(unsigned)(s256*3))-(unsigned)(rz_cdu*12)-(unsigned)(rz_rdu*25);
    rz_v0=(unsigned)(16*256+(unsigned)(s256*2))-(unsigned)(rz_cdv*12)-(unsigned)(rz_rdv*25);
    rz_row=0;
}
static void rz_rows(int n)
{
    unsigned u,v,cx,t;unsigned char far *p;unsigned char far *q;
    for(;n>0 && rz_row<FX_H/2;n--,rz_row++) {
        u=rz_u0+(unsigned)(rz_rdu*rz_row);v=rz_v0+(unsigned)(rz_rdv*rz_row);
        p=video+row_ofs[FX_Y+rz_row*2]+FX_X/2;q=video+row_ofs[FX_Y+rz_row*2+1]+FX_X/2;
        for(cx=0;cx<FX_W/4;cx++) {
            t=rz_tex[((v>>3)&0x3e0)|((u>>8)&31)];
            p[0]=p[1]=q[0]=q[1]=(unsigned char)t;p+=2;q+=2;
            u+=rz_cdu;v+=rz_cdv;
        }
    }
}
/* Waving flag: 28 two-pixel columns hung on the pole, each shifted by a
   travelling sine that grows toward the free end; folds facing away are
   shaded. Uncovered sky is restored from fxbuf bytes. */
#define FLAG_X 14
#define FLAG_Y 30
#define FLAG_C 28
#define FLAG_H 36
static signed char flag_off[FLAG_C];
static int flag_on;
static void flag_frame(long s256)
{
    int off[FLAG_C+1],c,r,y,o,lo,hi,slope;unsigned ph=(unsigned)(s256>>1);
    unsigned char lit,dark,v;unsigned char far *p;
    for(c=0;c<=FLAG_C;c++)off[c]=fx_sin[(unsigned)(c*14-ph)&255]*c*7/(127*FLAG_C);
    for(c=0;c<FLAG_C;c++) {
        o=off[c];slope=off[c+1]-o;
        if(flag_on && o!=flag_off[c]) {
            if(o>flag_off[c]){lo=flag_off[c];hi=o;}
            else {lo=o+FLAG_H;hi=flag_off[c]+FLAG_H;}
            for(y=FLAG_Y+lo;y<FLAG_Y+hi;y++)
                video[row_ofs[FX_Y+y]+FX_X/2+FLAG_X/2+c]=fxbuf?fxbuf[y*FX_BW+FLAG_X/2+c]:0;
        }
        for(r=0;r<FLAG_H;r++) {
            if((((c>>2)+(r/6))&1)){lit=13;dark=5;}else{lit=14;dark=6;}
            v=(unsigned char)((slope>0?dark:lit)*17);
            if(r==0 || r==FLAG_H-1)v=(unsigned char)(slope>0?0x88:0xff);
            p=video+row_ofs[FX_Y+FLAG_Y+o+r]+FX_X/2+FLAG_X/2+c;*p=v;
        }
        flag_off[c]=(signed char)o;
    }
    flag_on=1;
}

/* DJ Alfredo: the classic white stick figure behind the decks, posed every
   half beat with a head bob on each beat. Redrawn only when the pose
   changes; the booth hides him below the waist. */
#define AL_X 48
#define AL_Y 50
#define AL_BOOTH 70
#define AL_C0 13
#define AL_C1 36
#define AL_R0 24
typedef struct { signed char ex,ey,hx,hy; } Arm;
static const Arm al_pose[6][2]={
    {{-10,8,-17,16},{10,8,17,16}},    /* both hands on the decks */
    {{-10,8,-17,16},{8,-6,11,-18}},   /* fist pump */
    {{-10,-4,-12,-16},{10,-4,12,-16}},/* raise the roof */
    {{-9,2,-6,-7},{10,8,17,16}},      /* hand on the headphones */
    {{-10,8,-17,16},{9,-4,19,-11}},   /* point at the crowd */
    {{-9,-6,-15,-14},{10,8,17,16}}};  /* wave */
static const unsigned char al_seq[16]={0,1,0,1,0,3,0,3,2,2,4,4,5,0,5,0};
static const signed char al_head[8][2]={{5,0},{5,1},{5,2},{4,3},{3,4},{2,5},{1,5},{0,5}};
static int al_shown=-1;
static void al_line(int x0,int y0,int x1,int y1,int c)
{
    if(y0>=AL_BOOTH)y0=AL_BOOTH-1;
    if(y1>=AL_BOOTH)y1=AL_BOOTH-1;
    fx_line(x0,y0,x1,y1,c);
}
static void al_frame(long s256)
{
    int pose=al_seq[(unsigned)(s256>>7)&15],bob=(s256&255)<80?2:0,key=pose*4+bob;
    int nx=AL_X,ny=AL_Y+bob,hx=nx,hy=ny-7,i,k,y;const Arm *a;
    if(key==al_shown)return;
    /* Erase by restoring his whole box from the decoded scene. */
    if(fxbuf && al_shown>=0)for(y=AL_R0;y<AL_BOOTH;y++)
        _fmemcpy(video+row_ofs[FX_Y+y]+FX_X/2+AL_C0,fxbuf+y*FX_BW+AL_C0,AL_C1-AL_C0);
    al_line(nx,ny,nx,AL_BOOTH,15);
    for(i=0;i<2;i++) {
        a=&al_pose[pose][i];
        al_line(nx,ny+1,nx+a->ex,ny+a->ey,15);
        al_line(nx+a->ex,ny+a->ey,nx+a->hx,ny+a->hy,15);
    }
    for(k=0;k<8;k++) {
        fx_px(hx+al_head[k][0],hy+al_head[k][1],15);fx_px(hx-al_head[k][0],hy+al_head[k][1],15);
        fx_px(hx+al_head[k][0],hy-al_head[k][1],15);fx_px(hx-al_head[k][0],hy-al_head[k][1],15);
    }
    /* Headphones. */
    fx_line(hx-5,hy-4,hx-3,hy-6,13);fx_line(hx-3,hy-6,hx+3,hy-6,13);fx_line(hx+3,hy-6,hx+5,hy-4,13);
    for(y=hy-1;y<=hy+2;y++){fx_px(hx-6,y,13);fx_px(hx-7,y,13);fx_px(hx+6,y,13);fx_px(hx+7,y,13);}
    al_shown=key;
}
static int fx_still_done;
static void fx_sprites_off(void)
{
    cube_on=0;st_on=0;flag_on=0;rz_row=FX_H/2;al_shown=-1;fx_still_done=0;
}
/* Ready period and calm mode: draw the scene's figure once, standing still. */
static void fx_still(unsigned s)
{
    if(fx_still_done)return;
    fx_still_done=1;
    switch(fx_type[s]) {
    case FXK_CUBE:cube_frame(0);break;
    case FXK_FLAG:flag_frame(0);break;
    case FXK_ALFREDO:al_frame(0);break;
    case FXK_ROTOZOOM:rz_start(0);rz_rows(FX_H/2);break;
    }
}
static void fx_frame_box(void)
{
    bevel(FX_X-2,FX_Y-2,FX_W+4,FX_H+4,8,1,NO_COLOR);
}
/* Start of a song or retry: draw the current scene at once. */
static void fx_reset(long nowf)
{
    unsigned y;
    if(fx_scene<0)fx_scene=0;
    fx_slot0=-1;fx_credit=0;
    fx_frame_box();
    for(y=0;y<FX_H;y++)fx_row((unsigned)fx_scene,y);
    fx_wipe=FX_DONE;fx_sprites_off();stars_reset(nowf);
    fx_seen_mask|=1u<<fx_scene;
    fx_pal((unsigned)fx_scene,0);
    fx_ready=1;
}
static int fx_heavy(unsigned s){return fx_type[s]==FXK_ROTOZOOM || fx_type[s]==FXK_FLAG;}
static void fx_begin(unsigned s)
{
    fx_scene=(int)s;fx_wipe=0;fx_sprites_off();fx_switches++;
    fx_seen_mask|=1u<<s;
}
/* Called once per playfield frame after lanes and HUD; core is the fine
   time those took, used to decide how much the window may spend. */
static void fx_frame(long nowf,unsigned core)
{
    long s256,slot;unsigned target,s,n;unsigned long t0,used;
    if(!fx_ready)return;
    t0=clk_fine();
    /* Running average of the playfield's own cost; slow machines skip the
       heavy scenes (with hysteresis). */
    fx_core_avg=(fx_core_avg*15+(unsigned long)core*16)/16;
    if(fx_core_avg/16>150)fx_lite=1;
    else if(fx_core_avg/16<110)fx_lite=0;
    if(reduced || no_fx) {
        /* Frozen: finish a wipe in one go and hold a still palette. */
        if(fx_wipe<FX_DONE) {
            while(fx_wipe<FX_DONE)fx_wipe_row((unsigned)fx_scene);
            fx_pal((unsigned)fx_scene,0);
        }
        fx_still((unsigned)fx_scene);
        return;
    }
    s256=fx_beat256(nowf);
    fx_credit+=FX_CREDIT;
    if(fx_credit>FX_CREDIT_MAX)fx_credit=FX_CREDIT_MAX;
    /* A new scene every FX_BEATS beats; the rotation continues across songs. */
    slot=nowf<0?-1:s256/(256L*FX_BEATS);
    if(fx_slot0<0 && slot>=0){fx_slot0=slot;fx_slot=slot;}
    if(slot>=0 && slot!=fx_slot && fx_wipe>=FX_DONE) {
        fx_slot=slot;fx_base++;
        target=fx_base%FX_SCENES;
        for(n=0;n<FX_SCENES && fx_lite && fx_heavy(target);n++)target=(target+1)%FX_SCENES;
        if(target!=(unsigned)fx_scene)fx_begin(target);
    }
    s=(unsigned)fx_scene;
    if(fx_wipe<FX_DONE) {
        /* The new palette takes over as the new scene starts scanning in. */
        if(fx_wipe>=FX_H)fx_pal(s,(s256*fx_speed[s])>>8);
        /* At least one row a frame, more while the credit lasts. */
        for(n=0;n<FX_WIPE_ROWS && fx_wipe<FX_DONE;n++) {
            if(n && !clk_virtual && (long)(clk_fine()-t0)>=fx_credit)break;
            fx_wipe_row(s);
        }
        if(fx_wipe<FX_DONE)span(FX_X,FX_Y+(fx_wipe<FX_H?fx_wipe:fx_wipe-FX_H),FX_W,fx_wipe<FX_H?8:15);
        else stars_reset(nowf);
        used=clk_fine()-t0;fx_spent+=used;fx_credit-=(long)used;
        return;
    }
    if(nowf<0){fx_still(s);return;}
    fx_pal(s,(s256*fx_speed[s])>>8);
    fx_still_done=1;
    if(fx_credit<=0)return;
    switch(fx_type[s]) {
    case FXK_CUBE:cube_frame(s256);break;
    case FXK_STARS:stars_frame(nowf);break;
    case FXK_FLAG:flag_frame(s256);break;
    case FXK_ALFREDO:al_frame(s256);break;
    case FXK_ROTOZOOM:
        if(rz_row>=FX_H/2)rz_start(s256);
        if(clk_virtual)rz_rows(FX_H/2);
        else while(rz_row<FX_H/2 && (long)(clk_fine()-t0)<fx_credit)rz_rows(5);
        break;
    }
    used=clk_fine()-t0;fx_spent+=used;fx_credit-=(long)used;
}
/* Results card: it covers part of the window, so only the palette moves. */
static void fx_palette_only(long nowf)
{
    if(!fx_ready || reduced || no_fx || fx_scene<0 || fx_wipe<FX_DONE || nowf<0)return;
    fx_pal((unsigned)fx_scene,(fx_beat256(nowf)*fx_speed[fx_scene])>>8);
}
