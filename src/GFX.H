/* Tandy mode 9 drawing: 320x200, 16 colors, four interleaved 8K banks,
 * two pixels per byte with the left pixel in the high nibble.
 * Row addresses come from a table; an 8088 MUL by 160 costs more than the
 * byte it addresses. Horizontal runs use the far string routines (REP STOSB
 * and REP MOVSB) instead of per-pixel calls.
 */
#define SCR_W 320
#define SCR_H 200
#define NO_COLOR 255
static unsigned char far *video=(unsigned char far *)0xb8000000UL;
static unsigned row_ofs[SCR_H];
static unsigned long vram_bytes;
static void gfx_init(void)
{
    unsigned y;
    for(y=0;y<SCR_H;y++)row_ofs[y]=(y&3)*8192+(y>>2)*160;
}
static void px(int x,int y,unsigned c)
{
    unsigned char far *p;
    if(x<0 || x>=SCR_W || y<0 || y>=SCR_H)return;
    p=video+row_ofs[y]+(x>>1);
    *p=(unsigned char)((x&1)?(*p&0xf0)|c:(*p&0x0f)|(c<<4));
}
static unsigned getpx(int x,int y)
{
    unsigned char v;
    if(x<0 || x>=SCR_W || y<0 || y>=SCR_H)return 0;
    v=video[row_ofs[y]+(x>>1)];
    return (x&1)?(v&15):(v>>4);
}
/* Any-alignment horizontal run. */
static void span(int x,int y,int w,unsigned c)
{
    int n;
    if(y<0 || y>=SCR_H)return;
    if(x<0){w+=x;x=0;}
    if(x+w>SCR_W)w=SCR_W-x;
    if(w<=0)return;
    if(x&1){px(x,y,c);x++;w--;}
    n=w>>1;
    if(n){_fmemset(video+row_ofs[y]+(x>>1),(int)(c|(c<<4)),n);vram_bytes+=n;}
    if(w&1)px(x+w-1,y,c);
}
static void fill(int x,int y,int w,int h,unsigned c)
{
    int i;
    for(i=0;i<h;i++)span(x,y+i,w,c);
}
static void vline(int x,int y,int h,unsigned c)
{
    int i;
    for(i=0;i<h;i++)px(x,y+i,c);
}
/* Raised panel: light top/left, dark bottom/right, filled inside. */
static void bevel(int x,int y,int w,int h,unsigned light,unsigned dark,unsigned face)
{
    if(face!=NO_COLOR)fill(x+1,y+1,w-2,h-2,face);
    span(x,y,w,light);vline(x,y,h,light);
    span(x+1,y+h-1,w-1,dark);vline(x+w-1,y+1,h-1,dark);
}
static void clear_screen(void)
{
    unsigned b;
    for(b=0;b<4;b++)_fmemset(video+b*8192,0,8000);
}

/* 5x7 font, ASCII 32..95, rows top to bottom, bit 4 is the left pixel.
   Every glyph is distinct; the old 3x5 face could not tell M/N or W/H apart. */
