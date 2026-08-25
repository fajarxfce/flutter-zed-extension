# Compatibility Matrix and Migration Guide

This matrix separates what was exercised in this repository's local/offline tests from what requires a user's installed prerequisites. A **verified** entry cites a passing artifact. It is not a claim that a real Zed installation, real Flutter SDK, device, or external user's tmux server was exercised unless the cited artifact says so.

## Evidence vocabulary

- **Verified (fixture/Linux):** a passing local test with temporary fixtures, fake executables/adapters, and where applicable an isolated `tmux -L` server.
- **Supported, prerequisite-dependent:** documented product path, but not live-validated here.
- **Optional:** not needed for the core configuration/template path.
- **Unverified:** no passing platform/live-integration evidence in this checkout.
- **Unsupported:** deliberately outside the product boundary.

## Matrix

| Area / combination | Status | Scope and limitation | Evidence or basis |
| --- | --- | --- | --- |
| Linux + Python offline core checks | **Verified (fixture/Linux)** | The deterministic suite validates project detection, configuration/template generation, SDK resolution, task execution, and release checks; fixture commands use fake tools, not a host Flutter SDK or Zed. | `task-16-full-workflow.txt`; `task-20-clean-artifact.txt` |
| Linux + Flutter/Dart SDK resolution | **Verified (fake SDK)** | A temporary usable `.fvm/flutter_sdk` is probed with exact `flutter --version` and `dart --version` argv. It does not validate a host SDK version or download/install one. | `.sisyphus/evidence/task-16-full-workflow.txt`; `SDK_RESOLUTION.md` |
| Linux + FVM project-local SDK | **Optional; Verified (fake SDK)** | FVM is opt-in (`sdk_mode: "fvm"`). Only an already-present usable `.fvm/flutter_sdk` is selected; this product never invokes FVM or downloads an SDK. | `.sisyphus/evidence/task-16-full-workflow.txt`; `SDK_RESOLUTION.md` |
| Linux + generated Flutter tasks | **Verified (fake SDK)** | Generated `Flutter: Analyze` is run with exact fixture argv and cwd. A real Flutter task/device remains prerequisite-dependent. | `.sisyphus/evidence/task-16-full-workflow.txt` |
| Linux + generated Dart DAP JSON | **Verified (fake adapter)** | Generated launch JSON is accepted by the explicit fake DAP adapter. This is not live Dart/Zed debugging proof. | `.sisyphus/evidence/task-16-full-workflow.txt` |
| Linux + Unicode/spaced project paths | **Verified (fixture/Linux)** | Detection, fake FVM probing, setup writes, and task execution preserved exact Unicode/space paths; hostile shell-hook environment values were removed. | `task-18-spaced-path.txt` |
| Zed manifest and Flutter snippets | **Supported, live validation unverified** | This repository supplies Flutter snippets only. Install Zed's official Dart extension for Dart Analysis Server navigation and the Dart debug adapter; no local Zed CLI/application was available to live-load the combined setup. | `README.md`; `.sisyphus/evidence/task-17-fresh-project.txt` |
| Zed project-local `.zed/tasks.json` / `.zed/debug.json` | **Verified (generation/merge only)** | Setup generates/merges the JSON and preserves workflow boundaries in fixtures. A local Zed plus Dart adapter is required to use it live. | `.sisyphus/evidence/task-16-full-workflow.txt`; `.sisyphus/evidence/task-17-no-tmux.txt` |
| Linux + optional explicit tmux bridge | **Verified (isolated tmux)** | An isolated UUID-scoped `tmux -L` server exercised owned-runner start/stop, fixed `r`/`R`, stale/foreign refusal, and cleanup. It is not a test of the default/user tmux server. | `.sisyphus/evidence/task-16-full-workflow.txt`; `.sisyphus/evidence/task-16-boundary-failures.txt`; `task-18-interrupt-cleanup.txt`; `.sisyphus/evidence/task-19-foreign-resource.txt` |
| tmux bridge with untrusted configuration values | **Verified (isolated probe)** | Metacharacters remain data: argv execution uses no shell and the sentinel was not created. | `.sisyphus/evidence/task-19-injection-probe.txt` |
| macOS core configuration/templates/SDK path | **Supported, unverified locally** | Supported when compatible Python and selected Flutter SDK are available. No macOS run, real SDK, Zed, or DAP evidence exists here. | `README.md` |
| macOS optional tmux bridge | **Unverified** | Ownership verification relies on `/proc`; validate local `/proc` semantics and tmux server before lifecycle control. | `README.md`; `CONFIGURATION.md` |
| WSL core configuration/templates/SDK path | **Supported, unverified locally** | Supported when compatible Python and selected Flutter SDK are available; no WSL run is recorded. | `README.md` |
| WSL optional tmux bridge | **Conditional, unverified locally** | Use only after testing the WSL `/proc` semantics and tmux server. Keep bridge process, project, and target pane in the same environment. | `README.md` |
| Windows-native core configuration/templates | **Supported guidance, unverified locally** | It can work with compatible Python and Flutter SDK. No native-Windows test, live Zed test, or real SDK evidence exists in this repository. | `README.md` |
| Windows-native tmux bridge | **Unsupported** | Native Windows tmux bridge is neither supported nor tested. Native Zed terminal control is not provided. | `README.md`; `task-22-windows-guidance.txt` |
| Git Bash tmux bridge on Windows | **Conditional, unverified locally** | Treat it as an optional bridge only after testing it. The bridge, project, and explicitly configured target pane must all live in the same Git-Bash tmux environment; it is not native Zed terminal control. | `README.md`; `task-22-windows-guidance.txt` |
| Native Zed commands/panels/device picker/save hooks/terminal stdin | **Unsupported** | This is not a VS Code compatibility layer or a native Zed terminal controller. The upstream API document is a proposal only, not an accepted API claim. | `README.md`; `UPSTREAM_ZED_API_PROPOSAL.md`; `.sisyphus/evidence/task-21-non-goals.txt` |
| Future Zed extension API integration | **Optional/future; unverified** | If a relevant official API becomes available, add a version-gated adapter while preserving declarative project-local task/debug files and the external bridge fallback. No accepted upstream API is assumed. | `UPSTREAM_ZED_API_PROPOSAL.md`; `.sisyphus/evidence/task-21-non-goals.txt` |

