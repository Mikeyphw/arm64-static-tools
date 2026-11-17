# Exact-source qualification and single-event CI

## Previously observed defects

- A source lock recorded `7zzs` at an upstream `main` URL. That URL changed.
  GitHub Actions observed SHA-256 `265e45b5847392c0cd97a84acb6b3f9933c3e43d698fb5a2979f5e9a80c05758`
  while the stale lock expected `277907bc627633ec344757fe47699856cbb6e37f75cbc310d37d62cfacdd73b2`.
- On R04 HEAD `7e3c5b1d5d79401cd52e1c826b5531dd4c1efd1b`, both
  `push` and `pull_request` events ran the same full package workflow.

## Reviewed correction

The recorded upstream commit is
`5ea67098a9bf2e32d6a85ef9775a19bf147b6285`, containing Git blob
`7ed130434d40c8f5c44eee85b192b3f0c6833e9d` at `linux/arm64/7zzs`
(size 3,105,552 bytes). The exact download now uses a **commit-specific**
`raw.githubusercontent.com` URL, with the CI-observed SHA-256 committed as
`source_sha256` and `sha256`. This explicit requalification does not permit
implicit repinning. `make fetch` must still verify the download and static ELF.

`repo_file()` in the metadata updater now resolves the remote default HEAD to
an immutable 40-character commit and asks for contents **at that commit**. It
refuses symlinks and malformed refs rather than accepting moving download URLs.

`.github/workflows/package.yml` preserves the `pull_request` workflow for
feature branches, restricts automatic `push` jobs to `master`, and groups
concurrent runs by PR number or ref, cancelling obsolete jobs. A cancelled job
is not a qualified success. Schedule and manual dispatch remain opt-in.
Release publishing is independently explicit and not CI-qualified by this fix.

## Acceptance gates

1. Native Devtool check, apply and durable session verified on exact R04 HEAD.
2. PR-triggered workflow at **new commit** passes all unit/negative tests,
   exact-source `make fetch`, Python/plugin packaging and ZIP qualification.
3. GitHub shows a single active package workflow for a new feature PR HEAD.
4. PRs integrated in review order without reset/rebase/force push.
5. Real ARM64 recovery runtime and PitchBlack Nerd Mono rendering are
   qualified separately on a device; hosted Linux is not that evidence.