static const unsigned char font5[64][7]={
 {0,0,0,0,0,0,0},{4,4,4,4,4,0,4},{10,10,0,0,0,0,0},{10,31,10,10,31,10,0},
 {4,15,20,14,5,30,4},{24,25,2,4,8,19,3},{12,18,20,8,21,18,13},{4,4,8,0,0,0,0},
 {2,4,8,8,8,4,2},{8,4,2,2,2,4,8},{0,4,21,14,21,4,0},{0,4,4,31,4,4,0},
 {0,0,0,0,12,4,8},{0,0,0,31,0,0,0},{0,0,0,0,0,12,12},{1,1,2,4,8,16,16},
 {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},{31,2,4,2,1,17,14},
 {2,6,10,18,31,2,2},{31,16,30,1,1,17,14},{6,8,16,30,17,17,14},{31,1,2,4,8,8,8},
 {14,17,17,14,17,17,14},{14,17,17,15,1,2,12},{0,12,12,0,12,12,0},{0,12,12,0,12,4,8},
 {2,4,8,16,8,4,2},{0,0,31,0,31,0,0},{8,4,2,1,2,4,8},{14,17,1,2,4,0,4},
 {14,17,23,21,23,16,14},{14,17,17,31,17,17,17},{30,17,17,30,17,17,30},{14,17,16,16,16,17,14},
 {30,17,17,17,17,17,30},{31,16,16,30,16,16,31},{31,16,16,30,16,16,16},{14,17,16,23,17,17,15},
 {17,17,17,31,17,17,17},{14,4,4,4,4,4,14},{7,2,2,2,2,18,12},{17,18,20,24,20,18,17},
 {16,16,16,16,16,16,31},{17,27,21,21,17,17,17},{17,17,25,21,19,17,17},{14,17,17,17,17,17,14},
 {30,17,17,30,16,16,16},{14,17,17,17,21,18,13},{30,17,17,30,20,18,17},{15,16,16,14,1,1,30},
 {31,4,4,4,4,4,4},{17,17,17,17,17,17,14},{17,17,17,17,17,10,4},{17,17,17,21,21,21,10},
 {17,17,10,4,10,17,17},{17,17,10,4,4,4,4},{31,1,2,4,8,16,31},{14,8,8,8,8,8,14},
 {16,16,8,4,2,1,1},{14,2,2,2,2,2,14},{4,10,17,0,0,0,0},{0,0,0,0,0,0,31}
};
static unsigned glyph(int ch)
{
    if(ch>='a' && ch<='z')ch-=32;
    if(ch<32 || ch>95)return 0;
    return (unsigned)(ch-32);
}
/* Opaque 5x7 text on a 6-pixel (three byte) cell. x is rounded to even. */
static void text(int x,int y,const char *s,unsigned fg,unsigned bg)
{
    unsigned char lut[4];unsigned row,bits;const unsigned char *g;
    unsigned char far *p;
    if(y<0 || y>SCR_H-7)return;
    lut[0]=(unsigned char)(bg|(bg<<4));lut[1]=(unsigned char)((bg<<4)|fg);
    lut[2]=(unsigned char)((fg<<4)|bg);lut[3]=(unsigned char)(fg|(fg<<4));
    x&=~1;
    for(;*s && x<=SCR_W-6;s++,x+=6) {
        g=font5[glyph(*s)];
        for(row=0;row<7;row++) {
            bits=g[row];p=video+row_ofs[y+row]+(x>>1);
            p[0]=lut[(bits>>3)&3];p[1]=lut[(bits>>1)&3];p[2]=lut[(bits&1)<<1];
        }
        vram_bytes+=21;
    }
}
static int text_width(const char *s,unsigned scale)
{
    int n=0;
    while(s[n])n++;
    return n?n*6*(int)scale-(int)scale:0;
}

/* Styled text through a near scratch buffer: per-row gradient, per-letter
   colors, outline and drop shadow. NO_COLOR background composites over what
   is already on screen. The box is the glyph area plus a one pixel outline
   margin and a shadow margin of `scale` pixels; x must be even. */
#define TBUF 4608
static unsigned char tbuf[TBUF];
static unsigned tb_w,tb_h,tb_stride;
typedef struct {
    unsigned char scale,fg,outline,shadow,bg;
    const unsigned char *rows;unsigned char nrows;
    const unsigned char *letters;unsigned char nletters;
} Style;
/* Drop shadows step one or two pixels, never a whole scaled glyph pixel. */
#define SHADOW_OFS(sc) ((sc)>2?2u:(unsigned)(sc))
/* Horizontal run in the scratch buffer: one nibble at each odd edge,
   whole bytes between. Styled glyphs are drawn as runs, never pixels. */
