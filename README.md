# Radio Shack Rave

You've got questions. We've got bangers.

An independent three-key DOS rhythm game for Tandy 1000 EX class machines:
320x200, 16 colors and three PSG tone voices. Tap **Z / X / C** as notes reach
the cyan line. Timing allows three BIOS ticks either side (about 165 ms).
Hits build score and combo; NICE!, AWESOME! and MISS! appear beside the lanes.
Backing and uncharted melody continue after misses. Required notes sound only
when hit. Holding a key produces one tap until release.

This is the latest **v5 engine**, including v4 side patterns and judgment words.
The public package uses its tested plain title fallback. Supplied Radio Shack
logo bitmap assets are omitted because no redistribution grant was recorded.
The DOS game and converter are otherwise the current bytes; no older build is
substituted. There is no official Radio Shack sponsorship or affiliation.

## Play the original demo

Extract the DOS ZIP into a new folder such as `C:\RAVE`. From that folder run
`PLAY`. No Python is needed on the DOS machine. **Space** starts, **R** retries,
**M** toggles calm decoration, **Esc** exits. A two-second ready period follows
Space; retries go straight to that ready period. Calm mode freezes background
motion while keeping playable notes and judgment words. No strobe effect.

The original 32-second composition **Circuit After Hours** contains 128 lead
onsets: 64 required taps and 64 automatic notes. Its source MML and permissive
music grant are included. No commercial songs, samples, supplied logo pixels,
private notation or private listening recordings are distributed.

## Convert your own score on a modern computer

Use Python 3 (standard library only):

```
python tools/import_score.py music/ORIGINAL.MML runtime/ORIGINAL.RBG --lead 1 --parts 1,2,3 --difficulty normal
python tools/import_score.py your-song.mml MYSONG.RBG --lead 1 --difficulty easy
```

Copy the generated RBG beside the DOS executable and run `RSRAVE MYSONG.RBG`.
The converter also writes a deterministic selection/report JSON and normalized
event JSON. Choose the lead explicitly when automatic voice ranking selects
accompaniment. All authored lead onsets remain audible: density thinning marks
some as automatic; it does not discard them. Misses suppress required tones.

Bounded ArcheAge-style MML profile: optional `MML@...;`, case-insensitive notes,
rests, sharps/flats, octaves, lengths, dots, tempo, volume, same-pitch ties and
up to eight comma voices. Defaults O4/L4/T120/V100 are reported. Tempo conflicts,
unknown syntax, overflow and unsupported effects fail with explanatory errors.
Selected PSG voices must fit MIDI 45..96; use explicit transposition, never
clamping. Up to three tones are selected; no invented noise/percussion layer.
Runtime bounds are 512 total lead events, 1024 backing states and 600 seconds.
Longer/dense scores need explicit arrangement choices; they are not truncated.

## Build and checks

Corresponding source is under `src`, including the unchanged cooperative
sound adapter and nested PITCORE header. Use your own existing Microsoft C 6
DOS toolchain, small model `/G0 /AS /O /W3`, then `BUILD.BAT`. It caps extra DOS
allocation with LINK `/CP:4096`. No compiler, DOS/Windows or emulator binaries
are bundled. Runtime uses integer geometry, bounded static buffers and elapsed
BIOS ticks; it never reprograms PIT0. Exit restores video, IRQ1, sound ownership
and speaker state. Run in an exclusive plain-DOS foreground session.

`python -B tests/run_checks.py --cc gcc` runs portable host checks against the
actual C judgment core, generic MML validation and original golden outputs.
GitHub CI covers these host checks, not DOS hardware, listening or desktop input.
Native release qualification is recorded in `QUALIFICATION.json` and evidence.
For native reproduction, provide your own toolchain at DOS C:, mount the source
package at D: and a fresh scratch directory at E:. Copy `tests/BAD.RBG` to that
scratch directory and create its `evidence` subdirectory. From D: run
`tests\NATIVE.BAT` in an exclusive Tandy DOS session. It rebuilds and runs the
recorded diagnostics, writes output only into the package/scratch directories,
then exits. Coordinate emulator ownership yourself; no shared PC lock or local
host path is bundled. Screenshot dumps are diagnostics, not hardware timing.

V4 visuals and v5 startup/fallback have source-matched MSC6/DOSBox checks for
audio/score equivalence, misses, calm, retry, input spam and cleanup. A previous
build was reported playable on the physical Tandy; that does not qualify v5.
DOSBox cycle settings are not calibrated 4.77 MHz performance measurements.
The final original-demo combination passed its allocated native qualification:
exact rebuild, full hit/miss traces, calm, retry, spam, exit and plain-title
cleanup. Native game/title captures are in `evidence/NATIVE`. This remains an
experimental release; physical v5 acceptance and human timing feel are pending.

Game/converter: GPL version 3, `LICENSE` and `NOTICE.TXT`. Original music has a
separate permissive grant in `music/LICENSE.TXT`. Keep source/notices with forks.
