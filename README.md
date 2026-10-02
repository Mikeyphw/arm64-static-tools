# ARM64 Static Tools — root module packager

ARM64-only Magisk / KernelSU / APatch module repository for a curated root-shell toolkit.

**Policy:** prebuilt binaries only. This repository does **not** compile any tool from source. `rclone` is intentionally excluded.

## Included tool manifest

Core: `busybox toybox bash sqlite3 jq yq coreutils zsh git`

Search / navigation: `rg fd fzf zoxide`

Inspection: `xxd strings readelf objdump nm`

Archives: `7zz zstd lz4 xz brotli pigz cpio`

Transfer / network: `curl aria2c rsync socat`

Debug: `strace ltrace lsof`

`lz4` is currently marked optional until the resolver finds a qualifying prebuilt. The package job will not compile it.

## How it works

`manifest/sources.json` is the source of truth. `scripts/fetch.py` downloads only ARM64 prebuilts from the declared upstream/provider sources, extracts the requested executable, verifies it is AArch64, records provenance and SHA-256, and enforces the static-link policy.

Some providers publish Android executables that are static; others may link only against standard Android/Bionic libraries. Those exceptions must be explicitly declared in the manifest. Git from bnsmb is currently such an explicit exception candidate and will be recorded as static or dynamic by the generated provenance report.

## Build the module package

No tool source code is built. "Build" here means **download, verify, and package**:

```sh
make package
```

Output:

```text
dist/arm64-static-tools-<version>.zip
dist/arm64-static-tools-<version>.zip.sha256
build/provenance.json
```

To fetch/test only one or more entries:

```sh
python3 scripts/fetch.py --only git --only zsh
```

## Module layout

The package installs files systemlessly under `/system/bin`, making them naturally available to root/ADB shells. The repository never writes directly to the physical `/system` partition.

Because several tools overlap with Android/Toybox applets, the manifest favors standalone names and a multicall `coreutils` binary rather than generating hundreds of uutils symlinks automatically.

## Sources

Current providers include:

- `bnsmb/binaries-for-Android` — ARM64 Android binaries; project states entries are either static or depend only on Android standard libraries.
- `bnsmb/clang19_toolchain_for_android` — source for the prebuilt ARM64 Android Git executable.
- `osm0sis/android-busybox-ndk`
- `rojenzaman/sqlite3-magisk-module`
- official upstream release assets for jq, yq, uutils/coreutils, ripgrep, fd, fzf and zoxide.
- maintained static-binary collections for selected classic Unix tools.

Exact resolved URLs, versions, checksums and ELF linkage are written to `build/provenance.json` at packaging time.

## Validation policy

Every downloaded executable must resolve as AArch64/ARM64. Entries marked `static: required` fail packaging if `readelf` finds an ELF interpreter or `DT_NEEDED` libraries. Entries marked `static: preferred` are recorded in provenance and are accepted only where the manifest explicitly permits the Android-system-library case.

The CI runner performs the networked fetch. Local syntax/manifest checks can be run without network using `make check`.
