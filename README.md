# easy-service

`easy-service` makes a command feel like a service on macOS, Linux, and Windows without asking for administrator privileges.

The product thesis is narrow on purpose:

- Cross-platform by default
- No admin by default
- Simple UX by default

This repository is the initial scaffold for that idea. It includes the product framing, the architecture choices, and a small Python CLI/package skeleton that can render and install user-level services using the native service manager on each platform.

## Positioning

`easy-service` is for people who want this:

- "Run my bot, local gateway, dev server, or sync loop in the background"
- "Use the native platform service manager instead of keeping a terminal open"
- "Do not ask me for `sudo`, UAC elevation, or system-wide installation"

It is not trying to be a full deployment platform.

## Why This Exists

There are solid building blocks in the ecosystem, but there is still a gap:

- Broad service abstractions often default to system-level services
- Windows-first wrappers are usually admin-oriented
- Unix daemon helpers do not cover all three desktop platforms
- Cross-platform tools often expose the platform differences instead of hiding them

`easy-service` is opinionated around one use case: current-user background services that are easy to install, inspect, and remove.

## Chosen Platform Strategy

- macOS: `LaunchAgent` in `~/Library/LaunchAgents`
- Linux: `systemd --user` unit in `~/.config/systemd/user`
- Windows: current-user `Task Scheduler` task plus a local launcher script

Those choices are deliberate. They are the native, user-level primitives that do not require administrator access in the normal case.

## Differentiation

- User-level first, not system-level first
- One mental model across platforms: `install`, `start`, `stop`, `restart`, `status`, `render`
- Plain-text artifacts you can inspect before installing
- Native platform integration instead of a long-running wrapper daemon
- Minimal configuration surface

## Non-Goals

- System-wide services
- Admin-only installation flows
- Container orchestration
- Remote fleet management
- Hidden background daemons that manage other daemons

## Current Scaffold

The first commit is intentionally small but concrete:

- Product and architecture docs
- A Python package with a cross-platform CLI shape
- Platform backends for rendering and user-level install/start/stop/status flows
- Basic unit tests for naming and manifest generation

## Planned CLI

```bash
easy-service doctor
easy-service render my-bot --cwd ~/code/my-bot -- python -m my_bot
easy-service install my-bot --cwd ~/code/my-bot -- python -m my_bot
easy-service start my-bot
easy-service stop my-bot
easy-service restart my-bot
easy-service status my-bot
easy-service uninstall my-bot
```

## Repository Layout

```text
docs/
  architecture.md
  market-scan.md
  roadmap.md
src/easy_service/
  cli.py
  models.py
  utils.py
  platforms/
tests/
```

## Installation

```bash
# Run directly from GitHub — no clone needed
uvx --from git+https://github.com/billxc/easy-service.git easy-service --help

# Or install as a uv tool (persistent, adds to PATH)
uv tool install git+https://github.com/billxc/easy-service.git

# Or install from a local clone
uv pip install .
```

## Development

```bash
# Sync the project
uv sync

# Run the tests
uv run python -m unittest discover -s tests -p 'test_*.py'
```
```

