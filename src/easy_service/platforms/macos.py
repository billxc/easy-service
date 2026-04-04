"""macOS LaunchAgent backend."""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

from easy_service.models import ServiceSpec, ServiceStatus
from easy_service.platforms.base import ServiceManager
from easy_service.utils import slugify


class MacOSLaunchAgentManager(ServiceManager):
    platform_name = "macos"

    def label(self, name: str) -> str:
        return f"dev.easy-service.{slugify(name)}"

    def plist_path(self, name: str) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self.label(name)}.plist"

    def log_dir(self) -> Path:
        return Path.home() / "Library" / "Logs" / "easy-service"

    def _domain(self) -> str:
        return f"gui/{os.getuid()}"

    def _job(self, name: str) -> str:
        return f"{self._domain()}/{self.label(name)}"

    def render(self, spec: ServiceSpec) -> dict[Path, str]:
        spec.validate()
        log_dir = self.log_dir()
        plist = {
            "Label": self.label(spec.name),
            "ProgramArguments": list(spec.command),
            "RunAtLoad": spec.auto_start,
            "KeepAlive": spec.keep_alive,
            "StandardOutPath": str(log_dir / f"{spec.slug}.log"),
            "StandardErrorPath": str(log_dir / f"{spec.slug}.err"),
        }
        if spec.working_dir:
            plist["WorkingDirectory"] = str(spec.working_dir)
        if spec.env:
            plist["EnvironmentVariables"] = dict(spec.env)
        content = plistlib.dumps(plist, sort_keys=False).decode("utf-8")
        return {self.plist_path(spec.name): content}

    def install(self, spec: ServiceSpec) -> None:
        self._require_binary("launchctl")
        artifacts = self.render(spec)
        plist_path, content = next(iter(artifacts.items()))
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir().mkdir(parents=True, exist_ok=True)
        plist_path.write_text(content)
        self._run(["launchctl", "bootout", self._job(spec.name)], check=False)
        self._run(["launchctl", "bootstrap", self._domain(), str(plist_path)])
        if spec.auto_start:
            self._run(["launchctl", "kickstart", "-k", self._job(spec.name)])

    def uninstall(self, name: str) -> None:
        self._require_binary("launchctl")
        self._run(["launchctl", "bootout", self._job(name)], check=False)
        plist_path = self.plist_path(name)
        if plist_path.exists():
            plist_path.unlink()

    def start(self, name: str) -> None:
        self._require_binary("launchctl")
        plist_path = self.plist_path(name)
        self._run(["launchctl", "bootstrap", self._domain(), str(plist_path)], check=False)
        self._run(["launchctl", "kickstart", "-k", self._job(name)])

    def stop(self, name: str) -> None:
        self._require_binary("launchctl")
        self._run(["launchctl", "bootout", self._job(name)], check=False)

    def status(self, name: str) -> ServiceStatus:
        plist_path = self.plist_path(name)
        if not plist_path.exists():
            return ServiceStatus(installed=False, running=None, detail="plist not found")
        result = self._run(["launchctl", "print", self._job(name)], check=False)
        running = result.returncode == 0
        detail = (result.stderr or result.stdout).strip() or "unknown"
        return ServiceStatus(installed=True, running=running, detail=detail)

    def doctor(self) -> list[str]:
        lines = super().doctor()
        lines.append(f"launch_agents_dir={self.plist_path('example').parent}")
        lines.append(f"log_dir={self.log_dir()}")
        lines.append(f"launchctl={'yes' if self._require_binary('launchctl') else 'no'}")
        return lines

