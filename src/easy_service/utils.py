"""Shared helpers."""

from __future__ import annotations

import re
import shlex


def slugify(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", name.strip().lower()).strip("-")
    if not value:
        raise ValueError("service name must contain at least one letter or number")
    return value


def shell_join(parts: list[str] | tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def parse_env_items(values: list[str] | None) -> tuple[tuple[str, str], ...]:
    if not values:
        return ()

    items: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid environment entry: {value!r}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid environment entry: {value!r}")
        items.append((key, raw))
    return tuple(items)

