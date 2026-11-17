#!/system/bin/sh
# AST_RECOVERY_ENTRYPOINT_V1
# Run using `sh /data/local/tmp/ast` if recovery has no /system/bin/sh.
set -u
umask 077

ast_err() { printf 'AST: %s\n' "$*" >&2; }
ast_die() { ast_err "$*"; exit 1; }

# No eval, environment sourcing or execution from /data/local/tmp beyond this file.
# AST_ROOT is only honored for non-root test mode.
AST_ROOT=/data/adb/modules/arm64_static_tools
if [ "$(id -u 2>/dev/null)" != 0 ] && [ -n "${AST_TEST_ROOT:-}" ]; then
  AST_ROOT=$AST_TEST_ROOT
fi
if [ ! -f "$AST_ROOT/module.prop" ] && [ -f /data/adb/modules_update/arm64_static_tools/module.prop ]; then
  AST_ROOT=/data/adb/modules_update/arm64_static_tools
fi
[ -f "$AST_ROOT/module.prop" ] || ast_die "Module files unavailable: mount and decrypt /data first."
[ -d "$AST_ROOT/system/bin" ] || ast_die "Module binary directory missing."
if [ -L "$AST_ROOT" ] || [ -L "$AST_ROOT/system/bin" ]; then ast_die "Unsafe module symlink refused"; fi

AST_MODE=android
if [ "${AST_FORCE_RECOVERY:-0}" = 1 ] || [ -e /sbin/recovery ] || [ -e /twres ] || [ -e /etc/recovery.fstab ]; then AST_MODE=recovery; fi
AST_STATE=/data/adb/arm64-static-tools
if [ "$(id -u 2>/dev/null)" != 0 ] && [ -n "${AST_TEST_STATE:-}" ]; then AST_STATE=$AST_TEST_STATE; fi
if [ -L "$AST_STATE" ]; then ast_die "Unsafe state symlink refused"; fi
if [ ! -d "$AST_STATE" ]; then mkdir -m 700 -p "$AST_STATE" 2>/dev/null || ast_die "Cannot initialize writable state at $AST_STATE"; fi
chmod 700 "$AST_STATE" 2>/dev/null || :
AST_HOME=$AST_STATE/home
AST_ZDOTDIR=$AST_STATE/zsh
AST_CACHE=$AST_STATE/cache
AST_TMP=$AST_STATE/tmp
AST_PYTHON=$AST_ROOT/ast/runtime/python/bin/python3
for p in "$AST_HOME" "$AST_ZDOTDIR" "$AST_CACHE" "$AST_TMP"; do
  [ ! -L "$p" ] || ast_die "Unsafe state symlink $p"
  if [ ! -d "$p" ]; then mkdir -m 700 -p "$p" || ast_die "Cannot create $p"; fi
  chmod 700 "$p" 2>/dev/null || :
done
# Keep the recovery shell independent of Py2Droid and systemless mounts.
PATH="$AST_ROOT/ast/runtime/python/bin:$AST_ROOT/system/bin:/sbin:/system/bin:/system/xbin:/bin:/usr/bin"
HOME=$AST_HOME
ZDOTDIR=$AST_ZDOTDIR
XDG_CONFIG_HOME=$AST_STATE/config
XDG_CACHE_HOME=$AST_CACHE
XDG_DATA_HOME=$AST_STATE/share
TMPDIR=$AST_TMP
PYTHONHOME="$AST_ROOT/ast/runtime/python"
PYTHONPATH="$AST_ROOT/ast/runtime/python/site-packages"
PYTHONNOUSERSITE=1
PYTHONDONTWRITEBYTECODE=1
PYTHONSAFEPATH=1
export AST_ROOT AST_STATE AST_HOME AST_ZDOTDIR AST_CACHE AST_MODE AST_PYTHON PATH HOME ZDOTDIR XDG_CONFIG_HOME XDG_CACHE_HOME XDG_DATA_HOME TMPDIR PYTHONHOME PYTHONPATH PYTHONNOUSERSITE PYTHONDONTWRITEBYTECODE PYTHONSAFEPATH
if [ -z "${TERM:-}" ]; then TERM=vt100; export TERM; fi
# Explicit test probe, never used in installed module.
if [ "${AST_TEST_PRINT_ENV:-0}" = 1 ]; then printf 'AST_ROOT=%s\nAST_MODE=%s\nHOME=%s\nZDOTDIR=%s\nPATH=%s\n' "$AST_ROOT" "$AST_MODE" "$HOME" "$ZDOTDIR" "$PATH"; exit 0; fi

