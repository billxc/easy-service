"""CLI and rendering tests."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from easy_service.cli import build_spec, main
from easy_service.platforms.linux import LinuxUserServiceManager
from easy_service.platforms.macos import MacOSLaunchAgentManager
from easy_service.platforms.windows import WindowsTaskSchedulerManager
from easy_service.utils import slugify


class SlugifyTests(unittest.TestCase):
    def test_slugify_normalizes_service_name(self) -> None:
        self.assertEqual(slugify("My Bot"), "my-bot")


class BuildSpecTests(unittest.TestCase):
    def test_build_spec_strips_separator(self) -> None:
        class Args:
            name = "demo"
            cwd = None
            env = ["FOO=bar"]
            no_auto_start = False
            no_keep_alive = False
            service_command = ["--", "python", "-m", "demo"]

        spec = build_spec(Args())
        self.assertEqual(spec.command, ("python", "-m", "demo"))
        self.assertEqual(dict(spec.env), {"FOO": "bar"})


class RenderTests(unittest.TestCase):
    def test_linux_render_contains_user_unit_name(self) -> None:
        manager = LinuxUserServiceManager()
        content = next(iter(manager.render(build_spec_args("my bot")).values()))
        self.assertIn("easy-service-my-bot.service", str(next(iter(manager.render(build_spec_args("my bot")).keys()))))
        self.assertIn("ExecStart=python -m bot", content)

    def test_macos_render_contains_launchagent_label(self) -> None:
        manager = MacOSLaunchAgentManager()
        content = next(iter(manager.render(build_spec_args("demo")).values()))
        self.assertIn("dev.easy-service.demo", content)

    def test_windows_render_contains_task_script(self) -> None:
        manager = WindowsTaskSchedulerManager()
        artifacts = manager.render(build_spec_args("demo"))
        paths = {path.name for path in artifacts}
        self.assertIn("launcher.cmd", paths)
        self.assertIn("register-task.ps1", paths)


class CLITests(unittest.TestCase):
    def test_render_command_prints_artifact(self) -> None:
        stdout = io.StringIO()
        argv = [
            "render",
            "demo",
            "--platform",
            "linux",
            "--",
            "python",
            "-m",
            "bot",
        ]
        with redirect_stdout(stdout):
            code = main(argv)
        self.assertEqual(code, 0)
        self.assertIn("easy-service-demo.service", stdout.getvalue())


def build_spec_args(name: str):
    class Args:
        cwd = None
        env = []
        no_auto_start = False
        no_keep_alive = False
        service_command = ["--", "python", "-m", "bot"]

    args = Args()
    args.name = name
    return build_spec(args)


if __name__ == "__main__":
    unittest.main()
