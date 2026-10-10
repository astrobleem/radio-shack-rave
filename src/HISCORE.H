/* High score table: the top five per song, in RAVE.HI beside the game.
 *
 * Nothing is written unless a real game earns a place and the player types
 * initials and presses Enter. Demos and scripted runs never record. A save
 * to a write-protected floppy must not reach DOS's "Abort, Retry, Fail"
 * prompt over the graphics screen, so a three-byte critical-error handler
 * (mov al,3 / iret: fail the call) is installed only around file access;
 * the game then reports "not saved" and carries on.
 *
 * RAVE.HI: "RHI1", u16 song count, then per song a u32 key and five rows of
 * initials[3], grade, u32 score, u16 accuracy x10. All little-endian. A
 * missing or malformed file reads as an empty table.
 */
#define HS_SONGS 64
#define HS_TOP 5
#define HS_ROW 10
#define HS_REC (4+HS_TOP*HS_ROW)
#define HS_FILE "RAVE.HI"
#define HS_IDLE 0
#define HS_ENTER 1
#define HS_SAVED 2
#define HS_FAILED 3
#define HS_SKIPPED 4
typedef struct { char ini[3];unsigned char grade;unsigned long score;unsigned acc; } HsRow;
typedef struct { unsigned long key;HsRow row[HS_TOP]; } HsSong;
static HsSong hs_tab[HS_SONGS];
static unsigned hs_count;
/* hs_state is defined in PLAY.H, which reads it on the results card. */
static int hs_rank,hs_drawn=-1,hs_blink=-1;
static char hs_ini[4];
static unsigned hs_len;

static unsigned long hs_key(void)
{
    unsigned long h=2166136261UL;const char *p;
    for(p=song_title;*p;p++)h=(h^(unsigned char)*p)*16777619UL;
    h=(h^duration)*16777619UL;h=(h^states)*16777619UL;
    h=(h^taps)*16777619UL;h=(h^required_taps)*16777619UL;
    return (h^ndrums)*16777619UL;
}
static int hs_find(unsigned long key)
{
    unsigned i;
    for(i=0;i<hs_count;i++)if(hs_tab[i].key==key)return (int)i;
    return -1;
}
/* Critical-error guard. DOS 2.x has no "fail" answer; there the stub
   answers "ignore", which loses the write but never stops the game. */
#ifndef RAVE_LINT
static unsigned char hs_int24[3]={0xb0,0x03,0xcf};
static void (interrupt far *hs_old24)(void);
static void hs_guard(int on)
{
    union REGS r;
    if(on) {
        r.h.ah=0x30;int86(0x21,&r,&r);
        if(r.h.al<3)hs_int24[1]=0;
        hs_old24=_dos_getvect(0x24);
        _dos_setvect(0x24,(void (interrupt far *)(void))(void far *)hs_int24);
    } else _dos_setvect(0x24,hs_old24);
}
#else
static void hs_guard(int on){(void)on;}
#endif
static unsigned long hs_u32(const unsigned char *b)
{
    return (unsigned long)b[0]|((unsigned long)b[1]<<8)|((unsigned long)b[2]<<16)|((unsigned long)b[3]<<24);
}
static void hs_put32(unsigned char *b,unsigned long v)
{
    b[0]=(unsigned char)v;b[1]=(unsigned char)(v>>8);b[2]=(unsigned char)(v>>16);b[3]=(unsigned char)(v>>24);
}
static void hs_load(void)
{
    FILE *f;unsigned char head[6],rec[HS_REC];unsigned i,k,n;int ok=1;HsRow *r;
    hs_count=0;
    hs_guard(1);
    f=fopen(HS_FILE,"rb");
    if(f) {
        if(fread(head,1,6,f)!=6 || memcmp(head,"RHI1",4))ok=0;
        n=head[4]|(head[5]<<8);
        if(n>HS_SONGS)ok=0;
        for(i=0;ok && i<n;i++) {
            if(fread(rec,1,HS_REC,f)!=HS_REC){ok=0;break;}
            hs_tab[i].key=hs_u32(rec);
            for(k=0;k<HS_TOP;k++) {
                r=&hs_tab[i].row[k];
                memcpy(r->ini,rec+4+k*HS_ROW,3);r->grade=rec[7+k*HS_ROW];
                r->score=hs_u32(rec+8+k*HS_ROW);
                r->acc=rec[12+k*HS_ROW]|(rec[13+k*HS_ROW]<<8);
                if(r->acc>1000 || (k && r->score>hs_tab[i].row[k-1].score))ok=0;
            }
        }
        if(ok && fgetc(f)!=EOF)ok=0;
        fclose(f);
        hs_count=ok?n:0;
    }
    hs_guard(0);
}
static int hs_save(void)
{
    FILE *f;unsigned char head[6],rec[HS_REC];unsigned i,k;int ok=1;HsRow *r;
    hs_guard(1);
    f=fopen(HS_FILE,"wb");
    if(!f)ok=0;
    else {
        memcpy(head,"RHI1",4);head[4]=(unsigned char)hs_count;head[5]=(unsigned char)(hs_count>>8);
        if(fwrite(head,1,6,f)!=6)ok=0;
        for(i=0;ok && i<hs_count;i++) {
            hs_put32(rec,hs_tab[i].key);
            for(k=0;k<HS_TOP;k++) {
                r=&hs_tab[i].row[k];
                memcpy(rec+4+k*HS_ROW,r->ini,3);rec[7+k*HS_ROW]=r->grade;
                hs_put32(rec+8+k*HS_ROW,r->score);
                rec[12+k*HS_ROW]=(unsigned char)r->acc;rec[13+k*HS_ROW]=(unsigned char)(r->acc>>8);
            }
            if(fwrite(rec,1,HS_REC,f)!=HS_REC)ok=0;
        }
        if(ferror(f))ok=0;
        if(fclose(f))ok=0;
    }
    hs_guard(0);
    return ok;
}
/* Rank 1..5 this score would take for the current song, or 0. Ties stay
   below the score already on the board. */
