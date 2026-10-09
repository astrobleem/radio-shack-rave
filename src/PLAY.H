/* Playfield: lanes, key caps, tunnel, stars, HUD, PSG meters, judgment words
 * and the results card. Everything redraws only what changed.
 *
 * Lanes are a row compositor. Each lane interior row (14 bytes) is described
 * by a one-byte code: background for that row, a beat or bar line, a row of a
 * gem, a row of a hit burst. Each frame builds the wanted codes, compares
 * them with what is on screen and rewrites only rows that differ. A gem
 * moving one pixel changes about three rows, not the whole lane.
 */
#define LANE_TOP 17
#define LANE_BOT 167
#define LANE_ROWS (LANE_BOT-LANE_TOP+1)
#define HIT_Y 157
#define GEM_H 5
#define GEM_B 12
#define SCROLL 3
#define LANE_IW 14
#define CAP_Y 171
#define RC_BG 0
#define RC_BEAT 1
#define RC_BAR 2
#define RC_GEM 3
#define RC_DEAD 8
#define RC_BURST 16
#define RC_PRESS 0x80
#define BURST_FRAMES 6
#define BURST_TOP (HIT_Y-12)
#define PARTS 12
#define TUN_X 52
#define TUN_Y 96
#define TUN_R 46
#define STARS 8
/* Pixels of travel above and below the hit line, in 1/256 tick units. */
#define LOOK_AHEAD ((long)(HIT_Y-LANE_TOP+GEM_H)*256/SCROLL+256)
#define LOOK_BEHIND ((long)(LANE_BOT-HIT_Y+GEM_H)*256/SCROLL+256)

static const int lane_x[3]={104,140,176};
static const unsigned char lane_fg[3]={10,13,14};
static const unsigned char lane_dk[3]={2,5,6};
static unsigned char rows_shown[3][LANE_ROWS],rows_want[3][LANE_ROWS];
static unsigned char bg_row[LANE_ROWS];
static unsigned char gem_val[3][GEM_H][GEM_B];
static unsigned char dead_val[GEM_H][GEM_B];
static signed char part_x[BURST_FRAMES][PARTS],part_y[BURST_FRAMES][PARTS];
static int burst_t0[3],burst_seen[3];
static unsigned vis_from;
static unsigned rows_written;

typedef struct { unsigned seg,k;unsigned long t; } BeatCur;
static BeatCur grid_cur,pulse_cur;
static void beat_reset(BeatCur *c)
{
    c->seg=0;c->k=0;c->t=nsegs?segs[0].start:0;
}
static int beat_valid(const BeatCur *c){return c->seg<nsegs;}
static unsigned beat_index(const BeatCur *c){return segs[c->seg].first+c->k;}
static void beat_next(BeatCur *c)
{
    if(c->seg>=nsegs)return;
    if(++c->k<segs[c->seg].count){c->t+=segs[c->seg].period;return;}
    c->seg++;c->k=0;
    if(c->seg<nsegs)c->t=segs[c->seg].start;
}
static long beat_fine(const BeatCur *c){return (long)(c->t>>8);}

/* Far cache (inside LINK /CP headroom): the static tunnel, for erasing
   pulse rings by byte copy, and pre-rendered judgment words. */
