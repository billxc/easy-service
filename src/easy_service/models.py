"""Core models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from easy_service.utils import slugify


@dataclass(frozen=True)
class ServiceSpec:
    """Cross-platform service definition."""

    name: str
    command: tuple[str, ...] | Sequence[str]
    working_dir: Path | None = None
    env: tuple[tuple[str, str], ...] | Mapping[str, str] = ()
    auto_start: bool = True
    keep_alive: bool = True

    def __post_init__(self) -> None:
        # Normalize mutable inputs to immutable types
        if not isinstance(self.command, tuple):
            object.__setattr__(self, "command", tuple(self.command))
        if isinstance(self.env, Mapping):
            object.__setattr__(self, "env", tuple(self.env.items()))
        elif not isinstance(self.env, tuple):
            object.__setattr__(self, "env", tuple(self.env))
        if self.working_dir is not None and not isinstance(self.working_dir, Path):
            object.__setattr__(self, "working_dir", Path(self.working_dir).expanduser())

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
    enabled: bool | None = None