static int hs_rank_of(unsigned long sc)
{
    int i=hs_find(hs_key()),k;
    if(!sc)return 0;
    if(i<0)return 1;
    for(k=0;k<HS_TOP;k++)if(sc>hs_tab[i].row[k].score)return k+1;
    return 0;
}
static const HsRow *hs_top(void)
{
    int i=hs_find(hs_key());
    return (i<0 || !hs_tab[i].row[0].score)?0:&hs_tab[i].row[0];
}
static void hs_commit(void)
{
    int i=hs_find(hs_key()),k;unsigned j,low;HsRow *r;
    if(i<0) {
        if(hs_count<HS_SONGS)i=(int)hs_count++;
        else {
            /* Full: reuse the song whose best score is lowest. */
            for(low=0,j=1;j<hs_count;j++)
                if(hs_tab[j].row[0].score<hs_tab[low].row[0].score)low=j;
            i=(int)low;
        }
        memset(&hs_tab[i],0,sizeof(HsSong));hs_tab[i].key=hs_key();
    }
    for(k=HS_TOP-1;k>=hs_rank;k--)hs_tab[i].row[k]=hs_tab[i].row[k-1];
    r=&hs_tab[i].row[hs_rank-1];
    for(k=0;k<3;k++)r->ini[k]=(char)(k<(int)hs_len?hs_ini[k]:' ');
    r->grade=(unsigned char)grade_letter();r->score=score;r->acc=accuracy10();
    hs_state=hs_save()?HS_SAVED:HS_FAILED;
}
/* Results start. Only real games may enter the table; /HISCORE plays
   itself and types its initials for the native test. */
static void hs_begin(int demo)
{
    static const unsigned char typed[4]={46,38,32,28}; /* C L D Enter */
    unsigned i;
    hs_state=HS_IDLE;hs_drawn=-1;hs_len=0;hs_ini[0]=0;
    if(demo || (auto_mode && auto_mode!=16))return;
    hs_rank=hs_rank_of(score);
    if(!hs_rank)return;
    hs_state=HS_ENTER;
    if(auto_mode==16)for(i=0;i<4;i++){key_event(typed[i]);key_event(typed[i]|128);}
}
static const unsigned char hs_scan[26]={30,48,46,32,18,33,34,35,23,36,37,38,50,49,24,25,16,19,31,20,22,47,17,45,21,44};
/* While initials are being typed every key belongs to the entry. */
static int hs_entry_key(unsigned k)
{
    unsigned i;
    if(hs_state!=HS_ENTER)return 0;
    if(k==1){hs_state=HS_SKIPPED;return 1;}
    if(k==14 && hs_len){hs_ini[--hs_len]=0;return 1;}
    if(k==28 && hs_len){hs_commit();return 1;}
    for(i=0;i<26;i++)if(hs_scan[i]==k && hs_len<3) {
        hs_ini[hs_len++]=(char)('A'+i);hs_ini[hs_len]=0;sfx_blip(76+(int)hs_len*3);
    }
    return 1;
}
/* Results card lines, redrawn only when something changes. */
static void hs_draw(void)
{
    char buf[32];int b=(int)((clk_ticks()>>3)&1),key=hs_state*16+(int)hs_len;
    if(hs_state==HS_IDLE)return;
    if(key==hs_drawn && (hs_state!=HS_ENTER || b==hs_blink))return;
    hs_drawn=key;hs_blink=b;
    fill(64,133,192,24,0);
    if(hs_state==HS_ENTER) {
        sprintf(buf,"NEW HIGH SCORE!  RANK %d",hs_rank);
        text(center_x(buf,1),135,buf,14,0);
        sprintf(buf,"INITIALS %c %c %c   ENTER",
            hs_len>0?hs_ini[0]:(b?'_':' '),hs_len>1?hs_ini[1]:(hs_len==1 && b?'_':' '),
            hs_len>2?hs_ini[2]:(hs_len==2 && b?'_':' '));
        text(center_x(buf,1),147,buf,15,0);
        return;
    }
    if(hs_state==HS_SAVED)sprintf(buf,"SAVED AS %s  RANK %d",hs_ini,hs_rank);
    else if(hs_state==HS_FAILED)strcpy(buf,"NOT SAVED: DISK PROTECTED?");
    else strcpy(buf,"SCORE NOT SAVED");
    text(center_x(buf,1),135,buf,hs_state==HS_SAVED?10:(hs_state==HS_FAILED?12:8),0);
    text(center_x("R RETRY    SPACE MENU",1),148,"R RETRY    SPACE MENU",8,0);
}
