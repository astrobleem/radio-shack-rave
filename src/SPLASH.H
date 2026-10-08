/* Pure bounded format/clock helpers, also compiled by the host QA harness. */
#define SPLASH_ROW 160
#define SPLASH_ORIGINAL_TICKS 18
#define SPLASH_BANGERS_TICKS 9
static unsigned splash_u16(const unsigned char *p)
{ return (unsigned)p[0]|((unsigned)p[1]<<8); }
static int splash_header(const unsigned char *h)
{
    unsigned w=splash_u16(h+4),height=splash_u16(h+6);
    unsigned x=splash_u16(h+8),y=splash_u16(h+10);
    return h[0]=='R' && h[1]=='S' && h[2]=='P' && h[3]=='L' &&
        w>=2 && w<=320 && !(w&1) && height>=1 && height<=200 &&
        x<=320-w && !(x&1) && y<=200-height;
}
static unsigned long splash_age(unsigned long now,unsigned long start)
{ return now>=start?now-start:now+0x1800b0UL-start; }
