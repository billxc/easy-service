"""Linux user-level systemd backend."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from easy_service.models import ServiceSpec, ServiceStatus
from easy_service.platforms.base import ServiceManager
from easy_service.utils import shell_join, slugify


class LinuxUserServiceManager(ServiceManager):
    platform_name = "linux"

    def unit_name(self, name: str) -> str:
        return f"easy-service-{slugify(name)}.service"

    def unit_path(self, name: str) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / self.unit_name(name)

    def _require_installed(self, name: str) -> Path:
        path = self.unit_path(name)
        if not path.exists():
            raise RuntimeError(
                f"service {name!r} is not installed (no unit at {path})\n"
                f"hint: run 'easy-service install {name} -- <command>' first"
            )
        return path

    def list_installed(self) -> list[str]:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        if not unit_dir.exists():
            return []
        prefix, suffix = "easy-service-", ".service"
        return sorted(
            f.name[len(prefix):-len(suffix)]
            for f in unit_dir.iterdir()
            if f.name.startswith(prefix) and f.name.endswith(suffix)
        )

    def render(self, spec: ServiceSpec) -> dict[Path, str]:
        spec.validate()
        lines = [
            "[Unit]",
            f"Description=easy-service ({spec.name})",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={shell_join(spec.command)}",
        ]
        if spec.working_dir:
            lines.append(f"WorkingDirectory={spec.working_dir}")
        for key, value in spec.env:
            escaped = value.replace('"', '\\"')
            lines.append(f'Environment="{key}={escaped}"')
        if spec.keep_alive:
            lines.extend(["Restart=on-failure", "RestartSec=5"])
        lines.extend(["", "[Install]", "WantedBy=default.target", ""])
        return {self.unit_path(spec.name): "\n".join(lines)}

    def install(self, spec: ServiceSpec) -> None:
        self._require_binary("systemctl")
        artifacts = self.render(spec)
        unit_path, content = next(iter(artifacts.items()))
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(content)
        self._run(["systemctl", "--user", "daemon-reload"])
        self._run(["systemctl", "--user", "enable", self.unit_name(spec.name)])
        if spec.auto_start:
            self.start(spec.name)

    def uninstall(self, name: str, *, clean: bool = False) -> None:
        self._require_binary("systemctl")
        self._require_installed(name)
        unit = self.unit_name(name)
        self._run(["systemctl", "--user", "stop", unit], check=False)
        self._run(["systemctl", "--user", "disable", unit], check=False)
        self.unit_path(name).unlink()
        self._run(["systemctl", "--user", "daemon-reload"])

    def start(self, name: str) -> None:
        self._require_binary("systemctl")
        self._require_installed(name)
        self._run(["systemctl", "--user", "start", self.unit_name(name)])

    def stop(self, name: str) -> None:
        self._require_binary("systemctl")
        self._require_installed(name)
        self._run(["systemctl", "--user", "stop", self.unit_name(name)])

    def status(self, name: str) -> ServiceStatus:
        unit = self.unit_name(name)
        path = self.unit_path(name)
        if not path.exists():
            return ServiceStatus(installed=False, running=None, detail="unit file not found")

        result = self._run(["systemctl", "--user", "is-active", unit], check=False)
        state = (result.stdout or "").strip()
        return ServiceStatus(
            installed=True,
            running=state == "active",
            detail=state or "unknown",
        )

    def logs(self, name: str, follow: bool = False) -> None:
        self._require_installed(name)
        unit = self.unit_name(name)
        cmd = ["journalctl", "--user", "-u", unit, "--no-pager"]
        if follow:
            cmd.append("-f")
        subprocess.run(cmd)

    def events(self, name: str, follow: bool = False) -> None:
        self._require_installed(name)
        unit = self.unit_name(name)
        cmd = ["journalctl", "--user", "-u", unit, "--no-pager",
               "--output", "short", "--grep", "systemd"]
        if follow:
            cmd.append("-f")
        subprocess.run(cmd)

    def doctor(self) -> list[str]:
        lines = super().doctor()
        unit_dir = self.unit_path("example").parent
        lines.append(f"unit_dir={unit_dir}")
        lines.append(f"unit_dir_exists={unit_dir.exists()}")
        try:
            self._require_binary("systemctl")
            lines.append("systemctl=yes")
        except RuntimeError:
            lines.append("systemctl=MISSING (required)")
        return lines

