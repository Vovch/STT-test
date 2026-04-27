"""Pure mapping from human-readable status messages to a progress-bar state.

Lives outside `MainWindow._on_status_update` so it is unit-testable without Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProgressState:
    """How a QProgressBar should display a given status message."""

    range_min: int
    range_max: int
    value: Optional[int]
    fmt: str


_FAILED = ProgressState(0, 1, 0, "Failed")
_READY = ProgressState(0, 1, 1, "Ready")


def format_status_to_progress(msg: str) -> ProgressState:
    """Map status text to a `ProgressState`. Mirror of the original if/elif ladder."""
    lower = msg.lower()
    if lower.startswith("error:") or " exited " in lower or "failed" in lower:
        return _FAILED
    if "downloading..." in lower and "%" in msg:
        pct = _try_parse_percent(msg)
        if pct is not None:
            return ProgressState(0, 100, pct, f"Downloading from internet — {pct}%")
    if "model download" in lower and "%" in msg:
        pct = _try_parse_percent(msg)
        if pct is not None:
            return ProgressState(0, 100, pct, f"Downloading model from internet — {pct}%")
    if (
        "waiting for parakeet service to finish model download" in lower
        or "downloading parakeet windows package" in lower
        or "package url failed, downloading" in lower
    ):
        return ProgressState(0, 0, None, "Downloading from internet...")
    if "preparing parakeet http stt engine" in lower:
        return ProgressState(0, 0, None, "Preparing STT (may download from internet)...")
    if "extracting package" in lower:
        return ProgressState(0, 0, None, "Extracting downloaded package...")
    if "installing fallback dependencies" in lower:
        return ProgressState(0, 0, None, "Installing dependencies (downloading from internet)...")
    if "loading onnx asr model" in lower:
        return ProgressState(0, 0, None, "Loading model...")
    if "preparing onnx asr engine" in lower:
        return ProgressState(0, 0, None, "Preparing ONNX model...")
    if "marian" in lower and "hugging face" in lower:
        return ProgressState(0, 0, None, "Downloading translation model...")
    if "ready." in lower or "file transcribed" in lower:
        return _READY
    if "transcribing" in lower:
        return ProgressState(0, 0, None, "Transcribing...")
    return ProgressState(0, 0, None, "Working...")


def _try_parse_percent(msg: str) -> Optional[int]:
    pct_str = msg.split("%", 1)[0].split()[-1]
    try:
        return max(0, min(100, int(float(pct_str))))
    except (ValueError, IndexError):
        return None
