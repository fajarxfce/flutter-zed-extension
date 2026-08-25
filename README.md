# Flutter Zed Extension

This repository supplies a small, offline-verifiable Flutter workflow foundation for Zed: Flutter-project detection, safe generation of project-local Zed task and debug configuration, SDK selection, and an optional explicitly targeted tmux runner bridge. It also registers the Dart language-server foundation and Flutter snippets in `extension.toml`.

It is **not** a published workflow, a VS Code-compatibility layer, or a native Zed terminal controller. In particular, it does not provide native command-palette commands, a device picker, a custom panel, save hooks, terminal stdin control, or generic VS Code debug parity.

## Prerequisites and scope

* Python 3.11+ is required for the offline checks (`tomllib` is standard library). No Python package installation or network access is required.
* A Flutter SDK is needed only when resolving SDKs or running generated Flutter tasks. The fixture walkthrough uses a fake SDK; it does not need a host Flutter installation or a device.
* FVM is optional. Resolution uses a usable project-local `.fvm/flutter_sdk` when `sdk_mode` is `fvm`; it never invokes FVM or downloads an SDK.
* Generated Zed files are intentionally portable: system Flutter tasks require `flutter` (and the formatter requires `dart`) on `PATH`; FVM tasks require `fvm` on `PATH` and invoke its `flutter`/`dart` proxies. Generated task working directories use `$ZED_WORKTREE_ROOT`, while targets and debug programs are project-relative.
* Zed is optional for every offline command below. A locally installed Zed application/CLI is required to live-load the extension and use generated `.zed/tasks.json` or `.zed/debug.json`. Live loading is not verified here because this environment has no Zed CLI/application.
* The core configuration, detection, generated task/debug JSON, and SDK-resolution path are supported on Linux, macOS, and WSL when Python and the selected Flutter SDK are available. All direct child processes use argv arrays (not shell strings), preserve Unicode and spaces in paths, and retain required caller environment variables while dropping `BASH_ENV`, `ENV`, and `CDPATH` shell hook values.
* The tmux bridge is optional and disabled unless the configuration includes every explicit target component. Its owned-runner lifecycle and fixed `r`/`R` operations are verified on Linux only because ownership verification uses `/proc`; macOS and WSL users must validate their local `/proc` semantics and tmux server before relying on lifecycle control. An interrupt sends `SIGINT` only to the token- and PID-verified owned runner; it never kills or recreates the configured pane, window, session, or tmux server.
* Windows-native core configuration generation can work with a compatible Python and Flutter SDK, but the tmux bridge is not supported or tested in native Windows. Use the bridge only through a tested WSL or Git-Bash tmux environment with the bridge, project, and target pane in that same environment; native Zed terminal control is not provided.

Existing `.zed/tasks.json` and `.zed/debug.json` files are read before generated entries are merged. Zed requires `.zed/tasks.json` to be a top-level JSON array; setup emits that schema and safely upgrades its recognized legacy generated `{ "tasks": [...] }` wrapper. Debug configuration accepts JSONC `//` and `/* ... */` comments outside JSON strings, then serializes the merged result as standard JSON; comments are therefore not retained after a write. Malformed JSON, unsupported task shapes, or JSONC are never overwritten.

To run a generated Flutter task in Zed, open the Command Palette, choose `task: spawn` (or `task::Spawn`), then select the Flutter task.

Run the complete deterministic verification surface from the repository root:

```sh
make check
```

## Release packaging

Release metadata uses Semantic Versioning and has one consistency contract: `extension.toml`, `[project].version` in `pyproject.toml`, and the newest release heading in `CHANGELOG.md` must match exactly. Validate it with:

```sh
make release-check
```

Create a deterministic local source archive without publishing it:

```sh
make package
```

The archive has sorted members and normalized owner, timestamp, and gzip metadata. It excludes `.git`, `.sisyphus`, `tests`, fixture data, root evidence files, caches, virtual environments, build output, bytecode, and secret-shaped filenames. `make package` re-inspects the completed archive and rejects unsafe paths, links, excluded content, and unsorted members.

CI always runs the dependency-free offline core checks and package build on Ubuntu/Python 3.11. The tmux integration test runs only when the repository variable `RUN_TMUX_TESTS` is explicitly `true`; it installs tmux for that Linux-only opt-in job. No other platform or registry/signing integration is configured.

This command is noninteractive and uses only repository fixtures/fake tools. It does not require Zed, Flutter, FVM, tmux, a device, or network access.

