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

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash


APP_NAME = "diemRenLuyen"
SOURCE_ROOT = Path(__file__).resolve().parent
ASSET_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))


def default_data_root() -> Path:
    override = os.getenv("DIEMRENLUYEN_DATA_DIR")
    if override:
        return Path(override)
    if not getattr(sys, "frozen", False):
        return SOURCE_ROOT
    if sys.platform == "win32":
        return Path(os.getenv("LOCALAPPDATA", Path.home())) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


DATA_ROOT = default_data_root()
RUNTIME_DIR = DATA_ROOT / "data"
ENV_FILE = DATA_ROOT / ".env"
PID_FILE = RUNTIME_DIR / "desktop.pid"
LOG_FILE = RUNTIME_DIR / "desktop.log"
HOST = "127.0.0.1"
PORT = 8000
DASHBOARD_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{DASHBOARD_URL}/health"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_RUN_VALUE = APP_NAME
MAC_LABEL = "com.diemrenluyen.desktop"
MAC_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"
MAC_DOMAIN = f"gui/{os.getuid()}" if hasattr(os, "getuid") else ""
MAC_TARGET = f"{MAC_DOMAIN}/{MAC_LABEL}" if MAC_DOMAIN else ""


def configure_environment() -> None:
    os.environ["DIEMRENLUYEN_DATA_DIR"] = str(DATA_ROOT)
    os.environ["DIEMRENLUYEN_ASSET_DIR"] = str(ASSET_ROOT)


def create_configuration(password: str) -> None:
    if len(password) < 12:
        raise ValueError("The dashboard password must contain at least 12 characters.")
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        f"{key}='{value}'"
        for key, value in {
            "DASHBOARD_PASSWORD_HASH": generate_password_hash(password),
            "FLASK_SECRET_KEY": os.urandom(32).hex(),
            "CONFIG_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "DATABASE_FILE": "data/notifier.db",
            "HOST": HOST,
            "PORT": str(PORT),
            "COOKIE_SECURE": "0",
        }.items()
    )
    ENV_FILE.write_text(body + "\n", encoding="utf-8")


def read_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return None
    return pid if pid > 0 else None


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


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


def server_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--server"]
    return [sys.executable, str(SOURCE_ROOT / "desktop_launcher.py"), "--server"]


def start_server(wait_seconds: float = 20.0) -> str:
    if not ENV_FILE.is_file():
        raise RuntimeError("First-time setup is required.")
    if healthcheck():
        return f"{APP_NAME} is already running."
    if port_is_in_use():
        raise RuntimeError(f"Port {PORT} is already being used by another application.")

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    creation_flags = 0
    startup_info = None
    if sys.platform == "win32":
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"\n--- Starting {APP_NAME} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log.flush()
        process = subprocess.Popen(
            server_command(),
            cwd=DATA_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=sys.platform != "win32",
            creationflags=creation_flags,
            startupinfo=startup_info,
            env={**os.environ, "DIEMRENLUYEN_DATA_DIR": str(DATA_ROOT), "DIEMRENLUYEN_ASSET_DIR": str(ASSET_ROOT)},
        )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            raise RuntimeError(f"{APP_NAME} stopped while starting. See {LOG_FILE}.")
        if healthcheck(0.5):
            return f"{APP_NAME} started."
        time.sleep(0.35)
    stop_server()
    raise RuntimeError(f"{APP_NAME} did not become ready. See {LOG_FILE}.")


def stop_server() -> str:
    if sys.platform == "darwin" and mac_service_loaded():
        subprocess.run(["launchctl", "bootout", MAC_TARGET], check=False)
        return f"{APP_NAME} stopped. It will start again at your next login."
    pid = read_pid()
    if pid is None or not process_exists(pid):
        PID_FILE.unlink(missing_ok=True)
        return f"{APP_NAME} is not running under this launcher."
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    return f"{APP_NAME} stopped."


def windows_startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --start --open'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{executable}" "{SOURCE_ROOT / "desktop_launcher.py"}" --start --open'


