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
#define _A_NORMAL 0
#define _A_SUBDIR 16
#define _A_VOLID 8
struct find_t {unsigned attrib;char name[13];};
unsigned _dos_findfirst(const char *,unsigned,struct find_t *);
unsigned _dos_findnext(struct find_t *);
static unsigned irq_save(void){return 0;}
static void irq_restore(unsigned f){(void)f;}
#endif
