"""CLI and rendering tests."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from easy_service.cli import build_spec, main
from easy_service.models import ServiceSpec
from easy_service.platforms import manager_for_platform
from easy_service.platforms.linux import LinuxUserServiceManager
from easy_service.platforms.macos import MacOSLaunchAgentManager
from easy_service.platforms.windows import WindowsTaskSchedulerManager
from easy_service.utils import slugify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(name: str = "demo", **overrides) -> ServiceSpec:
    defaults = dict(
        name=name,
        command=("python", "-m", "bot"),
        working_dir=None,
        env=(),
        auto_start=True,
        keep_alive=True,
    )
    defaults.update(overrides)
    return ServiceSpec(**defaults)


def _build_spec_from_args(name: str, extra_env=None, cwd=None):
    class Args:
        no_auto_start = False
        no_keep_alive = False
        service_command = ["--", "python", "-m", "bot"]

    args = Args()
    args.name = name
    args.env = extra_env or []
    args.cwd = cwd
    return build_spec(args)


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class SlugifyTests(unittest.TestCase):
    def test_normalizes_service_name(self) -> None:
        self.assertEqual(slugify("My Bot"), "my-bot")

    def test_strips_leading_trailing_hyphens(self) -> None:
        self.assertEqual(slugify("--my--bot--"), "my-bot")

    def test_rejects_empty_string(self) -> None:
        with self.assertRaises(ValueError):
            slugify("---")


# ---------------------------------------------------------------------------
# build_spec
# ---------------------------------------------------------------------------

class BuildSpecTests(unittest.TestCase):
    def test_strips_separator(self) -> None:
        spec = _build_spec_from_args("demo")
        self.assertEqual(spec.command, ("python", "-m", "bot"))

    def test_env_parsing(self) -> None:
        spec = _build_spec_from_args("demo", extra_env=["FOO=bar", "BAZ=1"])
        self.assertEqual(dict(spec.env), {"FOO": "bar", "BAZ": "1"})

    def test_rejects_nonexistent_cwd(self) -> None:
        with self.assertRaises(ValueError):
            _build_spec_from_args("demo", cwd=Path("/nonexistent/path/xyz"))

    def test_accepts_valid_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = _build_spec_from_args("demo", cwd=Path(tmpdir))
            self.assertEqual(spec.working_dir, Path(tmpdir).resolve())

    def test_rejects_empty_command(self) -> None:
        class Args:
            name = "demo"
            cwd = None
            env = []
            no_auto_start = False
            no_keep_alive = False
            service_command = ["--"]

        with self.assertRaises(ValueError):
            build_spec(Args())


# ---------------------------------------------------------------------------
# manager_for_platform
# ---------------------------------------------------------------------------

class PlatformSelectionTests(unittest.TestCase):
    def test_explicit_macos(self) -> None:
        self.assertIsInstance(manager_for_platform("macos"), MacOSLaunchAgentManager)

    def test_explicit_linux(self) -> None:
        self.assertIsInstance(manager_for_platform("linux"), LinuxUserServiceManager)

    def test_explicit_windows(self) -> None:
        self.assertIsInstance(manager_for_platform("windows"), WindowsTaskSchedulerManager)

    def test_unknown_platform_raises(self) -> None:
        with self.assertRaises(ValueError):
            manager_for_platform("freebsd")


# ---------------------------------------------------------------------------
# Render tests (all platforms, no side effects)
# ---------------------------------------------------------------------------

class MacOSRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = MacOSLaunchAgentManager()

    def test_plist_contains_label(self) -> None:
        spec = _make_spec("demo")
        content = next(iter(self.mgr.render(spec).values()))
        self.assertIn("dev.easy-service.demo", content)

    def test_plist_includes_working_dir(self) -> None:
        spec = _make_spec(working_dir=Path("/tmp/work"))
        content = next(iter(self.mgr.render(spec).values()))
        self.assertIn("/tmp/work", content)

    def test_plist_includes_env_vars(self) -> None:
        spec = _make_spec(env=(("FOO", "bar"),))
        content = next(iter(self.mgr.render(spec).values()))
        self.assertIn("FOO", content)
        self.assertIn("bar", content)

    def test_plist_path_convention(self) -> None:
        path = next(iter(self.mgr.render(_make_spec("my bot")).keys()))
        self.assertTrue(str(path).endswith("dev.easy-service.my-bot.plist"))

    def test_log_paths_in_plist(self) -> None:
        content = next(iter(self.mgr.render(_make_spec()).values()))
        self.assertIn("demo.log", content)
        self.assertIn("demo.err", content)


class LinuxRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = LinuxUserServiceManager()

    def test_unit_name_in_path(self) -> None:
        path = next(iter(self.mgr.render(_make_spec("my bot")).keys()))
        self.assertIn("easy-service-my-bot.service", str(path))

    def test_exec_start(self) -> None:
        content = next(iter(self.mgr.render(_make_spec()).values()))
        self.assertIn("ExecStart=python -m bot", content)

    def test_working_directory(self) -> None:
        spec = _make_spec(working_dir=Path("/srv/app"))
        content = next(iter(self.mgr.render(spec).values()))
        self.assertIn("WorkingDirectory=/srv/app", content)

    def test_environment_variables(self) -> None:
        spec = _make_spec(env=(("KEY", "val"),))
        content = next(iter(self.mgr.render(spec).values()))
        self.assertIn('Environment="KEY=val"', content)

    def test_restart_on_failure(self) -> None:
        spec = _make_spec(keep_alive=True)
        content = next(iter(self.mgr.render(spec).values()))
        self.assertIn("Restart=on-failure", content)

    def test_no_restart_when_disabled(self) -> None:
        spec = _make_spec(keep_alive=False)
        content = next(iter(self.mgr.render(spec).values()))
        self.assertNotIn("Restart=on-failure", content)


class WindowsRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = WindowsTaskSchedulerManager()

    def test_artifacts_contain_launcher_and_script(self) -> None:
        artifacts = self.mgr.render(_make_spec())
        names = {p.name for p in artifacts}
        self.assertIn("run.ps1", names)
        self.assertIn("register-task.ps1", names)

    def test_runner_contains_command(self) -> None:
        artifacts = self.mgr.render(_make_spec())
        runner = [v for p, v in artifacts.items() if p.name == "run.ps1"][0]
        self.assertIn("$psi.FileName = 'python'", runner)

    def test_runner_sets_cwd(self) -> None:
        spec = _make_spec(working_dir=Path("C:/app"))
        artifacts = self.mgr.render(spec)
        runner = [v for p, v in artifacts.items() if p.name == "run.ps1"][0]
        self.assertIn("$psi.WorkingDirectory = 'C:\\app'", runner)

    def test_runner_sets_env(self) -> None:
        spec = _make_spec(env=(("KEY", "val"),))
        artifacts = self.mgr.render(spec)
        runner = [v for p, v in artifacts.items() if p.name == "run.ps1"][0]
        self.assertIn("$psi.EnvironmentVariables['KEY'] = 'val'", runner)

    def test_ps1_script_contains_task_name(self) -> None:
        artifacts = self.mgr.render(_make_spec("my-svc"))
        ps1 = [v for p, v in artifacts.items() if p.name == "register-task.ps1"][0]
        self.assertIn("EasyService-my-svc", ps1)

    def test_ps1_script_executes_runner_via_powershell(self) -> None:
        artifacts = self.mgr.render(_make_spec("my-svc"))
        ps1 = [v for p, v in artifacts.items() if p.name == "register-task.ps1"][0]
        self.assertIn("powershell", ps1)
        self.assertIn("run.ps1", ps1)

    def test_runner_binds_child_process_to_job(self) -> None:
        artifacts = self.mgr.render(_make_spec("my-svc"))
        runner = [v for p, v in artifacts.items() if p.name == "run.ps1"][0]
        self.assertIn("AssignProcessToJobObject", runner)
        self.assertIn("JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE", runner)


# ---------------------------------------------------------------------------
# Existence guard tests
# ---------------------------------------------------------------------------

class ExistenceGuardTests(unittest.TestCase):
    """start/stop/uninstall should fail with a clear message when not installed."""

    def test_macos_start_uninstalled(self) -> None:
        mgr = MacOSLaunchAgentManager()
        with self.assertRaises(RuntimeError) as ctx:
            mgr._require_installed("nonexistent-xyz")
        self.assertIn("not installed", str(ctx.exception))

    def test_linux_start_uninstalled(self) -> None:
        mgr = LinuxUserServiceManager()
        with self.assertRaises(RuntimeError) as ctx:
            mgr._require_installed("nonexistent-xyz")
        self.assertIn("not installed", str(ctx.exception))

    def test_windows_start_uninstalled(self) -> None:
        mgr = WindowsTaskSchedulerManager()
        with self.assertRaises(RuntimeError) as ctx:
            mgr._require_installed("nonexistent-xyz")
        self.assertIn("not installed", str(ctx.exception))


# ---------------------------------------------------------------------------
# Status tests (no side effects)
# ---------------------------------------------------------------------------

class StatusTests(unittest.TestCase):
    def test_macos_not_installed(self) -> None:
        mgr = MacOSLaunchAgentManager()
        status = mgr.status("nonexistent-xyz-abc")
        self.assertFalse(status.installed)
        self.assertIsNone(status.running)

    def test_linux_not_installed(self) -> None:
        mgr = LinuxUserServiceManager()
        status = mgr.status("nonexistent-xyz-abc")
        self.assertFalse(status.installed)
        self.assertIsNone(status.running)

    def test_windows_not_installed(self) -> None:
        mgr = WindowsTaskSchedulerManager()
        status = mgr.status("nonexistent-xyz-abc")
        self.assertFalse(status.installed)
        self.assertIsNone(status.running)


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class CLITests(unittest.TestCase):
    def test_render_linux(self) -> None:
        stdout = io.StringIO()
        argv = ["render", "demo", "--platform", "linux", "--", "python", "-m", "bot"]
        with redirect_stdout(stdout):
            code = main(argv)
        self.assertEqual(code, 0)
        self.assertIn("easy-service-demo.service", stdout.getvalue())

    def test_render_macos(self) -> None:
        stdout = io.StringIO()
        argv = ["render", "demo", "--platform", "macos", "--", "python", "-m", "bot"]
        with redirect_stdout(stdout):
            code = main(argv)
        self.assertEqual(code, 0)
        self.assertIn("dev.easy-service.demo", stdout.getvalue())

    def test_render_windows(self) -> None:
        stdout = io.StringIO()
        argv = ["render", "demo", "--platform", "windows", "--", "python", "-m", "bot"]
        with redirect_stdout(stdout):
            code = main(argv)
        self.assertEqual(code, 0)
        self.assertIn("launcher.cmd", stdout.getvalue())

    def test_status_not_installed_returns_1(self) -> None:
        stdout = io.StringIO()
        # Use a name guaranteed not to be installed
        argv = ["status", "nonexistent-xyz-abc-999", "--platform", "macos"]
        with redirect_stdout(stdout):
            code = main(argv)
        self.assertEqual(code, 1)
        self.assertIn("not installed", stdout.getvalue())

    def test_doctor_runs(self) -> None:
        stdout = io.StringIO()
        argv = ["doctor", "--platform", "macos"]
        with redirect_stdout(stdout):
            code = main(argv)
        self.assertEqual(code, 0)
        self.assertIn("platform=macos", stdout.getvalue())


# ---------------------------------------------------------------------------
# ServiceSpec validation
# ---------------------------------------------------------------------------

class ServiceSpecValidationTests(unittest.TestCase):
    def test_empty_command_rejected(self) -> None:
        spec = ServiceSpec(name="demo", command=())
        with self.assertRaises(ValueError):
            spec.validate()

    def test_bad_name_rejected(self) -> None:
        spec = ServiceSpec(name="---", command=("echo", "hi"))
        with self.assertRaises(ValueError):
            spec.validate()

    def test_slug_property(self) -> None:
        spec = _make_spec("My Cool Bot")
        self.assertEqual(spec.slug, "my-cool-bot")


if __name__ == "__main__":
    unittest.main()
