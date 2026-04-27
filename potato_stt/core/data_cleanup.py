"""Resolve path to the Windows PowerShell script that clears local caches and settings."""

from __future__ import annotations

import sys
from pathlib import Path

CLEAR_DATA_SCRIPT_NAME = "Clear-PotatoSTTData.ps1"


def clear_data_script_path() -> Path:
    """Frozen: next to PotatoSTT.exe. Dev: repository ``scripts/`` folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CLEAR_DATA_SCRIPT_NAME
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "scripts" / CLEAR_DATA_SCRIPT_NAME
