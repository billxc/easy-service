"""Platform manager selection."""

from __future__ import annotations

import sys

from easy_service.platforms.base import ServiceManager
from easy_service.platforms.linux import LinuxUserServiceManager
from easy_service.platforms.macos import MacOSLaunchAgentManager
from easy_service.platforms.windows import WindowsTaskSchedulerManager


def detect_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError(f"unsupported platform: {sys.platform}")


def manager_for_platform(name: str | None = None) -> ServiceManager:
    platform_name = name or detect_platform()
    if platform_name == "macos":
        return MacOSLaunchAgentManager()
    if platform_name == "linux":
        return LinuxUserServiceManager()
    if platform_name == "windows":
        return WindowsTaskSchedulerManager()
    raise ValueError(f"unknown platform: {platform_name!r}")

