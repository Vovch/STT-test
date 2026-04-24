"""Push-to-talk recording start/stop cues (bundled WAV samples).

Samples are from Kenney's *Interface Sounds* pack (CC0). See ``assets/sounds/``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _sounds_dir() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "potato_stt" / "assets" / "sounds"
    return Path(__file__).resolve().parent / "assets" / "sounds"


def _play_cue(filename: str) -> None:
    path = _sounds_dir() / filename
    if not path.is_file():
        return
    if sys.platform != "win32":
        return
    import winsound

    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)


def play_recording_started_cue() -> None:
    _play_cue("recording_start.wav")


def play_recording_stopped_cue() -> None:
    _play_cue("recording_stop.wav")