static void tb_span(int x,int y,int w,unsigned c)
{
    unsigned char *p;
    if(y<0 || y>=(int)tb_h)return;
    if(x<0){w+=x;x=0;}
    if(x+w>(int)tb_w)w=(int)tb_w-x;
    if(w<=0)return;
    p=tbuf+(unsigned)y*tb_stride;
    if(x&1){p[x>>1]=(unsigned char)((p[x>>1]&0xf0)|c);x++;w--;}
    if(w>1)memset(p+(x>>1),(int)(c|(c<<4)),(unsigned)w>>1);
    if(w&1){x+=w-1;p[x>>1]=(unsigned char)((p[x>>1]&0x0f)|(c<<4));}
}
/* pass 0: drop shadow, 1: outline, 2: face. */
static void tb_glyph(int ox,int oy,unsigned gi,unsigned pass,unsigned color,const Style *st)
{
    unsigned r,c,c0,a,sc=st->scale,bits;int x,y,w;const unsigned char *g=font5[gi];
    for(r=0;r<7;r++) {
        bits=g[r];
        for(c=0;c<5;) {
            if(!(bits&(16>>c))){c++;continue;}
            for(c0=c;c<5 && (bits&(16>>c));c++);
            x=ox+(int)(c0*sc);w=(int)((c-c0)*sc);
            for(a=0;a<sc;a++) {
                y=oy+(int)(r*sc+a);
                if(pass==0)tb_span(x+(int)SHADOW_OFS(sc),y+(int)SHADOW_OFS(sc),w,st->shadow);
                else if(pass==1) {
                    if(!a)tb_span(x-1,y-1,w+2,st->outline);
                    tb_span(x-1,y,w+2,st->outline);
                    if(a==sc-1)tb_span(x-1,y+1,w+2,st->outline);
                } else tb_span(x,y,w,color!=NO_COLOR?color:
                    st->rows[((r*sc+a)*st->nrows)/(7*sc)]);
            }
        }
    }
}
/* Render into tbuf. Background: solid, or read back from the screen at x,y. */
static int fancy_render(int x,int y,const char *s,const Style *st)
{
    unsigned i,n,sc=st->scale,c;int r;
    n=0;while(s[n])n++;
    tb_w=(unsigned)text_width(s,sc)+2+SHADOW_OFS(sc);tb_h=7*sc+2+SHADOW_OFS(sc);
    tb_stride=(tb_w+1)>>1;
    if((unsigned long)tb_stride*tb_h>TBUF)return 0;
    for(r=0;r<(int)tb_h;r++) {
        if(st->bg==NO_COLOR) {
            if(y+r<0 || y+r>=SCR_H)return 0;
            _fmemcpy((void far *)(tbuf+r*tb_stride),video+row_ofs[y+r]+(x>>1),tb_stride);
        } else memset(tbuf+r*tb_stride,st->bg|(st->bg<<4),tb_stride);
    }
    if(st->shadow!=NO_COLOR)for(i=0;i<n;i++)
        tb_glyph(1+(int)(i*6*sc),1,glyph(s[i]),0,0,st);
    if(st->outline!=NO_COLOR)for(i=0;i<n;i++)
        tb_glyph(1+(int)(i*6*sc),1,glyph(s[i]),1,0,st);
    for(i=0;i<n;i++) {
        c=st->letters?st->letters[i%st->nletters]:(st->rows?NO_COLOR:st->fg);
        tb_glyph(1+(int)(i*6*sc),1,glyph(s[i]),2,c,st);
    }
    return 1;
}
static void tb_blit(int x,int y)
{
    int r;
    if(y<0 || y+(int)tb_h>SCR_H || x<0 || x+(int)tb_w>SCR_W)return;
    for(r=0;r<(int)tb_h;r++)
        _fmemcpy(video+row_ofs[y+r]+(x>>1),(void far *)(tbuf+r*tb_stride),tb_stride);
    vram_bytes+=(unsigned long)tb_h*tb_stride;
}
/* Draws whole strings when they fit the scratch buffer, else letter by
   letter over a transparent background. x is rounded to even. */
static void fancy(int x,int y,const char *s,const Style *st)
{
    unsigned n=0,sc=st->scale,w;char one[2];Style each;
    while(s[n])n++;
    x&=~1;
    if(fancy_render(x,y,s,st)){tb_blit(x,y);return;}
    each=*st;each.bg=NO_COLOR;one[1]=0;
    for(w=0;w<n;w++) {
        one[0]=s[w];
        if(st->letters){each.letters=st->letters+(w%st->nletters);each.nletters=1;}
        if(fancy_render(x+(int)(w*6*sc),y,one,&each))tb_blit(x+(int)(w*6*sc),y);
    }
}
/* Fast opaque double-size text: each glyph pixel is one whole byte, rows
   doubled. Colors per glyph row (7 entries) or per letter. x even. */
static void text2x(int x,int y,const char *s,const unsigned char *rows,
    const unsigned char *letters,unsigned nletters,unsigned bg)
{
    unsigned row,col,bits,i,c;unsigned char far *p;unsigned char far *q;
    unsigned char on,off=(unsigned char)(bg*17);const unsigned char *g;
    if(y<0 || y>SCR_H-14)return;
    x&=~1;
    for(i=0;s[i] && x<=SCR_W-12;i++,x+=12) {
        g=font5[glyph(s[i])];
        for(row=0;row<7;row++) {
            c=letters?letters[i%nletters]:rows[row];
            on=(unsigned char)(c*17);bits=g[row];
            p=video+row_ofs[y+row*2]+(x>>1);q=video+row_ofs[y+row*2+1]+(x>>1);
            for(col=0;col<5;col++)p[col]=q[col]=(bits&(16>>col))?on:off;
            p[5]=q[5]=off;
        }
        vram_bytes+=84;
    }
}
static int center_x(const char *s,unsigned scale)
{
    return ((SCR_W-text_width(s,scale)-2-(int)SHADOW_OFS(scale))/2)&~1;
}
