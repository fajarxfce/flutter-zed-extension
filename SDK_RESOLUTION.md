# SDK and FVM Resolution

`scripts/sdk_resolution.py` resolves a Flutter SDK after configuration parsing and project detection. It is separate from `scripts/project_detection.py`: detection reads metadata only, while resolution validates executable candidates and runs their version commands.

## Precedence

1. When `FlutterConfiguration.sdk_mode` is `fvm`, a valid project-local `.fvm/flutter_sdk` wins.
2. A valid caller-provided `explicit_sdk` root wins next. It is an integration input, not a new configuration field.
3. Matching `flutter` and `dart` executables in `PATH` are the final system fallback.

A candidate is valid only when both `bin/flutter` and `bin/dart` exist, are executable, and return zero from `--version`. The resolver returns their canonical paths and preserves each command's stdout and stderr. FVM metadata alone is not sufficient: the local SDK must be present and usable.

## Safety and errors

The resolver never invokes a shell, downloads an SDK, invokes FVM, or mutates `PATH`. Every version probe uses an argv array equivalent to `[executable_path, "--version"]`, so paths containing spaces remain a single argument.

`SdkResolutionError` is the stable error type. Its messages name missing or non-executable candidates, version-command failures (including command output), incompatible PATH pairs, and remediation when PATH has no SDK: install Flutter or configure an SDK directory.

Default tests create fake executable files and supply an isolated environment. They do not probe a locally installed Flutter or Dart SDK.
