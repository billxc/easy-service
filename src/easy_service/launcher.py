"""Windows launcher daemon.

Starts the service process, writes a PID file, and optionally restarts
the child on exit (keep_alive) with exponential backoff.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _write_pid(pid_path: Path) -> None:
    pid_path.write_text(f"{os.getpid()} {_creation_time(os.getpid())}")


def _creation_time(pid: int) -> str:
    """Return process creation time as a string for PID reuse detection."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
    if not handle:
        return "0"
    try:
        creation = wintypes.FILETIME()
        exit_t = wintypes.FILETIME()
        kernel_t = wintypes.FILETIME()
        user_t = wintypes.FILETIME()
        if kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_t),
            ctypes.byref(kernel_t),
            ctypes.byref(user_t),
        ):
            return str(
                creation.dwHighDateTime << 32 | creation.dwLowDateTime
            )
        return "0"
    finally:
        kernel32.CloseHandle(handle)


def launch(name: str, app_dir: Path) -> int:
    """Launcher daemon entry point. Returns exit code."""
    spec_path = app_dir / "spec.json"
    if not spec_path.exists():
        print(f"error: {spec_path} not found", file=sys.stderr)
        return 1

    spec = json.loads(spec_path.read_text())
    command = spec["command"]
    working_dir = spec.get("working_dir")
    env_pairs = spec.get("env", {})
    keep_alive = spec.get("keep_alive", True)

    # Build environment
    child_env = os.environ.copy()
    if isinstance(env_pairs, dict):
        child_env.update(env_pairs)
    elif isinstance(env_pairs, list):
        for pair in env_pairs:
            child_env[pair[0]] = pair[1]

    # Write launcher PID file
    pid_path = app_dir / "pid"
    log_path = app_dir / "launcher.log"
    output_path = app_dir / "output.log"
    _write_pid(pid_path)

    def _log(msg: str) -> None:
        with open(log_path, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

    backoff = 1
    max_backoff = 60
    stable_threshold = 60  # seconds

    _log(f"launcher started, pid={os.getpid()}, keep_alive={keep_alive}")

    try:
        while True:
            start_time = time.monotonic()
            _log(f"starting child: {command}")
            output_file = open(output_path, "a")
            proc = subprocess.Popen(
                command,
                cwd=working_dir,
                env=child_env,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            _log(f"child started, pid={proc.pid}")
            try:
                proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                _log("interrupted, exiting")
                return 1
            finally:
                output_file.close()

            _log(f"child exited, code={proc.returncode}")

            if not keep_alive:
                return proc.returncode or 0

            # Stable run → restart immediately; crash loop → backoff
            elapsed = time.monotonic() - start_time
            if elapsed >= stable_threshold:
                backoff = 1
                _log("restarting immediately")
            else:
                backoff = min(backoff * 2, max_backoff)
                _log(f"restarting in {backoff}s (crash loop backoff)")
                time.sleep(backoff)
    finally:
        _log("launcher exiting")
        pid_path.unlink(missing_ok=True)