#define CACHE_BYTES 9216
#define TUN_B0 ((TUN_X-TUN_R)>>1)
#define TUN_BW 47
#define TUN_Y0 (TUN_Y-TUN_R)
#define TUN_ROWS (TUN_R*2+1)
typedef struct { unsigned off,w,h,stride; } Sprite;
static unsigned char far *cache;
static unsigned cache_used;
static Sprite word_spr[4];
static int sprite_make(Sprite *sp,const char *s,const Style *st)
{
    unsigned n;
    sp->h=0;
    if(!cache || !fancy_render(0,0,s,st))return 0;
    n=tb_stride*tb_h;
    if(cache_used+n>CACHE_BYTES)return 0;
    _fmemcpy(cache+cache_used,(void far *)tbuf,n);
    sp->off=cache_used;sp->w=tb_w;sp->h=tb_h;sp->stride=tb_stride;
    cache_used+=n;return 1;
}
static void sprite_draw(const Sprite *sp,int x,int y)
{
    unsigned r;
    x&=~1;
    for(r=0;r<sp->h;r++)
        _fmemcpy(video+row_ofs[y+r]+(x>>1),cache+sp->off+r*sp->stride,sp->stride);
    vram_bytes+=(unsigned long)sp->h*sp->stride;
}
static void set_nib(unsigned char *row,unsigned x,unsigned c)
{
    row[x>>1]=(unsigned char)((x&1)?(row[x>>1]&0xf0)|c:(row[x>>1]&0x0f)|(c<<4));
}
static unsigned char dither(unsigned a,unsigned b){return (unsigned char)((a<<4)|b);}
static unsigned char bg_band(int y,unsigned l,int pressed)
{
    int d=y-HIT_Y;
    if(d<0)d=-d;
    if(pressed) {
        if(!d)return 0xff;
        if(d==1)return (unsigned char)(lane_fg[l]*17);
        return (y&1)?dither(lane_fg[l],0):dither(0,lane_fg[l]);
    }
    if(!d)return 0xff;
    if(d==1)return 0xbb;
    return (y&1)?0x30:0x03;
}
static void lanes_init(void)
{
    int r,y,f,x,k,i,s;unsigned l,c;
    static const signed char dir[PARTS][2]={
        {8,2},{7,4},{6,6},{4,7},{2,8},{0,8},{-2,8},{-4,7},{-6,6},{-7,4},{-8,2},{1,5}};
    for(r=0;r<LANE_ROWS;r++) {
        y=LANE_TOP+r;
        if(y>=HIT_Y-2 && y<=HIT_Y+2)bg_row[r]=bg_band(y,0,0);
        else if(y>HIT_Y+2)bg_row[r]=(y&1)?0x10:0x01;
        else {
            f=(y-LANE_TOP)*100/(HIT_Y-2-LANE_TOP);
            if(f>=78)bg_row[r]=(y&1)?0x10:0x01;
            else if(f>=55)bg_row[r]=(y&1)?0:((y&2)?0x10:0x01);
            else if(f>=30)bg_row[r]=(y&3)?0:((y&4)?0x10:0x01);
            else bg_row[r]=0;
        }
    }
    for(r=0;r<GEM_H;r++)for(x=0;x<GEM_B*2;x++) {
        k=(r==0 || r==GEM_H-1) && (x==0 || x==GEM_B*2-1);
        for(l=0;l<4;l++) {
            /* l==3 builds the grey "missed" gem; corners are dark. */
            if(k)c=0;
            else if(r==0)c=l<3?15:7;
            else if(r==GEM_H-1)c=l<3?lane_dk[l]:0;
            else if(x==0)c=l<3?15:7;
            else if(x==GEM_B*2-1)c=l<3?lane_dk[l]:0;
            else if(r==1 && x>=3 && x<=6)c=l<3?15:7;
            else c=l<3?lane_fg[l]:8;
            if(l<3)set_nib(gem_val[l][r],x,c);else set_nib(dead_val[r],x,c);
        }
    }
    for(f=0;f<BURST_FRAMES;f++)for(i=0;i<PARTS;i++) {
        s=2+i%3;
        x=14+dir[i][0]*(f+1)*s/8;
        y=12-dir[i][1]*(f+1)*s/8+f*f/2;
        if(x<0 || x>27 || y<0 || y>15)x=y=-1;
        part_x[f][i]=(signed char)x;part_y[f][i]=(signed char)y;
    }
}
static unsigned part_color(unsigned l,unsigned f)
{
    static const unsigned char ramp[BURST_FRAMES]={15,15,14,0,0,8};
    if(f==3)return lane_fg[l];
    if(f==4)return lane_dk[l];
    return ramp[f];
}
/* One lane row. Gem rows are fixed 12-byte images with a background byte
   either side; plain rows are a single repeated byte; only burst rows are
   composed pixel by pixel. */
static void lane_row(unsigned l,unsigned r,unsigned code)
{
    unsigned char rb[LANE_IW];unsigned y=LANE_TOP+r,k,f,i,base;int d;
    unsigned char far *v=video+row_ofs[y]+((lane_x[l]+2)>>1);
    rows_written++;
    if(code>=RC_GEM && code<RC_DEAD+GEM_H) {
        v[0]=v[LANE_IW-1]=bg_row[r];
        k=code>=RC_DEAD?code-RC_DEAD:code-RC_GEM;
        _fmemcpy(v+1,(void far *)(code>=RC_DEAD?dead_val[k]:gem_val[l][k]),GEM_B);
        return;
    }
    base=(code&RC_PRESS)?bg_band((int)y,l,1):bg_row[r];
    code&=0x7f;
    if(code<RC_BURST) {
        if(code==RC_BEAT)base=0x80;
        else if(code==RC_BAR)base=0x78;
        _fmemset(v,(int)base,LANE_IW);
        return;
    }
    memset(rb,(int)base,LANE_IW);
    f=(code-RC_BURST)>>4;k=(code-RC_BURST)&15;
    d=(int)y-HIT_Y;if(d<0)d=-d;
    if(f==0 && d<=2)memset(rb,d<=1?0xff:lane_fg[l]*17,LANE_IW);
    else if(f==1 && d<=1)memset(rb,d?lane_fg[l]*17:0xff,LANE_IW);
    if(!reduced)for(i=0;i<PARTS;i++)if(part_y[f][i]==(signed char)k)
        set_nib(rb,(unsigned)part_x[f][i],part_color(l,f));
    _fmemcpy(v,(void far *)rb,LANE_IW);
}
static int to_px(long d)
{
    /* Floor of d*SCROLL/256 for either sign. */
    if(d>=0)return (int)((d*SCROLL)>>8);
    return -(int)(((-d)*SCROLL+255)>>8);
}
static unsigned char key_lit[3];
/* Rows each lane stamped this frame and last frame. Only those rows can
   differ from the screen, so only those are compared. */
