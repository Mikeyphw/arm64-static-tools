#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

DIST_DIR=${DIST_DIR:-"$ROOT/dist"}
mkdir -p "$DIST_DIR" "$ROOT/build"
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/arm64-static-tools-module.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/system/bin" "$STAGE/system/etc/arm64-static-tools"

# Module source is text-only; binaries are materialized directly from the external
# cache into this temporary staging tree and disappear when packaging completes.
cp -a module/. "$STAGE/"
python3 scripts/fetch.py \
  --mode locked \
  --export-dir "$STAGE/system/bin" \
  --provenance "$ROOT/build/provenance.json"

cp build/provenance.json manifest/sources.json manifest/lock.json \
  "$STAGE/system/etc/arm64-static-tools/"
chmod 0755 "$STAGE/customize.sh" "$STAGE/post-fs-data.sh"
find "$STAGE/system/bin" -type f -exec chmod 0755 {} +

VERSION=$(awk -F= '$1=="version"{print $2}' module/module.prop)
OUT="$DIST_DIR/arm64-static-tools-${VERSION}.zip"
rm -f "$OUT" "$OUT.sha256"
(cd "$STAGE" && zip -qr "$OUT" .)
sha256sum "$OUT" > "$OUT.sha256"
printf '%s\n' "$OUT"
