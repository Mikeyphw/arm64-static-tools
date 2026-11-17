.PHONY: check update fetch package release install clean clean-cache

check:
	python3 scripts/verify_manifest.py
	python3 scripts/check_repo_purity.py
	python3 -m py_compile scripts/fetch.py scripts/verify_manifest.py scripts/check_repo_purity.py scripts/package_python_runtime.py scripts/verify_module_zip.py module/ast/manager/*.py
	bash -n scripts/package.sh scripts/install.sh module/customize.sh module/post-fs-data.sh module/service.sh module/uninstall.sh module/ast/entrypoint.sh module/ast/install-entrypoint.sh
	python3 -m unittest discover -s tests -p 'test_*.py' -v

# Resolve current provider versions, qualify downloads in the external cache,
# and update metadata only (manifest/lock.json + build/update-report.*).
update: check
	python3 scripts/fetch.py --mode update

# Re-fetch/verify the exact metadata lock without resolving newer versions.
fetch: check
	python3 scripts/fetch.py --mode locked

# Reproducible package from manifest/lock.json and python-runtime.json.
# Requires pinned external source cache or HTTPS to download verified assets. Does not silently update tools.
package: check
	bash scripts/package.sh

# Convenience: resolve latest approved prebuilts, then package them.
release: update package

# Installs the newest locally packaged ZIP through a detected root manager CLI.
install: package
	bash scripts/install.sh

clean:
	rm -rf build dist .artifacts

# Downloaded executables live outside the repository by default.
clean-cache:
	rm -rf "$${STATIC_TOOLS_CACHE:-$${XDG_CACHE_HOME:-$$HOME/.cache}/arm64-static-tools-module}"
