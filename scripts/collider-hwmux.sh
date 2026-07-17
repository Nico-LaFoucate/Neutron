#!/usr/bin/env bash
#
# collider-hwmux.sh (v3) -- Hardware-export finalize shim for Premiere under Wine.
#
# Premiere's NVENC hardware export works under Wine, but Adobe's final MP4
# multiplex writes 0 bytes and deletes its temps. This daemon performs that
# missing interleave from Adobe's own elementary-stream temps:
#     <output>.<pid>.<tid>.m4v   (raw H.264)
#     <output>.<pid>.<tid>.aac   (ADTS AAC)
# It watches the export folder, grabs each temp as it appears, and on close
# muxes the pair into <output>.mp4 (overwriting the 0-byte file Adobe leaves).
#
# XMP metadata: Adobe writes <output>.mp4.xmp during finalize. Under Wine the
# "embed into output file" step (also part of finalize) doesn't run, so the
# sidecar is left behind even when the user chose an embed mode. --metadata
# lets the daemon honor the Premiere setting:
#     keep   (default) leave the .xmp as Adobe left it      -> "Create Sidecar File"
#     embed  embed .xmp into the .mp4, delete the sidecar    -> "Embed in Output File"
#     both   embed .xmp into the .mp4, keep the sidecar      -> "Embed ... and Create Sidecar"
#     strip  delete the .xmp, do not embed                   -> tidy output / "None"
# embed/both require exiftool (pacman -S perl-image-exiftool).
#
# USAGE: ./collider-hwmux.sh [--dir DIR] [--fps FPS] [--metadata MODE] [--grace SEC] [--keep]
# REQUIRES: inotify-tools (inotifywait), ffmpeg. (exiftool only for embed/both.)

set -u

DIR="$HOME/.premiere2025/drive_c/users/$USER/Documents"
FPS_OVERRIDE=""
DEFAULT_FPS="24000/1001"
META="keep"
GRACE=4
KEEP=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)      DIR="$2"; shift 2 ;;
        --fps)      FPS_OVERRIDE="$2"; shift 2 ;;
        --metadata) META="$2"; shift 2 ;;
        --grace)    GRACE="$2"; shift 2 ;;
        --keep)     KEEP=1; shift ;;
        -h|--help)  sed -n '2,33p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

case "$META" in
    keep|embed|both|strip) ;;
    *) echo "ERROR: --metadata must be keep|embed|both|strip" >&2; exit 2 ;;
esac

command -v inotifywait >/dev/null 2>&1 || { echo "ERROR: inotifywait not found (install inotify-tools)" >&2; exit 1; }
command -v ffmpeg      >/dev/null 2>&1 || { echo "ERROR: ffmpeg not found" >&2; exit 1; }
[ -d "$DIR" ] || { echo "ERROR: watch dir does not exist: $DIR" >&2; exit 1; }
if { [ "$META" = embed ] || [ "$META" = both ]; } && ! command -v exiftool >/dev/null 2>&1; then
    echo "[collider-hwmux] WARNING: --metadata $META needs exiftool (not found);"
    echo "[collider-hwmux]          will mux normally but cannot embed XMP. (pacman -S perl-image-exiftool)"
fi

# Stage on the SAME filesystem as DIR (sibling dir, NOT inside DIR so we don't
# watch our own files). Fall back to TMPDIR only if that fails.
PARENT="$(dirname "$DIR")"
if ! STAGE="$(mktemp -d "$PARENT/.collider-hwmux.XXXXXX" 2>/dev/null)"; then
    STAGE="$(mktemp -d "${TMPDIR:-/tmp}/collider-hwmux.XXXXXX")"
    echo "[collider-hwmux] WARNING: staging on a different filesystem ($STAGE);"
    echo "[collider-hwmux]          relying on copy-on-close (slightly racier)."
fi
cleanup() { [ "$KEEP" = 1 ] || rm -rf "$STAGE"; }

if ln "$0" "$STAGE/.lntest" 2>/dev/null; then
    rm -f "$STAGE/.lntest"; LINKMODE="hardlink (same fs, race-proof)"
else
    LINKMODE="copy-on-close (cross fs)"
fi

echo "[collider-hwmux] watching : $DIR"
echo "[collider-hwmux] staging  : $STAGE"
echo "[collider-hwmux] capture  : $LINKMODE"
echo "[collider-hwmux] fps      : ${FPS_OVERRIDE:-auto (xmp -> $DEFAULT_FPS)}"
echo "[collider-hwmux] metadata : $META"

resolve_fps() {
    local xmp="$1" raw=""
    if [ -n "$FPS_OVERRIDE" ]; then echo "$FPS_OVERRIDE"; return; fi
    if [ -f "$xmp" ]; then
        raw="$(grep -oiE 'videoFrameRate[^0-9]{0,4}[0-9]+(\.[0-9]+)?' "$xmp" 2>/dev/null \
               | grep -oE '[0-9]+(\.[0-9]+)?' | head -1)"
    fi
    [ -n "$raw" ] || { echo "$DEFAULT_FPS"; return; }
    case "$raw" in
        23.97|23.976|23.9760|23.976023|23.976024) echo "24000/1001" ;;
        29.97|29.970|29.97003)                     echo "30000/1001" ;;
        59.94|59.940|59.94006)                     echo "60000/1001" ;;
        47.95|47.952)                              echo "48000/1001" ;;
        119.88)                                    echo "120000/1001" ;;
        *)                                         echo "$raw" ;;
    esac
}