def mac_service_loaded() -> bool:
    if sys.platform != "darwin":
        return False
    return subprocess.run(
        ["launchctl", "print", MAC_TARGET],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def autostart_enabled() -> bool:
    if sys.platform == "darwin":
        return MAC_PLIST.is_file()
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            winreg.QueryValueEx(key, WINDOWS_RUN_VALUE)
        return True
    except OSError:
        return False


def install_autostart() -> str:
    if sys.platform == "darwin":
        if read_pid() and process_exists(read_pid() or 0):
            stop_server()
        MAC_PLIST.parent.mkdir(parents=True, exist_ok=True)
        command = server_command()
        definition = {
            "Label": MAC_LABEL,
            "ProgramArguments": command,
            "WorkingDirectory": str(DATA_ROOT),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Background",
            "StandardOutPath": str(LOG_FILE),
            "StandardErrorPath": str(RUNTIME_DIR / "desktop-error.log"),
            "EnvironmentVariables": {
                "DIEMRENLUYEN_DATA_DIR": str(DATA_ROOT),
                "DIEMRENLUYEN_ASSET_DIR": str(ASSET_ROOT),
            },
        }
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        if mac_service_loaded():
            subprocess.run(["launchctl", "bootout", MAC_TARGET], check=False)
        with MAC_PLIST.open("wb") as plist_file:
            plistlib.dump(definition, plist_file)
        result = subprocess.run(
            ["launchctl", "bootstrap", MAC_DOMAIN, str(MAC_PLIST)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Could not enable automatic startup.")
        return f"{APP_NAME} will start when you sign in to macOS."
    if sys.platform != "win32":
        raise RuntimeError("Automatic startup is supported on Windows and macOS.")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
        winreg.SetValueEx(key, WINDOWS_RUN_VALUE, 0, winreg.REG_SZ, windows_startup_command())
    return f"{APP_NAME} will start when you sign in to Windows."


def uninstall_autostart() -> str:
    if sys.platform == "darwin":
        if mac_service_loaded():
            subprocess.run(["launchctl", "bootout", MAC_TARGET], check=False)
        MAC_PLIST.unlink(missing_ok=True)
        return "Automatic startup is disabled."
    if sys.platform != "win32":
        raise RuntimeError("Automatic startup is supported on Windows and macOS.")
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, WINDOWS_RUN_VALUE)
    except FileNotFoundError:
        pass
    return "Automatic startup is disabled."


def run_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    root = tk.Tk()
    root.title(f"{APP_NAME} Desktop")
    root.geometry("460x390")
    root.resizable(False, False)

    def ensure_setup() -> bool:
        if ENV_FILE.is_file():
            return True
        messagebox.showinfo(APP_NAME, "Create a private dashboard password to finish first-time setup.")
        first = simpledialog.askstring(APP_NAME, "Dashboard password (12+ characters):", show="*", parent=root)
        if first is None:
            return False
        second = simpledialog.askstring(APP_NAME, "Repeat the password:", show="*", parent=root)
        if first != second:
            messagebox.showerror(APP_NAME, "The passwords did not match.")
            return False
        try:
            create_configuration(first)
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return False
        return True

    def update_status() -> None:
        status_text.set("Running at http://127.0.0.1:8000" if healthcheck() else "Stopped")
        startup_text.set("Enabled" if autostart_enabled() else "Disabled")

    def start_and_open() -> None:
        if not ensure_setup():
            return
        try:
            start_server()
            webbrowser.open(DASHBOARD_URL)
        except RuntimeError as exc:
            messagebox.showerror(APP_NAME, str(exc))
        update_status()

    def stop_clicked() -> None:
        messagebox.showinfo(APP_NAME, stop_server())
        update_status()

    def enable_startup() -> None:
        try:
            messagebox.showinfo(APP_NAME, install_autostart())
        except RuntimeError as exc:
            messagebox.showerror(APP_NAME, str(exc))
        update_status()

    def disable_startup() -> None:
        try:
            messagebox.showinfo(APP_NAME, uninstall_autostart())
        except RuntimeError as exc:
            messagebox.showerror(APP_NAME, str(exc))
        update_status()

    tk.Label(root, text=APP_NAME, font=("Segoe UI", 24, "bold")).pack(pady=(28, 4))
    tk.Label(root, text="Facebook Page alerts → Telegram", fg="#666666").pack()
    status_text = tk.StringVar()
    startup_text = tk.StringVar()
    summary = tk.Frame(root)
    summary.pack(fill="x", padx=50, pady=24)
    tk.Label(summary, text="Service:", anchor="w").grid(row=0, column=0, sticky="w")
    tk.Label(summary, textvariable=status_text, anchor="e").grid(row=0, column=1, sticky="e")
    tk.Label(summary, text="Start automatically:", anchor="w").grid(row=1, column=0, sticky="w", pady=(8, 0))
    tk.Label(summary, textvariable=startup_text, anchor="e").grid(row=1, column=1, sticky="e", pady=(8, 0))
    summary.columnconfigure(1, weight=1)

    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=50)
    tk.Button(buttons, text="Start / Open Dashboard", command=start_and_open, height=2).pack(fill="x")
    tk.Button(buttons, text="Stop", command=stop_clicked).pack(fill="x", pady=(8, 0))
    startup_buttons = tk.Frame(buttons)
    startup_buttons.pack(fill="x", pady=(8, 0))
    tk.Button(startup_buttons, text="Enable auto-start", command=enable_startup).pack(side="left", expand=True, fill="x")
    tk.Button(startup_buttons, text="Disable auto-start", command=disable_startup).pack(side="left", expand=True, fill="x", padx=(8, 0))
    tk.Button(buttons, text="Close launcher", command=root.destroy).pack(fill="x", pady=(8, 0))
    update_status()
    root.mainloop()
    return 0


def main() -> int:
    configure_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--install-autostart", action="store_true")
    parser.add_argument("--uninstall-autostart", action="store_true")
    args = parser.parse_args()

    if args.server:
        from dashboard import main as dashboard_main

        dashboard_main()
        return 0
    if args.install_autostart:
        print(install_autostart())
        return 0
    if args.uninstall_autostart:
        print(uninstall_autostart())
        return 0
    if args.stop:
        print(stop_server())
    if args.start:
        print(start_server())
    if args.open:
        webbrowser.open(DASHBOARD_URL)
    if any((args.start, args.stop, args.open)):
        return 0
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