#define STAMPS 40
static unsigned char st_row[2][3][STAMPS],st_len[2][3][STAMPS],st_n[2][3];
static unsigned st_cur;
static int lanes_full;
static void stamp(unsigned l,int r,int n)
{
    unsigned k=st_n[st_cur][l];
    if(r<0){n+=r;r=0;}
    if(r+n>LANE_ROWS)n=LANE_ROWS-r;
    if(n<=0)return;
    if(k>=STAMPS){lanes_full=1;return;}
    st_row[st_cur][l][k]=(unsigned char)r;st_len[st_cur][l][k]=(unsigned char)n;
    st_n[st_cur][l]=(unsigned char)(k+1);
}
static void lanes_diff(unsigned l,unsigned r,unsigned n)
{
    unsigned char *w=rows_want[l]+r,*s=rows_shown[l]+r;
    for(;n;n--,r++,w++,s++)if(*w!=*s){lane_row(l,r,*w);*s=*w;}
}
static void lanes_frame(long nowf,int now)
{
    unsigned l,r,i,f,k,p,now_px,lim;int y,top;BeatCur c;unsigned code;
    st_cur^=1;
    for(l=0;l<3;l++){memset(rows_want[l],RC_BG,LANE_ROWS);st_n[st_cur][l]=0;}
    /* Beat grid. */
    while(beat_valid(&grid_cur) && beat_fine(&grid_cur)<nowf-LOOK_BEHIND)
        beat_next(&grid_cur);
    for(c=grid_cur;beat_valid(&c) && beat_fine(&c)<=nowf+LOOK_AHEAD;beat_next(&c)) {
        y=HIT_Y-to_px(beat_fine(&c)-nowf);
        if(y<LANE_TOP || y>LANE_BOT || (y>=HIT_Y-2 && y<=HIT_Y+2))continue;
        code=(beat_index(&c)&3)?RC_BEAT:RC_BAR;
        for(l=0;l<3;l++){rows_want[l][y-LANE_TOP]=(unsigned char)code;stamp(l,y-LANE_TOP,1);}
    }
    /* Hit bursts and pressed keys. */
    for(l=0;l<3;l++) {
        if(flash_until[l]!=burst_seen[l]) {
            burst_seen[l]=flash_until[l];
            if(flash_kind[l]==1 && !no_fx)burst_t0[l]=now;
        }
        if(burst_t0[l]!=-32767 && now>=burst_t0[l] && now-burst_t0[l]<BURST_FRAMES)
        {
            for(f=(unsigned)(now-burst_t0[l]),r=0;r<16;r++)
                rows_want[l][BURST_TOP+r-LANE_TOP]=(unsigned char)(RC_BURST+f*16+r);
            stamp(l,BURST_TOP-LANE_TOP,16);
        }
        if(key_lit[l])stamp(l,HIT_Y-2-LANE_TOP,5);
        if(key_lit[l])for(y=HIT_Y-2;y<=HIT_Y+2;y++) {
            code=rows_want[l][y-LANE_TOP];
            if(code==RC_BG || code>=RC_BURST)rows_want[l][y-LANE_TOP]=(unsigned char)(code|RC_PRESS);
        }
    }
    /* Gems, in 16-bit pixel space: a note sits tick*SCROLL pixels down the
       song, the screen at now_px (modular arithmetic keeps the ready period
       right). Hit and automatic notes are not drawn; misses fall on grey. */
    {
        long np=nowf>=0?(nowf*SCROLL)>>8:-(((-nowf)*SCROLL+255)>>8);
        now_px=(unsigned)np;lim=LANE_BOT-HIT_Y+GEM_H;
        while(vis_from<taps && (long)chart[vis_from].tick*SCROLL<np-(long)lim)vis_from++;
    }
    for(i=vis_from;i<taps;i++) {
        if((int)chart[i].tick-now>60)break;
        top=(int)(chart[i].tick*SCROLL-now_px);
        if(top>HIT_Y-LANE_TOP+GEM_H)break;
        if(chart[i].reserved || judged[i]==1 || judged[i]==3)continue;
        top=HIT_Y-GEM_H/2-top;
        l=chart[i].lane;stamp(l,top-LANE_TOP,GEM_H);
        for(r=0;r<GEM_H;r++) {
            y=top+(int)r;
            if(y>=LANE_TOP && y<=LANE_BOT)
                rows_want[l][y-LANE_TOP]=(unsigned char)((judged[i]==2?RC_DEAD:RC_GEM)+(r==3?2:r));
        }
    }
    for(l=0;l<3;l++) {
        if(lanes_full){lanes_diff(l,0,LANE_ROWS);continue;}
        for(p=0;p<2;p++)for(k=0;k<st_n[st_cur^p][l];k++)
            lanes_diff(l,st_row[st_cur^p][l][k],st_len[st_cur^p][l][k]);
    }
    lanes_full=0;
}

