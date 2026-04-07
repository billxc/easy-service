"""Windows current-user scheduled task backend."""

from __future__ import annotations

import os
import shutil
import subprocess
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

    def runner_path(self, name: str) -> Path:
        return self.app_dir(name) / "run.ps1"

    def pid_path(self, name: str) -> Path:
        return self.app_dir(name) / "pid"

    def _powershell(self) -> str:
        return self._require_binary("powershell")

    def _schtasks(self) -> str:
        return self._require_binary("schtasks")

    def _require_installed(self, name: str) -> Path:
        path = self.runner_path(name)
        if not path.exists():
            raise RuntimeError(
                f"service {name!r} is not installed (no runner at {path})\n"
                f"hint: run 'easy-service install {name} -- <command>' first"
            )
        return path

    def _ps_quote(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _runner_content(self, spec: ServiceSpec) -> str:
        pid_file = self.pid_path(spec.name)
        args_list = list(spec.command[1:])
        args_str = subprocess.list2cmdline(args_list)

        lines: list[str] = []
        # Set environment variables before starting the process
        for key, value in spec.env:
            lines.append(f"$env:{key} = {self._ps_quote(value)}")

        start_cmd = f"Start-Process -FilePath {self._ps_quote(spec.command[0])} -PassThru -NoNewWindow"
        if args_str:
            start_cmd += f" -ArgumentList {self._ps_quote(args_str)}"
        if spec.working_dir:
            start_cmd += f" -WorkingDirectory {self._ps_quote(str(spec.working_dir))}"

        lines.extend(
            [
                f"$process = {start_cmd}",
                f"\"$($process.Id) $($process.StartTime.ToFileTimeUtc())\" | Out-File -FilePath {self._ps_quote(str(pid_file))} -Encoding ascii -NoNewline",
                "",
            ]
        )
        return "\r\n".join(lines)

    def _registration_script(self, spec: ServiceSpec) -> str:
        runner = self.runner_path(spec.name)
        task_name = self.task_name(spec.name)
        return (
            "$action = New-ScheduledTaskAction -Execute 'powershell' "
            f"-Argument '-NoProfile -ExecutionPolicy Bypass -File \"{runner}\"'; "
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
            self.runner_path(spec.name): self._runner_content(spec),
        }

    def install(self, spec: ServiceSpec) -> None:
        self._powershell()
        artifacts = self.render(spec)
        for path, content in artifacts.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self._run([self._powershell(), "-NoProfile", "-Command",
                   self._registration_script(spec)])
        if spec.auto_start:
            self.start(spec.name)

    def uninstall(self, name: str) -> None:
        self._require_installed(name)
        # Stop process if running
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
            shutil.rmtree(app_dir)

    def start(self, name: str) -> None:
        self._require_installed(name)
        runner = self.runner_path(name)
        self._run([self._powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(runner)])

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
                # Verify process exists and creation time matches
                result = self._run(
                    [self._powershell(), "-NoProfile", "-Command",
                     f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; "
                     f"if ($p) {{ $p.StartTime.ToFileTimeUtc() }} else {{ 'gone' }}"],
                    check=False,
                )
                actual_time = result.stdout.strip()
                if actual_time == "gone" or actual_time != saved_time:
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
        runner = self.runner_path(name)
        if not runner.exists():
            return ServiceStatus(installed=False, running=None, detail="not installed")
        pid = self._read_pid(name)
        if pid is not None:
            return ServiceStatus(installed=True, running=True, detail=f"running (pid {pid})")
        return ServiceStatus(installed=True, running=False, detail="stopped")

    def doctor(self) -> list[str]:
        lines = super().doctor()
        lines.append(f"app_dir={self.app_dir('example').parent}")
        try:
            self._require_binary("schtasks")
            lines.append("schtasks=yes")
        except RuntimeError:
            lines.append("schtasks=MISSING (required)")
        try:
            self._require_binary("powershell")
            lines.append("powershell=yes")
        except RuntimeError:
            lines.append("powershell=MISSING (required)")
        return lines
