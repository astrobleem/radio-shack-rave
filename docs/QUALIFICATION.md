# Sound and runtime qualification

The full-song baseline was played by the user on a real Tandy with their privately supplied Call Me MIDI. They reported that the sound was amazing and gameplay felt great. That is attributed listening/gameplay feedback, not a calibrated latency measurement. The private MIDI, chart, prepared states and captured audio are excluded from this publication.

The restored intro/results sounds and lean VU additions use the same soundtrack parser, renderer, instruments and prepared data as that accepted baseline. They have completed local emulator and host qualification; a new physical test of these additions remains pending.

| Full-song test | Accepted baseline draw time | VU/effects release draw time | Maximum draw | Maximum soundtrack poll gap |
| --- | ---: | ---: | ---: | ---: |
| HX model, 4.772728 MHz | 124.8 ms | 130.6 ms | 176 ms | 17 ms |
| HX model, 7.159092 MHz EX speed proxy | 68.9 ms | 73.3 ms | 109 ms | 12 ms |

Both runs scored all 469 required notes with zero misses, delivered all 17,578 channel messages with zero output errors, and completed playback. Each captured all 10,626 scheduled frames / 107,268 PSG bytes and 490 PIT programs in the exact expected order. This proves unchanged register output, not an identical physical waveform or perfect timing. The VU adds 4.65% and 6.39% to average draw time respectively. The 7.16 MHz run is an HX CPU-speed proxy, not an exact EX model.

The native intro test verified all 31 original tone/noise attacks, final mute, and keyboard/video/sound restoration. The completed results test verified the opening note, tally blips, grade chord and original decay after the full soundtrack. Real keyboard IRQ injection tested judgment windows, four animation toggles, R replay with a fresh time origin, ordered key events, no queue overflow, and clean exit. PIT0/IRQ0 remained unchanged.

Host verification includes 79 public tests (one GUI/display case skipped), 16 SFX phase checks and 96 complete-frame comparisons of the optimized meter cells. The original test fixtures and new original MIDI demo are redistributable; CI reruns public checks against pinned public dependencies and separately tests a fresh OpenWatcom build. An OpenWatcom build is not expected to have the same bytes as the MSC6 reference.

The hardware-supported range is not the same as MIDI label admission. PSG-only mode accepts melodic labels 45–127 (83 labels, 82 distinct current table dividers). Speaker assist accepts 0–127 but folds 0–13 upward; notes 14–44 add 31 lower nominal positions. PIT is one additional square-wave voice, and high notes remain PSG. The nominal 10-bit PSG lower divider limit is about 109.35 Hz; the nonzero 16-bit PIT runtime limit is about 18.21 Hz. The lowest direct PIT lookup note is D0, about 18.35 Hz. Integer dividers, voice allocation and coarse high-note quantization limit the reproduced pitches.

The OpenWatcom compatibility build uses the medium code model because its combined game/MIDI code exceeds a single 64 KiB code segment. All game, adapter and shared MIDI objects use that model together; data remains near and hardware interrupt handlers remain explicitly far. The native-qualified MSC6 reference keeps its original small code model and binary. OpenWatcom compatibility is established by its own CI diagnostics, not inferred from the MSC6 binary.