ast_doctor() {
  printf 'AST Recovery doctor\nmode=%s\nroot=%s\nstate=%s\nterm=%s\n' "$AST_MODE" "$AST_ROOT" "$AST_STATE" "$TERM"
  if [ -x "$AST_PYTHON" ]; then echo "OK   embedded static Python"; else echo "MISS embedded static Python (terminal still works)"; fi
  for tool in zsh busybox fzf jq lsd bat oh-my-posh; do
    if [ -x "$AST_ROOT/system/bin/$tool" ]; then printf 'OK   %s\n' "$tool"; else printf 'MISS %s\n' "$tool"; fi
  done
  if [ -r "$AST_ROOT/ast/zinit/zinit.zsh" ]; then echo 'OK   zinit offline'; else echo 'MISS zinit offline (shell remains usable)'; fi
  if [ -f "$AST_ROOT/ast/themes/ast-compact.omp.json" ]; then echo 'OK   prompt themes'; fi
  if [ -w "$AST_STATE" ]; then echo 'OK   state writable'; else echo 'WARN state not writable'; fi
}

ast_shell() {
  if [ -x "$AST_ROOT/system/bin/zsh" ]; then
    # Avoid importing arbitrary profile from writable HOME.
    if [ "${AST_SAFE:-0}" = 1 ]; then exec "$AST_ROOT/system/bin/zsh" -f -i; fi
    if [ -L "$AST_ZDOTDIR/.zshrc" ]; then ast_die "Unsafe Zsh profile symlink"; fi
    if [ ! -f "$AST_ZDOTDIR/.zshrc" ]; then
      ( umask 077; printf '%s\n' '[[ -r "$AST_ROOT/ast/zshrc" ]] && source "$AST_ROOT/ast/zshrc"' > "$AST_ZDOTDIR/.zshrc" ) || ast_die "Cannot initialize Zsh profile"
      chmod 600 "$AST_ZDOTDIR/.zshrc" 2>/dev/null || :
    fi
    exec "$AST_ROOT/system/bin/zsh" -i
  fi
  ast_err 'Zsh unavailable; falling back to recovery sh'
  if [ -x "$AST_ROOT/system/bin/busybox" ]; then exec "$AST_ROOT/system/bin/busybox" sh; fi
  exec sh
}

ast_python() {
  [ -x "$AST_PYTHON" ] && [ -f "$AST_ROOT/ast/manager/main.py" ] || {
    ast_err 'Embedded Python / Rich dashboard unavailable; Zsh and CLI remain functional'
    return 127
  }
  [ ! -L "$AST_ROOT/ast/runtime" ] && [ ! -L "$AST_ROOT/ast/runtime/python" ] && \
  [ ! -L "$AST_ROOT/ast/manager" ] && [ ! -L "$AST_PYTHON" ] && \
  [ ! -L "$AST_ROOT/ast/manager/main.py" ] || {
    ast_err 'Unsafe Python / dashboard symlink refused'; return 126;
  }
  "$AST_PYTHON" -s "$AST_ROOT/ast/manager/main.py" "$@"
}

