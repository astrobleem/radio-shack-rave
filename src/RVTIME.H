/* SPDX-License-Identifier: MIT
   Exact foreground-only u32 / PIT frequency. Same reciprocal/correction
   construction as pinned libtandy LTMATH.H; no I/O or IRQ state. */
#ifndef RAVE_TIME_H
#define RAVE_TIME_H
/* Precondition n <= 0xffffffff. 3599=floor(2^32/1193182).
   The two word products are <2^28. The estimate is at most one low;
   q*1193182 <= n, so the one correction cannot overflow. */
static unsigned long rave_time_div(unsigned long n)
{
#if defined(_MSC_VER) && (defined(_M_I86) || defined(M_I86) || _MSC_VER < 1000)
    unsigned short carry,wordQ;
    unsigned long q;
    _asm mov cx,3599
    _asm mov ax,word ptr n
    _asm mul cx
    _asm mov carry,dx
    _asm mov ax,word ptr n+2
    _asm mul cx
    _asm add ax,carry
    _asm adc dx,0
    _asm mov wordQ,dx
    q=wordQ;
#else
    unsigned long low=(unsigned long)(unsigned short)n*3599UL;
    unsigned long high=(n>>16)*3599UL+(low>>16);
    unsigned long q=high>>16;
#endif
    return q+(n-q*1193182UL>=1193182UL);
}
#endif
