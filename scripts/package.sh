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
python3 scripts/package_plugins.py --out "$STAGE/ast"
# Native manager update URL is stamped from an explicitly provided or
# verified canonical GitHub origin. Never guess a module-release address.
RELEASE_REPO=${AST_RELEASE_REPOSITORY:-}
if [[ -z "$RELEASE_REPO" ]]; then
  origin=$(git remote get-url origin 2>/dev/null || true)
  if [[ "$origin" =~ ^git@github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(\.git)?$ ]]; then
    RELEASE_REPO=${BASH_REMATCH[1]%.git}
  elif [[ "$origin" =~ ^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(\.git)?/?$ ]]; then
    RELEASE_REPO=${BASH_REMATCH[1]%.git}
  fi
fi
if [[ -n "$RELEASE_REPO" ]]; then
  [[ "$RELEASE_REPO" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo 'Invalid release repository' >&2; exit 1; }
  printf 'updateJson=https://github.com/%s/releases/latest/download/update.json\n' "$RELEASE_REPO" >> "$STAGE/module.prop"
else
  echo 'WARN: no verified GitHub release origin; no updateJson stamped in this developer build' >&2
fi
chmod 0755 "$STAGE/customize.sh" "$STAGE/post-fs-data.sh" "$STAGE/service.sh" "$STAGE/uninstall.sh" "$STAGE/ast/entrypoint.sh" "$STAGE/ast/install-entrypoint.sh"
find "$STAGE/system/bin" -type f -exec chmod 0755 {} +

VERSION=$(awk -F= '$1=="version"{print $2}' module/module.prop)
OUT="$DIST_DIR/arm64-static-tools-${VERSION}.zip"
rm -f "$OUT" "$OUT.sha256"
(cd "$STAGE" && zip -qr "$OUT" .)
sha256sum "$OUT" > "$OUT.sha256"
printf '%s\n' "$OUT"
