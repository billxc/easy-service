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
- Windows: a launcher script plus a current-user scheduled task

## CLI Contract

The public CLI surface is intentionally small:

- `doctor`
- `render`
- `install`
- `uninstall`
- `start`
- `stop`
- `restart`
- `status`

`render` is an explicit part of the design. Users should be able to inspect the generated artifact before installing it.

## Backend Selection

`easy-service` auto-detects the current platform by default:

- `darwin` -> `LaunchAgent`
- `linux` -> `systemd --user`
- `win32` -> current-user `Task Scheduler`

`render` also accepts an explicit `--platform` so users can inspect artifacts for another OS.

## Platform-Specific Details

### macOS

- Artifact path: `~/Library/LaunchAgents/dev.easy-service.<name>.plist`
- Launch style: `launchctl bootstrap gui/<uid> <plist>`
- Restart behavior: `KeepAlive=true`
- Logs: `~/Library/Logs/easy-service/<name>.log` and `.err`

### Linux

- Artifact path: `~/.config/systemd/user/easy-service-<name>.service`
- Launch style: `systemctl --user`
- Restart behavior: `Restart=on-failure`
- Install behavior: `daemon-reload`, `enable`, optional `start`

### Windows

- Artifact path: `%LOCALAPPDATA%\\easy-service\\<name>\\launcher.cmd`
- Registration style: current-user scheduled task
- Launch style: trigger on logon plus manual `schtasks /run`
- Restart behavior: task registration is user-scoped, not a system service

The Windows choice is the key trade-off. We avoid Windows Services because they typically push the tool toward administrator privileges. The result is slightly different semantics, but the UX stays simple and consistent.

## UX Principles

- Prefer one obvious path over many advanced modes
- Default to user scope
- Generate human-readable artifacts
- Use the native manager instead of keeping a wrapper daemon alive
- Fail with concrete remediation

## Caveats

- Linux boot-time behavior without a login session may require enabling lingering; that is not the v0 focus
- Windows Task Scheduler is not identical to a Windows Service
- User-level services are per-user by design

