"""Windows current-user scheduled task backend."""

from __future__ import annotations

import json
import os
import shutil
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

    def _service_exe(self, name: str) -> Path:
        """Copy the tool venv and rename python.exe for Task Manager identification.

        python.exe uses pyvenv.cfg (relative lookup), so the copy is fully
        isolated from the original venv — no file locking on upgrade.
        """
        src_venv = Path(sys.executable).parent.parent
        dst_venv = self.app_dir(name) / "venv"
        if dst_venv.exists():
            shutil.rmtree(dst_venv)
        shutil.copytree(src_venv, dst_venv)
        scripts = dst_venv / "Scripts"
        # Keep only pythonw.exe (windowless, no console); remove everything else
        for f in scripts.iterdir():
            if f.name.lower() != "pythonw.exe":
                f.unlink()
        # Rename pythonw.exe for Task Manager identification
        src_exe = scripts / "pythonw.exe"
        dst_exe = scripts / f"{self.task_name(name)}.exe"
        src_exe.rename(dst_exe)
        return dst_exe

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

    def _list_installed(self) -> list[str]:
        """Return names of all installed services."""
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        base = local_app / "easy-service"
        if not base.exists():
            return []
        return [
            d.name for d in sorted(base.iterdir())
            if d.is_dir() and (d / "spec.json").exists()
        ]

    def list_installed(self) -> list[str]:
        return self._list_installed()

    def _load_spec(self, name: str) -> ServiceSpec:
        """Read spec.json back into a ServiceSpec."""
        data = json.loads(self.spec_path(name).read_text())
        return ServiceSpec(
            name=data["name"],
            command=tuple(data["command"]),
            working_dir=Path(data["working_dir"]) if data.get("working_dir") else None,
            env=data.get("env", {}),
            auto_start=data.get("auto_start", True),
            keep_alive=data.get("keep_alive", True),
        )

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
        exe = self._service_exe(spec.name)
        task_name = self.task_name(spec.name)
        return (
            f"$action = New-ScheduledTaskAction -Execute '{exe}' "
            f"-Argument '-m easy_service _launch {spec.name}'; "
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

    def upgrade(self, name: str | None = None) -> list[str]:
        """Re-copy venv and re-register task for one or all services.

        Returns list of upgraded service names.
        """
        names = [name] if name else self._list_installed()
        if not names:
            raise RuntimeError("no services installed")
        powershell = self._require_binary("powershell")
        upgraded = []
        for n in names:
            self._require_installed(n)
            was_running = self._read_pid(n) is not None
            if was_running:
                self.stop(n)
            spec = self._load_spec(n)
            self._service_exe(n)
            self._run([powershell, "-NoProfile", "-Command",
                       self._registration_script(spec)])
            if was_running:
                self.start(n)
            upgraded.append(n)
        return upgraded

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
