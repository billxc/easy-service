"""Windows current-user scheduled task backend."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from easy_service.models import ServiceSpec, ServiceStatus
from easy_service.platforms.base import ServiceManager
from easy_service.utils import slugify


class WindowsTaskSchedulerManager(ServiceManager):
    platform_name = "windows"

    def task_name(self, name: str) -> str:
        return f"EasyService-{slugify(name)}"

    def app_dir(self, name: str) -> Path:
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local_app / "easy-service" / slugify(name)

    def spec_path(self, name: str) -> Path:
        return self.app_dir(name) / "spec.json"

    def pid_path(self, name: str) -> Path:
        return self.app_dir(name) / "pid"

    def _uv_bin(self) -> str:
        return self._require_binary("uv")

    def _resolve_python(self) -> str:
        """Resolve Python path via uv for use in Task Scheduler."""
        uv = self._uv_bin()
        result = self._run([uv, "run", "--no-project", "python", "-c",
                           "import sys; print(sys.executable)"])
        return result.stdout.strip()

    def _launcher_script(self, name: str) -> Path:
        return self.app_dir(name) / "launcher.py"

    def _copy_launcher(self, name: str) -> None:
        """Copy launcher.py to app_dir so it can run standalone."""
        from easy_service import launcher
        src = Path(launcher.__file__)
        dst = self._launcher_script(name)
        shutil.copy2(src, dst)

    def _easy_service_bin(self) -> str:
        return self._require_binary("easy-service")

    def _schtasks(self) -> str:
        return self._require_binary("schtasks")

    def _require_installed(self, name: str) -> Path:
        path = self.spec_path(name)
        if not path.exists():
            raise RuntimeError(
                f"service {name!r} is not installed (no spec at {path})\n"
                f"hint: run 'easy-service install {name} -- <command>' first"
            )
        return path

    @staticmethod
    def _spec_to_json(spec: ServiceSpec) -> str:
        data = {
            "name": spec.name,
            "command": list(spec.command),
            "working_dir": str(spec.working_dir) if spec.working_dir else None,
            "env": {k: v for k, v in spec.env},
            "auto_start": spec.auto_start,
            "keep_alive": spec.keep_alive,
        }
        return json.dumps(data, indent=2)

    def _registration_script(self, spec: ServiceSpec) -> str:
        python = self._resolve_python()
        launcher = self._launcher_script(spec.name)
        app_dir = self.app_dir(spec.name)
        task_name = self.task_name(spec.name)
        return (
            f"$action = New-ScheduledTaskAction -Execute '{python}' "
            f"-Argument '{launcher} {spec.name} {app_dir}'; "
            "$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
            "$settings = New-ScheduledTaskSettingsSet "
            "-AllowStartIfOnBatteries "
            "-DontStopIfGoingOnBatteries "
            "-ExecutionTimeLimit ([TimeSpan]::Zero); "
            f"Register-ScheduledTask -TaskName '{task_name}' "
            "-Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force"
        )

    def render(self, spec: ServiceSpec) -> dict[Path, str]:
        spec.validate()
        return {
            self.spec_path(spec.name): self._spec_to_json(spec),
        }

    def install(self, spec: ServiceSpec) -> None:
        artifacts = self.render(spec)
        for path, content in artifacts.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self._copy_launcher(spec.name)
        powershell = self._require_binary("powershell")
        self._run([powershell, "-NoProfile", "-Command",
                   self._registration_script(spec)])
        if spec.auto_start:
            self.start(spec.name)

    def uninstall(self, name: str) -> None:
        self._require_installed(name)
        pid = self._read_pid(name)
        if pid is not None:
            self._run(
                [self._require_binary("taskkill"), "/T", "/F", "/PID", str(pid)],
                check=False,
            )
        task_name = self.task_name(name)
        self._run([self._schtasks(), "/delete", "/tn", task_name, "/f"], check=False)
        app_dir = self.app_dir(name)
        if app_dir.exists():
            for f in app_dir.iterdir():
                if f.suffix == ".log":
                    continue
                if f.is_dir():
                    shutil.rmtree(f)
                else:
                    f.unlink()

    def start(self, name: str) -> None:
        self._require_installed(name)
        task_name = self.task_name(name)
        self._run([self._schtasks(), "/run", "/tn", task_name])

    def _read_pid(self, name: str) -> int | None:
        """Read PID from pid file; return None if stale or missing."""
        pid_file = self.pid_path(name)
        if not pid_file.exists():
            return None
        try:
            parts = pid_file.read_text().strip().split()
            pid = int(parts[0])
            if len(parts) >= 2:
                saved_time = parts[1]
                from easy_service.launcher import _creation_time
                actual_time = _creation_time(pid)
                if actual_time == "0" or actual_time != saved_time:
                    pid_file.unlink(missing_ok=True)
                    return None
            return pid
        except (ValueError, OSError):
            return None

    def stop(self, name: str) -> None:
        self._require_installed(name)
        pid = self._read_pid(name)
        if pid is None:
            raise RuntimeError(f"service {name!r} is not running (no pid file)")
        self._run(
            [self._require_binary("taskkill"), "/T", "/F", "/PID", str(pid)],
            check=False,
        )
        self.pid_path(name).unlink(missing_ok=True)

    def status(self, name: str) -> ServiceStatus:
        sp = self.spec_path(name)
        if not sp.exists():
            return ServiceStatus(installed=False, running=None, detail="not installed")
        pid = self._read_pid(name)
        if pid is not None:
            return ServiceStatus(installed=True, running=True, detail=f"running (pid {pid})")
        return ServiceStatus(installed=True, running=False, detail="stopped")

    def _tail_file(self, path: Path, follow: bool) -> None:
        if not path.exists():
            print(f"no logs yet: {path}")
            return
        if follow:
            import time
            try:
                with open(path) as f:
                    sys.stdout.write(f.read())
                    sys.stdout.flush()
                    while True:
                        line = f.readline()
                        if line:
                            sys.stdout.write(line)
                            sys.stdout.flush()
                        else:
                            time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        else:
            print(path.read_text(), end="")

    def logs(self, name: str, follow: bool = False) -> None:
        self._tail_file(self.app_dir(name) / "output.log", follow)

    def events(self, name: str, follow: bool = False) -> None:
        self._tail_file(self.app_dir(name) / "launcher.log", follow)

    def doctor(self) -> list[str]:
        lines = super().doctor()
        lines.append(f"app_dir={self.app_dir('example').parent}")
        try:
            self._require_binary("schtasks")
            lines.append("schtasks=yes")
        except RuntimeError:
            lines.append("schtasks=MISSING (required)")
        try:
            self._require_binary("easy-service")
            lines.append("easy-service=yes")
        except RuntimeError:
            lines.append("easy-service=MISSING (required)")
        return lines
