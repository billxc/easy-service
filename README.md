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
- Windows: current-user `Task Scheduler` task with a named launcher exe

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

`easy-service` must be **installed** (not just run via `uvx`), because the Windows backend copies the installed exe to create per-service named processes.

```bash
# Install as a uv tool (persistent, adds to PATH)
uv tool install git+https://github.com/billxc/easy-service.git

# Or install from a local clone
uv pip install .

# After upgrading easy-service or Python, reinstall existing services:
# easy-service install <name> -- <command>
```

## Programmatic Usage

Other Python projects can add `easy-service` as a dependency and use it as a library:

```bash
uv add git+https://github.com/billxc/easy-service.git
```

### Basic: install and manage a service

```python
from easy_service import ServiceSpec, manager_for_platform

spec = ServiceSpec(
    name="my-bot",
    command=["python", "-m", "my_bot"],
    working_dir="~/code/my-bot",
)

manager = manager_for_platform()   # auto-detects macOS / Linux / Windows
manager.install(spec)              # install + auto-start
manager.status("my-bot")           # => ServiceStatus(installed=True, running=True, ...)
manager.stop("my-bot")
manager.uninstall("my-bot")
```

### Preview artifacts before installing

```python
spec = ServiceSpec(name="sync-loop", command=["python", "sync.py"])

for path, content in manager_for_platform().render(spec).items():
    print(f"# {path}")
    print(content)
```

### With environment variables

```python
spec = ServiceSpec(
    name="web-hook",
    command=["python", "-m", "webhook_server"],
    env={"PORT": "8080", "LOG_LEVEL": "info"},
    keep_alive=True,
)
```

### Render for a different platform

```python
from easy_service import ServiceSpec, manager_for_platform

spec = ServiceSpec(name="my-bot", command=["python", "-m", "my_bot"])

# Generate a systemd unit file on macOS for deployment to a Linux server
linux = manager_for_platform("linux")
for path, content in linux.render(spec).items():
    path.name  # => "easy-service-my-bot.service"
```

## Development

```bash
# Sync the project
uv sync

# Run the tests
uv run python -m unittest discover -s tests -p 'test_*.py'
```
```