/* Key caps under the lanes: raised when up, lit and sunk when held. */
static unsigned char cap_shown[3];
static void cap_draw(unsigned l,unsigned down)
{
    int x=lane_x[l]+4;char s[2];
    s[0]="ZXC"[l];s[1]=0;
    fill(x,CAP_Y,24,14,0);
    if(down) {
        bevel(x,CAP_Y+1,24,13,15,lane_dk[l],lane_fg[l]);
        text(x+10,CAP_Y+4,s,0,lane_fg[l]);
    } else {
        bevel(x,CAP_Y,24,13,7,0,8);
        text(x+10,CAP_Y+3,s,lane_fg[l],8);
    }
}
static Sprite cap_spr[3][2];
static void sprite_grab(Sprite *sp,int x,int y,unsigned w,unsigned h)
{
    unsigned r,n=(w>>1)*h;
    sp->h=0;
    if(!cache || cache_used+n>CACHE_BYTES)return;
    for(r=0;r<h;r++)_fmemcpy(cache+cache_used+r*(w>>1),video+row_ofs[y+r]+(x>>1),w>>1);
    sp->off=cache_used;sp->w=w;sp->h=h;sp->stride=w>>1;cache_used+=n;
}
static void caps_init(void)
{
    unsigned l,d;
    for(l=0;l<3;l++)for(d=0;d<2;d++) {
        cap_draw(l,d);sprite_grab(&cap_spr[l][d],lane_x[l]+4,CAP_Y,24,14);
    }
}
static void caps_frame(void)
{
    unsigned l;
    for(l=0;l<3;l++)if(cap_shown[l]!=key_lit[l]) {
        if(cap_spr[l][key_lit[l]].h)sprite_draw(&cap_spr[l][key_lit[l]],lane_x[l]+4,CAP_Y);
        else cap_draw(l,key_lit[l]);
        cap_shown[l]=key_lit[l];
    }
}

/* Tunnel: static dithered diamonds, beat pulses and star streaks on top.
   Anything erased is restored from tunnel_bg(), so no saved pixels. */
static unsigned tunnel_bg(int x,int y)
{
    int d=(x>TUN_X?x-TUN_X:TUN_X-x)+(y>TUN_Y?y-TUN_Y:TUN_Y-y),p=(x+y)&1;
    if(d>TUN_R)return 0;
    if(d==46 || d==30 || d==14)return 11;
    if(d<=7)return p?15:11;
    if(d<=14)return p?11:3;
    if(d<=22)return p?3:1;
    if(d<=30)return p?1:0;
    if(d<=38)return p?9:1;
    return p?1:0;
}
static void tunnel_draw(void)
{
    int y,x,w;
    for(y=TUN_Y-TUN_R;y<=TUN_Y+TUN_R;y++) {
        w=TUN_R-(y>TUN_Y?y-TUN_Y:TUN_Y-y);
        for(x=TUN_X-w;x<=TUN_X+w;x++)px(x,y,tunnel_bg(x,y));
    }
    if(cache)for(y=0;y<TUN_ROWS;y++)
        _fmemcpy(cache+(unsigned)y*TUN_BW,video+row_ofs[TUN_Y0+y]+TUN_B0,TUN_BW);
}
/* Diamond |dx|+|dy|=r, two points per row. Erasing copies the two bytes
   back from the cached tunnel; rings sit four pixels apart, so a restored
   neighbour pixel never belongs to another ring. */
static void ring(int r,int color)
{
    int dy,k,y;unsigned a,b;unsigned char far *p;const unsigned char far *q;
    unsigned char hi=(unsigned char)(color<<4),lo=(unsigned char)color;
    if(r<2)return;
    for(dy=-r;dy<=r;dy+=2) {
        k=r-(dy<0?-dy:dy);y=TUN_Y+dy;
        a=(unsigned)(TUN_X-k)>>1;b=(unsigned)(TUN_X+k)>>1;
        p=video+row_ofs[y];
        if(color<0) {
            if(cache){q=cache+(unsigned)(y-TUN_Y0)*TUN_BW-TUN_B0;p[a]=q[a];p[b]=q[b];}
            else{px(TUN_X-k,y,tunnel_bg(TUN_X-k,y));px(TUN_X+k,y,tunnel_bg(TUN_X+k,y));}
            continue;
        }
        /* TUN_X is even: TUN_X-k and TUN_X+k share parity. */
        if(k&1){p[a]=(unsigned char)((p[a]&0xf0)|lo);p[b]=(unsigned char)((p[b]&0xf0)|lo);}
        else {p[a]=(unsigned char)((p[a]&0x0f)|hi);p[b]=(unsigned char)((p[b]&0x0f)|hi);}
    }
}
static int ring_shown[2],ring_col[2];
/* One bright ring per beat (white on bar lines) and a dim one on the
   off-beat, each growing from the centre to the rim over one beat. */
