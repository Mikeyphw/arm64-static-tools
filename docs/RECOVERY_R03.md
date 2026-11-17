# R03 — qualified offline Vector recovery edits and package hardening

## Source model

Vector's authoritative SQLite schema is in `JingMatrix/Vector`,
`daemon/src/main/kotlin/org/matrix/vector/daemon/data/Database.kt` (reviewed
source commit `6f6b976e3315c158d501f743c3c609e80cae7ec8`). The schema
is `DB_VERSION=5`: modules (mid, module_pkg_name, apk_path, enabled,
auto_include), scope (mid, app_pkg_name, user_id), auto_include (mid,user_id),
and configs (module_pkg_name,user_id,group,key,data). R03 recognizes exactly
that layout with intact primary/foreign-key invariants. Other and older
versions are **inspection-only**. No direct Android daemon CLI in recovery.

## Terminal commands

`sh /data/local/tmp/ast` still enters interactive Zsh. `ast menu` is optional;
`ast vector` opens the interactive management menu. Non-interactive listing is
available through `ast vector list`. Mutation commands require a real terminal
and exact typed confirmation (`VECTOR WRITE`, or `SCOPE SET` for replacement).
Examples (after recovery detection and /data decryption):

```
ast vector enable com.example.module
ast vector disable com.example.module
ast vector scope-add com.example.module com.example.target --user 0
ast vector scope-remove com.example.module com.example.target --user 0
ast vector scope-set com.example.module com.example.one com.example.two --user 10
ast vector scope-set com.example.module NONE --user 10
```

`scope-set` changes **only the selected Android user's scope**, preserving
other users. `NONE` deliberately clears the selected user's scope, not the
entire database. No module is installed by these operations. No recovery edit
runs automatically on boot. The module's own `lspd` row is not writable.

## Safety and recovery

- Mutations require a verified recovery environment, a registered module,
  SQLite `user_version=5`, exact column inventory, expected primary and
  foreign keys, quick_check/foreign_key_check, and no unreviewed triggers.
- The config, database and journal paths must not be symlinked. Missing or
  externally linked databases are refused. SQLite starts in read-only mode.
- A consistent SQLite-aware backup captures the **whole** Vector config tree
  before each edit, including uncommitted WAL state, file hashes, mode,
  ownership and SELinux label metadata. Backup verification precedes writes. Retention cleanup occurs **only after** a successful SQLite commit and post-write verification; an aborted/no-op operation never evicts an old restore point.
- One `BEGIN IMMEDIATE` transaction owns each change; SQLite rolls it back on
  any failure. Post-commit schema/integrity checks run before reporting success.
- If the post-commit check unexpectedly fails, AST **does not** report success.
  It identifies a retained verified backup for deliberate operator restoration.
  AST never silently deletes the original configuration.
- The existing five-verified-backup retention policy remains; corrupt backups
  are never silently pruned. A restore retains the former config as a rollback
  sibling. No direct writes if the source changes while backing up.
- Live Android operation is deliberately unsupported. Recovery cannot run
  Android's Vector daemon, and a hook module change takes effect after reboot.

## Python static archive package hardening

Only the SHA-256 locked full AArch64 musl static CPython archive is accepted.
Its legitimate internal relative symlinks are copied as regular files or
bounded directories. Hardlinks, escaping/dangling links, cyclic/overdepth alias chains,
cyclic directory aliases and special files are rejected. Bounded legitimate
in-tree linked-link chains are resolved before materialization. `verify_elf` still
rejects PT_INTERP and DT_NEEDED. Generated module ZIPs are inspected for
AArch64 Python, file permissions, required resources, traversal and bytecode.

## Acceptance evidence boundaries

- Host Python regression and negative tests: runnable on Linux/Termux.
- Native Devtool overlay validation and package/payload verification: must
  run from a clean, named target branch against exact Git source HEAD/tree.
- Hosted packaging: must rebuild and pass at actual PR HEAD; earlier failing
  checks are not converted into passes by local tests.
- Real ARM64 recovery: verify /data decryption/mount, `ast --safe`, Zsh/Zinit,
  fzf/Rich prompt, static Python `import rich,sqlite3,zlib,ssl`, module
  inspection, harmless test module toggle, Vector backup/restore and actual
  qualified v5 schema before enabling live mutations. Do not claim device
  or release qualification until observed.
- Incompatible databases remain read-only by design, not a failed installer.

## Hosted packaging provenance

`Package ARM64 module` runs on push and pull request at the exact source commit;
`make fetch` uses the **already committed** `manifest/lock.json` and
`make package` verifies the produced ZIP. It never calls `make update` before
producing a PR/package artifact. A separate scheduled/manual `update-report`
job checks newer approved prebuilts and uploads a review artifact without
writing a commit or publishing an updated module. No automatic lock repin,
package upgrade or release publication is implied.
