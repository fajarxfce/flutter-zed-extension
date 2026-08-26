from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from scripts.configuration import DapSettings, FlutterConfiguration, TmuxTarget
from scripts.dap_templates import DapAdapterError, execute_adapter_validation, generate_debug_configurations
from scripts.diagnostics import DiagnosticError, invalid_project, process_failure
from scripts.project_detection import detect_project
from scripts.project_setup import setup_project
from scripts.sdk_resolution import SdkResolutionError, resolve_sdk
from scripts.task_templates import execute_task_template, generate_task_templates
from scripts.tmux_runner import HotOperation, interrupt_runner, perform_hot_operation, start_runner, status_runner, stop_runner

ROOT = Path(__file__).resolve().parents[1]
FAKE_FLUTTER = ROOT / "tests" / "fake_flutter_sdk.py"
FAKE_ADAPTER = ROOT / "tests" / "fake_dap_adapter.py"


class WorkflowFixture:
    def __init__(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temporary_directory.name)
        self.project = self.directory / "fixture app"
        self.sdk = self.project / ".fvm" / "flutter_sdk"
        self.task_log = self.directory / "task.json"
        self.version_log = self.directory / "versions.jsonl"
        self.adapter_log = self.directory / "adapter.json"
        self.runner_log = self.directory / "runner.log"
        self.runner_state = self.directory / "runner-state.json"
        self.socket = f"flutter-zed-task16-{uuid.uuid4().hex}"
        self.server_options = ("-L", self.socket)
        self.tmux = shutil.which("tmux")
        self.target = TmuxTarget("known", "app", "%0")

    def __enter__(self) -> "WorkflowFixture":
        (self.project / "lib").mkdir(parents=True)
        (self.project / "lib" / "main.dart").write_text("void main() {}\n", encoding="utf-8")
        (self.project / "pubspec.yaml").write_text(
            "name: fixture_app\nenvironment:\n  sdk: \">=3.0.0 <4.0.0\"\ndependencies:\n  flutter:\n    sdk: flutter\nflutter:\n",
            encoding="utf-8",
        )
        self._make_sdk()
        self._make_adapter()
        return self

    def __exit__(self, *_: object) -> None:
        if self.tmux is not None:
            subprocess.run((self.tmux, *self.server_options, "kill-server"), check=False, capture_output=True, text=True)
        self.temporary_directory.cleanup()

    def _make_sdk(self) -> None:
        bin_directory = self.sdk / "bin"
        bin_directory.mkdir(parents=True)
        for name in ("flutter", "dart"):
            executable = bin_directory / name
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "if sys.argv[1:] == ['--version']:\n"
                "    Path(os.environ['FAKE_VERSION_LOG']).open('a', encoding='utf-8').write(json.dumps({'executable': Path(sys.argv[0]).name, 'arguments': sys.argv[1:]}, sort_keys=True) + '\\n')\n"
                "    print(f'{Path(sys.argv[0]).name} fake-16.0')\n"
                "    raise SystemExit(0)\n"
                "os.environ['FAKE_SDK_EXECUTABLE'] = sys.argv[0]\n"
                f"from runpy import run_path\nrun_path({str(FAKE_FLUTTER)!r}, run_name='__main__')\n",
                encoding="utf-8",
            )
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    def _make_adapter(self) -> None:
        self.adapter = self.directory / "fake adapter"
        self.adapter.write_text(
            f"#!{sys.executable}\nfrom runpy import run_path\nrun_path({str(FAKE_ADAPTER)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        self.adapter.chmod(self.adapter.stat().st_mode | stat.S_IXUSR)

    def configuration(self, *, tmux: TmuxTarget | None = None) -> FlutterConfiguration:
        return FlutterConfiguration(
            project_root=self.project.resolve(),
            worktree_root=self.project.resolve(),
            sdk_mode="fvm",
            target=(self.project / "lib" / "main.dart").resolve(),
            device="fake-device",
            flavor="fixture",
            mode="debug",
            args=("--dart-define=FIXTURE=1",),
            dap=DapSettings("Dart", "launch", {}),
            tmux=tmux,
        )

    def environment(self, **extra: str) -> dict[str, str]:
        return os.environ | {"FAKE_SDK_LOG": str(self.task_log), "FAKE_VERSION_LOG": str(self.version_log), "FAKE_DAP_LOG": str(self.adapter_log), **extra}

    def start_server(self) -> None:
        assert self.tmux is not None
        subprocess.run((self.tmux, *self.server_options, "new-session", "-d", "-s", "known"), check=True, capture_output=True, text=True)
        subprocess.run((self.tmux, *self.server_options, "rename-window", "-t", "known:0", "app"), check=True, capture_output=True, text=True)


def require_flutter_project(path: Path) -> None:
    detection = detect_project(path)
    if not detection.has_run_configuration:
        raise DiagnosticError(invalid_project("Workflow requires a detected Flutter application.", project_root=str(path)))


class WorkflowOrchestrationTests(unittest.TestCase):
    def test_unicode_spaced_path_preserves_root_args_and_environment(self) -> None:
        with WorkflowFixture() as fixture:
            renamed = fixture.directory / "unicodé fixture app"
            fixture.project.rename(renamed)
            fixture.project = renamed
            fixture.sdk = fixture.project / ".fvm" / "flutter_sdk"
            configuration = fixture.configuration()
            detection = detect_project(fixture.project / "lib")
            sdk = resolve_sdk(configuration, detection, environment=fixture.environment(BASH_ENV="ignored", ENV="ignored", CDPATH="ignored"))
            setup = setup_project(configuration, sdk)
            analyze = next(task for task in generate_task_templates(configuration, sdk).tasks if task.label == "Flutter: Analyze")
            result = execute_task_template(analyze, environment=fixture.environment(FAKE_SDK_LOG_CWD="1", BASH_ENV="ignored", ENV="ignored", CDPATH="ignored"))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(setup.changed)
            self.assertEqual(
                json.loads(fixture.task_log.read_text(encoding="utf-8")),
                {"arguments": ["analyze", "--dart-define=FIXTURE=1"], "cwd": str(fixture.project.resolve()), "executable": str(sdk.flutter.path)},
            )

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is optional and unavailable")
    def test_interrupt_stops_only_owned_runner_and_preserves_target(self) -> None:
        with WorkflowFixture() as fixture:
            fixture.start_server()
            command = (sys.executable, "-c", "import time; time.sleep(60)")
            started = start_runner(fixture.target, command, fixture.runner_state, fixture.runner_log, server_options=fixture.server_options)
            interrupted = interrupt_runner(fixture.target, fixture.runner_state, server_options=fixture.server_options)
            time.sleep(0.05)
            pane = subprocess.run((fixture.tmux, *fixture.server_options, "display-message", "-p", "-t", "known:app.%0", "#{session_name}\\t#{window_name}\\t#{pane_id}"), check=True, capture_output=True, text=True)

            self.assertEqual(started.state, "running-owned")
            self.assertEqual(interrupted.state, "stopped-owned")
            self.assertEqual(pane.stdout.strip(), "known\\tapp\\t%0")
            self.assertEqual(status_runner(fixture.target, fixture.runner_state, server_options=fixture.server_options).state, "stopped-owned")

    def test_complete_offline_workflow_records_generated_artifacts_and_fixed_tmux_inputs(self) -> None:
        if shutil.which("tmux") is None:
            self.skipTest("tmux is optional and unavailable")
        with WorkflowFixture() as fixture:
            configuration = fixture.configuration(tmux=fixture.target)
            detection = detect_project(fixture.project / "lib")
            sdk = resolve_sdk(configuration, detection, environment=fixture.environment())
            setup = setup_project(configuration, sdk)
            analyze = next(task for task in generate_task_templates(configuration, sdk).tasks if task.label == "Flutter: Analyze")
            task_result = execute_task_template(analyze, environment=fixture.environment(FAKE_SDK_LOG_CWD="1"))
            launch = generate_debug_configurations(configuration, sdk).configurations[0]
            adapter_result = execute_adapter_validation(fixture.adapter, launch, environment=fixture.environment())

            fixture.start_server()
            command = (sys.executable, "-c", "import time; time.sleep(60)")
            started = start_runner(fixture.target, command, fixture.runner_state, fixture.runner_log, server_options=fixture.server_options)
            reloaded = perform_hot_operation(fixture.target, HotOperation.RELOAD, fixture.runner_state, server_options=fixture.server_options)
            restarted = perform_hot_operation(fixture.target, HotOperation.RESTART, fixture.runner_state, server_options=fixture.server_options)
            pane = subprocess.run((fixture.tmux, *fixture.server_options, "capture-pane", "-p", "-t", "known:app.%0"), check=True, capture_output=True, text=True)
            stopped = stop_runner(fixture.target, fixture.runner_state, server_options=fixture.server_options)

            self.assertEqual(detection.kind, "flutter_app")
            self.assertEqual([json.loads(line) for line in fixture.version_log.read_text(encoding="utf-8").splitlines()], [{"arguments": ["--version"], "executable": "flutter"}, {"arguments": ["--version"], "executable": "dart"}])
            self.assertTrue(setup.changed)
            self.assertTrue(setup.tasks_path.is_file())
            self.assertTrue(setup.debug_path.is_file())
            self.assertEqual(task_result.returncode, 0, task_result.stderr)
            self.assertEqual(json.loads(fixture.task_log.read_text(encoding="utf-8")), {"arguments": ["analyze", "--dart-define=FIXTURE=1"], "cwd": str(fixture.project.resolve()), "executable": str(sdk.flutter.path)})
            self.assertEqual(adapter_result.returncode, 0, adapter_result.stderr)
            self.assertEqual(json.loads(fixture.adapter_log.read_text(encoding="utf-8")), launch.as_json())
            self.assertEqual((started.state, reloaded.operation, restarted.operation, stopped.state), ("running-owned", HotOperation.RELOAD, HotOperation.RESTART, "stopped-owned"))
            self.assertIn("rR", pane.stdout)

    def test_boundary_failures_are_stable_and_leave_unsafe_inputs_untouched(self) -> None:
        with WorkflowFixture() as fixture:
            cases: list[tuple[str, str]] = []
            invalid = fixture.directory / "not-a-project"
            invalid.mkdir()
            with self.assertRaises(DiagnosticError) as detection_error:
                require_flutter_project(invalid)
            cases.append(("detection", detection_error.exception.diagnostic.code))
            self.assertFalse((invalid / ".zed").exists())

            configuration = fixture.configuration()
            detected = detect_project(fixture.project)
            shutil.rmtree(fixture.sdk)
            with self.assertRaises(SdkResolutionError) as sdk_error:
                resolve_sdk(configuration, detected, environment={"PATH": str(Path(sys.executable).parent)})
            assert sdk_error.exception.diagnostic is not None
            cases.append(("sdk", sdk_error.exception.diagnostic.code))

            fixture._make_sdk()
            sdk = resolve_sdk(configuration, detected, environment=fixture.environment())
            test_task = next(task for task in generate_task_templates(configuration, sdk).tasks if task.label == "Flutter: Test")
            result = execute_task_template(test_task, environment=fixture.environment(FAKE_SDK_OUTCOME="failure"))
            with self.assertRaises(DiagnosticError) as task_error:
                if result.returncode != 0:
                    raise DiagnosticError(process_failure((str(test_task.command), *test_task.args), exit_status=result.returncode, stdout=result.stdout, stderr=result.stderr, message="Generated task failed."))
            cases.append(("task", task_error.exception.diagnostic.code))
            self.assertEqual(json.loads(fixture.task_log.read_text(encoding="utf-8"))["arguments"], ["test", "--dart-define=FIXTURE=1"])

            launch = generate_debug_configurations(configuration, sdk).configurations[0]
            with self.assertRaises(DapAdapterError) as dap_error:
                execute_adapter_validation(fixture.directory / "missing-adapter", launch)
            cases.append(("dap", dap_error.exception.diagnostic.code))

            if fixture.tmux is not None:
                fixture.start_server()
                foreign = status_runner(fixture.target, fixture.runner_state, server_options=fixture.server_options)
                self.assertEqual(foreign.state, "foreign-no-owned-runner")
                with self.assertRaises(DiagnosticError) as foreign_error:
                    perform_hot_operation(fixture.target, HotOperation.RELOAD, fixture.runner_state, server_options=fixture.server_options)
                cases.append(("tmux-foreign", foreign_error.exception.diagnostic.code))
                command = (sys.executable, "-c", "import time; time.sleep(60)")
                started = start_runner(fixture.target, command, fixture.runner_state, fixture.runner_log, server_options=fixture.server_options)
                assert started.process_start_time is not None
                before_stale = subprocess.run((fixture.tmux, *fixture.server_options, "capture-pane", "-p", "-t", "known:app.%0"), check=True, capture_output=True, text=True)
                fixture.runner_state.write_text(fixture.runner_state.read_text(encoding="utf-8").replace(started.process_start_time, "0", 1), encoding="utf-8")
                with self.assertRaises(DiagnosticError) as stale_error:
                    perform_hot_operation(fixture.target, HotOperation.RESTART, fixture.runner_state, server_options=fixture.server_options)
                cases.append(("tmux-stale", stale_error.exception.diagnostic.code))
                after_stale = subprocess.run((fixture.tmux, *fixture.server_options, "capture-pane", "-p", "-t", "known:app.%0"), check=True, capture_output=True, text=True)
                self.assertEqual(before_stale.stdout, after_stale.stdout)
            self.assertEqual(cases, [("detection", "project.invalid"), ("sdk", "sdk.missing"), ("task", "process.failed"), ("dap", "dap.failed")] + ([("tmux-foreign", "tmux.failed"), ("tmux-stale", "tmux.failed")] if fixture.tmux is not None else []))


if __name__ == "__main__":
    unittest.main()
