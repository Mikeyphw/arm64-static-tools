#!/usr/bin/env python3
import json,sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
p=root/"manifest/sources.json"; d=json.load(open(p)); names=[x["name"] for x in d["tools"]]
assert d["architecture"]=="arm64"
assert d["policy"]["prebuilt_only"] is True
assert d["policy"]["build_from_source"] is False
assert "rclone" not in names
assert len(names)==len(set(names)), "duplicate tool names"
required={"busybox","toybox","bash","sqlite3","jq","yq","coreutils","rg","fd","fzf","zoxide","xxd","strings","readelf","objdump","nm","7zz","zstd","xz","brotli","pigz","cpio","curl","aria2c","rsync","socat","strace","ltrace","lsof","git","zsh"}
missing=required-set(names)
assert not missing, f"missing: {sorted(missing)}"
print(f"manifest OK: {len(names)} tools; ARM64-only; prebuilt-only; rclone absent")
