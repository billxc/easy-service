"""Windows current-user scheduled task backend."""

from __future__ import annotations

import os
import shutil
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

    def launcher_path(self, name: str) -> Path:
        return self.app_dir(name) / "launcher.cmd"

    def _powershell(self) -> str:
        return self._require_binary("powershell")

    def _schtasks(self) -> str:
        return self._require_binary("schtasks")

    def _require_installed(self, name: str) -> Path:
        path = self.launcher_path(name)
        if not path.exists():
            raise RuntimeError(
                f"service {name!r} is not installed (no launcher at {path})\n"
                f"hint: run 'easy-service install {name} -- <command>' first"
            )
        return path

    def _launcher_content(self, spec: ServiceSpec) -> str:
        lines = ["@echo off"]
        if spec.working_dir:
            lines.append(f'cd /d "{spec.working_dir}"')
        for key, value in spec.env:
            lines.append(f'set "{key}={value}"')
        command = " ".join(f'"{part}"' if " " in part else part for part in spec.command)
        lines.append(command)
        lines.append("")
        return "\r\n".join(lines)

    def _registration_script(self, spec: ServiceSpec) -> str:
        launcher = self.launcher_path(spec.name)
        task_name = self.task_name(spec.name)
        return (
            "$action = New-ScheduledTaskAction -Execute 'cmd.exe' "
            f"-Argument '/c \"{launcher}\"'; "
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
            self.launcher_path(spec.name): self._launcher_content(spec),
            self.app_dir(spec.name) / "register-task.ps1": self._registration_script(spec),
        }

    def install(self, spec: ServiceSpec) -> None:
        self._powershell()
        artifacts = self.render(spec)
        for path, content in artifacts.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        script = artifacts[self.app_dir(spec.name) / "register-task.ps1"]
        self._run([self._powershell(), "-NoProfile", "-Command", script])
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
        self._run([self._schtasks(), "/end", "/tn", self.task_name(name)])

    def status(self, name: str) -> ServiceStatus:
        launcher = self.launcher_path(name)
        if not launcher.exists():
            return ServiceStatus(installed=False, running=None, detail="launcher not found")
        result = self._run(
            [self._schtasks(), "/query", "/tn", self.task_name(name), "/fo", "list"],
            check=False,
        )
        if result.returncode != 0:
            return ServiceStatus(
                installed=True,
                running=None,
                detail="launcher exists but task not registered in Task Scheduler",
            )
        running = "Running" in result.stdout
        detail = (result.stdout or result.stderr).strip() or "unknown"
        return ServiceStatus(installed=True, running=running, detail=detail)

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

