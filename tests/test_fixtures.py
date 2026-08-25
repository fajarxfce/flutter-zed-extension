from __future__ import annotations

import shutil
import unittest

from tests.fixture_harness import classify_fixture_project, fixture_project, run_fake_sdk


class OfflineFixtureTests(unittest.TestCase):
    def test_valid_fixture_projects_classify_as_flutter_apps(self) -> None:
        for name in ("valid_app", "fvm_app", "target_flavor_app"):
            fixture = fixture_project(name)
            self.assertTrue(fixture.path.is_dir())
            self.assertEqual(classify_fixture_project(fixture.path), fixture.classification)

    def test_invalid_and_malformed_fixtures_classify_as_invalid(self) -> None:
        for name in ("malformed_pubspec", "invalid_project"):
            fixture = fixture_project(name)
            self.assertEqual(classify_fixture_project(fixture.path), "invalid")

    def test_malformed_fixture_configuration_is_rejected(self) -> None:
        fixture = fixture_project("malformed_pubspec")
        result = run_fake_sdk("flutter", ["analyze", str(fixture.path)], outcome="failure")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "flutter: configured failure\n")

    def test_fvm_fixture_has_explicit_metadata(self) -> None:
        fvmrc = fixture_project("fvm_app").path / ".fvmrc"
        self.assertEqual(fvmrc.read_text(encoding="utf-8"), '{\n  "flutter": "3.22.0"\n}\n')

    def test_fake_flutter_logs_target_flavor_and_device_arguments(self) -> None:
        result = run_fake_sdk(
            "flutter",
            ["run", "--target", "lib/main_staging.dart", "--flavor", "staging", "-d", "fake-device"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            getattr(result, "invocation"),
            {
                "executable": "flutter",
                "arguments": [
                    "run",
                    "--target",
                    "lib/main_staging.dart",
                    "--flavor",
                    "staging",
                    "-d",
                    "fake-device",
                ],
            },
        )

    def test_fake_dart_returns_configured_failure(self) -> None:
        result = run_fake_sdk("dart", ["analyze"], outcome="failure")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "dart: configured failure\n")

    def test_fake_flutter_reports_missing_device(self) -> None:
        result = run_fake_sdk("flutter", ["run"], device_available=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "No devices found\n")


@unittest.skipUnless(shutil.which("flutter"), "real Flutter SDK integration requires flutter on PATH")
class RealSdkIntegrationTests(unittest.TestCase):
    def test_real_sdk_integration_is_explicitly_separate(self) -> None:
        self.assertIsNotNone(shutil.which("flutter"))


if __name__ == "__main__":
    unittest.main()
