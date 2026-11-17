#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
manifest_path = ROOT / "manifest/sources.json"
lock_path = ROOT / "manifest/lock.json"

d = json.loads(manifest_path.read_text())
names = [x["name"] for x in d["tools"]]
assert d["architecture"] == "arm64"
assert d["policy"]["prebuilt_only"] is True
assert d["policy"]["build_from_source"] is False
assert d["policy"]["allow_rclone"] is False
assert "rclone" not in names
assert len(names) == len(set(names)), "duplicate tool names"
required = {
    "busybox", "toybox", "bash", "sqlite3", "jq", "yq", "coreutils",
    "rg", "fd", "fzf", "zoxide", "xxd", "strings", "readelf", "objdump",
    "7zz", "zstd", "xz", "brotli", "pigz", "cpio", "curl", "aria2c", "rsync",
    "socat", "strace", "ltrace", "lsof", "git", "zsh",
}
missing = required - set(names)
assert not missing, f"missing: {sorted(missing)}"

allowed_kinds = {"direct", "github_release_asset", "github_repo_file", "github_repo_file_glob", "alias"}
for tool in d["tools"]:
    assert tool["kind"] in allowed_kinds, f"{tool['name']}: unsupported kind"
    assert tool.get("provider") or tool["kind"] in {"direct", "alias"}, f"{tool['name']}: provider missing"
    assert tool.get("static") in {"required", "preferred"}, f"{tool['name']}: invalid static policy"

if lock_path.exists():
    lock = json.loads(lock_path.read_text())
    assert lock.get("architecture") == "arm64"
    assert lock.get("prebuilt_only") is True
    locked_names = [x["name"] for x in lock.get("tools", [])]
    assert "rclone" not in locked_names
    assert len(locked_names) == len(set(locked_names)), "duplicate locked tool names"
    unknown = set(locked_names) - set(names)
    assert not unknown, f"lock contains tools absent from manifest: {sorted(unknown)}"
    for entry in lock.get("tools", []):
        for key in ("source_url", "source_sha256", "sha256", "size", "file", "static"):
            assert key in entry, f"{entry['name']}: lock missing {key}"
        assert len(entry["source_sha256"]) == 64 and len(entry["sha256"]) == 64

print(f"manifest OK: {len(names)} tools; ARM64-only; prebuilt-only; rclone absent")
print(f"metadata lock: {'present' if lock_path.exists() else 'not created yet (run make update)'}")
