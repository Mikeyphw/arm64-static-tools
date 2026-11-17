#!/system/bin/sh
MODDIR=${0%/*}
# Refresh installed entry point only after /data has mounted. No network or updates.
MODDIR="$MODDIR" sh "$MODDIR/ast/install-entrypoint.sh" >&2 || :
exit 0
