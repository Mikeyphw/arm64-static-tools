# AST Recovery R02 — Embedded Rich and offline module-management contract

R01's terminal always remains the primary entry point. R02 adds only optional
Python applications invoked from Zsh or `sh /data/local/tmp/ast <command>`.
No Textual hosts, no intercepted stdout/stderr, no clipboard writes, no
network calls or root module mutations at startup.

## Static runtime

- CPython 3.12.14, upstream python-build-standalone 20260901,
  `aarch64-unknown-linux-musl-noopt+static-full.tar.zst`.
- Wheel locks: Rich 14.2.0, Pygments 2.19.2, markdown-it-py 4.0.0,
  mdurl 0.1.2. All expected SHA-256 digests in `manifest/python-runtime.json`.
- `package_python_runtime.py` verifies full archive/wheels and rejects archive
  traversal, symlinks escaping installation, ELF wrong machine, PT_INTERP /
  DT_NEEDED, native binary wheels and overlarge payloads. Host CI must have
  `zstd` and `readelf`. No `install_only` or dynamic musl runtime accepted.
- Execution uses isolated `PYTHONHOME`, `PYTHONPATH`, `PYTHONSAFEPATH`,
  `PYTHONNOUSERSITE`, `PYTHONDONTWRITEBYTECODE`; no Py2Droid dependency.
- Cross-platform source tests do not prove runtime launches on ARM64 recovery;
  acceptance must run `ast python -s -c 'import rich,sqlite3,zlib,ssl'` and
  confirm `ast menu` behavior on device, with `/data` decrypted.

## Modules

- Read `module.prop` and `disable`/`remove` markers under `/data/adb/modules`.
- On supported KernelSU, use `/data/adb/ksud module enable|disable|uninstall`.
- Never run unknown module install or action scripts from recovery.
- Filesystem fallback requires real recovery, valid module ID, existing
  `module.prop`, no path symlinks, explicit typed consent, and descriptor-relative
  marker mutations; unknown/malformed modules are skipped/refused.
- `DISABLE ALL` emergency operation always requires exact confirmation.

## Vector

- `ast vector`: read-only SQLite inspection of `*.db` / `*.sqlite` /
  `*.sqlite3` inside `/data/adb/lspd/config`. WAL-aware read-only connection,
  `quick_check`, schema introspection and modules list only when relevant
  `module_pkg_name` + `enabled` columns are present.
- Vector CLI depends on a daemon and is **not** invoked in offline recovery.
- R03 is responsible for version/schema-qualified scope and toggle mutations.

## Backup/restore

- Each creation checks the source tree and refuses symlinks, special files,
  outsize files and path traversal.
- SQLite database is backed up via `sqlite3.Connection.backup` to capture WAL
  consistency; standalone `-wal`/`-shm` files aren't copied.
- Snapshot manifest records hashes, timestamps, owner, mode and SELinux label
  metadata for each captured file. Verification runs before retention pruning.
- Keep at most five verified snapshot directories; never silently remove
  unrecognized or corrupted backups. Data backup root must be private.
- Restore requires explicit recovery detection and exact backup name; the
  existing directory is retained as a rollback sibling, never deleted.
- No unsupported Vector database schema is modified in R02.

## Terminal fallback / diagnostics

- UI uses Rich panels/tables and optional fzf; numbered menus remain available.
- Interactive prompts require **both** stdin and stdout to be terminals. Piped or
  redirected stdout must never borrow Termux stdin and block headless validation.
- The CLI regression suite explicitly closes stdin and tests PTY stdin with
  piped stdout; each subprocess has a bounded timeout.
- `NO_COLOR`, `CLICOLOR=0`, `TERM=dumb` and redirected streams produce plain output.
- `ast doctor` reports Python, root-manager and Vector status without private
  file contents; JSON diagnostics can be written to a fresh 0600 file.
- If the runtime is missing/incompatible, the launcher reports the failure;
  `ast shell` / `ast --safe` / BusyBox remain independent.

## Evidence boundaries

Linux unit tests, module package checksum validation, native Devtool overlay
validation, hosted CI and real Android/PitchBlack device testing are distinct.
No skipped stage is reported as passed. `R02` must not publish a release until
locked runtime packaging and on-device Python startup are qualified.

The `ast py2droid` command is **diagnostic-only** until a separate
ABI/linker qualification is completed on the actual recovery. It never runs
external module scripts as root.
