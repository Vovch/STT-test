"""Microphone recording controller.

Owns the `sounddevice.InputStream`, raw PCM accumulation, and audio cue playback.
Exposes a small API used by `MainWindow` and `TranscriptionController`. No Qt UI here —
status/recording-active updates are emitted on the shared `AppSignals` bus.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from potato_stt.core.audio_utils import float_to_int16_pcm
from potato_stt.platform.recording_cues import (
    play_recording_started_cue,
    play_recording_stopped_cue,
)
from potato_stt.platform.win32_paste import get_foreground_hwnd
from potato_stt.ui.signals import AppSignals


class RecordingController:
    """Controls the audio stream and PCM buffer used by the talk/web pipeline."""

    def __init__(
        self,
        *,
        signals: AppSignals,
        sample_rate: int,
        channels: int,
        audio_cues_enabled: Callable[[], bool],
        ptt_status_phrase: Callable[[], str],
    ) -> None:
        self._signals = signals
        self._sample_rate = sample_rate
        self._channels = channels
        self._audio_cues_enabled = audio_cues_enabled
        self._ptt_status_phrase = ptt_status_phrase

        self._pcm_lock = threading.Lock()
        self._pcm_blocks: list[np.ndarray] = []
        self._stream = None
        self._recording = False
        self._capture_mode: Optional[str] = None
        self._paste_target_hwnd: Optional[int] = None
        self._mic_stt_busy = False

    # --- public state ---------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def capture_mode(self) -> Optional[str]:
        return self._capture_mode

    @capture_mode.setter
    def capture_mode(self, value: Optional[str]) -> None:
        self._capture_mode = value

    @property
    def paste_target_hwnd(self) -> Optional[int]:
        return self._paste_target_hwnd

    @property
    def mic_stt_busy(self) -> bool:
        return self._mic_stt_busy

    @mic_stt_busy.setter
    def mic_stt_busy(self, value: bool) -> None:
        self._mic_stt_busy = value

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    # --- lifecycle ------------------------------------------------------------

    def start(self, *, mode: str) -> None:
        """Begin audio capture. Mirrors the original `MainWindow._start_recording` semantics."""
        if self._recording or self._mic_stt_busy:
            return

        if mode == "ptt":
            try:
                self._paste_target_hwnd = get_foreground_hwnd()
            except Exception:
                self._paste_target_hwnd = None
        else:
            self._paste_target_hwnd = None

        self._pcm_blocks = []
        self._recording = True
        self._capture_mode = mode
        if mode == "web":
            self._signals.statusChanged.emit("Recording web query... release button to search.")
        else:
            self._signals.statusChanged.emit(
                f"Recording... (release {self._ptt_status_phrase()} to transcribe)"
            )

        def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
            if not self._recording:
                return
            if status:
                return
            pcm = float_to_int16_pcm(indata)
            with self._pcm_lock:
                self._pcm_blocks.append(pcm)

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            blocksize=1024,
            callback=callback,
        )
        if self._audio_cues_enabled():
            play_recording_started_cue()
        self._stream.start()
        if mode == "ptt":
            self._signals.recordingActive.emit(True)
        else:
            self._signals.webSearchOverlaySyncRequest.emit()

    def stop(self, *, play_stop_cue: bool = True) -> None:
        if not self._recording:
            return
        mode = self._capture_mode
        self._recording = False
        if mode == "ptt":
            self._signals.recordingActive.emit(False)

        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if play_stop_cue and self._audio_cues_enabled():
            play_recording_stopped_cue()

    def snapshot_pcm(self) -> list[np.ndarray]:
        """Atomically take ownership of the accumulated PCM blocks; resets the buffer."""
        with self._pcm_lock:
            blocks = self._pcm_blocks
            self._pcm_blocks = []
        return blocks
