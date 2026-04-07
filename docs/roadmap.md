# Roadmap

## Done

- Repository scaffold, product docs, platform abstraction
- Artifact rendering
- Install/start/stop/restart/status on all three platforms
- `logs` command on all platforms (stdout/stderr output)
- `events` command on all platforms (launcher lifecycle events)
- Windows launcher daemon with keep_alive (exponential backoff restart)
- Windows Job Object for process tree cleanup
- Per-service venv copy with renamed `pythonw.exe` for Task Manager identification and upgrade isolation
- `.cmd`/`.bat` command detection (e.g. `npx`, `npm`) with automatic `shell=True`
- `list` command for installed services
- `upgrade` command to re-sync service runtime (Windows)
- `--version` flag

## Next

- Harden install/uninstall flows on all three platforms
- Better error messages and remediation hints

## Future

- Optional environment file support
- Optional health checks and configurable restart policies (backoff parameters, max retries)
- Optional import/export of service definitions

## Explicitly Deferred

- System-wide services
- Administrator-only flows
- SSH / remote host management
- Container integration
