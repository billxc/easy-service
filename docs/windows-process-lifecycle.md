# Windows Process Lifecycle: Known Limitation

## Problem

On Windows, `schtasks /end` does not kill child processes. It only terminates the
direct process started by Task Scheduler.

### Root Cause

1. **`TerminateProcess` only kills one process.** `schtasks /end` internally calls
   `TerminateProcess` on the top-level process. This API does not propagate to
   child processes — they become orphaned.

2. **Job Object `KILL_ON_JOB_CLOSE` does not work under Task Scheduler.** Windows
   Task Scheduler wraps launched processes in its own Job Object. When our runner
   script creates a second (nested) Job Object and assigns the child process to it,
   the child belongs to both Jobs. When our Job handle is closed (because PowerShell
   was killed), `KILL_ON_JOB_CLOSE` does not fire — the child is still held by
   Task Scheduler's Job.

   This was verified empirically: `IsProcessInJob` returned `True` for both the
   PowerShell runner and the child process before termination. After `schtasks /end`
   killed PowerShell, the child remained alive and still belonged to a Job Object
   (Task Scheduler's).

### Impact

Any architecture that uses a wrapper process (PowerShell, cmd, etc.) to launch the
actual service command will hit this: `schtasks /end` kills the wrapper, but the
real process survives.

## Current Solution

PID file approach:

- `run.ps1` starts the process via `ProcessStartInfo`, writes the PID to a `pid`
  file, and exits immediately.
- `stop` reads the PID file and calls `Stop-Process -Id <pid> -Force`.
- `status` checks whether the PID in the file is still alive.

This is reliable and simple. The tradeoff is that `schtasks /end` alone does not
stop the service — our `stop` command must be used.

## Alternatives Explored

| Approach | Result |
|---|---|
| Job Object with `KILL_ON_JOB_CLOSE` | Fails due to Task Scheduler's nested Job |
| Register user command directly (no wrapper) | Loses env var support; Task Scheduler shows "Ready" immediately for some executables |
| `schtasks /end` relying on process tree kill | Windows does not support this |

## Future Possibilities

- If env vars are not needed, registering the user's command directly as the
  scheduled task action would let Task Scheduler manage the process natively. This
  could be a fast path for the common case.
- Windows Services API (requires admin) would give full process lifecycle control,
  but conflicts with the project's no-admin design goal.
