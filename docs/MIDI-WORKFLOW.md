# Private MIDI workflow

Run `python tools/rave_workbench.py` with the existing Python/Tk installation.
The tools use the standard library. Downloaded files and arrangements are local
data in ignored `midi-local/` and `SONGS/` folders. No outside song is bundled.

Open a MIDI, choose the lead and up to two backing parts, select a short bar
span, Arrange, Play, and save. Track suggestions are guesses from note counts
and registers; listen before accepting them. Channel 10 is imported
automatically as percussion. Assigning it to a tone voice is rejected.
GUI chart thinning uses the existing metrical policy and forgiving input-window
eligibility; every other lead event remains automatic. CLI defaults to the
legacy elapsed policy, or accepts `--chart-policy metrical`.

The saved `.arrangement.json` is authoritative. It holds the original PPQ,
tempo map, excerpt bounds, tone grid runs and transpositions, and every measured
percussion onset/key/velocity. `.mml` is a tone editing companion with one rounded
tempo; importing it alone loses percussion and original tempo changes.
Use the sidecar command printed in the report:

```console
python tools/midi_to_mml.py YOUR.mid --list
python tools/midi_to_mml.py YOUR.mid --voice 1.1:top --voice 2.2:bottom --from-bar 1 --to-bar 9 --title "MY ORIGINAL" --chart-policy metrical --check -o SONGS/ORIGINAL.mml
python tools/midi_arrangement.py SONGS/ORIGINAL.arrangement.json SONGS/ORIGINAL.RBG
```

`--to-bar` is exclusive; the GUI's last bar is inclusive. Track/channel numbers
come from the file's listing. GUI output names use the first eight safe title
characters for DOS 8.3 compatibility. Review the reported output name before
copying it into an existing song catalog.

Exact rational SMF tempo integration maps both tone grid boundaries and
measured drum attacks onto the game clock. A tempo override explicitly flattens
playback; the drum ledger retains both measured and changed playback times.
Meter changes currently produce an explicit rejection; split the source into
constant-meter files. The game's four-quarter visual accents do not express
every musical meter.

RBG5 has one noise channel. Hits rounding to the same BIOS tick use the cue
skill's priority: kick, snare, crash, low tom, high tom, open hat, closed hat.
Within a kind, louder velocity wins; stable source order resolves ties. Every
losing source hit is retained in the report. This priority is separately
declared from the legacy MML drum importer, whose behavior is unchanged.
GM keys map to the existing seven-kind noise kit. Unknown percussion keys are
rejected. Velocities 1..127 map to 16 attenuation levels; they remain exact in
the source ledger. An endpoint hit may extend native duration by one BIOS tick,
reported as `native_tail_extension_ticks`.

The report also records tone polyphony/grid reductions, source event ticks,
carry-in omissions, end cuts, octave shifts/folding, and unsupported controller,
patch, sustain and pitch-bend event counts. Tone output uses fixed selected
voice levels. The converter does not synthesize General MIDI instruments.

The preview reads actual delivered RBG bytes, plays all lead events as an
auto/reference run, and applies the native drum priority, timing, kit envelope
and single-noise interruption. It approximates PSG square/noise waveforms;
it is not physical hardware audio. `midi_preview.render_comparison` makes a
stereo WAV: full source MIDI oscillator/percussion approximation on the left,
reduced game preview on the right. Neither side is an original recording.

Bounds: MIDI 8 MiB, 256 tracks, 100,000 attacks per track and 500,000 per file;
50,000 grid cells and 5,000,000 reduction cell operations per selected voice;
MML 131,072 bytes; native 2,048 lead events,
4,096 backing states, 4,096 noise hits, 64 beat segments, 600 seconds. Unknown
formats/SMPTE division, malformed bytes/sidecars, incompatible ranges and
collapsed lead intervals fail explicitly. No song is silently trimmed to fit.

The downloader permits HTTP(S) data only, validates the full bounded SMF before
replacing a file, rejects path/reserved-name escapes, and saves source/resolved/
final URLs plus byte size and SHA-256. Existing files remain unless forced.
Downloaded MIDI is never executed. Eligibility must be established separately
before distributing any third-party MIDI or arrangement.
