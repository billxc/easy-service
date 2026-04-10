"""CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from easy_service.models import ServiceSpec
from easy_service.platforms import manager_for_platform
from easy_service.utils import parse_env_items


def _get_version() -> str:
    from importlib.metadata import version
    v = version("easy-service")
    try:
        from easy_service._build_meta import COMMIT
        return f"easy-service {v} (commit: {COMMIT})"
    except Exception:
        return f"easy-service {v}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="easy-service",
        description="Cross-platform, no-admin service management for user-level commands.",
    )
    parser.add_argument(
        "-V", "--version", action="version",
        version=_get_version(),
    )
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="Show backend and install locations")
    doctor.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)

    _add_spec_command(sub, "render", "Render platform artifacts without installing")

    _add_spec_command(sub, "install", "Install a user-level service")

    sub.add_parser("list", help="List installed services")

    uninstall = sub.add_parser("uninstall", help="Uninstall a service")
    uninstall.add_argument("name")
    uninstall.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)
    uninstall.add_argument("--clean", action="store_true", default=False, help="Remove all data including logs")

    for name in ("start", "stop", "restart", "status", "disable", "enable"):
        cmd = sub.add_parser(name, help=f"{name.capitalize()} a service")
        cmd.add_argument("name")
        cmd.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)

    upgrade = sub.add_parser("upgrade", help="Re-sync service runtime (Windows only)")
    upgrade.add_argument("name", nargs="?", default=None, help="Service name (omit to upgrade all)")
    upgrade.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)

    logs = sub.add_parser("logs", help="Show service output (stdout/stderr)")
    logs.add_argument("name")
    logs.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)
    logs.add_argument("-f", "--follow", action="store_true", default=False, help="Follow log output")

    events = sub.add_parser("events", help="Show launcher lifecycle events")
    events.add_argument("name")
    events.add_argument("--platform", choices=["macos", "linux", "windows"], default=None)
    events.add_argument("-f", "--follow", action="store_true", default=False, help="Follow event output")

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
        cwd = cwd.expanduser().resolve()
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

    if not args.command:
        parser.print_help()
        return 2

    try:
        manager = manager_for_platform(getattr(args, "platform", None))
        if args.command == "doctor":
            for line in manager.doctor():
                print(line)
            return 0

        if args.command == "list":
            names = manager.list_installed()
            if not names:
                print("no services installed")
                return 0
            for n in names:
                st = manager.status(n)
                state = "running" if st.running else "stopped"
                if st.running is None:
                    state = "unknown"
                if st.enabled is False:
                    state += " (disabled)"
                print(f"{n}\t{state}")
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
            manager.uninstall(args.name, clean=args.clean)
            print(f"uninstalled {args.name}")
            return 0

        if args.command == "upgrade":
            if not hasattr(manager, "upgrade"):
                print(f"error: upgrade is not supported on {manager.platform_name}", file=sys.stderr)
                return 1
            upgraded = manager.upgrade(args.name)
            for name in upgraded:
                print(f"upgraded {name}")
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
            if status.enabled is False:
                state += " (disabled)"
            print(f"{args.name}: {state}")
            if status.detail:
                print(status.detail)
            return 0

        if args.command == "disable":
            manager.disable(args.name)
            print(f"disabled {args.name}")
            return 0

        if args.command == "enable":
            manager.enable(args.name)
            print(f"enabled {args.name}")
            return 0

        if args.command == "logs":
            manager.logs(args.name, follow=args.follow)
            return 0

        if args.command == "events":
            manager.events(args.name, follow=args.follow)
            return 0

    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
