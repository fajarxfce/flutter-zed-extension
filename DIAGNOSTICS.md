# Diagnostics Contract

`scripts/diagnostics.py` defines the typed failure record used by Flutter workflow boundaries. It models errors only: it does not invoke Flutter, a shell, DAP, or tmux.

## Stable codes

| Code | Boundary | Meaning |
| --- | --- | --- |
| `sdk.missing` | SDK resolution | No usable Flutter/Dart SDK was found. |
| `project.invalid` | Project detection consumer | Project metadata is not usable. |
| `configuration.invalid` | Configuration consumer | Configuration is malformed or unsafe. |
| `process.failed` | External command consumer | A command returned a nonzero exit status. |
| `process.unexpected_failure` | External command consumer | A command ended unexpectedly after cleanup was attempted. |
| `device.unavailable` | Flutter task consumer | The requested Flutter device is unavailable. |
| `dap.failed` | Future DAP consumer | A modeled DAP request failed. |
| `tmux.failed` | tmux target inspector and future tmux consumer | The configured explicit target is unavailable, mismatched, or tmux cannot be inspected. |

Every `Diagnostic` has a stable `code`, actionable `message`, and string `context`. Command-related diagnostics additionally retain the argv tuple, exact captured `stdout` and `stderr`, and exit status when available. Consumers must preserve external stderr verbatim rather than replace it with generic text.

`SdkResolutionError` keeps its established message and adds an optional `.diagnostic`. Future project/configuration/DAP/tmux/task consumers can use the helpers without implementing those external operations.
