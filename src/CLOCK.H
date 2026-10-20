/* Fine clock: BIOS tick count plus the phase of PIT counter 0, read only.
 * PIT0 is never reprogrammed. The BIOS runs it in mode 3, where the latched
 * count runs 65536..0 twice per tick, so a single read is ambiguous by half a
 * tick. Readings are kept monotonic: within one tick the first-half answer is
 * used until the count wraps under the previous reading, then the second
 * half. That holds while reads are less than half a tick (27 ms) apart,
 * which the bounded drawing service points must guarantee. A pending IRQ0 at read time means
 * the new period has begun but the BIOS has not counted it yet. If an odd
 * count is ever seen, the BIOS is using mode 2 and the phase is direct.
 * Units: 1/256 BIOS tick (about 0.21 ms).
 *
 * Render mode replaces all of this with a virtual clock that advances
 * exactly half a tick per presented frame, for deterministic captures.
 */
#ifndef RAVE_LINT
static unsigned irq_save(void)
{
    unsigned flags;
    _asm pushf
    _asm pop flags
    _asm cli
    return flags;
}
static void irq_restore(unsigned flags)
{
    _asm push flags
    _asm popf
}
#endif
#define BIOS_DAY 0x1800b0UL
#define RENDER_STEP 128
static unsigned long clk_last,clk_wrap,clk_vtime;
static int clk_mode2,clk_virtual;
static unsigned long clk_fine(void)
{
    unsigned flags,lo,hi,c,irr,before;unsigned long t,a;
    if(clk_virtual)return clk_vtime;
#if defined(_MSC_VER)
    /* Same atomic read and I/O order as below, without CRT port calls.
       Save every nonvolatile register touched; restore incoming IF exactly. */
    _asm push bx
    _asm push es
    _asm pushf
    _asm pop flags
    _asm cli
    _asm xor ax,ax
    _asm mov al,0ah
    _asm out 20h,al
    _asm in al,20h
    _asm mov irr,ax
    _asm clock_latch:
    /* If PIT0 wraps between the latch and IRR read, repeat the snapshot.
       A new pending IRQ must never be paired with an old-period counter. */
    _asm xor al,al
    _asm out 43h,al
    _asm in al,40h
    _asm mov bl,al
    _asm in al,40h
    _asm mov bh,al
    _asm mov c,bx
    _asm mov ax,40h
    _asm mov es,ax
    _asm mov ax,es:[6ch]
    _asm mov word ptr t,ax
    _asm mov ax,es:[6eh]
    _asm mov word ptr t+2,ax
    _asm in al,20h
    _asm xor ah,ah
    _asm mov bx,irr
    _asm mov irr,ax
    _asm xor bx,ax
    _asm test bl,1
    _asm jnz clock_latch
    _asm push flags
    _asm popf
    _asm pop es
    _asm pop bx
#else
    flags=irq_save();
    outp(0x20,0x0a);irr=inp(0x20);
    do {
        before=irr;
        outp(0x43,0);lo=inp(0x40);hi=inp(0x40);
        t=*(unsigned long far *)0x0040006cUL;
        irr=inp(0x20);
    } while((before^irr)&1);
    irq_restore(flags);
    c=lo|(hi<<8);
#endif
    if(c&1)clk_mode2=1;
    t+=clk_wrap;
    if(irr&1)t++;
    /* Midnight: the BIOS count restarts at zero. Keep our timeline running. */
    if((t<<8)+0x10000UL<clk_last && (clk_last>>8)-t>0x100000UL) {
        clk_wrap+=BIOS_DAY;t+=BIOS_DAY;
    }
    if(clk_mode2)a=(t<<8)+(((unsigned)(0-c))>>8);
    else {
        a=(t<<8)+(((unsigned)(0-c))>>9);
        if(a<clk_last)a+=128;
    }
    if(a<clk_last)a=clk_last;
    clk_last=a;
    return a;
}
static unsigned long clk_ticks(void)
{
    return clk_fine()>>8;
}
/* Loading/drawing a new scene can leave a gap longer than half a tick.
 * Establish the mode-3 half from a real BIOS tick transition before choosing
 * a playback origin. Interrupts remain enabled; PIT0 and IRQ0 stay unchanged.
 * The transition puts the next sample in the known first half of its tick.
 */
static void clk_sync(void)
{
    unsigned tick;
    if(clk_virtual)return;
    tick=*(volatile unsigned far *)0x0040006cUL;
    do {clk_fine();} while(*(volatile unsigned far *)0x0040006cUL==tick);
    clk_fine();
}
/* Wait for the start of vertical retrace (status bit 3), bounded. */
static int vsync_on=1;
static void vsync_wait(void)
{
    unsigned n;
    if(clk_virtual || !vsync_on)return;
    for(n=0;n<30000 && (inp(0x3da)&8);n++);
    for(n=0;n<30000 && !(inp(0x3da)&8);n++);
}
