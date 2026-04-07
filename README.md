# easy-service

`easy-service` makes a command feel like a service on macOS, Linux, and Windows without asking for administrator privileges.

- Cross-platform by default
- No admin by default
- Simple UX by default

## Installation

```bash
uv tool install git+https://github.com/billxc/easy-service.git
```

> **Note:** On Windows, `easy-service` must be installed persistently (not run via `uvx`), because the launcher daemon needs a stable exe to copy.

## Quick Start

```bash
# Install a service (starts automatically)
easy-service install my-bot --cwd ~/code/my-bot -- python -m my_bot

# Check status
easy-service status my-bot

# View service output
easy-service logs my-bot
easy-service logs my-bot --follow   # tail -f style

# Stop and restart
easy-service stop my-bot
easy-service start my-bot

# Remove
easy-service uninstall my-bot
```

## CLI

```bash
easy-service doctor                                                 # check platform prerequisites
easy-service list                                                   # list installed services
easy-service render my-bot --cwd ~/code/my-bot -- python -m my_bot  # preview artifacts
easy-service install my-bot --cwd ~/code/my-bot -- python -m my_bot # install + auto-start
easy-service start my-bot
easy-service stop my-bot
easy-service restart my-bot
easy-service status my-bot
easy-service uninstall my-bot
easy-service logs my-bot [-f/--follow]                              # view service stdout/stderr
easy-service events my-bot [-f/--follow]                            # view launcher lifecycle events
easy-service upgrade [my-bot]                                       # re-sync service runtime (Windows)
easy-service --version                                              # show version
```

### Options

`render` and `install` accept these flags:

- `--cwd <path>` — working directory for the service
- `--env KEY=VALUE` — environment variable (repeatable)
- `--no-auto-start` — install without starting immediately
- `--no-keep-alive` — do not auto-restart on exit
- `--platform <name>` — override platform detection (e.g., generate Linux artifacts on macOS)

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

### Why Windows needs extra work

macOS `launchd` and Linux `systemd` are full-featured service managers — they handle process supervision, auto-restart (`KeepAlive` / `Restart=on-failure`), log collection, and clean process lifecycle out of the box.

Windows Task Scheduler is not a service manager. It can launch a process, but it has no built-in support for:

- **Process supervision**: no automatic restart when a process crashes
- **Process grouping**: "End Task" in Task Scheduler only kills the top-level process, not child processes
- **Log management**: no stdout/stderr capture

`easy-service` fills these gaps with a **launcher daemon** that wraps the user's command:

- Automatic restart with exponential backoff (2s -> 4s -> 8s -> ... -> 60s max, reset after 60s of stable running)
- Windows Job Object with `KILL_ON_JOB_CLOSE` to ensure the entire process tree is killed together
- stdout/stderr redirection to log files, viewable via `easy-service logs`
- Automatic detection of `.cmd`/`.bat` commands (e.g. `npx`, `npm`) — runs them through `cmd.exe` so Windows resolves them correctly

**Why copy the venv?** The launcher daemon is a long-running process. If `easy-service` runs directly from the tool virtualenv, `uv tool install --force` would fail with "access denied" because Windows locks running executables and loaded DLLs. By copying the tool's virtualenv into each service's data directory, the original installation is free to be upgraded at any time. The copied `pythonw.exe` is renamed to `EasyService-<name>.exe` so each service shows with a distinct name in Task Manager, and `pythonw.exe` (instead of `python.exe`) ensures no console window appears.

The copied venv's `pyvenv.cfg` points to uv's managed Python installation (e.g. `%APPDATA%/uv/python/cpython-3.13-...`). If uv upgrades Python, run `easy-service upgrade` to re-sync all services.

**Why `upgrade`?** The `upgrade` command re-copies the tool venv and re-registers the Task Scheduler task for each service. This picks up both Python version changes (updated `pyvenv.cfg`) and `easy-service` code changes (updated `site-packages`). Run it after `uv tool install --force easy-service` or after uv upgrades Python.

## Differentiation

- User-level first, not system-level first
- One mental model across platforms: `install`, `start`, `stop`, `restart`, `status`, `logs`
- Plain-text artifacts you can inspect before installing
- Native platform integration (macOS/Linux); thin launcher daemon where native gaps exist (Windows)
- Minimal configuration surface

## Non-Goals

- System-wide services
- Admin-only installation flows
- Container orchestration
- Remote fleet management

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