finalbase_of() { echo "$1" | sed -E 's/\.[0-9]+\.[0-9]+$//'; }

stage_grab() {
    local path="$1" base; base="$(basename "$path")"
    ln -f "$path" "$STAGE/$base" 2>/dev/null && return 0
    cp -f "$path" "$STAGE/$base" 2>/dev/null
}

# Honor the XMP export mode. Adobe leaves <out>.xmp; embed/both write it into
# the mp4 (exiftool) the way Adobe's finalize would have.
handle_xmp() {
    local out="$1" xmp="$1.xmp" i
    case "$META" in
        keep)  return ;;
        strip) [ -f "$xmp" ] && { rm -f "$xmp"; echo "[collider-hwmux] stripped sidecar $(basename "$xmp")"; }; return ;;
        embed|both) ;;
    esac
    # Adobe may still be writing the sidecar; wait briefly for it.
    for i in $(seq 1 $((GRACE * 2))); do
        [ -s "$xmp" ] && break
        sleep 0.5
    done
    [ -s "$xmp" ] || { echo "[collider-hwmux] note: no sidecar to embed for $(basename "$out")"; return; }
    command -v exiftool >/dev/null 2>&1 || { echo "[collider-hwmux] WARN: exiftool missing; leaving sidecar" >&2; return; }
    if exiftool -q -overwrite_original -tagsFromFile "$xmp" -all:all "$out" >/dev/null 2>&1; then
        echo "[collider-hwmux] embedded XMP -> $(basename "$out")"
        if [ "$META" = embed ]; then rm -f "$xmp"; echo "[collider-hwmux] removed sidecar $(basename "$xmp")"; fi
    else
        echo "[collider-hwmux] WARN: exiftool embed failed; leaving sidecar" >&2
    fi
}

do_mux() {
    local stem="$1" v="$2" a="$3"
    local lock="$STAGE/.lock.$stem"
    mkdir "$lock" 2>/dev/null || return
    if [ ! -s "$v" ]; then
        echo "[collider-hwmux] WARN: staged video empty/missing, skipping ($stem)" >&2
        rm -f "$v" "$a"; rmdir "$lock" 2>/dev/null; return
    fi

    local finalbase out fps abytes
    finalbase="$(finalbase_of "$stem")"
    out="$DIR/$finalbase.mp4"
    fps="$(resolve_fps "$DIR/$finalbase.mp4.xmp")"
    abytes=0; [ -s "$a" ] && abytes="$(stat -c%s "$a")"

    echo "[collider-hwmux] muxing -> $out  (fps=$fps, video=$(stat -c%s "$v")B, audio=${abytes}B)"
    if [ -s "$a" ]; then
        ffmpeg -loglevel error -y -r "$fps" -i "$v" -i "$a" -c copy -movflags +faststart "$out"
    else
        ffmpeg -loglevel error -y -r "$fps" -i "$v" -c copy -movflags +faststart "$out"
    fi
    if [ $? -eq 0 ] && [ -s "$out" ]; then
        echo "[collider-hwmux] OK: $(basename "$out") ($(stat -c%s "$out") bytes)"
        handle_xmp "$out"
    else
        echo "[collider-hwmux] ffmpeg FAILED for $out" >&2
    fi

    [ "$KEEP" = 1 ] || rm -f "$v" "$a"
    rmdir "$lock" 2>/dev/null
}

# Sweeper: video-only exports (no .aac) once the m4v has been idle >= GRACE.
(
    while true; do
        sleep "$GRACE"
        for v in "$STAGE"/*.m4v; do
            [ -e "$v" ] || continue
            stem="$(basename "$v" .m4v)"
            [ -f "$STAGE/$stem.aac" ] && continue
            age=$(( $(date +%s) - $(stat -c %Y "$v" 2>/dev/null || echo 0) ))
            [ "$age" -ge "$GRACE" ] && do_mux "$stem" "$v" ""
        done
    done
) &
SWEEPER=$!
trap 'cleanup; kill "$SWEEPER" 2>/dev/null' EXIT INT TERM

declare -A CLOSED

inotifywait -m -e create -e close_write --format '%e|%f' "$DIR" 2>/dev/null \
| while IFS='|' read -r ev f; do
    case "$f" in
        *.m4v|*.aac) ;;
        *) continue ;;
    esac
    path="$DIR/$f"
    base="$f"
    ext="${base##*.}"
    stem="${base%.*}"

    case "$ev" in
        *CREATE*)
            stage_grab "$path"
            ;;
        *CLOSE_WRITE*)
            stage_grab "$path"
            sz=$(stat -c%s "$STAGE/$base" 2>/dev/null || echo 0)
            echo "[collider-hwmux] captured $base ($sz bytes)"
            CLOSED["$stem.$ext"]=1
            v="$STAGE/$stem.m4v"; a="$STAGE/$stem.aac"
            if [ "${CLOSED[$stem.m4v]:-}" = 1 ] && [ "${CLOSED[$stem.aac]:-}" = 1 ] \
               && [ -s "$v" ] && [ -s "$a" ]; then
                do_mux "$stem" "$v" "$a"
            fi
            ;;
    esac
done
