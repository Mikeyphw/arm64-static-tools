#!/system/bin/sh
SKIPUNZIP=0

ui_print "- ARM64 Static Tools"
ui_print "- Prebuilt-only toolkit; no source compilation"

ABI="$(getprop ro.product.cpu.abi 2>/dev/null)"
case "$ABI" in
  arm64-v8a|aarch64) ;;
  *)
    ui_print "! Unsupported ABI: ${ABI:-unknown}"
    ui_print "! This module supports ARM64 only."
    abort "Unsupported architecture"
    ;;
esac

set_perm_recursive "$MODPATH/system/bin" 0 0 0755 0755
set_perm_recursive "$MODPATH/system/etc/arm64-static-tools" 0 0 0755 0644
[ -d "$MODPATH/system/share" ] && set_perm_recursive "$MODPATH/system/share" 0 0 0755 0644

# Recovery entry point also works when systemless /system/bin mounts are absent.
set_perm_recursive "$MODPATH/ast" 0 0 0755 0644
set_perm "$MODPATH/ast/entrypoint.sh" 0 0 0755
set_perm "$MODPATH/ast/install-entrypoint.sh" 0 0 0755
[ -f "$MODPATH/ast/runtime/python/bin/python3" ] && set_perm "$MODPATH/ast/runtime/python/bin/python3" 0 0 0755
MODDIR="$MODPATH" sh "$MODPATH/ast/install-entrypoint.sh" || \
  abort "Cannot install trusted AST recovery entry point"
