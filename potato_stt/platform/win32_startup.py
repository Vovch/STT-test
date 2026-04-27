"""
Windows: register or remove a CurrentVersion\\Run value so the app can start at user login.
"""
from __future__ import annotations

import os
import sys

_REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "PotatoSTT"


def build_launch_command() -> str:
    """Command line written to the Run registry value (quoted paths)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    if sys.platform == "win32":
        bindir = os.path.dirname(exe)
        pythonw = os.path.join(bindir, "pythonw.exe")
        if os.path.isfile(pythonw):
            exe = pythonw
    return f'"{exe}" -m potato_stt'


def is_run_at_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_SUBKEY, 0, winreg.KEY_READ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            except FileNotFoundError:
                return False
    except OSError:
        return False
    return value.strip() == build_launch_command().strip()


def set_run_at_startup_enabled(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_SUBKEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, build_launch_command())
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
