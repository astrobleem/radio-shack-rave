/* Host lint shim: just enough of MSC6 <dos.h> to type-check the DOS game
   as strict C89 with GCC. Nothing here runs. */
#ifndef RAVE_SHIM_DOS_H
#define RAVE_SHIM_DOS_H
#define far
#define interrupt
#define _cdecl
struct WORDREGS { unsigned ax,bx,cx,dx,si,di,cflag; };
struct BYTEREGS { unsigned char al,ah,bl,bh,cl,ch,dl,dh; };
union REGS { struct WORDREGS x; struct BYTEREGS h; };
int int86(int,union REGS *,union REGS *);
void (*_dos_getvect(unsigned))(void);
void _dos_setvect(unsigned,void (*)(void));
static unsigned irq_save(void){return 0;}
static void irq_restore(unsigned f){(void)f;}
#endif
