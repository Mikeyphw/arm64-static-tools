# AST — single-pass packaging and native required-CI qualification

## Hosted packaging path

For a PR, the `Package ARM64 module` GitHub workflow validates the **exact PR HEAD**.
Its package job executes `make check package` in one Make invocation. GNU Make's
single-run dependency tracking executes the `check` prerequisite once; the
`package` recipe invokes `scripts/package.sh`, which executes
`python3 scripts/fetch.py --mode locked --export-dir ... --provenance ...`.
This preserves independent source checks, exact binary source SHA-256,
ARM64/ELF/static qualification, plugin and static-Python packaging, module ZIP
verification, and artifact upload. No `make update` or silent lock repin occurs.

The update-report job continues to run only on schedule/manual dispatch. Feature
branch pushes never run a second packaging workflow; `pull_request` is the
source-bound gate. `master` still receives push checks, including config changes.

## Native Devtool durable-session CI — required policy

This branch adds `config/delivery-required-ci.json` using Devtool's committed
policy schema v1, bound to repository `Mikeyphw/arm64-static-tools`, PR base
`feature/ast-recovery-ci-qualification-20261117`, event `pull_request`, and
*exact* workflow name `Package ARM64 module` / GitHub workflow ID `420937101`.
It never treats workflow names, local tests, skipped jobs, or stale runs as
sufficient proof. The native coordinator must independently inspect:

- Exact PR head/number/base and workflow registration inside the session window.
- Per-run `GET`, attempt number, required job success, workflow ID and source SHA.
- GitHub branch protection AND effective rulesets, including required contexts.
- Committed policy SHA-256, durable session state, verified event stream/receipt.

`REQUIRED_CHECKS_PASSED` (with `checks_qualified=true`) is the only formal
Devtool CI success state. `REQUIRED_CI_SKIPPED_NO_POLICY`, `CHECKS_RUNNING`,
`CHECKS_EVIDENCE_PENDING`, `BRANCH_RULES_UNVERIFIED`, etc. are **not** passes.
The workflow's skipped `update-report` job is not counted as a pass.

**Important: old session:** PR #6 was created from a commit without a committed
required-CI policy. Its preexisting native durable session cannot be upgraded
retroactively by editing an uncommitted file or changing its bound HEAD. Keep
that session intact. This new feature branch creates a new session *after* the
policy is committed via native overlay delivery, then runs authorized PR/CI.

**Branch-specific policy:** After merging or changing the target PR base, the
policy no longer matches the new branch; review/update it in a separate
source-bound delivery before trying formal CI on a different base. Do not
silently retarget it to `master` or substitute a historic Devtool commit.

**Native verification from Termux:** run `AST_NATIVE_SESSION_AUDIT_TERMUX.sh`
from the delivery bundle after applying. It locates candidate journal IDs
read-only and calls the native source-bound launcher's `status`/`report`
commands. The script does not create a session, apply overlays, push or claim
that a hosted green result is a native receipt. A native CI *observation* is
performed by `apply --approve-remote --watch-ci` and can be resumed via its
saved session ID. A missing/inaccessible ruleset or GitHub scope blocks formal
qualification; never bypass that requirement.

CI success is **not** a release, device, or merger qualification.
