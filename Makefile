.PHONY: format lint typecheck build test package release-check check

format:
	python3 scripts/format_check.py

lint:
	python3 -m compileall -q scripts tests

typecheck:
	python3 scripts/validate_manifest.py extension.toml
	python3 scripts/validate_snippets.py extension.toml
	python3 -c "import scripts.configuration, scripts.dap_templates, scripts.diagnostics, scripts.project_detection, scripts.project_setup, scripts.runtime, scripts.sdk_resolution, scripts.task_templates, scripts.tmux_runner, scripts.tmux_target"

build:
	python3 -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))"

release-check:
	python3 scripts/release_check.py versions .

package: release-check
	python3 scripts/package_release.py --root . --output dist/flutter-zed-extension.tar.gz
	python3 scripts/release_check.py archive dist/flutter-zed-extension.tar.gz

test:
	python3 -m unittest discover -s tests -v

check: format lint typecheck build release-check test
