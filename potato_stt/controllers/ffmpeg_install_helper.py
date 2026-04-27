"""Helper that kicks off `winget install ffmpeg` in a new console window on Windows."""

from __future__ import annotations

import sys

from PySide6.QtCore import QProcess

from potato_stt.core.media_decode import FFMPEG_WINGET_INSTALL_ARGV


def try_start_ffmpeg_winget_install() -> bool:
    """Windows: open a new console running winget to install FFmpeg (adds ffmpeg/ffprobe to PATH).

    Returns True if a detached process was started, False on non-Windows or launch failure.
    """
    if sys.platform != "win32":
        return False
    args = ["/c", "start", "", "winget", *FFMPEG_WINGET_INSTALL_ARGV]
    return QProcess.startDetached("cmd.exe", args)
