"""Create a desktop shortcut that starts her window, with no Command Prompt."""

from __future__ import annotations

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


def shortcut_script(name: str, target: Path, arguments: str, folder: Path, icon: Path) -> str:
    """PowerShell that puts a shortcut on the desktop and prints where it went.

    The desktop is looked up with GetFolderPath, so a desktop moved into
    OneDrive is found too.
    """
    return "; ".join([
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        f"$path = Join-Path $desktop {_ps(name + '.lnk')}",
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)",
        f"$s.TargetPath = {_ps(target)}",
        f"$s.Arguments = {_ps(arguments)}",
        f"$s.WorkingDirectory = {_ps(folder)}",
        f"$s.IconLocation = {_ps(icon)}",
        f"$s.Description = {_ps(name)}",
        "$s.Save()",
        "Write-Output $path",
    ])


def create_desktop_shortcut(name: str) -> str:
    """Put a shortcut called ``name`` on the desktop; returns its path."""
    if sys.platform != "win32":
        raise RuntimeError("desktop shortcuts are only made on Windows")
    icon = make_icon()
    script = shortcut_script(name, windowless_python(), "-m assistant", PROJECT_ROOT, icon)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "PowerShell couldn't create the shortcut")
    return result.stdout.strip()
