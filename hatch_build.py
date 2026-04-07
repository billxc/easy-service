"""Hatch build hook: embed git commit hash into _build_meta.py."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class GitCommitHook(BuildHookInterface):
    PLUGIN_NAME = "git-commit"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        commit = "unknown"
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                commit = result.stdout.strip()
        except Exception:
            pass

        meta = Path(self.root) / "src" / "easy_service" / "_build_meta.py"
        meta.write_text(f'COMMIT = "{commit}"\n')
