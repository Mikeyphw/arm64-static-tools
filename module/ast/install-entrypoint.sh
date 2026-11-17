#!/system/bin/sh
# AST_RECOVERY_ENTRYPOINT_INSTALLER_V1
# Root manager installer/service only. Never follow symlink destinations.
set -eu
umask 077
MODDIR=${MODDIR:-${0%/*}/..}
SOURCE="$MODDIR/ast/entrypoint.sh"
TARGET=/data/local/tmp/ast
[ -f "$SOURCE" ] && [ ! -L "$SOURCE" ] || { echo 'AST: missing trusted launcher source' >&2; exit 1; }
[ -d /data/local/tmp ] && [ ! -L /data/local/tmp ] || { echo 'AST: /data/local/tmp unavailable or unsafe' >&2; exit 1; }
if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
  [ -f "$TARGET" ] && [ ! -L "$TARGET" ] && grep -q '^# AST_RECOVERY_ENTRYPOINT_V1$' "$TARGET" || {
    echo 'AST: existing /data/local/tmp/ast is not AST-owned, refusing overwrite' >&2; exit 1;
  }
fi
STAGE=/data/local/tmp/.ast-stage-$$
( umask 077; mkdir "$STAGE" ) || { echo 'AST: cannot reserve private staging directory' >&2; exit 1; }
trap 'rm -f "$STAGE/entrypoint"; rmdir "$STAGE"' 0 1 2 3 15
( umask 077; cat "$SOURCE" > "$STAGE/entrypoint" )
chmod 0755 "$STAGE/entrypoint"
chown 0:0 "$STAGE/entrypoint" 2>/dev/null || :
# Only atomic rename, no copying files into the installed module or /system.
mv -f "$STAGE/entrypoint" "$TARGET"
rmdir "$STAGE"
trap - 0 1 2 3 15
exit 0
