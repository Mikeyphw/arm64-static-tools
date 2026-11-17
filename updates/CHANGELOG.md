# ARM64 Static Tools v0.5.0 — AST Recovery R03

- Vector v5-only offline enable/disable and application scope add/remove/replace for selected Android users, with explicit typed confirmation and a verified pre-write SQLite backup.
- Strict table/column/foreign-key/integrity checks and transactional writes; unsupported Vector/LSPosed databases remain read-only.
- Verified Python archive internal relative aliases are materialized safely without filesystem symlinks; external and dangling links remain refused.
- Module ZIP verification checks package inventory, executable permissions, static-Python architecture and host bytecode leakage.
- Terminal and Zsh remain fully available regardless of Python/Rich/Vector compatibility.
- Local test evidence does not constitute hosted CI, device, or release acceptance.

# ARM64 Static Tools v0.4.0 — AST Recovery R02

- Embedded version-locked ARM64 static Python 3.12.14 and pure-Python Rich dependencies.
- Native-terminal Rich/fzf recovery dashboard with numbered fallback and direct Zsh access.
- KernelSU/APatch/Magisk module inspection, confirmed enable/disable and staged removal.
- Vector/LSPosed offline SQLite read-only inspection with unknown-schema refusal.
- Five verified Vector config backups with SQLite WAL-consistent snapshots, controlled restore and preserved rollback.
- Optional Py2Droid detection without reliance on its interpreter or login scripts.
- Improved diagnostics, negative tests, recovery fallback and static release packaging.

R03 will add schema-qualified offline Vector edits and further physical recovery qualification.
No release or device qualification is implied by this changelog.