## Upgrade and migration

### Version and schema contract

The current release is `0.1.0`. Before release, `extension.toml`, `[project].version` in `pyproject.toml`, and the newest `CHANGELOG.md` release heading must match exactly. This is the product's release/manifest-version contract; configuration has no separately declared migration schema version. The mismatch diagnostic and clean-package run are recorded in `task-20-version-mismatch.txt` and `task-20-clean-artifact.txt`.

`configuration.json` is the validated input contract. Keep `project_root` relative and contained, choose `sdk_mode` (`flutter` or opt-in `fvm`), and supply all three tmux target components only when enabling the optional bridge. Validate before setup with `python3 scripts/configuration.py configuration.json`. See `CONFIGURATION.md`.

### Generated-config ownership and safe upgrade

`setup_project` owns only this workflow's stable task/debug labels. Zed project `.zed/tasks.json` uses a top-level JSON array, which setup emits and merges while preserving unrelated task entries. It safely upgrades only the recognized legacy generated `{ "tasks": [...] }` wrapper and refuses other object shapes rather than discarding user data. It parses both existing `.zed/tasks.json` and `.zed/debug.json` before writing either, writes atomically with mode `0600`, and is idempotent after a successful setup. Use Command Palette → `task: spawn` (or `task::Spawn`) to choose a generated Flutter task. Take a normal project backup/review the `dry_run=True` diff before upgrading generated configuration; do not hand-edit entries owned by this workflow if you expect regeneration to replace them. The fixture workflow generated both files, while boundary tests reject unsafe inputs without creating `.zed`; see `.sisyphus/evidence/task-16-full-workflow.txt` and `.sisyphus/evidence/task-16-boundary-failures.txt`.

### Migration/fallback order

1. Upgrade release metadata as one unit and run `make check`; use `make package` only for the deterministic local archive.
2. Validate existing configuration. Resolve a real selected Flutter/Dart SDK only when running real tasks; FVM remains optional and must already have a usable local SDK.
3. Run setup in dry-run mode, review the diff, then regenerate project-local `.zed/tasks.json` and `.zed/debug.json`. A live Zed/Dart adapter is still a user prerequisite.
4. Keep the **core templates** as the normal fallback when the optional tmux bridge is unavailable, disabled, lacks an exact target, or refuses foreign/stale state. Do not broaden tmux permissions or target discovery to recover from a refusal.
5. If moving to WSL/Git Bash for the bridge, re-create/validate the explicit tmux target in that same environment. Do not use Windows-native bridge behavior.
6. If a future official Zed API replaces an external bridge capability, introduce a versioned, opt-in adapter only after official support and live validation. Retain declarative task/debug configuration and the optional external bridge as compatibility paths until the migration is tested.

## Operational limits

- No claim is made for full VS Code parity, arbitrary terminal control, or any accepted upstream API.
- The local tests deliberately avoid real Zed, Flutter/Dart, DAP, device, network, and default tmux services.
- The bridge never discovers targets: it requires exact `session`, `window`, and `pane` configuration and refuses missing, foreign, or stale state rather than mutating user resources.
