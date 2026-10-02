#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ZIP=${1:-}

if [[ -z "$ZIP" ]]; then
  ZIP=$(ls -1t "$ROOT"/dist/arm64-static-tools-*.zip 2>/dev/null | head -n1 || true)
fi
[[ -n "$ZIP" && -f "$ZIP" ]] || { echo "No module ZIP found. Run: make package" >&2; exit 1; }

run_root() {
  if [[ $(id -u) -eq 0 ]]; then
    "$@"
  elif command -v su >/dev/null 2>&1; then
    local quoted=""
    printf -v quoted '%q ' "$@"
    su -c "$quoted"
  else
    echo "Root shell/su is required to install a module." >&2
    exit 1
  fi
}

manager=${MODULE_MANAGER:-auto}
if [[ "$manager" == auto || "$manager" == magisk ]]; then
  if run_root sh -c 'command -v magisk >/dev/null 2>&1' 2>/dev/null; then
    echo "Installing with Magisk: $ZIP"
    run_root magisk --install-module "$ZIP"
    exit 0
  elif [[ "$manager" == magisk ]]; then
    echo "Magisk CLI not found." >&2; exit 1
  fi
fi
if [[ "$manager" == auto || "$manager" == kernelsu ]]; then
  if run_root sh -c 'command -v ksud >/dev/null 2>&1' 2>/dev/null; then
    echo "Installing with KernelSU: $ZIP"
    run_root ksud module install "$ZIP"
    exit 0
  elif [[ "$manager" == kernelsu ]]; then
    echo "KernelSU ksud CLI not found." >&2; exit 1
  fi
fi
if [[ "$manager" == auto || "$manager" == apatch ]]; then
  if run_root sh -c 'command -v apd >/dev/null 2>&1' 2>/dev/null; then
    echo "Installing with APatch: $ZIP"
    run_root apd module install "$ZIP"
    exit 0
  elif [[ "$manager" == apatch ]]; then
    echo "APatch apd CLI not found." >&2; exit 1
  fi
fi

echo "No supported module-manager CLI detected." >&2
echo "Install $ZIP from your Magisk/KernelSU/APatch manager, or set MODULE_MANAGER explicitly." >&2
exit 1
