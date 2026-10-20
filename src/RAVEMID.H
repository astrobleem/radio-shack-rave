#ifndef RAVE_MIDI_H
#define RAVE_MIDI_H
int _cdecl RaveMidiOpen(const char *path);
void _cdecl RaveMidiRewind(void);
void _cdecl RaveMidiSilence(void);
void _cdecl RaveMidiPoll(unsigned long elapsedMs);
void _cdecl RaveMidiClose(void);
int _cdecl RaveMidiActive(void);
unsigned _cdecl RaveMidiEvents(void);
unsigned _cdecl RaveMidiDelivered(void);
unsigned _cdecl RaveMidiErrors(void);
unsigned _cdecl RaveMidiMaxPollGap(void);
unsigned _cdecl RaveMidiMaxLateness(void);
int _cdecl RaveMidiEnded(void);
unsigned long _cdecl RaveMidiDuration(void);
int _cdecl RaveMidiPrepared(void);
/* Packed nibbles are the last successfully emitted PSG attenuation. */
unsigned _cdecl RaveMidiPackedVolume(void);
/* Last successfully emitted PIT gate state: 0 off, 1 on. */
unsigned _cdecl RaveMidiPitGate(void);
void _cdecl RaveMidiPollFine(unsigned long fine);
#endif
