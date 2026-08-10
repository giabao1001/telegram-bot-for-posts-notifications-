from __future__ import annotations

import argparse
import os
import plistlib
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PID_FILE = DATA_DIR / "pagepulse.pid"
LOG_FILE = DATA_DIR / "pagepulse.log"
PYTHON = ROOT / ".venv" / "bin" / "python"
DASHBOARD = ROOT / "dashboard.py"
ENV_FILE = ROOT / ".env"
HOST = "127.0.0.1"
PORT = 8000
DASHBOARD_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{DASHBOARD_URL}/health"
LAUNCH_AGENT_LABEL = "com.diemrenluyen.pagepulse"
LAUNCH_AGENT_FILE = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)
LAUNCHCTL_DOMAIN = f"gui/{os.getuid()}"
LAUNCHCTL_TARGET = f"{LAUNCHCTL_DOMAIN}/{LAUNCH_AGENT_LABEL}"


def read_pid() -> int | None:
    try:
        value = PID_FILE.read_text(encoding="utf-8").strip()
        pid = int(value)
    except (FileNotFoundError, ValueError, OSError):
        return None
    return pid if pid > 0 else None


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def process_is_pagepulse(pid: int) -> bool:
    if not process_exists(pid):
        return False
    try:
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
        cwd_output = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
    except OSError:
        return False
    cwd = next(
        (line[1:] for line in cwd_output.splitlines() if line.startswith("n")),
        "",
    )
    return "dashboard.py" in command and Path(cwd) == ROOT


def managed_pid() -> int | None:
    pid = read_pid()
    if pid is not None and process_is_pagepulse(pid):
        return pid
    if PID_FILE.exists():
        PID_FILE.unlink(missing_ok=True)
    return None


def healthcheck(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def port_is_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        return connection.connect_ex((HOST, PORT)) == 0


def require_setup() -> None:
    if not PYTHON.is_file():
        raise RuntimeError(
            "The project environment is missing. Run: python3 -m venv .venv && "
            ".venv/bin/python -m pip install -r requirements.txt"
        )
    if not ENV_FILE.is_file():
        raise RuntimeError("First-time setup is required. Run: .venv/bin/python setup.py")
    if not DASHBOARD.is_file():
        raise RuntimeError(f"Dashboard file not found: {DASHBOARD}")


def launch_agent_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", LAUNCHCTL_TARGET],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def launch_agent_definition() -> dict[str, object]:
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [str(PYTHON), str(DASHBOARD)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "StandardOutPath": str(LOG_FILE),
        "StandardErrorPath": str(DATA_DIR / "pagepulse-error.log"),
    }


def bootout_launch_agent() -> None:
    if not launch_agent_loaded():
        return
    result = subprocess.run(
        ["launchctl", "bootout", LAUNCHCTL_TARGET],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Could not stop the login service.")


def bootstrap_launch_agent(wait_seconds: float = 20.0) -> str:
    if not LAUNCH_AGENT_FILE.is_file():
        raise RuntimeError("The automatic-login service has not been installed.")
    if not launch_agent_loaded():
        result = subprocess.run(
            ["launchctl", "bootstrap", LAUNCHCTL_DOMAIN, str(LAUNCH_AGENT_FILE)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or "Could not start the automatic-login service."
            )

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if healthcheck(timeout=0.5):
            return "diemRenLuyen started automatically in the background."
        time.sleep(0.35)
    details = log_tail()
    raise RuntimeError(
        "The automatic-login service did not become ready within 20 seconds."
        + (f"\n\nRecent log output:\n{details}" if details else "")
    )


def install_autostart() -> str:
    require_setup()
    if managed_pid() is not None:
        stop()
    elif healthcheck() and not launch_agent_loaded():
        raise RuntimeError(
            "PagePulse is already running outside the launcher. Stop it before "
            "installing automatic startup."
        )
    if launch_agent_loaded():
        bootout_launch_agent()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = LAUNCH_AGENT_FILE.with_suffix(".plist.tmp")
    with temporary_file.open("wb") as plist_file:
        plistlib.dump(launch_agent_definition(), plist_file)
    temporary_file.replace(LAUNCH_AGENT_FILE)
    bootstrap_launch_agent()
    return (
        "Automatic startup is enabled. diemRenLuyen will start whenever you log "
        "into this Mac."
    )


def uninstall_autostart() -> str:
    bootout_launch_agent()
    LAUNCH_AGENT_FILE.unlink(missing_ok=True)
    return "Automatic startup is disabled."


def log_tail(lines: int = 12) -> str:
    try:
        content = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def start(wait_seconds: float = 20.0) -> str:
    require_setup()
    if LAUNCH_AGENT_FILE.is_file():
        return bootstrap_launch_agent(wait_seconds)
    pid = managed_pid()
    if pid is not None and healthcheck():
        return f"PagePulse is already running (PID {pid})."
    if healthcheck():
        return "PagePulse is already running outside this launcher."
    if port_is_in_use():
        raise RuntimeError(
            f"Port {PORT} is occupied by another process that is not responding as PagePulse."
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"\n--- Starting PagePulse at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log.flush()
        process = subprocess.Popen(
            [str(PYTHON), str(DASHBOARD)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            details = log_tail()
            raise RuntimeError(
                "PagePulse stopped while starting."
                + (f"\n\nRecent log output:\n{details}" if details else "")
            )
        if healthcheck(timeout=0.5):
            return f"PagePulse started successfully (PID {process.pid})."
        time.sleep(0.35)

    stop()
    details = log_tail()
    raise RuntimeError(
        "PagePulse did not become ready within 20 seconds."
        + (f"\n\nRecent log output:\n{details}" if details else "")
    )


def stop(wait_seconds: float = 8.0) -> str:
    if launch_agent_loaded():
        bootout_launch_agent()
        return "diemRenLuyen stopped. It will start again at your next Mac login."
    pid = managed_pid()
    if pid is None:
        return "PagePulse is not running under this launcher."

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not process_exists(pid):
            PID_FILE.unlink(missing_ok=True)
            return "PagePulse stopped."
        time.sleep(0.2)

    os.kill(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    return "PagePulse was forced to stop after it did not exit normally."


def status() -> str:
    if launch_agent_loaded():
        state = "healthy" if healthcheck() else "starting or not responding"
        return f"autostart|diemRenLuyen is running automatically ({state})."
    pid = managed_pid()
    if pid is not None:
        state = "healthy" if healthcheck() else "not responding"
        return f"managed|PagePulse is running (PID {pid}, {state})."
    if healthcheck():
        return "external|PagePulse is running outside this launcher."
    if port_is_in_use():
        return f"conflict|Port {PORT} is occupied by another process."
    if LAUNCH_AGENT_FILE.is_file():
        return "stopped-auto|diemRenLuyen is stopped until it is opened or you log in."
    return "stopped|PagePulse is stopped."


def main() -> int:
    parser = argparse.ArgumentParser(description="Start and stop the local PagePulse service.")
    parser.add_argument(
        "action",
        choices=(
            "start",
            "stop",
            "status",
            "open",
            "install-autostart",
            "uninstall-autostart",
        ),
    )
    args = parser.parse_args()

    try:
        if args.action == "start":
            print(start())
        elif args.action == "stop":
            print(stop())
        elif args.action == "status":
            print(status())
        elif args.action == "install-autostart":
            print(install_autostart())
        elif args.action == "uninstall-autostart":
            print(uninstall_autostart())
        else:
            webbrowser.open(DASHBOARD_URL)
            print(f"Opened {DASHBOARD_URL}")
    except (RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
