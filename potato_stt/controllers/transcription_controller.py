"""Push-to-talk / web-search transcription pipeline.

Runs the off-thread job that turns recorded PCM into transcript text, optionally translates
it, and dispatches to either the paste path (PTT) or the web-search runner (web).
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import Callable, Optional

import numpy as np

from PySide6.QtCore import QSettings

from potato_stt.config import Settings
from potato_stt.core.audio_utils import write_wav_from_int16_pcm
from potato_stt.core.onnx_asr_engine import OnnxAsrEngine
from potato_stt.core.stt_client import transcribe_wav
from potato_stt.core.transcript_utils import postprocess_transcript_text
from potato_stt.controllers.recording_controller import RecordingController
from potato_stt.controllers.translation_coordinator import TranslationCoordinator
from potato_stt.controllers.web_search_coordinator import WebSearchCoordinator
from potato_stt.input.ptt_keys import specs_summary_phrase
from potato_stt.settings_keys import (
    TRANSLATE_RU_EN_ENABLED,
    TRANSLATE_RU_EN_ENABLED_DEFAULT,
)
from potato_stt.ui.signals import AppSignals


class TranscriptionController:
    """Bridges `RecordingController.snapshot_pcm()` to the STT + translate + dispatch pipeline."""

    def __init__(
        self,
        *,
        qsettings: QSettings,
        settings: Settings,
        signals: AppSignals,
        recording: RecordingController,
        translation: TranslationCoordinator,
        web_search: WebSearchCoordinator,
        onnx_engine_provider: Callable[[], Optional[OnnxAsrEngine]],
        ptt_specs_provider: Callable[[], list[str]],
        filter_phrases_provider: Callable[[], Optional[list[str]]],
    ) -> None:
        self._qsettings = qsettings
        self._settings = settings
        self._signals = signals
        self._recording = recording
        self._translation = translation
        self._web_search = web_search
        self._onnx_engine_provider = onnx_engine_provider
        self._ptt_specs_provider = ptt_specs_provider
        self._filter_phrases_provider = filter_phrases_provider

    def stop_and_transcribe(self, *, mode: str) -> None:
        if not self._recording.is_recording:
            return

        signals = self._signals

        if self._recording.mic_stt_busy:
            self._recording.stop()
            signals.webSearchOverlaySyncRequest.emit()
            signals.statusChanged.emit("Transcription busy; try again.")
            return

        self._recording.stop()
        blocks = self._recording.snapshot_pcm()
        if not blocks:
            signals.webSearchOverlaySyncRequest.emit()
            signals.statusChanged.emit("No audio captured.")
            return

        pcm = np.concatenate(blocks)
        sample_rate = self._recording.sample_rate
        if pcm.shape[0] < int(sample_rate * 0.35):
            signals.webSearchOverlaySyncRequest.emit()
            signals.statusChanged.emit(
                f"Too short; hold {specs_summary_phrase(self._ptt_specs_provider())} and speak more."
            )
            return

        signals.micSttBusy.emit(True)
        signals.statusChanged.emit("Transcribing...")
        filter_phrases = self._filter_phrases_provider()
        translate_enabled = bool(
            self._qsettings.value(
                TRANSLATE_RU_EN_ENABLED,
                TRANSLATE_RU_EN_ENABLED_DEFAULT,
                type=bool,
            )
        )
        translation_fetch_ok = self._translation.fetch_approved()

        threading.Thread(
            target=self._job,
            args=(pcm, sample_rate, mode, filter_phrases, translate_enabled, translation_fetch_ok),
            daemon=True,
        ).start()

    def _job(
        self,
        pcm_data: np.ndarray,
        sample_rate: int,
        capture_mode: str,
        filter_phrases: Optional[list[str]],
        translate_enabled: bool,
        translation_fetch_ok: bool,
    ) -> None:
        signals = self._signals
        if capture_mode == "web":
            signals.webSearchPipelineJobStarted.emit()
        try:
            with tempfile.TemporaryDirectory(prefix="potato-stt-audio-") as tmpdir:
                wav_path = os.path.join(tmpdir, f"talk_{int(time.time()*1000)}.wav")
                write_wav_from_int16_pcm(pcm_data, wav_path, sample_rate=sample_rate)

                t0 = time.time()
                if self._settings.stt_backend.lower() == "onnx_asr":
                    engine = self._onnx_engine_provider()
                    if engine is None:
                        raise RuntimeError("ONNX ASR engine is not initialized.")
                    text = engine.transcribe_wav(wav_path)
                else:
                    text = transcribe_wav(
                        wav_path,
                        api_url=self._settings.stt_api_url,
                        model=self._settings.stt_model,
                        response_format=self._settings.stt_response_format,
                        timeout_seconds=self._settings.stt_timeout_seconds,
                    )
                took = time.time() - t0
                cleaned = postprocess_transcript_text(text, filter_phrases=filter_phrases)
                if cleaned:
                    signals.transcriptAppend.emit(cleaned)
                    if capture_mode == "web":
                        signals.micSttBusy.emit(False)
                        signals.statusChanged.emit("Searching web…")
                        with self._web_search.semaphore:
                            summary = self._web_search.run_command(cleaned)
                        signals.webSearchReady.emit(cleaned, summary)
                        signals.statusChanged.emit(
                            f"Web summary ready in {took:.1f}s + search time. Ready. Hold "
                            f"{specs_summary_phrase(self._ptt_specs_provider())} to talk."
                        )
                    else:
                        to_paste = cleaned
                        if translate_enabled:
                            signals.statusChanged.emit("Translating to English…")

                            def _tr_status(msg: str) -> None:
                                signals.statusChanged.emit(msg)

                            to_paste = TranslationCoordinator.translate(
                                cleaned,
                                on_status=_tr_status,
                                model_fetch_allowed=translation_fetch_ok,
                            )
                            if to_paste.strip() != cleaned.strip():
                                signals.transcriptAppend.emit(f"{to_paste.strip()}")
                        signals.transcriptReady.emit(to_paste)
                        signals.statusChanged.emit(
                            f"Transcribed in {took:.1f}s. Ready. Hold "
                            f"{specs_summary_phrase(self._ptt_specs_provider())} to talk."
                        )
                else:
                    signals.webSearchOverlaySyncRequest.emit()
                    signals.statusChanged.emit("No speech recognized. Ready.")
        except Exception as e:
            signals.webSearchOverlaySyncRequest.emit()
            signals.errorOccurred.emit(f"{type(e).__name__}: {e}")
        finally:
            signals.micSttBusy.emit(False)
            if capture_mode == "web":
                signals.webSearchPipelineJobFinished.emit()
            self._recording.capture_mode = None
