# Architecture

## Product Goal

Turn an arbitrary long-running command into a user-level background service on macOS, Linux, and Windows with one small CLI.

The hard requirement is not "all service managers." The hard requirement is:

- no administrator permission
- native platform integration
- obvious install/uninstall story

## Core Model

Every service is defined by the same input:

- `name`
- `command`
- `working_dir`
- `env`
- `auto_start`
- `keep_alive`

That becomes a platform-specific artifact:

- macOS: a `plist`
- Linux: a `systemd --user` unit
- Windows: a `spec.json` consumed by a launcher daemon (see [Windows details](#windows) below)

## CLI Contract

The public CLI surface is intentionally small:

- `doctor`
- `list` — show installed services and their status
- `render`
- `install`
- `uninstall`
- `start`
- `stop`
- `restart`
- `status`
- `disable` — prevent auto-start on login without uninstalling
- `enable` — re-enable auto-start on login
- `logs` — view service stdout/stderr output
- `events` — view launcher lifecycle events (start, crash, restart)
- `upgrade` — re-sync service runtime after Python or easy-service upgrades (Windows only)
- `--version`

`render` is an explicit part of the design. Users should be able to inspect the generated artifact before installing it.

## Backend Selection

`easy-service` auto-detects the current platform by default:

- `darwin` -> `LaunchAgent`
- `linux` -> `systemd --user`
- `win32` -> current-user `Task Scheduler`

`render` also accepts an explicit `--platform` so users can inspect artifacts for another OS.

## Platform-Specific Details

### macOS

- Artifact path: `~/Library/LaunchAgents/dev.easy-service.<slug>.plist`
- Launch style: `launchctl bootstrap gui/<uid> <plist>`
- Restart behavior: `KeepAlive=true`
- Logs: `~/Library/Logs/easy-service/<slug>.log` and `.err`

### Linux

- Artifact path: `~/.config/systemd/user/easy-service-<slug>.service`
- Launch style: `systemctl --user`
- Restart behavior: `Restart=on-failure`
- Install behavior: `daemon-reload`, `enable`, optional `start`

### Windows

Windows Task Scheduler is not a service manager — it lacks process supervision, process grouping, and log capture. `easy-service` compensates with a **launcher daemon**.

- Artifact path: `%LOCALAPPDATA%\easy-service\<slug>\spec.json`
- Registration: current-user scheduled task (via `Register-ScheduledTask`)
- Launch chain: Task Scheduler -> `EasyService-<name>.exe -m easy_service _launch <name>` -> launcher daemon -> child process
- The exe is a renamed `pythonw.exe` (windowless Python) from a per-service venv copy
- Restart behavior: launcher daemon with exponential backoff (2s -> 4s -> 8s -> ... -> 60s max, reset after 60s stable run)
- Process grouping: Windows Job Object with `KILL_ON_JOB_CLOSE` — killing the launcher kills all children
- `.cmd`/`.bat` detection: commands like `npx` and `npm` are automatically run through `cmd.exe`
- Logs: `%LOCALAPPDATA%\easy-service\<slug>\output.log` (service stdout/stderr), `launcher.log` (lifecycle events)

**Per-service venv**: Each service gets a copy of the tool's virtualenv (~700 KB) in its data directory. The `pythonw.exe` inside is renamed to `EasyService-<name>.exe`. This serves three purposes: (1) the running process does not lock the original installation, so `uv tool install --force` can upgrade freely; (2) each service shows with a distinct name in Task Manager; (3) `pythonw.exe` runs without a console window.

**Upgrade**: `easy-service upgrade` re-copies the venv and re-registers the Task Scheduler task for all services. This picks up Python path changes (`pyvenv.cfg`) and code updates (`site-packages`). Run it after upgrading `easy-service` or after uv upgrades Python.

The Windows choice is the key trade-off. We avoid Windows Services because they typically push the tool toward administrator privileges. The launcher daemon fills the gaps that Task Scheduler leaves, while keeping the UX simple and consistent.

## UX Principles

- Prefer one obvious path over many advanced modes
- Default to user scope
- Generate human-readable artifacts
- Use the native manager where possible; on Windows, a thin launcher daemon fills gaps in Task Scheduler
- Fail with concrete remediation

## Caveats

- Linux boot-time behavior without a login session may require enabling lingering; that is not the v0 focus
- Windows Task Scheduler is not identical to a Windows Service — the launcher daemon compensates for missing features
- User-level services are per-user by design
- `uninstall` on Windows preserves log files (`.log`) in the service data directory
