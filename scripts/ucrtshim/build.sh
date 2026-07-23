#!/usr/bin/env bash
# Build the Neutron ucrtbase FH4 + "\\?\"-strip shim from MS's real UCRT.
#
#   build.sh <ucrtbase_orig.dll> <out ucrtbase.dll>
#
# Reproducible source for the 64-bit proxy that `neutron runtime capture` bakes into the
# bundle (replacing the opaquely-captured one) and `neutron prefix provision` stages into
# every Adobe prefix. See stub.c for what the two fixes are and why. Requires the mingw-w64
# toolchain (x86_64-w64-mingw32-gcc + objdump). 64-bit only — the FH4 proxy and the
# MainConcept muxer are 64-bit; the 32-bit ucrtbase is MS's real one, shipped untouched.
set -euo pipefail

ORIG="${1:?usage: build.sh <ucrtbase_orig.dll> <out ucrtbase.dll>}"
OUT="${2:?usage: build.sh <ucrtbase_orig.dll> <out ucrtbase.dll>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
CC=x86_64-w64-mingw32-gcc
OBJDUMP=x86_64-w64-mingw32-objdump

command -v "$CC"      >/dev/null 2>&1 || { echo "build-ucrtshim: $CC not found (install mingw-w64)" >&2; exit 2; }
command -v "$OBJDUMP" >/dev/null 2>&1 || { echo "build-ucrtshim: $OBJDUMP not found (install mingw-w64)" >&2; exit 2; }
[ -f "$ORIG" ] || { echo "build-ucrtshim: input not found: $ORIG" >&2; exit 2; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
DEF="$TMP/ucrt.def"

# .def: add __CxxFrameHandler4 (from vcruntime140_1) + our local _wstat64, then forward
# every OTHER real export back to ucrtbase_orig.
{
    echo 'LIBRARY "ucrtbase.dll"'
    echo 'EXPORTS'
    echo '    __CxxFrameHandler4 = vcruntime140_1.__CxxFrameHandler4'
    echo '    _wstat64'
    "$OBJDUMP" -p "$ORIG" | awk '
        /\+base\[/ {
            n = $NF
            if (n ~ /^[A-Za-z_?@]/ && n != "__CxxFrameHandler4" && n != "_wstat64")
                printf "    %s = ucrtbase_orig.%s\n", n, n
        }'
} > "$DEF"

"$CC" -shared -nostdlib -O2 -o "$OUT" "$HERE/stub.c" "$DEF" -Wl,-e,DllMain -lkernel32

# Sanity: FH4 must be a forwarder to vcruntime140_1, and _wstat64 must be LOCAL (our
# override), not a forwarder back to ucrtbase_orig. (Dump to a file first — piping into
# `grep -q` closes the pipe early and, under `set -o pipefail`, misreports SIGPIPE as a
# build failure.)
DUMP="$TMP/out.exports"
"$OBJDUMP" -p "$OUT" > "$DUMP"
grep -q "Forwarder RVA -- vcruntime140_1.__CxxFrameHandler4" "$DUMP" \
    || { echo "build-ucrtshim: __CxxFrameHandler4 forwarder missing in output" >&2; exit 3; }
if grep -qE "Forwarder RVA -- ucrtbase_orig\._wstat64$" "$DUMP"; then
    echo "build-ucrtshim: _wstat64 is still forwarded (override not applied)" >&2; exit 3
fi

echo "build-ucrtshim: built $OUT ($(stat -c%s "$OUT") bytes) from $(basename "$ORIG")"