if [ "$#" -eq 0 ]; then ast_shell; fi
case "$1" in
  shell|--shell) shift; [ "$#" -eq 0 ] || ast_die 'shell takes no arguments'; ast_shell ;;
  --safe|safe) AST_SAFE=1; export AST_SAFE; shift; [ "$#" -eq 0 ] || ast_die 'safe takes no arguments'; ast_shell ;;
  doctor|--doctor)
    shift
    if [ -x "$AST_PYTHON" ]; then
      if ast_python doctor "$@"; then :
      elif [ "$#" -eq 0 ]; then ast_doctor
      else ast_die 'Structured diagnostics unavailable; no invalid JSON emitted'
      fi
    else
      [ "$#" -eq 0 ] || ast_die 'Embedded Python unavailable for structured diagnostics'
      ast_doctor
    fi ;;
  theme)
    shift
    case "${1:-list}" in
      list) printf 'modern\ncompact\nminimal\n';;
      show) if [ -f "$AST_STATE/theme" ]; then cat "$AST_STATE/theme"; else echo compact; fi;;
      set)
        case "${2:-}" in modern|compact|minimal) : ;; *) ast_die 'Theme must be modern, compact or minimal' ;; esac
        [ ! -L "$AST_STATE/theme" ] || ast_die 'Unsafe theme state symlink'
        ( umask 077; printf '%s\n' "$2" > "$AST_STATE/theme.new.$$" ) || ast_die 'Cannot save theme'
        mv -f "$AST_STATE/theme.new.$$" "$AST_STATE/theme" || ast_die 'Cannot activate theme'
        printf 'AST theme selected: %s (restart Zsh to apply)\n' "$2" ;;
      *) ast_die 'Usage: ast theme [list|show|set modern|compact|minimal]' ;;
    esac ;;
  plugins)
    shift
    case "${1:-list}" in
      list)
        for plug in zsh-autosuggestions zsh-syntax-highlighting zsh-completions zsh-history-substring-search fzf-tab; do
          if [ -d "$AST_ROOT/ast/plugins/$plug" ]; then
            if [ -f "$AST_STATE/disabled-plugins" ] && grep -Fxq "$plug" "$AST_STATE/disabled-plugins"; then
              printf '[off] %s\n' "$plug"
            else printf '[on]  %s\n' "$plug"; fi
          else printf '[missing] %s\n' "$plug"; fi
        done ;;
      enable|disable)
        action=$1; plug=${2:-}
        case "$plug" in zsh-autosuggestions|zsh-syntax-highlighting|zsh-completions|zsh-history-substring-search|fzf-tab) : ;; *) ast_die 'Unknown plugin' ;; esac
        [ ! -L "$AST_STATE/disabled-plugins" ] || ast_die 'Unsafe disabled-plugins symlink'
        if [ -f "$AST_STATE/disabled-plugins" ]; then
          grep -Fxv "$plug" "$AST_STATE/disabled-plugins" > "$AST_STATE/disabled-plugins.new.$$" || :
        else : > "$AST_STATE/disabled-plugins.new.$$"; fi
        if [ "$action" = disable ]; then printf '%s\n' "$plug" >> "$AST_STATE/disabled-plugins.new.$$"; fi
        chmod 600 "$AST_STATE/disabled-plugins.new.$$" || :
        mv -f "$AST_STATE/disabled-plugins.new.$$" "$AST_STATE/disabled-plugins" || ast_die 'Unable to save plugin settings'
        printf 'AST: %sd %s (restart shell)\n' "$action" "$plug" ;;
      *) ast_die 'Usage: ast plugins [list|enable NAME|disable NAME]' ;;
    esac ;;
  menu|modules|vector|backups) cmd=$1; shift; ast_python "$cmd" "$@" ;;
  python) shift; [ -x "$AST_PYTHON" ] || ast_die 'Embedded Python unavailable'; exec "$AST_PYTHON" "$@" ;;
  py2droid)
    shift
    [ "$#" -eq 0 ] || ast_die 'Py2Droid is diagnostic-only until external ABI/linker qualification'
    [ -f /data/adb/py2droid/usr/bin/python3 ] && [ ! -L /data/adb/py2droid/usr/bin/python3 ] || ast_die 'Py2Droid unavailable'
    ast_err 'Py2Droid detected, but recovery compatibility is not yet qualified'
    ast_err 'No external interpreter or module scripts were executed'
    ;;
  --) shift; [ "$#" -gt 0 ] || ast_die 'Missing command after --'; exec "$@" ;;
  *) ast_die 'Usage: ast [shell|safe|doctor|theme|plugins|menu|modules|vector|backups|python|py2droid|-- command...]' ;;
esac
