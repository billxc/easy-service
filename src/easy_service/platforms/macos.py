"""macOS LaunchAgent backend."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from easy_service.models import ServiceSpec, ServiceStatus
from easy_service.platforms.base import ServiceManager
from easy_service.utils import shell_join, slugify


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

    def _require_installed(self, name: str) -> Path:
        path = self.plist_path(name)
        if not path.exists():
            raise RuntimeError(
                f"service {name!r} is not installed (no plist at {path})\n"
                f"hint: run 'easy-service install {name} -- <command>' first"
            )
        return path

    def list_installed(self) -> list[str]:
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        if not agents_dir.exists():
            return []
        prefix, suffix = "dev.easy-service.", ".plist"
        return sorted(
            f.name[len(prefix):-len(suffix)]
            for f in agents_dir.iterdir()
            if f.name.startswith(prefix) and f.name.endswith(suffix)
        )

    def render(self, spec: ServiceSpec) -> dict[Path, str]:
        spec.validate()
        log_dir = self.log_dir()
        plist: dict = {
            "Label": self.label(spec.name),
            "ProgramArguments": ["/bin/zsh", "-lc", shell_join(spec.command)],
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
        # Unload any previous version before overwriting
        self._run(["launchctl", "bootout", self._job(spec.name)], check=False)
        plist_path.write_text(content)
        self._run(["launchctl", "bootstrap", self._domain(), str(plist_path)])
        if spec.auto_start:
            self._run(["launchctl", "kickstart", "-k", self._job(spec.name)])

    def uninstall(self, name: str, *, clean: bool = False) -> None:
        self._require_binary("launchctl")
        self._require_installed(name)
        self._run(["launchctl", "bootout", self._job(name)], check=False)
        # Clear any disabled state so reinstalling starts fresh
        self._run(["launchctl", "enable", self._job(name)], check=False)
        plist_path = self.plist_path(name)
        plist_path.unlink()

    def start(self, name: str) -> None:
        self._require_binary("launchctl")
        plist_path = self._require_installed(name)
        # Bootstrap loads the job into launchd (no-op if already loaded)
        self._run(["launchctl", "bootstrap", self._domain(), str(plist_path)], check=False)
        self._run(["launchctl", "kickstart", "-k", self._job(name)])

    def stop(self, name: str) -> None:
        self._require_binary("launchctl")
        self._require_installed(name)
        # bootout unloads the job, which is necessary for KeepAlive services
        # (a simple kill would cause launchd to respawn immediately)
        self._run(["launchctl", "bootout", self._job(name)])

    def restart(self, name: str) -> None:
        self._require_binary("launchctl")
        plist_path = self._require_installed(name)
        # Ensure the job is loaded, then kickstart -k kills and restarts it
        self._run(["launchctl", "bootstrap", self._domain(), str(plist_path)], check=False)
        self._run(["launchctl", "kickstart", "-k", self._job(name)])

    def status(self, name: str) -> ServiceStatus:
        plist_path = self.plist_path(name)
        if not plist_path.exists():
            return ServiceStatus(installed=False, running=None, enabled=None, detail="plist not found")
        enabled = self._is_enabled(name)
        result = self._run(["launchctl", "print", self._job(name)], check=False)
        if result.returncode != 0:
            return ServiceStatus(installed=True, running=False, enabled=enabled, detail="not loaded")
        output = result.stdout or ""
        # launchctl print shows "state = running" or "state = not running"
        running = "state = running" in output.lower()
        return ServiceStatus(installed=True, running=running, enabled=enabled, detail=output.strip() or "loaded")

    def disable(self, name: str) -> None:
        self._require_binary("launchctl")
        self._require_installed(name)
        self._run(["launchctl", "disable", self._job(name)])

    def enable(self, name: str) -> None:
        self._require_binary("launchctl")
        self._require_installed(name)
        self._run(["launchctl", "enable", self._job(name)])

    def _is_enabled(self, name: str) -> bool:
        """Check if the service is enabled (not disabled via launchctl disable)."""
        result = self._run(["launchctl", "print-disabled", self._domain()], check=False)
        if result.returncode != 0:
            return True  # assume enabled if we can't check
        label = self.label(name)
        for line in (result.stdout or "").splitlines():
            # format: "dev.easy-service.xxx" => disabled
            if f'"{label}"' in line and "=> disabled" in line:
                return False
        return True

    def logs(self, name: str, follow: bool = False) -> None:
        self._require_installed(name)
        slug = slugify(name)
        log_file = self.log_dir() / f"{slug}.log"
        err_file = self.log_dir() / f"{slug}.err"
        existing = [f for f in (log_file, err_file) if f.exists()]
        if not existing:
            print(f"no logs yet for {name!r}")
            return
        if follow:
            cmd = ["tail", "-f"] + [str(f) for f in existing]
            subprocess.run(cmd)
        else:
            for f in existing:
                print(f"# {f}")
                content = f.read_text()
                if content:
                    print(content, end="" if content.endswith("\n") else "\n")
                else:
                    print("(empty)")

    def events(self, name: str, follow: bool = False) -> None:
        self._require_installed(name)
        cmd = ["log", "show", "--predicate",
               f'subsystem == "com.apple.launchd" AND composedMessage CONTAINS "{self.label(name)}"',
               "--last", "1h"]
        if follow:
            cmd = ["log", "stream", "--predicate",
                   f'subsystem == "com.apple.launchd" AND composedMessage CONTAINS "{self.label(name)}"']
        subprocess.run(cmd)

    def doctor(self) -> list[str]:
        lines = super().doctor()
        plist_dir = self.plist_path("example").parent
        lines.append(f"launch_agents_dir={plist_dir}")
        lines.append(f"launch_agents_dir_exists={plist_dir.exists()}")
        lines.append(f"log_dir={self.log_dir()}")
        try:
            self._require_binary("launchctl")
            lines.append("launchctl=yes")
        except RuntimeError:
            lines.append("launchctl=MISSING (required)")
        return lines

