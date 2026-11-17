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
    # Version-bound, immutable provider URI for this Toybox binary. A digest on
    # /latest/ still rejects drift, but makes CI fail after an upstream release.
    toybox = next(x for x in lock['tools'] if x['name'] == 'toybox')
    toybox_source = next(x for x in d['tools'] if x['name'] == 'toybox')
    assert toybox_source['url'] == toybox['source_url'], 'Toybox source/lock URL disagree'
    assert toybox['source_url'] == 'https://landley.net/toybox/downloads/binaries/0.8.14/toybox-aarch64', 'Toybox must use versioned upstream release'
    assert toybox['version'] == '0.8.14'
    assert toybox['sha256'] == toybox['source_sha256'] == '223b5ff5929371225d0bc62fb3b99a148692295fb6f85ad86bb924f689a55ea4'
    assert toybox['size'] == 838240
    for src in d['tools']:
        if src['kind'] == 'direct':
            assert '/latest/' not in src['url'], f"{src['name']}: mutable latest direct source"
    for entry in lock.get("tools", []):
        for key in ("source_url", "source_sha256", "sha256", "size", "file", "static"):
            assert key in entry, f"{entry['name']}: lock missing {key}"
        assert len(entry["source_sha256"]) == 64 and len(entry["sha256"]) == 64

# 7zz must be tied to an immutable Git revision; source hashes and executable
# bytes are qualified in `make fetch`. Future updates can be reviewed without
# editing historical hard-coded version gates.
if lock_path.exists():
    import re
    sevenzip = next((x for x in lock["tools"] if x["name"] == "7zz"), None)
    assert sevenzip is not None, "7zz must be pinned in the committed lock"
    pattern = (r"https://raw\.githubusercontent\.com/ollm/7zip-bin-full/"
               r"([0-9a-f]{40})/linux/arm64/7zzs")
    match = re.fullmatch(pattern, sevenzip["source_url"])
    assert match is not None, "7zz lock must reference an immutable upstream Git commit"
    assert sevenzip["version"] == match.group(1), "7zz lock revision differs from source URL"
    assert sevenzip["source_sha256"] == sevenzip["sha256"], "7zz source/binary hash mismatch"
    assert sevenzip["size"] > 0 and sevenzip["static"] is True, "7zz lock must be a static executable"

print(f"manifest OK: {len(names)} tools; ARM64-only; prebuilt-only; rclone absent")
print(f"metadata lock: {'present' if lock_path.exists() else 'not created yet (run make update)'}")
