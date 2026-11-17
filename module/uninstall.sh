#!/system/bin/sh
# Remove only our own entry point. Preserve recovery state for manual cleanup.
ENTRY=/data/local/tmp/ast
if [ -f "$ENTRY" ] && [ ! -L "$ENTRY" ] && \
    grep -q '^# AST_RECOVERY_ENTRYPOINT_V1$' "$ENTRY"; then
  rm -f "$ENTRY"
fi
exit 0
