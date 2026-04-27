"""File menu transcription pipeline (audio/video → transcript + SRT/VTT cues)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSettings

from potato_stt.config import Settings
from potato_stt.core.file_transcribe import transcribe_file_to_text_and_cues
from potato_stt.core.media_decode import FFmpegNotFoundError
from potato_stt.core.onnx_asr_engine import OnnxAsrEngine
from potato_stt.core.subtitle_export import cues_to_srt, cues_to_vtt
from potato_stt.core.transcript_utils import (
    apply_word_filter_after_normalize,
    filter_subtitle_cues,
)
from potato_stt.input.ptt_keys import specs_summary_phrase
from potato_stt.ui.signals import AppSignals


class FileTranscribeController:
    """Off-thread file transcription with subtitle export emission."""

    def __init__(
        self,
        *,
        qsettings: QSettings,
        settings: Settings,
        signals: AppSignals,
        onnx_engine_provider: Callable[[], Optional[OnnxAsrEngine]],
        ptt_specs_provider: Callable[[], list[str]],
        filter_phrases_provider: Callable[[], Optional[list[str]]],
    ) -> None:
        self._qsettings = qsettings
        self._settings = settings
        self._signals = signals
        self._onnx_engine_provider = onnx_engine_provider
        self._ptt_specs_provider = ptt_specs_provider
        self._filter_phrases_provider = filter_phrases_provider
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def start(self, source_path: Path) -> None:
        if self._busy:
            return
        self._busy = True
        signals = self._signals
        signals.statusChanged.emit(f"Transcribing file: {source_path.name} …")
        src_str = str(source_path.resolve())
        ptt_specs_snapshot = list(self._ptt_specs_provider())
        filter_phrases = self._filter_phrases_provider()
        onnx_engine = self._onnx_engine_provider()
        settings = self._settings

        def job() -> None:
            try:
                t0 = time.time()

                def _progress(part: str) -> None:
                    signals.statusChanged.emit(
                        f"Transcribing file: {source_path.name} — {part} …"
                    )

                cleaned, cues = transcribe_file_to_text_and_cues(
                    source_path,
                    chunk_seconds=settings.transcribe_chunk_seconds,
                    stt_backend=settings.stt_backend,
                    onnx_engine=onnx_engine,
                    stt_api_url=settings.stt_api_url,
                    stt_model=settings.stt_model,
                    stt_response_format=settings.stt_response_format,
                    stt_timeout_seconds=settings.stt_timeout_seconds,
                    on_progress=_progress,
                )
                fp = filter_phrases
                if fp:
                    cleaned = apply_word_filter_after_normalize(cleaned, fp)
                    cues = filter_subtitle_cues(list(cues), fp)
                took = time.time() - t0
                srt_body = cues_to_srt(cues) if cues else ""
                vtt_body = cues_to_vtt(cues) if cues else ""
                signals.fileTranscribeDone.emit(src_str, cleaned, srt_body, vtt_body)
                signals.statusChanged.emit(
                    f"File transcribed in {took:.1f}s. Transcript added (not pasted). Ready. Hold "
                    f"{specs_summary_phrase(ptt_specs_snapshot)} to talk."
                )
            except FFmpegNotFoundError as e:
                signals.errorOccurred.emit(
                    f"{type(e).__name__}: FFmpeg is not installed or not on PATH."
                )
                signals.ffmpegMissing.emit(str(e))
                signals.statusChanged.emit(
                    f"Ready. Hold {specs_summary_phrase(ptt_specs_snapshot)} to talk."
                )
            except Exception as e:
                signals.errorOccurred.emit(f"{type(e).__name__}: {e}")
                signals.statusChanged.emit(
                    f"Ready. Hold {specs_summary_phrase(ptt_specs_snapshot)} to talk."
                )
            finally:
                self._busy = False

        threading.Thread(target=job, daemon=True).start()
