/* Cooperative foreground DOS player API, MSC6 C89 /G0 /AS cdecl. */
#ifndef TANDY_DOSSND_H
#define TANDY_DOSSND_H
#define DS_PSG 1
#define DS_PIT 2
#define DS_PWM 4
#define DOS_SOUND_VERSION 1
#define DOS_SOUND_BUSY (-3)
#define DOS_SOUND_OWNER (-1)
#define DOS_SOUND_PITCH (-13)
#define DOS_SOUND_CAPABILITY (-16)
#define DOS_SOUND_CONTEXT (-20)
#define DOS_SOUND_SPEECH (-21)
int _cdecl DosSoundAcquire(unsigned resources);
int _cdecl DosSoundPsgByte(unsigned value);
/* Foreground complete state: 1..11 bytes, one lease check, no IRQ masking. */
int _cdecl DosSoundPsgBytes(const unsigned char *bytes,unsigned count);
int _cdecl DosSoundPitNote(unsigned note,unsigned attack);
/* Exact prepared Timer-2 divider from the shared MIDI renderer; zero gates off. */
int _cdecl DosSoundPitDivisor(unsigned divisor,unsigned attack);
int _cdecl DosSoundPwmBegin(void);
void _cdecl DosSoundPwmEnd(void);
void _cdecl DosSoundRelease(void);
#endif
