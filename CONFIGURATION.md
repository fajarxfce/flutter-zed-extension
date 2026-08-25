# Flutter Workflow Configuration

`configuration.json` is the single validated contract for downstream project detection, SDK, DAP, task, and tmux modules. Validate it offline:

```sh
python3 scripts/configuration.py configuration.json
```

The validator uses only the Python standard library. Parsing never probes or invokes Flutter, FVM, tmux, Zed, a DAP adapter, or a shell.

## Contract

```json
{
  "project_root": "example-app",
  "sdk_mode": "fvm",
  "target": "lib/main_staging.dart",
  "device": "emulator-5554",
  "flavor": "staging",
  "mode": "debug",
  "args": ["--dart-define=API_ENV=staging"],
  "dap": {
    "adapter": "Dart",
    "request": "launch",
    "flutterMode": "debug"
  },
  "tmux": {
    "session": "flutter",
    "window": "app",
    "pane": "%3"
  }
}
```

| Field | Type and validation | Default |
| --- | --- | --- |
| `project_root` | Required non-empty relative path to an existing directory. It cannot escape the configuration file's directory. | None |
| `sdk_mode` | `flutter` or `fvm`. FVM is opt-in and is not probed during parsing. | `flutter` |
| `target` | Optional non-empty relative path rooted at `project_root`; it cannot escape that root. File existence is downstream project-detection work. | None |
| `device`, `flavor` | Optional non-empty, single-line strings that do not start with `-`. | None |
| `mode` | `debug`, `profile`, or `release` only. | `debug` |
| `args` | Optional list of non-empty, single-line strings. The future command generator must allowlist accepted Flutter flags rather than shell-concatenate this input. | `[]` |
| `dap` | Optional object requiring Zed-compatible `adapter` and `request` (`launch` or `attach`). Other values are scalar strings, integers, booleans, or safe string lists, for adapter-specific settings. | None |
| `tmux` | Optional object. If present, it must contain all of `session`, `window`, and `pane` as non-empty, single-line strings. No component is inferred. | None |

## tmux inspection boundary

The optional `scripts.tmux_target.inspect_tmux_target` consumer accepts only the `TmuxTarget` produced by this schema. It uses one argv-only `tmux display-message -p -t SESSION:WINDOW.PANE` request and requires tmux to return the exact configured session name, window name, and pane ID. It does not list/discover targets or infer omitted values.

The consumer never creates, kills, renames, selects, attaches to, or sends input to tmux resources. A missing tmux executable, inaccessible server, missing pane, or mismatched identity raises the stable `tmux.failed` diagnostic before a later lifecycle/input consumer can act. Callers can pass server options as distinct argv entries—for example `("-L", "isolated-test-socket")`—to use an independent tmux server. No shell command strings are accepted or constructed.

## tmux owned runner lifecycle

`scripts.tmux_runner` provides opt-in `start_runner`, `status_runner`, and `stop_runner` operations. Every operation first uses the same exact `inspect_tmux_target` contract, so it never discovers or retargets tmux resources. Start uses the pre-existing configured pane only and neither creates, kills, renames, nor selects tmux sessions, windows, or panes.

A caller supplies runner argv, a controlled new state-file path, and a controlled new log-file path. Start assigns a cryptographic ownership token, verifies the pane process PID, Linux process start time, and token in `/proc`, then writes mode-`0600` state containing the exact target, PID identity, argv, and log path. Existing state or log paths are refused to preserve prior evidence.

`status_runner` reports one of `running-owned`, `stopped-owned`, `stale-mismatched`, or `foreign-no-owned-runner`, always retaining the recorded PID, identity, and log location where present. `stop_runner` sends graceful `SIGTERM` only after token and PID-start-time verification; foreign, absent, stopped, and stale runners are refused without changing their pane or process state. This lifecycle has no hot reload or restart input support.

The DAP names align with Zed's `.zed/debug.json` contract: `label` and `adapter` identify a configuration, `request` is `launch` or `attach`, and adapter-specific fields are passed through by the future DAP consumer. This schema deliberately models only reusable adapter settings; it does not declare a Zed debug adapter or execute DAP.

## Generated Dart/Flutter debug configurations

`scripts.dap_templates.generate_debug_configurations` produces the content a consumer project may write to `.zed/debug.json`; this extension does not write consumer files or declare a debug adapter. Entries target the existing Dart extension adapter identifier, `"Dart"`, with `type: "flutter"`.

- **Launch** maps `target` to `program`, `project_root` to `cwd`, `mode` to `flutterMode`, `device` to `deviceId`, and `flavor` to leading `toolArgs`. It then appends configured `args` and optional `dap.toolArgs` without changing their order. `sdk_mode: "fvm"` emits `useFvm: true`; executable selection remains owned by the resolved SDK contract.
- The requested **launch** or **attach** entry follows `dap.request`. **Attach** requires `dap.vmServiceUri` and maps it to `vmServiceUri`. It deliberately omits launch-only device, mode, and tool arguments; a generic process picker is not a Flutter attach substitute.
- Test-only `execute_adapter_validation` sends one generated JSON object over stdin to an explicitly supplied fake adapter through a one-element argv array. It preserves stdout, stderr, and exit status. A missing adapter raises actionable `dap.failed` and has no tmux path or fallback. It must not run Flutter's real `debug_adapter` command.

## Capability Matrix

| Capability | Owner | Status and boundary |
| --- | --- | --- |
| Dart language navigation | Zed's official Dart extension | Required for Dart Analysis Server navigation; this extension does not register a language server. |
| Flutter project validation and SDK selection | Future offline consumer | Contracted by this schema; no project detection or Flutter/FVM executable lookup occurs here. |
| Flutter tasks | `scripts/task_templates.py` → future `.zed/tasks.json` | The generator emits declarative `label`, `command`, `args`, and deterministic `cwd` task objects. It uses the resolved Flutter/Dart executable paths and never shell-concatenates values. Environment, terminal behavior, and save options remain Zed task fields for a future project-setup writer; this task deliberately does not write a consumer `.zed/tasks.json`. |
| Flutter debugging | `scripts/dap_templates.py` → consumer `.zed/debug.json` | Generates declarative Dart-adapter Flutter launch/attach entries; no adapter is declared or real DAP process executed. |
| Device picker, command palette, save hook, custom panel | Native extension API | Unsupported by this scaffold and not advertised as available. |
| Hot reload and restart | Explicit opt-in tmux bridge | Deferred. A future bridge may use only the exact configured `session`, `window`, and `pane`; it must never guess, create, kill, or otherwise mutate user-owned tmux resources. |

## Safety Rules

- Unknown top-level and tmux fields are rejected so consumers cannot silently assume unsupported behavior.
- Paths are relative and constrained to their declared roots.
- Mode values are limited to documented Flutter modes: `debug`, `profile`, and `release`.
- FVM and tmux remain opt-in configuration choices, not parse-time dependencies.
- Future command generators must allowlist Flutter flags and pass arguments as arrays rather than treating this schema as permission to shell-concatenate arbitrary input.
