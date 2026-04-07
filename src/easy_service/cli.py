"""CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from easy_service.models import ServiceSpec
from easy_service.platforms import manager_for_platform
from easy_service.utils import parse_env_items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="easy-service",
        description="Cross-platform, no-admin service management for user-level commands.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show backend and install locations")
    doctor.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)

    _add_spec_command(sub, "render", "Render platform artifacts without installing")

    _add_spec_command(sub, "install", "Install a user-level service")

    for name in ("uninstall", "start", "stop", "restart", "status"):
        cmd = sub.add_parser(name, help=f"{name.capitalize()} a service")
        cmd.add_argument("name")
        cmd.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)

    logs = sub.add_parser("logs", help="Show service logs")
    logs.add_argument("name")
    logs.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)
    logs.add_argument("-f", "--follow", action="store_true", default=False, help="Follow log output")

    # Internal command used by the Windows launcher daemon
    launch = sub.add_parser("_launch")
    launch.add_argument("name")

    return parser


def _add_spec_command(subparsers, name: str, help_text: str):
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument("name")
    parser.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)
    parser.add_argument("--cwd", type=Path, default=None)
    parser.add_argument("--env", action="append", default=[], help="Repeatable KEY=VALUE")
    parser.add_argument("--no-auto-start", action="store_true", default=False)
    parser.add_argument("--no-keep-alive", action="store_true", default=False)
    parser.add_argument(
        "service_command",
        nargs="+",
        help="Command to run. Use -- before the command when it includes flags.",
    )
    return parser


def build_spec(args) -> ServiceSpec:
    command = list(args.service_command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("no command provided (did you forget to add -- before the command?)")
    cwd = args.cwd
    if cwd is not None:
        cwd = cwd.resolve()
        if not cwd.is_dir():
            raise ValueError(f"working directory does not exist: {cwd}")
    spec = ServiceSpec(
        name=args.name,
        command=tuple(command),
        working_dir=cwd,
        env=parse_env_items(args.env),
        auto_start=not args.no_auto_start,
        keep_alive=not args.no_keep_alive,
    )
    spec.validate()
    return spec


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        manager = manager_for_platform(getattr(args, "platform", None))
        if args.command == "doctor":
            for line in manager.doctor():
                print(line)
            return 0

        if args.command == "_launch":
            from easy_service.launcher import launch
            from easy_service.platforms.windows import WindowsTaskSchedulerManager
            mgr = WindowsTaskSchedulerManager()
            return launch(args.name, mgr.app_dir(args.name))

        if args.command == "render":
            spec = build_spec(args)
            for path, content in manager.render(spec).items():
                print(f"# {path}")
                print(content.rstrip())
                print()
            return 0

        if args.command == "install":
            spec = build_spec(args)
            manager.install(spec)
            print(f"installed {spec.name} on {manager.platform_name}")
            return 0

        if args.command == "uninstall":
            manager.uninstall(args.name)
            print(f"uninstalled {args.name}")
            return 0

        if args.command == "start":
            manager.start(args.name)
            print(f"started {args.name}")
            return 0

        if args.command == "stop":
            manager.stop(args.name)
            print(f"stopped {args.name}")
            return 0

        if args.command == "restart":
            manager.restart(args.name)
            print(f"restarted {args.name}")
            return 0

        if args.command == "status":
            status = manager.status(args.name)
            if not status.installed:
                print(f"{args.name}: not installed")
                return 1
            state = "running" if status.running else "stopped"
            if status.running is None:
                state = "unknown"
            print(f"{args.name}: {state}")
            if status.detail:
                print(status.detail)
            return 0

        if args.command == "logs":
            manager.logs(args.name, follow=args.follow)
            return 0

    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
