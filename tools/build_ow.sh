#!/bin/sh
# Cross-build the DOS game with OpenWatcom 2 on Linux/macOS/WSL.
# MSC6 + BUILD.BAT remains the reference DOS toolchain; this produces the
# same small-model 8088 program from the same source for previews and CI.
#   WATCOM=/opt/ow tools/build_ow.sh [output.exe]
set -e
: "${WATCOM:?set WATCOM to your OpenWatcom 2 install}"
case "$(uname -s)" in Darwin) bin=$WATCOM/bino64;; *) bin=$WATCOM/binl64;; esac
[ -x "$bin/wcl" ] || bin=$WATCOM/binl
export PATH=$bin:$PATH INCLUDE=$WATCOM/h
root=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-$root/runtime/RSRAVE.EXE}
tmp=$(mktemp -d)
cp -r "$root/src/." "$tmp/"
(cd "$tmp" && wcl -q -bt=dos -ms -0 -ox -w4 -fe=RSRAVE.EXE BEAT.C DOSSND.C)
cp "$tmp/RSRAVE.EXE" "$out"
python3 "$root/tools/cap_dos_memory.py" "$out"
rm -rf "$tmp"
echo "built $out"
