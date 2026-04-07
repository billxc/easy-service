"""Windows current-user scheduled task backend."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from easy_service.models import ServiceSpec, ServiceStatus
from easy_service.platforms.base import ServiceManager
from easy_service.utils import slugify


class WindowsTaskSchedulerManager(ServiceManager):
    platform_name = "windows"

    def task_name(self, name: str) -> str:
        return f"EasyService-{slugify(name)}"

    def app_dir(self, name: str) -> Path:
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local_app / "easy-service" / slugify(name)

    def runner_path(self, name: str) -> Path:
        return self.app_dir(name) / "run.ps1"

    def _powershell(self) -> str:
        return self._require_binary("powershell")

    def _schtasks(self) -> str:
        return self._require_binary("schtasks")

    def _require_installed(self, name: str) -> Path:
        path = self.runner_path(name)
        if not path.exists():
            raise RuntimeError(
                f"service {name!r} is not installed (no runner at {path})\n"
                f"hint: run 'easy-service install {name} -- <command>' first"
            )
        return path

    def _ps_quote(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _runner_content(self, spec: ServiceSpec) -> str:
        command0 = spec.command[0]
        suffix = Path(command0).suffix.lower()
        if suffix in {".cmd", ".bat"}:
            file_name = "cmd.exe"
            arguments = subprocess.list2cmdline(["/c", *spec.command])
        elif suffix == ".ps1":
            file_name = "powershell"
            arguments = subprocess.list2cmdline(
                ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", *spec.command]
            )
        else:
            file_name = command0
            arguments = subprocess.list2cmdline(list(spec.command[1:]))

        env_lines = [
            f"$psi.EnvironmentVariables[{self._ps_quote(key)}] = {self._ps_quote(value)}"
            for key, value in spec.env
        ]
        working_dir_line = (
            f"$psi.WorkingDirectory = {self._ps_quote(str(spec.working_dir))}"
            if spec.working_dir
            else ""
        )

        lines = [
            "$ErrorActionPreference = 'Stop'",
            "",
            "Add-Type -TypeDefinition @\"",
            "using System;",
            "using System.Runtime.InteropServices;",
            "",
            "public static class EasyServiceNative {",
            "    [StructLayout(LayoutKind.Sequential)]",
            "    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {",
            "        public long PerProcessUserTimeLimit;",
            "        public long PerJobUserTimeLimit;",
            "        public uint LimitFlags;",
            "        public UIntPtr MinimumWorkingSetSize;",
            "        public UIntPtr MaximumWorkingSetSize;",
            "        public uint ActiveProcessLimit;",
            "        public UIntPtr Affinity;",
            "        public uint PriorityClass;",
            "        public uint SchedulingClass;",
            "    }",
            "",
            "    [StructLayout(LayoutKind.Sequential)]",
            "    public struct IO_COUNTERS {",
            "        public ulong ReadOperationCount;",
            "        public ulong WriteOperationCount;",
            "        public ulong OtherOperationCount;",
            "        public ulong ReadTransferCount;",
            "        public ulong WriteTransferCount;",
            "        public ulong OtherTransferCount;",
            "    }",
            "",
            "    [StructLayout(LayoutKind.Sequential)]",
            "    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {",
            "        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;",
            "        public IO_COUNTERS IoInfo;",
            "        public UIntPtr ProcessMemoryLimit;",
            "        public UIntPtr JobMemoryLimit;",
            "        public UIntPtr PeakProcessMemoryUsed;",
            "        public UIntPtr PeakJobMemoryUsed;",
            "    }",
            "",
            "    public const int JobObjectExtendedLimitInformation = 9;",
            "    public const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;",
            "",
            "    [DllImport(\"kernel32.dll\", CharSet = CharSet.Unicode, SetLastError = true)]",
            "    public static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);",
            "",
            "    [DllImport(\"kernel32.dll\", SetLastError = true)]",
            "    public static extern bool SetInformationJobObject(IntPtr hJob, int jobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);",
            "",
            "    [DllImport(\"kernel32.dll\", SetLastError = true)]",
            "    public static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);",
            "",
            "    [DllImport(\"kernel32.dll\", SetLastError = true)]",
            "    public static extern bool CloseHandle(IntPtr hObject);",
            "}",
            "\"@",
            "",
            "function New-EasyServiceJobObject {",
            "    $job = [EasyServiceNative]::CreateJobObject([IntPtr]::Zero, $null)",
            "    if ($job -eq [IntPtr]::Zero) {",
            "        throw [System.ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())",
            "    }",
            "",
            "    $info = New-Object EasyServiceNative+JOBOBJECT_EXTENDED_LIMIT_INFORMATION",
            "    $info.BasicLimitInformation.LimitFlags = [EasyServiceNative]::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
            "    $length = [Runtime.InteropServices.Marshal]::SizeOf([type] [EasyServiceNative+JOBOBJECT_EXTENDED_LIMIT_INFORMATION])",
            "    $ptr = [Runtime.InteropServices.Marshal]::AllocHGlobal($length)",
            "    try {",
            "        [Runtime.InteropServices.Marshal]::StructureToPtr($info, $ptr, $false)",
            "        if (-not [EasyServiceNative]::SetInformationJobObject($job, [EasyServiceNative]::JobObjectExtendedLimitInformation, $ptr, [uint32]$length)) {",
            "            throw [System.ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())",
            "        }",
            "    } finally {",
            "        [Runtime.InteropServices.Marshal]::FreeHGlobal($ptr)",
            "    }",
            "",
            "    return $job",
            "}",
            "",
            "$psi = New-Object System.Diagnostics.ProcessStartInfo",
            f"$psi.FileName = {self._ps_quote(file_name)}",
            f"$psi.Arguments = {self._ps_quote(arguments)}",
            "$psi.UseShellExecute = $false",
        ]
        if working_dir_line:
            lines.append(working_dir_line)
        lines.extend(env_lines)
        lines.extend(
            [
                "",
                "$job = New-EasyServiceJobObject",
                "$process = $null",
                "try {",
                "    $process = [System.Diagnostics.Process]::Start($psi)",
                "    if ($null -eq $process) {",
                "        throw 'failed to start process'",
                "    }",
                "    if (-not [EasyServiceNative]::AssignProcessToJobObject($job, $process.Handle)) {",
                "        throw [System.ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())",
                "    }",
                "    $process.WaitForExit()",
                "    exit $process.ExitCode",
                "} finally {",
                "    if ($process -ne $null) {",
                "        $process.Dispose()",
                "    }",
                "    if ($job -ne [IntPtr]::Zero) {",
                "        [EasyServiceNative]::CloseHandle($job) | Out-Null",
                "    }",
                "}",
                "",
            ]
        )
        return "\r\n".join(lines)

    def _registration_script(self, spec: ServiceSpec) -> str:
        runner = self.runner_path(spec.name)
        task_name = self.task_name(spec.name)
        return (
            "$action = New-ScheduledTaskAction -Execute 'powershell' "
            f"-Argument '-NoProfile -ExecutionPolicy Bypass -File \"{runner}\"'; "
            "$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
            "$settings = New-ScheduledTaskSettingsSet "
            "-AllowStartIfOnBatteries "
            "-DontStopIfGoingOnBatteries "
            "-ExecutionTimeLimit ([TimeSpan]::Zero); "
            f"Register-ScheduledTask -TaskName '{task_name}' "
            "-Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force"
        )

    def render(self, spec: ServiceSpec) -> dict[Path, str]:
        spec.validate()
        return {
            self.runner_path(spec.name): self._runner_content(spec),
            self.app_dir(spec.name) / "register-task.ps1": self._registration_script(spec),
        }

    def install(self, spec: ServiceSpec) -> None:
        self._powershell()
        artifacts = self.render(spec)
        for path, content in artifacts.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        script = artifacts[self.app_dir(spec.name) / "register-task.ps1"]
        self._run([self._powershell(), "-NoProfile", "-Command", script])
        if spec.auto_start:
            self.start(spec.name)

    def uninstall(self, name: str) -> None:
        self._require_installed(name)
        task_name = self.task_name(name)
        self._run([self._schtasks(), "/delete", "/tn", task_name, "/f"], check=False)
        app_dir = self.app_dir(name)
        if app_dir.exists():
            shutil.rmtree(app_dir)

    def start(self, name: str) -> None:
        self._require_installed(name)
        self._run([self._schtasks(), "/run", "/tn", self.task_name(name)])

    def stop(self, name: str) -> None:
        self._require_installed(name)
        self._run([self._schtasks(), "/end", "/tn", self.task_name(name)])

    def status(self, name: str) -> ServiceStatus:
        runner = self.runner_path(name)
        if not runner.exists():
            return ServiceStatus(installed=False, running=None, detail="runner not found")
        result = self._run(
            [self._schtasks(), "/query", "/tn", self.task_name(name), "/fo", "list"],
            check=False,
        )
        if result.returncode != 0:
            return ServiceStatus(
                installed=True,
                running=None,
                detail="runner exists but task not registered in Task Scheduler",
            )
        running = "Running" in result.stdout
        detail = (result.stdout or result.stderr).strip() or "unknown"
        return ServiceStatus(installed=True, running=running, detail=detail)

    def doctor(self) -> list[str]:
        lines = super().doctor()
        lines.append(f"app_dir={self.app_dir('example').parent}")
        try:
            self._require_binary("schtasks")
            lines.append("schtasks=yes")
        except RuntimeError:
            lines.append("schtasks=MISSING (required)")
        try:
            self._require_binary("powershell")
            lines.append("powershell=yes")
        except RuntimeError:
            lines.append("powershell=MISSING (required)")
        return lines
