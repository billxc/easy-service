"""Base service manager types."""

from __future__ import annotations

import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from easy_service.models import ServiceSpec, ServiceStatus


class ServiceManager(ABC):
    platform_name: str

    @abstractmethod
    def render(self, spec: ServiceSpec) -> dict[Path, str]:
        """Return installable artifacts for the platform."""

    @abstractmethod
    def install(self, spec: ServiceSpec) -> None:
        """Install the service for the current user."""

    @abstractmethod
    def uninstall(self, name: str) -> None:
        """Uninstall the service."""

    @abstractmethod
    def start(self, name: str) -> None:
        """Start the service."""

    @abstractmethod
    def stop(self, name: str) -> None:
        """Stop the service."""

    @abstractmethod
    def status(self, name: str) -> ServiceStatus:
        """Return service status."""

    @abstractmethod
    def logs(self, name: str, follow: bool = False) -> None:
        """Print service stdout/stderr to stdout."""

    @abstractmethod
    def events(self, name: str, follow: bool = False) -> None:
        """Print launcher lifecycle events."""

    def restart(self, name: str) -> None:
        self.stop(name)
        self.start(name)

    def doctor(self) -> list[str]:
        return [f"platform={self.platform_name}"]

    def _require_binary(self, name: str) -> str:
        found = shutil.which(name)
        if not found:
            raise RuntimeError(f"required command not found: {name}")
        return found

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(args, capture_output=True, text=True)
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(detail or f"command failed: {' '.join(args)}")
        return result

