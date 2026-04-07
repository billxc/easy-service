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
        command0 = spec.command[0]
        suffix = Path(command0).suffix.lower()
        if suffix in {".cmd", ".bat"}:
            file_name = "cmd.exe"
            arguments = subprocess.list2cmdline(["/c", *spec.command])
        elif suffix == ".ps1":
            file_name = "powershell"
            arguments = subprocess.list2cmdline(
                ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", *spec.command]
            )
        else:
            file_name = command0
            arguments = subprocess.list2cmdline(list(spec.command[1:]))

        pid_file = self.pid_path(spec.name)

        lines = [
            "$psi = New-Object System.Diagnostics.ProcessStartInfo",
            f"$psi.FileName = {self._ps_quote(file_name)}",
            f"$psi.Arguments = {self._ps_quote(arguments)}",
            "$psi.UseShellExecute = $false",
        ]
        if spec.working_dir:
            lines.append(
                f"$psi.WorkingDirectory = {self._ps_quote(str(spec.working_dir))}"
            )
        for key, value in spec.env:
            lines.append(
                f"$psi.EnvironmentVariables[{self._ps_quote(key)}] = {self._ps_quote(value)}"
            )
        lines.extend(
            [
                "",
                "$process = [System.Diagnostics.Process]::Start($psi)",
                f"$process.Id | Out-File -FilePath {self._ps_quote(str(pid_file))} -Encoding ascii -NoNewline",
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
        task_name = self.task_name(name)
        self._run([self._schtasks(), "/delete", "/tn", task_name, "/f"], check=False)
        app_dir = self.app_dir(name)
        if app_dir.exists():
            shutil.rmtree(app_dir)

    def start(self, name: str) -> None:
        self._require_installed(name)
        self._run([self._schtasks(), "/run", "/tn", self.task_name(name)])

    def stop(self, name: str) -> None:
        self._require_installed(name)
        pid_file = self.pid_path(name)
        if not pid_file.exists():
            raise RuntimeError(f"service {name!r} is not running (no pid file)")
        pid = int(pid_file.read_text().strip())
        self._run(
            [self._powershell(), "-NoProfile", "-Command",
             f"Stop-Process -Id {pid} -Force"],
            check=False,
        )
        pid_file.unlink(missing_ok=True)

    def status(self, name: str) -> ServiceStatus:
        runner = self.runner_path(name)
        if not runner.exists():
            return ServiceStatus(installed=False, running=None, detail="not installed")
        pid_file = self.pid_path(name)
        if not pid_file.exists():
            return ServiceStatus(installed=True, running=False, detail="stopped (no pid file)")
        try:
            pid = int(pid_file.read_text().strip())
            result = self._run(
                [self._powershell(), "-NoProfile", "-Command",
                 f"Get-Process -Id {pid} -ErrorAction Stop"],
                check=False,
            )
            if result.returncode == 0:
                return ServiceStatus(installed=True, running=True, detail=f"running (pid {pid})")
            # Process gone, clean up stale pid file
            pid_file.unlink(missing_ok=True)
            return ServiceStatus(installed=True, running=False, detail="stopped")
        except (ValueError, OSError):
            return ServiceStatus(installed=True, running=None, detail="invalid pid file")

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
