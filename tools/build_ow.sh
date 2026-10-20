#!/bin/sh
# Cross-build the DOS game with OpenWatcom 2 on Linux/macOS/WSL.
# MSC6 + BUILD.BAT remains the reference DOS toolchain; this produces the
# medium-code-model 8088 program from the same source for previews and CI.
#   WATCOM=/opt/ow tools/build_ow.sh [output.exe]
set -e
: "${WATCOM:?set WATCOM to your OpenWatcom 2 install}"
case "$(uname -s)" in Darwin) bin=$WATCOM/bino64;; *) bin=$WATCOM/binl64;; esac
[ -x "$bin/wcl" ] || bin=$WATCOM/binl
export PATH=$bin:$PATH INCLUDE=$WATCOM/h
root=$(cd "$(dirname "$0")/.." && pwd)
libtandy=${LIBTANDY:-$root/deps/libtandy}
[ -f "$libtandy/sound/SMF.C" ] || {
  echo "run python3 tools/fetch_sound_deps.py or set LIBTANDY to the pinned public source" >&2
  exit 2
}
out=${1:-$root/runtime/RSRAVE.EXE}
tmp=$(mktemp -d)
cp -r "$root/src/." "$tmp/"
(cd "$tmp" && wcl -q -bt=dos -mm -0 -ox -w4 \
  -i="$libtandy/include" -i="$libtandy/sound" -fe=RSRAVE.EXE \
  BEAT.C DOSSND.C RAVEMID.C "$libtandy/sound/SMF.C" \
  "$libtandy/sound/MIDISYN.C" "$libtandy/sound/INSTR.C")
cp "$tmp/RSRAVE.EXE" "$out"
python3 "$root/tools/cap_dos_memory.py" "$out"
rm -rf "$tmp"
echo "built $out"