static void pulses_frame(long nowf)
{
    long tb,tn,period;int r[2],col[2];unsigned i,bar=0;BeatCur n;
    r[0]=r[1]=0;col[0]=col[1]=0;
    if(!reduced && !no_fx && nowf>=0) {
        if(nsegs) {
            for(;;) {
                n=pulse_cur;beat_next(&n);
                if(!beat_valid(&n) || beat_fine(&n)>nowf)break;
                pulse_cur=n;
            }
            tb=beat_fine(&pulse_cur);bar=!(beat_index(&pulse_cur)&3);
            n=pulse_cur;beat_next(&n);
            if(beat_valid(&n))period=beat_fine(&n)-tb;
            else period=pulse_cur.k?(long)(segs[pulse_cur.seg].period>>8):2330L;
        } else {
            period=8*256L;tb=nowf-nowf%period;bar=!((tb/period)&3);
        }
        if(period<256)period=256;
        tn=nowf-tb;
        if(tn>=0 && tn<period) {
            r[0]=4+(int)(tn*7/period)*6;
            col[0]=bar?15:11;
        }
    }
    {
        int erased[2],changed[2];
        for(i=0;i<2;i++) {
            changed[i]=r[i]!=ring_shown[i] || col[i]!=ring_col[i];
            erased[i]=changed[i]?ring_shown[i]:-1;
            if(changed[i])ring(ring_shown[i],-1);
        }
        for(i=0;i<2;i++) {
            if(changed[i] || r[i]==erased[0] || r[i]==erased[1])
                if(r[i])ring(r[i],col[i]);
            ring_shown[i]=r[i];ring_col[i]=col[i];
        }
    }
}
static const signed char star_dir[16][2]={
    {64,0},{59,24},{45,45},{24,59},{0,64},{-24,59},{-45,45},{-59,24},
    {-64,0},{-59,-24},{-45,-45},{-24,-59},{0,-64},{24,-59},{45,-45},{59,-24}};
static unsigned star_seed=0x2a5d;
static unsigned rnd(void){star_seed=star_seed*25173u+13849u;return star_seed>>4;}
static long star_t0[STARS];
static unsigned char star_k[STARS],star_v[STARS];
static int star_xy[STARS][4];
/* Shifts on a positive bias instead of signed IDIV (170 clocks each). */
static void star_pos(unsigned i,int dist,int *x,int *y)
{
    int t=(int)(((unsigned)(star_dir[star_k[i]][1]*dist+16384))>>6)-256;
    *x=TUN_X-256+(int)(((unsigned)(star_dir[star_k[i]][0]*dist+16384))>>6);
    *y=TUN_Y-256+(int)(((unsigned)(t*27+8192))>>5);
}
static void stars_reset(long nowf)
{
    unsigned i;
    for(i=0;i<STARS;i++) {
        star_k[i]=(unsigned char)(rnd()&15);star_v[i]=(unsigned char)(24+(rnd()&31));
        star_t0[i]=nowf-(long)(rnd()&1023);star_xy[i][0]=-1;
    }
}
static unsigned star_phase;
static void stars_frame(long nowf)
{
    unsigned i;int d,x,y,tx,ty,live=!(reduced || no_fx);
    if((++star_phase&1) && live)return;
    for(i=0;i<STARS;i++) {
        if(star_xy[i][0]>=0) {
            px(star_xy[i][0],star_xy[i][1],tunnel_bg(star_xy[i][0],star_xy[i][1]));
            px(star_xy[i][2],star_xy[i][3],tunnel_bg(star_xy[i][2],star_xy[i][3]));
            star_xy[i][0]=-1;
        }
        if(!live)continue;
        d=(int)(nowf-star_t0[i]);
        d=d<0 || d>8000?999:56+(int)((((unsigned)d>>5)*star_v[i])>>6);
        star_pos(i,d,&x,&y);
        if(d<56 || x<1 || x>99 || y<44 || y>148) {
            star_k[i]=(unsigned char)(rnd()&15);star_v[i]=(unsigned char)(24+(rnd()&31));
            star_t0[i]=nowf;continue;
        }
        star_pos(i,d-4,&tx,&ty);
        px(tx,ty,8);px(x,y,15);
        star_xy[i][0]=x;star_xy[i][1]=y;star_xy[i][2]=tx;star_xy[i][3]=ty;
    }
}

