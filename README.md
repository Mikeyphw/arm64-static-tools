# ARM64 Static Tools — root module packager

ARM64-only Magisk / KernelSU / APatch module repository for a curated root-shell toolkit.

**Hard policy:** prebuilt binaries only. This Git repository never vendors or tracks downloaded executables. It does **not** compile any tool from source. `rclone` is intentionally excluded.

## Toolkit

Core: `busybox toybox bash sqlite3 jq yq coreutils zsh git`

Search / navigation: `rg fd fzf zoxide`

Inspection: `xxd strings readelf objdump nm`

Archives: `7zz zstd lz4 xz brotli pigz cpio`

Transfer / network: `curl aria2c rsync socat`

Debug: `strace ltrace lsof`

`lz4` is optional until its resolver finds a qualifying prebuilt. There is never a source-build fallback.

## Source-only repository design

The repository contains only scripts, module metadata and source/provenance metadata.

Downloaded executables default to the external cache:

```text
${XDG_CACHE_HOME:-$HOME/.cache}/arm64-static-tools-module/
```

They are never copied into a tracked repository directory. Packaging materializes the locked binaries directly from that cache into a temporary directory and deletes the staging tree afterward.

`make check` also runs `scripts/check_repo_purity.py`, which fails if Git tracks an ELF executable, archive payload, generated module ZIP, or anything under `module/system/bin/`.

You can override the external cache location with:

```sh
export STATIC_TOOLS_CACHE=/some/path
```

or pass `--cache-dir` directly to `scripts/fetch.py`.

## Update model

There are deliberately two different operations.

### Check for/download newer approved prebuilts

```sh
make update
```

This:

1. resolves each provider's current approved ARM64 prebuilt;
2. downloads it to the external cache;
3. verifies AArch64 ELF architecture;
4. checks static linkage / declared Android-system-library exceptions;
5. computes source-download and final-executable SHA-256 hashes;
6. updates **metadata only** in `manifest/lock.json`;
7. writes `build/update-report.md` and `build/update-report.json`.

The report separates `UPDATED`, `ADDED`, `UNCHANGED`, and `FAILED` entries. An optional tool that temporarily cannot be resolved keeps its previous lock entry when one exists.

`manifest/lock.json` is intended to be committed. It contains URLs, versions, hashes, sizes and ELF qualification metadata — **not binaries**.

### Re-fetch exactly the locked set

```sh
make fetch
```

This does **not** look for updates. It fetches the URLs in `manifest/lock.json`, verifies both the downloaded source checksum and extracted executable checksum, re-runs ELF qualification, and caches the executable outside the repository.

## Package the module

After the first metadata update:

```sh
make update
make package
```

`make package` is intentionally reproducible: it consumes `manifest/lock.json` and will not silently move to newer versions.

Output:

```text
dist/arm64-static-tools-<version>.zip
dist/arm64-static-tools-<version>.zip.sha256
build/provenance.json
```

`dist/` and `build/` are ignored generated outputs. The actual downloaded executables remain in the external cache, while the module staging directory is temporary.

For the convenience behavior “refresh first, then package”:

```sh
make release
```

## Install locally

On the rooted Android device:

```sh
make install
```

That packages the **locked** toolset and then `scripts/install.sh` attempts the available root-module CLI in this order: Magisk, KernelSU, APatch.

You can force one:

```sh
MODULE_MANAGER=magisk make install
MODULE_MANAGER=kernelsu make install
MODULE_MANAGER=apatch make install
```

If no supported CLI is exposed, the script leaves the ZIP untouched and tells you to install it from the root manager UI.

## Update only selected tools

For investigation or targeted refreshes:

```sh
python3 scripts/fetch.py --mode update --only git --only zsh
```

Unselected existing lock entries are preserved.

## Module behavior

The ZIP installs tools systemlessly under `/system/bin`; it never modifies the physical `/system` partition. `customize.sh` rejects non-ARM64 devices and sets module permissions.

Overlapping command families are kept conservative. BusyBox/Toybox/uutils are delivered as their own binaries rather than automatically creating hundreds of conflicting applet symlinks.

## Sources and qualification

`manifest/sources.json` is the source-of-truth resolver policy. Current providers include bnsmb Android prebuilts, BusyBox NDK, the SQLite Magisk module, and official ARM64 release assets for projects such as jq, yq, uutils/coreutils, ripgrep, fd, fzf and zoxide.

Every required-static executable must have no ELF interpreter and no `DT_NEEDED` entries. A dynamically linked executable is accepted only when its manifest entry explicitly permits Android system libraries. Git from the bnsmb ARM64 Android toolchain is currently treated this way and its actual linkage is recorded in the lock/provenance metadata.

The lock records both the downloaded source/archive SHA-256 and the extracted executable SHA-256, preventing a mutable upstream URL from silently changing the package.

## Useful commands

```sh
make check       # manifest + source-only Git purity + syntax checks
make update      # resolve latest approved prebuilts; update metadata lock/report
make fetch       # fetch and verify the exact locked set
make package     # package the exact locked set
make release     # update + package
make install     # package locked set + try local root-manager installation
make clean       # remove repo-local generated metadata/artifacts only
make clean-cache # remove external downloaded-binary cache
```

## Recovery shell (R01)

With `/data` mounted and decrypted, use `sh /data/local/tmp/ast` to enter the
standalone Zsh recovery shell. `sh /data/local/tmp/ast doctor` checks available
tools, `sh /data/local/tmp/ast safe` bypasses Zinit, and
`sh /data/local/tmp/ast -- jq --version` runs a command in AST's environment.
The launcher remains available if systemless PATH mounting is inactive.
The launcher does not auto-mount, decrypt, flash or fetch updates.

The offline Zinit bundle is built from pinned Git commits and trees in
`manifest/plugins.json` into the ZIP staging directory, not vendored into Git.
Plugin sources are downloaded only at package-build time, never in recovery.
`ast menu` remains a terminal entry point until the Rich dashboard in R02.

Optional LSD and Oh My Posh prebuilts are approved in `manifest/sources.json`
with static ELF qualification. After `make update`, commit the new lockfile.
Prompts default to a recovery-safe ASCII-compatible style; Nerd Fonts inside
PitchBlack require separate renderer/font verification.

## Root-manager update channel

See [docs/UPDATES.md](docs/UPDATES.md). `make update` changes binary lock
metadata, **not** the installed module. A stable module update requires
explicit release publishing using `.github/workflows/release.yml`, which
checks the pinned toolset, monotonic module `versionCode`, ZIP integrity,
and publishes `update.json`, changelog and ZIP as one stable release.
The `updateJson` manager feed is stamped only with verified
`AST_RELEASE_REPOSITORY=owner/repo` or a canonical GitHub `origin`. No URL
is invented for unbound local builds.
