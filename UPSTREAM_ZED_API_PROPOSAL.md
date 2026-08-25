# Proposal: Permissioned Workflow Controls for Zed Extensions

**Status:** Proposal only — no API described here is accepted, implemented, or required by current Zed releases.

## Summary

This proposal asks for a deliberately small set of opt-in Zed extension APIs for workflow-oriented extensions:

1. registered extension commands and optional keybindings;
2. scoped terminal/process input for an extension-created or explicitly user-selected process;
3. lifecycle events for workspace and explicit command invocations; and
4. a compact device/status surface.

The intent is not VS Code compatibility or a general terminal automation API. It is to let an extension such as this Flutter workflow expose safe, visible actions without exporting project state to an external tmux pane.

## Evidence and current boundary

Zed's current official extension documentation lists language, debugger, theme, icon theme, snippet, and MCP-server features; it does not document extension-contributed command-palette commands/keybindings, terminal stdin/control, lifecycle hooks, or a device/status UI. This is a documentation-surface observation, not a claim that an internal API cannot exist. Zed does document capability-gated `process:exec`, in which a denied operation returns an error.

This product currently registers Dart LSP/snippets and generates project-local `.zed/tasks.json`/`.zed/debug.json`; it does **not** provide native command-palette commands, a device picker, a custom panel, save hooks, terminal stdin control, or generic VS Code debug parity. Its optional tmux bridge is external, explicitly targeted, and deliberately limited to a proven owned runner plus literal `r`/`R` hot actions. Full source and reproducible-test traceability is recorded in `.sisyphus/evidence/task-21-traceability.txt`.

## Use cases

### Flutter run controls

A Flutter extension should be able to contribute visible `Flutter: Run`, `Flutter: Stop`, `Flutter: Hot Reload`, and `Flutter: Hot Restart` commands. `Run` creates a process with a reviewed argv/cwd. The hot actions are available only while the extension holds a handle to that exact process and should send the fixed bytes for `r` or `R`; they must not target an arbitrary terminal.

### Device visibility

After a user-triggered `flutter devices --machine` operation, the extension should display a short status item such as `Flutter: emulator-5554`, with an action that opens an extension-owned selector. This is not a request for unrestricted panels or device discovery by Zed core.

### Lifecycle-safe refresh

The extension should refresh its own status after workspace open/configuration change and optionally request a post-save callback for explicitly declared file globs. A save callback must not imply permission to run a process; execution remains separately gated and user initiated unless the user has explicitly enabled an automation rule.

## Smallest viable APIs

Names are illustrative pseudocode, not a binding.

### 1. Commands and keybindings

```rust
extension.register_command(CommandSpec {
    id: "flutter.run",
    title: "Flutter: Run",
    when: "workspace_has_file('pubspec.yaml')",
    handler: run_flutter,
});

extension.register_keybinding(KeybindingSpec {
    command: "flutter.hot_reload",
    default: None, // users opt in through normal keymap configuration
});
```

* Command IDs are namespaced by extension ID, titles are displayed in Zed's command UI, and handlers run only on an explicit command invocation.
* An extension may declare a keybinding target, but it receives no active default binding. User keymaps resolve conflicts and may bind or unbind it.
* Commands have no implicit process, filesystem, network, or UI permission.

### 2. Scoped process and stdin

```rust
let run = extension.process.spawn(ProcessSpec {
    argv: [flutter, "run", "-d", device_id],
    cwd: project_root,
    terminal: ProcessTerminal::Visible,
    stdin: StdinPolicy::FixedTokens([b"r", b"R"]),
    label: "Flutter run",
}).await?;

run.send_stdin(StdinToken::Named("hot_reload")).await?;
run.stop(StopPolicy::InterruptThenTerminate { grace_ms: 3_000 }).await?;
```

Minimum constraints:

* `spawn` requires the existing `process:exec` authorization narrowed by command and argument patterns; no shell string form is provided.
* The returned handle is opaque, non-forgeable, owned by the creating extension instance, and valid only while that process identity remains alive. It cannot name a pre-existing Zed terminal, PID, tmux pane, or another extension's process.
* `send_stdin` is denied unless `stdin:write` was granted **for that handle**. The initial minimal form permits only extension-declared fixed byte tokens, displays them in the permission review, and rejects arbitrary text, escape sequences, and terminal selection.
* Stop is limited to the owned handle, emits an interrupt then a bounded terminate request, and never kills an arbitrary process tree or a user terminal.
* Process output remains in Zed's visible task/terminal UI; the extension may receive structured exit/status events, but not a blanket terminal-control object.

### 3. Lifecycle hooks

```rust
extension.on_workspace(WorkspaceEvent::Opened, refresh_status);
extension.on_configuration_changed(["flutter-workflow"], validate_configuration);
extension.on_save(SaveSubscription {
    globs: ["**/*.dart"],
    mode: SaveMode::NotifyOnly,
}, mark_analysis_stale);
```

* Hooks are declarative, workspace-scoped, cancelable, and ordered only per extension; they do not run while Zed is restoring a workspace unless the user enables them.
* `Opened`, configuration-change, and notify-only save hooks require no process privilege.
* A hook cannot spawn a process without a separate per-workspace `automation:process` grant. The prompt identifies trigger, command allowlist, cwd scope, and rate limit. Default: disabled.
* Zed debounces save notifications and exposes a user-visible list of enabled automations. Hooks must be budgeted and cancellable to prevent UI stalls.

