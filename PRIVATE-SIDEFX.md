# Private 8088 side-effect revision

Source base: full locally verified commit
`811fcf5bf7e76c604aa80d929538d6ab527a457a` in
`astrobleem/radio-shack-rave`. This checkout is independent of the song
transcription owner's checkout. All 19 source files in the private catalog's
`SOURCE/ENGINE-SNAPSHOT.tar` exactly match that commit. The catalog's accepted
95,060-byte DOS executable exactly matches this checkout's unchanged bundled
runtime: SHA256
`2ad3fec1ddb89df81587c4ea4065855af65c9a3a7fcebd7b299bc6260fde13c2`.

This revision is private. No song, launcher, accepted kit, CF/D: file or
published artifact is changed. Historical qualification fields describe the
bundled baseline; the candidate executable is a separate, unqualified build.

## Findings and source changes

`src/LEFT.H` previously selected an absolute eight-beat slot, then spent part
or all of that slot clearing/drawing. If the wipe crossed a slot boundary, the
next frame could begin another scene. Dwell now requires both 16 elapsed beats
and 146 BIOS ticks (just over eight seconds). It arms on the frame after the
background and first sprite pass complete, once the palette has flushed.
First rotozoom passes must finish before arming. Calm/FXOFF resume gets a
fresh dwell. Song/retry reset retains the scene rotation and starts a fresh
hold; no accumulated old slot is replayed.

`tools/gen_fx.py` retains the same phase functions, dithering, overlays, texture,
sine table, gradients and speeds. It combines phase colors and static overlays
into final 4-bit mode-9 pixels on the host. `src/FXDATA.H` stores seven packed
4,800-byte images; the rotozoom's blank background uses zero fill. `fx_row`
copies 48 contiguous bytes to the appropriate interleaved Tandy bank, rather
than expanding phase bytes and touching each overlay pixel at runtime.
Sprite restoration reads the same immutable image. No scene heap buffer,
512-byte expansion LUT or 48-byte scratch row remains.

The two-pass black/new-image curtain and highlight are retained. The maximum
rows per frame rises from 10 to 20, within the existing 24-unit credit and
72-unit cap. The worst credit/debt case still makes only one row of progress.
Fully credited wipes need 10 frames instead of 20; this is a work count, not
a hardware speed measurement. Audio is serviced every four wipe/reset rows
and between five-row rotozoom batches. The existing slow-core hysteresis and
heavy-scene exclusions remain.

`BEAT.C`, `CLOCK.H`, `CORE.H`, `DOSSND.*`, `GFX.H`, `PLAY.H`, `SHOW.H`, `SONGS.H`,
the judgment words, music/input clock and IRQ/timestamp logic are unchanged.
Palette writes still use only logical colors 3, 4, 7 and 9. No lane colors or
palette-flush behavior changed. Additional polling calls the existing audio
service with the running elapsed song clock; no clock pause or rewind occurs.

## Before/after work per image entry

Every scene's static image still writes 4,800 bytes to video memory. The old
decoder also copied 4,800 bytes into its heap buffer; the new path copies zero.

| Scene | Old phase-byte decodes | Old overlay runs | Old per-pixel overlay updates | New decode/run/pixel work |
| --- | ---: | ---: | ---: | ---: |
| DJ Alfredo | 2,400 | 689 | 3,179 | 0 |
| Plasma | 2,400 | 0 | 0 | 0 |
| Starburst | 2,400 | 30 | 156 | 0 |
| Tunnel | 2,400 | 44 | 316 | 0 |
| Rotozoom blank | 0 | 0 | 0 | 0 |
| Copper | 2,400 | 402 | 1,194 | 0 |
| Flag sky | 2,400 | 160 | 1,013 | 0 |
| Grid | 2,400 | 702 | 5,009 | 0 |

Packed far data increases from 24,916 to 33,600 bytes (+8,684). The 4,800-byte
scene heap allocation is eliminated. The installed Watcom 1.9 maps show DGROUP
shrinking by 576 bytes and linker memory increasing from 118,928 to 126,816
bytes. Both far data and DGROUP remain below 64 KiB. The checked MZ extra
allocation cap remains 4,096 paragraphs. Its maximum image-plus-grant bound is
157,600 bytes for the candidate (PSP/environment excluded), versus 149,152 for
the same-toolchain baseline. This does not measure actual free conventional
memory after loading a song. Native memory and physical speed remain pending.

## QA and builds

Host-only QA passes:

- All 34 existing production converter/loader/core/playlist tests.
- Strict C89 production-game lint with GCC, including warnings as errors.
- 56 complete 32-KiB Tandy bank-image / 16-color palette pairs equal the
  baseline byte for byte: eight backgrounds, first still figures and five
  subsequent animation/erase passes each.
- Model-clock tests for slow wipes that exceed the old slot, ready time,
  fast/slow tempo limits, calm/FXOFF, incomplete first rotozoom passes and
  palette flush delay. Synthetic work costs exercise scheduling only.
- Exactly unchanged production core, clock, sound, lanes and song paths.
- Palette captures leave all twelve non-effect palette entries unchanged.

Visual QA: `../evidence/SCENES-HOST.png` was inspected; accepted scene images,
Alfredo, cube, flag, texture and palette colors are preserved.
Raw outputs and hashes: `../evidence/leftfx/RESULTS.json`.
Provenance, work counts and MZ evidence: `../evidence/PROVENANCE-WORK.json`.
Suite output: `../evidence/candidate-host.log`.

The installed Windows cross-compiler is **OpenWatcom 1.9**, with DOS small model
`-0 -ox -w4`. It does not reproduce the accepted pinned Watcom 2 binary.
Same-toolchain baseline: 83,700 bytes, SHA256
`ccaf340708bba6e6f6f858398ac0aa42bd8d0639e9ea638670b13039471387df`.
Separate candidate: `../candidate-build/RSRAVE.EXE`, 92,148 bytes, SHA256
`b87302611488b8b61bbac61523b0a7df819f62f8d8e5ab453ee844c21e9b03b5`.
The two existing inline-assembly flags warnings are unchanged from baseline.
No DOS guest was used for those host cross-builds.

Reproduce host render/dwell QA with the baseline source extracted to an
independent directory:

```powershell
python tests/leftfx_host.py --baseline ../baseline-build/src --out ../evidence/leftfx --cc C:/WATCOM/binnt/wcl386.exe
python tests/run_checks.py --cc C:/WATCOM/binnt/wcl386.exe
```

## Remaining qualification

An explicit exclusive **10-minute shared emulator allocation** was requested.
Until granted, no guest may start. Use the shared lock
`C:\Users\chad\Documents\Codex\2026-10-06\tandy-emulator.lock`, reject competing
emulators, use a bounded owned PID, and record guest evidence separately from
the known DOSBox-X host shutdown failure. No emulator cycle setting can prove
4.77 MHz physical speed. A real Tandy must confirm initial drawing latency,
visible dwell, note readability and uninterrupted listening/input.

Do not publish, replace the accepted runtime, or write CF until that evidence
and the required delivery authorization exist. The stock historical native
smoke test's four-switch expectation reflects the old shorter dwell; this
private revision needs its scoped dwell checks before that expectation is
updated for adoption.
