# Full-song MIDI mode

`RSRAVE CHART.RBG /MIDI SONG.MID` keeps the RBG as the independent gameplay chart and plays the complete MIDI sidecar through the shared libtandy SMF parser and MIDI synth. It validates and reads at most 60,000 bytes into a single far segment before acquiring sound hardware. The shared core uses `flags=3` (envelopes plus vibrato) and the separately selected speaker-assist mode. PSG and PIT output stay under the existing `DOSSND` lease; the prepared Timer-2 divisor is passed through the guarded owner API. `DOSSND` performs the same gate-off/program/gate-on sequence and its normal release cleanup.

While MIDI is active, chart input, automatic chart hits, misses and visual scoring continue. Legacy chart tones, backing PSG and drum writes, plus gameplay PSG effects are muted so they cannot replace or compete with the full soundtrack. The ordinary RBG launch path remains unchanged. Supply a `.MID` explicitly with `/MIDI`. The public demo is original, CC0 music; third-party songs and their derived charts/streams/captures are not part of the public catalog.

Lean rendering is the default on slow systems. Press **M** at the title or during play to toggle decoration, or launch with `/ANIM` to enable it and `/LEAN` to disable it. Lean mode keeps the same chart, note windows, scoring and soundtrack, uses stable cached judgments and plain numeric HUD text, and avoids cosmetic animation. MIDI playback suppresses legacy chart tones and drum effects in either display mode.

The DOS player services MIDI cooperatively during long playfield redraws, checking between eight-row lane batches, sprite rows, and HUD/text items. It samples current song time before and after each MIDI poll. Those service points also drain queued note keys using their real IRQ1 BIOS timestamps; command keys remain for the main loop. The existing note windows are unchanged. A BIOS tick transition establishes the mode-3 timer phase after scene loading and rewind, before choosing the song origin. PIT0 and IRQ0 remain unchanged. Service is enabled only during active gameplay and stops with a guarded PSG/PIT silence before results or return to the title.

For the stock 8088, prepare the full soundtrack offline and launch:

```
python tools/rave_prepare.py --song SONG.MID --out SONG.RWS --trace SONG-CYCLES.csv --evidence SONG-PREPARED.json
RSRAVE CHART.RBG /STREAM SONG.RWS
```

The preparer runs the pinned Windows producer scheduler, SMF parser, synth and existing instruments. RWS1 stores every resulting PSG/PIT state and its scheduled PIT-cycle time, rounded upward by at most 255 cycles (0.214 ms) for the DOS fine clock. The player loads and validates the complete stream into bounded far-memory blocks before play, then replays it through the same guarded sound owner without parsing or synthesis during drawing. The private qualification song exercised 10,626 frames and all 17,578 channel messages; it is not distributed. The bundled original demo provides a redistributable preparation/replay fixture. It requires a 640 KiB test configuration; free conventional-memory availability still matters. This path preserves the complete soundtrack while the RBG remains a separate reduced gameplay chart. It does not promise identical physical waveform timing to the Windows IRQ queue.

The preparer accepts `LIBTANDY` and `LIBWINTANDY` source roots; use the exact frozen dependency recorded by the preparation evidence. No third-party bank is included. `tools/check_rws.py` verifies complete replay against the actual frozen Windows output routine, including PIT lease behavior, malformed-stream rejection, silence and rewind.

The pinned engine dependency is recorded in `LIBTANDY.PIN.json`. Set `LIBTANDY` to that exact approved source tree when building away from this workspace. The DOS build links `SMF.C`, `MIDISYN.C`, and `INSTR.C` as separate objects; it does not include or fork their source text.

The chart tool's `--ignore-meter-changes` option uses the opening meter for bar labels while keeping the full elapsed MIDI timeline. It is explicit because Call Me changes meter. The generated full-song chart is a separate, deliberately lossy normal-difficulty chart, not the soundtrack. The private chart and MIDI are retained only under ignored `PRIVATE/` for local verification.

Presentation effects reserve the PSG only while gameplay owns the soundtrack. Intro, title and results use the existing effects even while the song file remains loaded. Results effects start after the guarded soundtrack silence. Lean VU meters sample the last successfully emitted PSG attenuation word, not the next prepared frame. Dirty 14-pixel segments have a four-per-tick drawing budget with audio service between updates; M controls decoration independently. See QUALIFICATION.json for the measured cost against accepted build23.