## Core workflow (no tmux required)

The core path is project-local configuration generation; it has no tmux dependency.

1. Create a Flutter application with a supported `pubspec.yaml`, `lib/`, and Flutter dependency metadata. Project detection reads only metadata; it does not run Flutter.
2. Create `configuration.json` beside the project. `project_root` must be a relative existing directory and all optional paths must remain under it. Start with the minimum configuration:

   ```json
   {
     "project_root": "my_flutter_app",
     "sdk_mode": "flutter",
     "dap": {
       "adapter": "Dart",
       "request": "launch"
     }
   }
   ```

3. Validate it before using it:

   ```sh
   python3 scripts/configuration.py configuration.json
   ```

4. Resolve a usable SDK through the programmatic resolver, then call `scripts.project_setup.setup_project(configuration, sdk)`. This generates or safely merges `.zed/tasks.json` and `.zed/debug.json` in the detected Flutter application. Use `dry_run=True` first to get a unified diff without writing; a repeated successful setup is idempotent (`changed=False` and an empty diff).

`setup_project` is deliberately a library API rather than a CLI. It first verifies that the target is a Flutter application, parses both existing JSON files before writing either one, preserves unrelated entries and top-level task settings, replaces only this workflow's stable labels, and writes atomically with mode `0600`. It never starts Flutter, Zed, a DAP adapter, tmux, a shell, or a runner.

### Clean-project walkthrough

The following executable fixture is the documented clean-project walkthrough. It creates a temporary Flutter-shaped project and fake FVM SDK, generates `.zed/tasks.json` and `.zed/debug.json`, exercises a generated analyze task and launch configuration, and removes all fixture state afterward:

```sh
python3 -m unittest tests.test_workflow_orchestration.WorkflowOrchestrationTests.test_complete_offline_workflow_records_generated_artifacts_and_fixed_tmux_inputs -v
```

For a strictly no-tmux core fallback (detection, configuration generation, task templates, and debug templates only), run:

```sh
python3 -m unittest tests.test_project_setup -v
```

These fixture commands are the safe local proof of generation behavior. They do not live-load Zed, contact a device, invoke a real Flutter SDK, or modify a consumer project.

## Generated Zed files

Zed calls task entries in `.zed/tasks.json` **tasks** and entries in `.zed/debug.json` **debug configurations**. Generated task entries have a stable `label`, resolved Flutter executable `command`, separate argv `args`, and project-root `cwd`; no shell string is constructed.

The generated task labels cover:

* `Flutter: Pub Get`, `Flutter: Analyze`, `Flutter: Format Check`, `Flutter: Test`;
* `Flutter: Build APK`, `Flutter: Build Web`;
* `Flutter: Run`, `Flutter: Devices`, and `Flutter: Clean`.

`target`, `flavor`, `mode`, `device`, and safe configured arguments are emitted only where the Flutter command accepts them. A configured device applies to `Flutter: Run`; it is not a native Zed device picker. If the selected device is absent when a real task runs, handle the resulting `device.unavailable` diagnostic by selecting/starting a valid Flutter device or removing/changing `device` in the configuration.

Generated debug configurations use Zed's `label`, `adapter`, and `request` terminology and the installed Dart adapter identifier (`"Dart"`) with `type: "flutter"`:

* `dap.request: "launch"` produces a Flutter launch configuration. `target` becomes `program`; `project_root` becomes `cwd`; mode, device, flavor, and allowed arguments become adapter fields.
* `dap.request: "attach"` requires `dap.vmServiceUri`; it produces an attach configuration and deliberately omits launch-only device, mode, and tool arguments. It does not implement a generic Flutter process picker.

A live debug session depends on Zed and its installed Dart adapter. The repository only validates generated JSON against a test-only fake adapter; it does not declare, install, or run a real debug adapter.

## SDK and optional FVM

SDK resolution happens after configuration validation and Flutter-project detection. The precedence is:

1. with `sdk_mode: "fvm"`, a valid project-local `.fvm/flutter_sdk`;
2. a caller-supplied explicit SDK root;
3. matching `flutter` and `dart` executables on `PATH`.

A candidate must have executable `bin/flutter` and `bin/dart`, and both `--version` commands must succeed. The resolver does not call FVM, mutate `PATH`, use a shell, or download anything. See [SDK_RESOLUTION.md](SDK_RESOLUTION.md) for the exact contract.

## Optional explicit tmux bridge

