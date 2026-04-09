# AGENTS.md

## Project Overview

`easy-service` is a cross-platform, no-admin service manager for user-level background commands. It supports macOS (`launchd`), Linux (`systemd --user`), and Windows (`Task Scheduler`).

## Package Management

This project uses **[uv](https://docs.astral.sh/uv/)** for dependency and environment management. Do not use `pip` or `pip install` directly.

```bash
# Create / sync the virtual environment
uv sync

# Install the package in editable mode
uv pip install -e .

# Install as a persistent CLI tool
uv tool install .
```

## Build System

- Build backend: **hatchling**
- Source layout: `src/easy_service/`
- Python requirement: `>=3.11`
- No runtime dependencies

## Running Tests

Tests use the standard library `unittest` (no pytest dependency):

```bash
python -m unittest discover -s tests -v
```

## Project Structure

```
src/easy_service/
  __init__.py          # Public API exports
  cli.py               # argparse-based CLI entry point
  models.py            # ServiceSpec / ServiceStatus dataclasses
  utils.py             # slugify, shell_join, env parsing
  launcher.py          # Windows launcher daemon
  platforms/
    base.py            # ServiceManager ABC
    macos.py           # LaunchAgent implementation
    linux.py           # systemd --user implementation
    windows.py         # Task Scheduler + launcher implementation
tests/
  test_cli.py          # CLI, rendering, and spec validation tests
```

## CLI Entry Point

Defined in `pyproject.toml`:

```
easy-service = "easy_service.cli:main"
```

## Conventions

- Frozen dataclasses for models (`ServiceSpec`, `ServiceStatus`).
- Platform backends extend `ServiceManager` ABC in `platforms/base.py`.
- Service names are slugified (`[A-Za-z0-9-]`).
- All platform modules can be imported on any OS; platform-specific syscalls are guarded at runtime.