/* HUD panel, meters, words, progress. */
static unsigned long hud_score;
static unsigned hud_combo,hud_best,hud_hits,hud_misses,hud_acc,hud_prog,hud_word,hud_demo;
static unsigned meter_lvl[3],meter_shown[3],hud_seen;
static int hud_score_tick;
static int meter_tick;
static const unsigned char rows_cyan[]={15,15,11,11,11,3};
static const unsigned char rows_green[]={15,15,10,10,10,2};
static const unsigned char rows_red[]={15,12,12,12,4,4};
static const unsigned char rows_gold[]={15,15,14,14,14,14,6,4,12,14,14,15};
static const unsigned char rows_chrome[]={15,15,11,11,11,3,15,7,7,15,15};
static const unsigned char rainbow[]={12,14,10,11,9,13};
static const unsigned char rows_combo7[7]={15,14,14,14,14,6,6};
static const unsigned char rows_gold7[7]={15,15,14,14,12,13,13};
static const unsigned char rows_acc7[7]={15,15,15,11,11,3,3};
static void style(Style *s,unsigned scale,unsigned fg,unsigned outline,unsigned shadow,unsigned bg)
{
    s->scale=(unsigned char)scale;s->fg=(unsigned char)fg;s->outline=(unsigned char)outline;
    s->shadow=(unsigned char)shadow;s->bg=(unsigned char)bg;
    s->rows=0;s->nrows=0;s->letters=0;s->nletters=0;
}
static unsigned accuracy10(void)
{
    unsigned judged_n=fx_awesome+fx_nice+fx_missed;
    if(!judged_n)return 1000;
    return (unsigned)(((unsigned long)(2*fx_awesome+fx_nice)*1000UL)/(2UL*judged_n));
}
/* Decimal without printf: repeated subtraction, cheap on an 8088.
   width>0 pads on the left with `pad`. Returns the end of the string. */
static char *fmt_u(char *s,unsigned long v,int width,char pad)
{
    static const unsigned long p10[7]={1000000UL,100000UL,10000UL,1000UL,100UL,10UL,1UL};
    char tmp[8];int i,n=0;char d;
    for(i=0;i<7;i++) {
        for(d='0';v>=p10[i];v-=p10[i])d++;
        if(d!='0' || n || i==6)tmp[n++]=d;
    }
    for(i=n;i<width;i++)*s++=pad;
    for(i=0;i<n;i++)*s++=tmp[i];
    *s=0;return s;
}
static void fmt_acc(char *s,unsigned a)
{
    s=fmt_u(s,a/10,0,' ');*s++='.';*s++=(char)('0'+a%10);*s++='%';*s=0;
}
static void label_num(char *buf,const char *label,unsigned v,int width)
{
    strcpy(buf,label);fmt_u(buf+strlen(label),v,0,' ');
    while((int)strlen(buf)<width)strcat(buf," ");
}
static const char *word_text[4]={"","NICE!","AWESOME!","MISS"};
static const unsigned char rows_white7[7]={15,15,15,15,15,15,15};
static void words_init(void)
{
    Style s;unsigned k;
    for(k=1;k<4;k++) {
        style(&s,2,15,1,NO_COLOR,0);
        if(k==1){s.rows=rows_green;s.nrows=6;s.outline=2;}
        else if(k==2){s.rows=rows_cyan;s.nrows=6;}
        else {s.rows=rows_red;s.nrows=6;s.outline=4;}
        sprite_make(&word_spr[k],word_text[k],&s);
    }
}
/* Pop frame: flat white. Then the outlined, shaded word from the cache. */
static void word_draw(unsigned w)
{
    unsigned kind=w>>1,pop=w&1,n;char buf[16];
    fill(220,144,100,19,0);
    if(!kind)return;
    if(kind>=4) {
        sprintf(buf,"%u COMBO",(kind-4)*25);n=strlen(buf);
        if(n<=8)text2x(269-(int)n*6,146,buf,0,rainbow,6,0);
        else text(269-(int)n*3,150,buf,14,0);
        return;
    }
    n=strlen(word_text[kind]);
    if(pop || !word_spr[kind].h)
        text2x(269-(int)n*6,146,word_text[kind],pop?rows_white7:(kind==1?rows_green:kind==2?rows_cyan:rows_red),0,0,0);
    else sprite_draw(&word_spr[kind],269-(int)word_spr[kind].w/2,144);
}
static int milestone_until,milestone_kind;
static unsigned milestone_last;
/* At most two HUD items redraw per frame after the judgment word, so a hit
   never lands every counter in the same frame; the rest follow next frame. */