### 4. Device/status UI

```rust
let status = extension.status.create(StatusItemSpec {
    id: "flutter.device",
    text: "Flutter: no device",
    tooltip: "Select Flutter device",
    on_activate: "flutter.select_device",
});

extension.ui.show_selector(SelectorSpec {
    title: "Select Flutter device",
    items: devices.iter().map(Device::to_safe_label),
    on_confirm: set_device,
});
```

* This is a bounded status item and selector API, not arbitrary webviews, dock panels, or unrestricted native UI.
* Extension-provided strings are text, not markup. Selection does not execute a command or change a device until a subsequent explicit command.
* The API is capability-gated as `ui:status` and `ui:selector`, with users able to disable either. It exposes no editor-wide device manager or access to other extensions' UI.

## Permissions, disclosure, and capability gating

Extend the existing capability model rather than creating an extension-specific trust bypass:

| Proposed capability | Scope | Default |
| --- | --- | --- |
| `commands:register` | Extension command namespace | Allowed; inert until invoked |
| `process:exec` | Command + argv-pattern + workspace cwd | Existing permission model; denied calls error |
| `stdin:write` | Owned process handle + declared fixed token names | Denied until explicitly granted |
| `lifecycle:observe` | Declared workspace/config/save event types | Allowed for notify-only events |
| `automation:process` | Trigger + command allowlist + cwd + rate limit | Denied until explicitly granted |
| `ui:status`, `ui:selector` | Extension-owned bounded surfaces | User-disableable |

Permission prompts must state the extension ID, workspace, executable, argv pattern, working-directory scope, stdin token literals, lifecycle trigger, and rate limit. Grants are revocable in settings and must be invalidated when the extension, workspace, executable path, or declared scope changes. APIs return typed denial/expired-handle errors and must not silently fall back to a shell, existing terminal, tmux, or external process.

## Compatibility and versioning

* Ship each API behind a named extension-API feature/version negotiated at load time.
* Older Zed builds continue loading an extension that marks these features optional; the extension hides unsupported commands/status actions and retains declarative tasks/debug configuration.
* New APIs are additive. Behavior changes require a new capability kind or versioned field rather than widening a prior grant.
* Stable command IDs and explicit deprecation windows allow keymap migration. Zed should surface disabled/unsupported actions with an explanatory reason, not a no-op.

## Migration path for this Flutter workflow

1. Preserve the current safe default: manifest LSP/snippets plus project-local tasks/debug configuration.
2. If command registration is available, map existing generated task intents to extension commands; retain `.zed/tasks.json` as the fallback.
3. If scoped process handles and `stdin:write` are granted, start Flutter through the owned-handle API and expose only fixed reload/restart tokens. Do not import tmux identity, PID, or pane semantics.
4. If lifecycle/status APIs are available and enabled, refresh an extension-owned device status item. Never auto-run Flutter from a save hook without `automation:process`.
5. Keep the external tmux bridge as a separately configured compatibility option until users migrate; it remains outside Zed terminal control.

## Alternatives considered

### Keep tasks/debug JSON only

This remains the baseline and is sufficient for run/test/debug configuration. It cannot express an extension-owned command UX, scoped process identity, fixed stdin tokens, or a live compact device/status selector.

### Continue using external tmux

tmux can supply an external interactive runner, but it requires explicit session/window/pane targeting and platform-specific ownership checks. It is intentionally not native Zed terminal control. The proposed process handle is safer because it cannot address arbitrary panes or foreign processes.

### General terminal API

Rejected for the initial design. Selecting a terminal and writing arbitrary bytes would reproduce the foreign-resource and injection risks that the current bridge avoids. A handle-scoped fixed-token API serves Flutter hot reload/restart without granting terminal automation.

### Arbitrary panels/webviews and broad background hooks

Rejected. A bounded status item/selector plus notify-only lifecycle hooks provides the stated UX without a broad UI or unattended-execution surface.

## Non-goals

* No claim that Zed has accepted or currently offers these APIs.
* No full VS Code extension/debug/terminal compatibility layer.
* No arbitrary terminal selection, terminal scraping, key injection, shell execution, process discovery, PID signaling, or tmux control.
* No automatic device selection, unattended save-triggered execution, network access, or persistent background daemon.
* No replacement for Zed tasks, debugger extensions, or user keymaps.
* No changes to Zed core or coupling of this repository's runtime to a future API.

## Requested feedback

1. Is an owned process handle with declared fixed stdin tokens compatible with Zed's extension sandbox and process model?
2. Should lifecycle automation be a separate permission as proposed, or should hooks be notify-only in the first release?
3. Which existing status/selector primitives can be safely exposed to extensions without broad custom-panel support?
4. What extension-API versioning convention best supports optional capability discovery?

## References

* Zed, [Developing Extensions](https://zed.dev/docs/extensions/developing-extensions) — official current documented extension feature list and dev-extension workflow; accessed 2026-08-25.
* Zed, [Extension Capabilities](https://zed.dev/docs/extensions/capabilities) — official current capability-grant and `process:exec` behavior; accessed 2026-08-25.
* Local implementation and reproducible evidence: `.sisyphus/evidence/task-21-traceability.txt`.
