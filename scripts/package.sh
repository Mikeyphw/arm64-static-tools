#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
rm -rf build/module
mkdir -p build/module/system/bin build/module/system/etc/arm64-static-tools dist
cp -a module/. build/module/
cp -a build/bin/. build/module/system/bin/
cp build/provenance.json manifest/sources.json build/module/system/etc/arm64-static-tools/
# module installer scripts should be executable
chmod 0755 build/module/customize.sh build/module/post-fs-data.sh
find build/module/system/bin -type f -exec chmod 0755 {} +
VERSION=$(awk -F= '$1=="version"{print $2}' module/module.prop)
OUT="dist/arm64-static-tools-${VERSION}.zip"
rm -f "$OUT"
(cd build/module && zip -qr "$ROOT/$OUT" .)
sha256sum "$OUT" > "$OUT.sha256"
echo "$OUT"
