"""Shortcuts that start her window with no Command Prompt: on the desktop, and in
Windows' Startup folder so she starts when you log in."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICON_FILE = PROJECT_ROOT / "assistant.ico"


def windowless_python() -> Path:
    """pythonw.exe: the same Python, but without opening a console window."""
    python = Path(sys.executable)
    quiet = python.with_name("pythonw.exe")
    return quiet if quiet.exists() else python


def make_icon(path: Path = ICON_FILE) -> Path:
    """Save the orb as a Windows icon file."""
    from PySide6.QtWidgets import QApplication

    from .window import orb_icon

    app = QApplication.instance() or QApplication([])  # needed to draw
    if not orb_icon(256).save(str(path), "ICO"):
        raise RuntimeError(f"couldn't save the icon to {path}")
    del app
    return path


def _ps(text: str) -> str:
    """A PowerShell string in single quotes (a ' inside is written twice)."""
    return "'" + str(text).replace("'", "''") + "'"


def shortcut_script(name: str, target: Path, arguments: str, folder: Path, icon: Path,
                    place: str = "Desktop") -> str:
    """PowerShell that puts a shortcut in ``place`` ("Desktop" or "Startup")
    and prints where it went.

    The folder is looked up with GetFolderPath, so a desktop moved into
    OneDrive is found too.
    """
    return "; ".join([
        f"$folder = [Environment]::GetFolderPath({_ps(place)})",
        f"$path = Join-Path $folder {_ps(name + '.lnk')}",
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)",
        f"$s.TargetPath = {_ps(target)}",
        f"$s.Arguments = {_ps(arguments)}",
        f"$s.WorkingDirectory = {_ps(folder)}",
        f"$s.IconLocation = {_ps(icon)}",
        f"$s.Description = {_ps(name)}",
        "$s.Save()",
        "Write-Output $path",
    ])


def create_shortcut(name: str, place: str = "Desktop", arguments: str = "-m assistant") -> str:
    """Put a shortcut called ``name`` in ``place``; returns its path."""
    if sys.platform != "win32":
        raise RuntimeError("shortcuts are only made on Windows")
    icon = make_icon()
    script = shortcut_script(name, windowless_python(), arguments, PROJECT_ROOT, icon, place)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "PowerShell couldn't create the shortcut")
    return result.stdout.strip()


def create_desktop_shortcut(name: str) -> str:
    return create_shortcut(name, "Desktop")


# -- Starting with Windows ---------------------------------------------------
# A shortcut in the Startup folder starts her when you log in, hidden in the
# tray (--minimized), so the window doesn't pop up every time.
AUTOSTART_ARGUMENTS = "-m assistant --minimized"


def startup_folder() -> Path:
    """Windows' Startup folder for your user account."""
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def autostart_path(name: str) -> Path:
    return startup_folder() / f"{name}.lnk"


# Names her Startup shortcut had before she was called by her own name.
OLD_NAMES = ("Assistentin", "Assistant")


def autostart_enabled(name: str) -> bool:
    if sys.platform != "win32":
        return False
    return any(autostart_path(n).exists() for n in (name, *OLD_NAMES))


def set_autostart(name: str, enabled: bool) -> None:
    """Start her when you log in to Windows (or stop doing that)."""
    if enabled:
        create_shortcut(name, "Startup", AUTOSTART_ARGUMENTS)
    for old in (n for n in OLD_NAMES if n != name):  # a shortcut under an older name
        autostart_path(old).unlink(missing_ok=True)
    if not enabled:
        autostart_path(name).unlink(missing_ok=True)


def rename_autostart(name: str) -> None:
    """If she starts with Windows under an older name, give the shortcut her name."""
    new = autostart_path(name)
    for old in (autostart_path(n) for n in OLD_NAMES if n != name):
        if old.exists() and not new.exists():
            old.rename(new)
        elif old.exists():
            old.unlink()
