"""Core models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from easy_service.utils import slugify


@dataclass(frozen=True)
class ServiceSpec:
    """Cross-platform service definition."""

    name: str
    command: tuple[str, ...]
    working_dir: Path | None = None
    env: tuple[tuple[str, str], ...] = ()
    auto_start: bool = True
    keep_alive: bool = True

    def validate(self) -> None:
        slugify(self.name)
        if not self.command:
            raise ValueError("command must not be empty")

    @property
    def slug(self) -> str:
        return slugify(self.name)


@dataclass(frozen=True)
class ServiceStatus:
    installed: bool
    running: bool | None
    detail: str

