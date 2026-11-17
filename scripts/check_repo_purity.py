#!/usr/bin/env python3
"""Fail if Git tracks vendored/generated binary payloads."""
from __future__ import annotations
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_PREFIXES = ("build/", "dist/", ".cache/", ".artifacts/", "module/system/bin/")
FORBIDDEN_SUFFIXES = (
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.xz", ".tar.zst", ".7z",
    ".apk", ".elf", ".so", ".bin", ".pyc", ".pyo",
)
MAGICS = {
    b"\x7fELF": "ELF",
    b"PK\x03\x04": "ZIP",
    b"\x1f\x8b": "gzip",
    b"\xfd7zXZ\x00": "xz",
    b"7z\xbc\xaf'\x1c": "7z",
    b"(\xb5/\xfd": "zstd",
}


def tracked_files():
    p = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), "ls-files", "-z"],
        stdout=subprocess.PIPE,
        check=True,
    )
    return [x.decode() for x in p.stdout.split(b"\0") if x]


def main():
    bad = []
    files = tracked_files()
    for rel in files:
        low = rel.lower()
        if rel.startswith(FORBIDDEN_PREFIXES) or low.endswith(FORBIDDEN_SUFFIXES):
            bad.append(f"{rel}: forbidden tracked artifact path/type")
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        head = p.read_bytes()[:8]
        for magic, kind in MAGICS.items():
            if head.startswith(magic):
                bad.append(f"{rel}: tracked {kind} payload")
                break
    if bad:
        print("Repository purity FAILED:")
        for x in bad:
            print(f"  - {x}")
        return 1
    print(f"repository purity OK: {len(files)} tracked files; no vendored/generated binary payloads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
