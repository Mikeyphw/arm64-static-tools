# Offline Zinit plugin archive policy

The package builder obtains each plugin from its existing exact Git commit/tree
lock and uses `git archive`; no mutable branch tip is used during extraction.

Each tar member is preflighted before staging. The extractor accepts ordinary
files and directories, plus **relative symlinks that resolve directly to a
regular file in that same verified archive**. These are materialized as
ordinary bytes, so the finished module contains no upstream plugin symlinks.
This is needed for the seven `highlighters/*/README.md` documentation links in
pinned `zsh-syntax-highlighting`.

The extractor rejects absolute and escaping links, dangling links, links to
other links or directories, hard links, special device members, path traversal,
filename collisions and already-linked staging paths. It verifies the
archive tree's source commit before extracting and reports each plugin's
commit, tree, archive digest and staged file count.

`python3 -m unittest discover -s tests -p 'test_*.py' -v` exercises legitimate
links and malicious archives. Hosted `make package` remains the integration
check that verifies the *actual pinned upstream plugin source*. Do not delete
these negative checks or bypass the archive guard to make CI green.

The repair doesn't change the recovery shell, Zinit update policy, release
channels, manifest pins, or installed module files outside the plugin bundle.
