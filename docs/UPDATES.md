# Release and module-manager updates

The root-manager feed is independent of `make update` (the *binary lock* updater).
AshReXcue's reference ZIP has `updateJson=` in `module.prop` and a separate WebUI
that fetches this JSON and installs the ZIP. AST initially implements the
standard manager-native feed, not an unattended updater or WebUI.

## Stable publication

- Installers contain a declared `updateJson` URL only when a release identity
  is explicitly provided (`AST_RELEASE_REPOSITORY=owner/repo`) or validated
  against canonical `origin` for a local GitHub checkout.
- The URL points to `https://github.com/owner/repo/releases/latest/download/update.json`.
- `scripts/release_metadata.py` verifies ZIP ID, version, versionCode, filename,
  update URL, archive members, and computes its SHA-256 digest.
- The GitHub Actions stable-release workflow only runs by explicit dispatch;
  no weekly build promotes code automatically.
- Release tags and artifact names are `v<version>` and
  `arm64-static-tools-<version>.zip`. Upload `update.json`, `changelog.md`,
  ZIP and SHA256 sidecar *before* publishing the previously drafted release.
- Before a release, compare the previous stable feed's versionCode; it must be
  lower than the new code. Never replace an existing release tag.
- Root managers read `version`, numeric `versionCode`, `zipUrl`, and `changelog`
  from the JSON. Managers have their own version comparison and install logic.

## Limitations

A JSON feed is a convenience, not a cryptographic signature. The SHA-256
sidecar gives independent operator verification, but ordinary manager update
handlers do not necessarily check it. Do not accept unreviewed download URLs.
Release authorization, hosting, PR checks and device testing are independent.

## State across module upgrades

User state lives in root-owned `/data/adb/arm64-static-tools`; update ZIPs never
contain or delete that directory. The launcher in `/data/local/tmp/ast` is
refreshed atomically by the module installer and during supported Android boot.
Nothing in this mechanism automatically flashes a module from recovery.