The bridge is separate from generated Zed tasks/debug configurations. It controls **only an explicitly configured external tmux pane**; it never controls Zed's native terminal.

Enable the bridge only by supplying all three fields:

```json
{
  "tmux": {
    "session": "flutter",
    "window": "app",
    "pane": "%3"
  }
}
```

No session, window, or pane is inferred or discovered. Before every lifecycle or hot operation, the bridge checks the exact `SESSION:WINDOW.PANE` identity. `start_runner`, `status_runner`, and `stop_runner` operate only on a runner this bridge started and can prove it owns. They never create, kill, rename, select, or attach to tmux sessions/windows/panes; `stop_runner` sends `SIGTERM` only after ownership and process-start-time verification.

For a proven owned runner, hot operations are intentionally fixed:

* reload sends literal `r`;
* restart sends literal `R`.

No arbitrary keystrokes or sequences are accepted. Each hot operation revalidates the target and ownership immediately before sending input. A missing target, stale identity, stopped runner, or foreign process fails with `tmux.failed` without pane input. The lifecycle test is covered by the full walkthrough above; it uses an isolated disposable tmux socket when tmux is available and is skipped otherwise.

## Troubleshooting and safe recovery

| Symptom | Exact check | Safe fix / limitation |
| --- | --- | --- |
| `sdk.missing` or Flutter/FVM cannot be resolved | Check that the selected root contains executable `bin/flutter` and `bin/dart`; run each with `--version`. For FVM, inspect `PROJECT/.fvm/flutter_sdk`. | Install/configure a usable SDK, pass a valid explicit SDK root, or correct `PATH`. FVM metadata alone is insufficient and the resolver will not run FVM or download an SDK. |
| Configuration is rejected or `configuration.invalid` | Run `python3 scripts/configuration.py configuration.json`. Check `project_root` is relative/existing, paths do not escape it, selectors do not start with `-`, and `dap.request` is `launch` or `attach`. | Correct the JSON. Existing malformed `.zed/tasks.json` or `.zed/debug.json` is never overwritten: repair it manually, then rerun setup/dry-run. |
| The project is invalid or setup writes nothing | Confirm `pubspec.yaml`, `lib/`, and supported Flutter dependency metadata are present. | Use a detected Flutter application. Dart-only packages and non-project directories cannot receive generated Flutter run configuration. |
| Zed is missing or generated files do not live-load | Check that the Zed application/CLI and Dart adapter are installed on the machine. | Use Zed's current extension-development/live-load workflow for `extension.toml`. Offline checks cannot verify live loading, and no Zed CLI is required for core generation. |
| Debug adapter is unavailable / `dap.failed` | Verify Zed has the Dart adapter and inspect the generated `.zed/debug.json` entry's `adapter`, `request`, and attach `vmServiceUri` if applicable. | Install/configure the adapter in Zed or correct the entry. There is no real-adapter fallback, tmux fallback, or generic Flutter process picker. |
| A run task has no usable device / `device.unavailable` | Run the generated `Flutter: Devices` task or use Flutter tooling to list devices. Compare with configured `device`. | Start/select a valid Flutter device, change `device`, or omit it. The workflow does not implement a native device selector. |
| `tmux.failed`: tmux missing, target missing, or target mismatch | Confirm `tmux` is on `PATH` and the exact configured `session`, `window`, and `pane` exist on the intended server. | Install tmux only if using the optional bridge, then correct the explicit target. Core setup/tasks/debug configuration do not need tmux. |
| `tmux.failed`: foreign runner or stale identity | Use `status_runner`; it reports `foreign-no-owned-runner` or `stale-mismatched` rather than retargeting. | Do not force hot input or kill the process through this bridge. Stop/clean up the external runner yourself, use a new controlled state/log path, then start a new bridge-owned runner. |
| Request for native terminal control, arbitrary keys, custom panel/commands, save hooks, or VS Code parity | Compare the request with the boundaries above. | Unsupported. The bridge is only an opt-in external tmux lifecycle with literal `r`/`R`; it is not native Zed terminal control. |

See [CONFIGURATION.md](CONFIGURATION.md), [SDK_RESOLUTION.md](SDK_RESOLUTION.md), and [DIAGNOSTICS.md](DIAGNOSTICS.md) for detailed contracts and stable diagnostic codes.

## Evidence convention

Run `make check` before changing documentation or behavior. Evidence belongs in `.sisyphus/evidence/`, records the exact command plus relevant output/assertions, and distinguishes offline fixture verification from prerequisite-dependent live Zed behavior.