static void hud_frame(int now)
{
    char buf[20];unsigned v,l,lvl,s,w;int budget=2;
    if(now<milestone_until)w=(unsigned)milestone_kind*2+(now<milestone_until-12);
    else if(now<fx_until)w=fx_kind*2+(now<fx_start+2);
    else w=0;
    if(w!=hud_word){hud_word=w;word_draw(w);}
    if(hud_combo!=combo) {
        hud_combo=combo;fmt_u(buf,combo,0,' ');budget--;
        fill(260,41,56,14,0);
        text2x(314-(int)strlen(buf)*12,42,buf,combo>=50?rows_gold7:rows_combo7,0,0,0);
        if(combo && combo%25==0 && combo!=milestone_last) {
            milestone_last=combo;milestone_until=now+14;milestone_kind=4+combo/25;
        }
        if(!combo)milestone_last=0;
    }
    if(hud_score!=score && now!=hud_score_tick && budget>0) {
        hud_score_tick=now;budget--;
        if(score<hud_score)hud_score=score;
        else hud_score+=(score-hud_score+1)/2;
        fmt_u(buf,hud_score,7,'0');text(228,31,buf,15,0);
    }
    if(!demo_mode) {
        if(fx_seen!=hud_seen && budget>0) {
            hud_seen=fx_seen;v=accuracy10();
            if(v!=hud_acc){hud_acc=v;budget--;fmt_acc(buf,v);fill(4,160,98,14,0);
                text2x(4,160,buf,rows_acc7,0,0,0);}
        }
    } else if(hud_demo!=(unsigned)((now>>4)&1)+1) {
        hud_demo=(unsigned)((now>>4)&1)+1;
        text(6,172,"PRESS SPACE",hud_demo==1?15:8,0);
        text(6,181,"TO PLAY",hud_demo==1?15:8,0);
    }
    if(budget>0 && hud_hits!=hits){hud_hits=hits;budget--;label_num(buf,"HIT  ",hits,9);text(228,168,buf,10,0);}
    if(budget>0 && hud_misses!=misses){hud_misses=misses;budget--;label_num(buf,"MISS ",misses,9);text(228,178,buf,12,0);}
    if(budget>0 && hud_best!=best){hud_best=best;budget--;label_num(buf,"BEST ",best,9);text(228,61,buf,8,0);}
    /* Song progress and meters are stepped once per tick. */
    if(now==meter_tick)return;
    meter_tick=now;
    v=now<=0?0:(unsigned)((unsigned long)now*104UL/duration);
    if(v>104)v=104;
    if(v!=hud_prog) {
        if(v<hud_prog){span(104,13,104,8);hud_prog=0;}
        span(104+hud_prog,13,v-hud_prog,11);if(v<104)px(104+v,13,15);
        hud_prog=v;
    }
    if(no_fx)return;
    for(l=0;l<3;l++) {
        if(!l)lvl=lead_div?15-lead_att:0;
        else lvl=(prev_div[l] && prev_div[l]!=65535 && prev_att[l]<15)?15-prev_att[l]:0;
        lvl=(lvl*12+14)/15;
        if(lvl>=meter_lvl[l])meter_lvl[l]=lvl;else meter_lvl[l]--;
        if(meter_lvl[l]==meter_shown[l])continue;
        for(s=0;s<12;s++) {
            if((s<meter_lvl[l])==(s<meter_shown[l]) && meter_shown[l]!=255)continue;
            if(s<meter_lvl[l])fill(252+l*20,136-s*4,14,3,s<7?10:(s<10?14:12));
            else {fill(252+l*20,136-s*4,14,3,0);span(252+l*20,137-s*4,14,8);}
        }
        meter_shown[l]=meter_lvl[l];
    }
}
static void hud_reset(void)
{
    unsigned l;
    hud_score=1;hud_combo=65535;hud_best=hud_hits=hud_misses=65535;
    hud_acc=65535;hud_prog=0;hud_seen=65535;hud_word=65535;hud_demo=0;
    milestone_until=-32767;milestone_last=0;meter_tick=-32767;
    for(l=0;l<3;l++){meter_lvl[l]=0;meter_shown[l]=255;}
    if(score==0)hud_score=1;
}
static const char *diff_name(void)
{
    static const char *names[4]={"EASY","NORMAL","HARD","FULL"};
    return difficulty<4?names[difficulty]:"";
}
static void scene_draw(void)
{
    unsigned l,i,n;int y;Style st;char line[17];const char *t;
    clear_screen();
    style(&st,1,15,NO_COLOR,1,0);st.letters=rainbow;st.nletters=6;
    fancy(center_x("RADIO SHACK RAVE",1),2,"RADIO SHACK RAVE",&st);
    span(104,13,104,8);
    for(l=0;l<3;l++) {
        y=lane_x[l];
        span(y,LANE_TOP-1,32,8);span(y,LANE_BOT+1,32,8);
        vline(y,LANE_TOP-1,LANE_ROWS+2,8);vline(y+1,LANE_TOP,LANE_ROWS,lane_dk[l]);
        vline(y+30,LANE_TOP,LANE_ROWS,lane_dk[l]);vline(y+31,LANE_TOP-1,LANE_ROWS+2,8);
    }
    for(y=HIT_Y-1;y<=HIT_Y+1;y++)span(100,y,112,y==HIT_Y?15:11);
    memset(rows_shown,255,sizeof(rows_shown));lanes_full=1;
    for(l=0;l<3;l++){cap_shown[l]=255;burst_t0[l]=-32767;burst_seen[l]=flash_until[l];}
    if(!cap_spr[0][0].h)caps_init();
    tunnel_draw();ring_shown[0]=ring_shown[1]=0;
    text(6,18,demo_mode?"DEMO PLAY":"NOW PLAYING",demo_mode?13:8,0);
    /* Title, wrapped on a space into two 16-character lines. */
    t=song_title;n=strlen(t);
    if(n<=16)text(6,28,t,11,0);
    else {
        for(i=16;i>0 && t[i]!=' ';i--);
        if(!i)i=16;
        memcpy(line,t,i);line[i]=0;text(6,28,line,11,0);
        text(6,37,t+i+(t[i]==' '),11,0);
    }
    if(demo_mode){style(&st,2,13,5,NO_COLOR,0);fancy(6,150,"DEMO",&st);}
    else {
        text(6,150,"ACCURACY",7,0);
        if(difficulty<4)text(6,182,diff_name(),difficulty==0?10:difficulty==1?14:difficulty==2?12:13,0);
    }
    bevel(222,17,96,56,9,1,0);
    text(228,21,"SCORE",7,0);text(228,46,"COMBO",7,0);
    text(226,80,"PSG",7,0);
    for(l=0;l<3;l++){line[0]="ABC"[l];line[1]=0;text(256+l*20,80,line,lane_fg[l],0);}
    text(4,193,"ESC MENU  R RETRY  M CALM",8,0);
    hud_reset();
}
static unsigned long prof[5];
static void playfield_frame(long nowf,int now)
{
    unsigned long t0=clk_fine(),t1;
    lanes_frame(nowf,now);t1=clk_fine();prof[0]+=t1-t0;t0=t1;
    caps_frame();t1=clk_fine();prof[1]+=t1-t0;t0=t1;
    pulses_frame(nowf);t1=clk_fine();prof[2]+=t1-t0;t0=t1;
    stars_frame(nowf);t1=clk_fine();prof[3]+=t1-t0;t0=t1;
    hud_frame(now);t1=clk_fine();prof[4]+=t1-t0;
}

