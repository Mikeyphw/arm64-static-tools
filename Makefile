.PHONY: check fetch package clean
check:
	python3 scripts/verify_manifest.py
	python3 -m py_compile scripts/fetch.py scripts/verify_manifest.py
	bash -n scripts/package.sh module/customize.sh module/post-fs-data.sh
fetch: check
	python3 scripts/fetch.py
package: fetch
	bash scripts/package.sh
clean:
	rm -rf build dist/*.zip dist/*.sha256
