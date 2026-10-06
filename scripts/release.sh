#!/usr/bin/env bash
# release.sh — the CLI's release files, from HEAD: release/neutron + release/SHA256SUMS.
#
# The CLI is one Python file. `neutron setup` (and Collider's Set up button, when the CLI is not
# installed yet) downloads it from the latest release and checks it against SHA256SUMS.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
die() { echo "release.sh: $*" >&2; exit 1; }

git -C "$REPO" diff --quiet HEAD -- bin/neutron || die "bin/neutron has uncommitted changes"
VER="$(git -C "$REPO" show HEAD:bin/neutron | sed -n 's/^CLI_VERSION = "\(.*\)"/\1/p')"
[ -n "$VER" ] || die "no CLI_VERSION in bin/neutron"

OUT="$REPO/release"
rm -rf "$OUT"; mkdir -p "$OUT"
git -C "$REPO" show HEAD:bin/neutron > "$OUT/neutron"
chmod 755 "$OUT/neutron"
if grep -qF "$HOME/" "$OUT/neutron"; then
    die "bin/neutron contains $HOME/"
fi
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$OUT/neutron"
( cd "$OUT" && sha256sum neutron > SHA256SUMS )
echo "Built the neutron CLI $VER."
echo "Publish:"
echo "  git tag v$VER && git push origin v$VER"
echo "  gh release create v$VER release/neutron release/SHA256SUMS --title \"neutron CLI $VER\" --notes \"...\""