/* Results card, revealed in steps. */
static int results_step;
static char grade_letter(void)
{
    unsigned a=accuracy10();
    if(a>=980 && !misses)return 'S';
    if(a>=930)return 'A';
    if(a>=850)return 'B';
    if(a>=700)return 'C';
    return 'D';
}
static void results_frame(int age)
{
    Style st;char buf[24],g[2];const char *head;unsigned a;
    static const int at[9]={0,6,9,12,15,18,21,28,34};
    while(results_step<9 && age>=at[results_step]) {
        switch(results_step) {
        case 0:
            bevel(60,34,200,132,11,1,0);bevel(62,36,196,128,9,0,NO_COLOR);
            head=misses?"SONG CLEAR!":"FULL COMBO!";
            style(&st,2,15,1,NO_COLOR,0);st.letters=rainbow;st.nletters=6;
            fancy(center_x(head,2),42,head,&st);
            span(70,63,180,9);
            sfx_note(0,72,4,2,10);break;
        case 1:sprintf(buf,"AWESOME  %4u",fx_awesome);text(128,72,buf,11,0);sfx_blip(76);break;
        case 2:sprintf(buf,"NICE     %4u",fx_nice);text(128,82,buf,10,0);sfx_blip(79);break;
        case 3:sprintf(buf,"MISS     %4u",misses);text(128,92,buf,12,0);sfx_blip(81);break;
        case 4:sprintf(buf,"MAX COMBO%4u",best);text(128,102,buf,14,0);sfx_blip(84);break;
        case 5:a=accuracy10();sprintf(buf,"ACCURACY%3u.%u%%",a/10,a%10);text(128,112,buf,15,0);sfx_blip(86);break;
        case 6:sprintf(buf,"SCORE  %7lu",score);text(128,122,buf,15,0);sfx_blip(88);break;
        case 7:
            g[0]=grade_letter();g[1]=0;
            style(&st,6,15,0,1,0);
            st.rows=g[0]=='S'?rows_gold:rows_chrome;st.nrows=g[0]=='S'?12:11;
            if(g[0]=='D'){st.rows=rows_red;st.nrows=6;}
            fancy(76,72,g,&st);text(84,126,"GRADE",7,0);
            if(g[0]<='B' || g[0]=='S')sfx_chord(84,79,72,2,3,24);
            else sfx_chord(76,72,64,3,3,16);
            break;
        case 8:
            if(demo_mode)text(center_x("PRESS SPACE TO PLAY",1),148,"PRESS SPACE TO PLAY",15,0);
            else text(center_x("R RETRY    SPACE MENU",1),148,"R RETRY    SPACE MENU",7,0);
            break;
        }
        results_step++;
    }
}
