from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np
import onnx_asr
import onnxruntime as ort

from potato_stt.audio_utils import write_wav_from_int16_pcm

if TYPE_CHECKING:
    from onnx_asr.asr import TimestampedResult

# DirectML / GPU path often surfaces as HRESULT 0x8007000E (E_OUTOFMEMORY) in the message.
_GPU_OOM_HINTS = (
    "not enough memory",
    "out of memory",
    "8007000e",
    "e_outofmemory",
    "resource exhausted",
    "failed to allocate",
)


def _looks_like_gpu_oom(exc: BaseException) -> bool:
    return any(h in f"{type(exc).__name__}: {exc}".lower() for h in _GPU_OOM_HINTS)


class OnnxAsrEngine:
    def __init__(self, *, model_name: str, providers: list[str]) -> None:
        self._model_name = model_name
        self._providers = providers
        self._lock = threading.Lock()
        self._model = None

    def _is_cpu_only_providers(self) -> bool:
        return self._providers == ["CPUExecutionProvider"]

    def _try_fallback_to_cpu_after_oom(self) -> bool:
        """Drop the loaded session and pin CPU-only providers for the next load."""
        with self._lock:
            if self._is_cpu_only_providers():
                return False
            self._model = None
            self._providers = ["CPUExecutionProvider"]
            return True

    @staticmethod
    def _probe_inference(model: object) -> None:
        """Run a tiny forward pass so DirectML OOM fails during startup, not on first real clip."""
        silence = np.zeros(4000, dtype=np.int16)
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="potato-stt-onnx-probe-")
        try:
            os.close(fd)
            p = Path(path)
            write_wav_from_int16_pcm(silence, p, sample_rate=16000)
            model.recognize(str(p))
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    def _ensure_model(self, on_status: Optional[Callable[[str], None]] = None):
        with self._lock:
            if self._model is not None:
                return self._model

            last_error: Optional[BaseException] = None
            for attempt in range(2):
                available = ort.get_available_providers()
                preferred = [p for p in self._providers if p in available]
                if not preferred:
                    preferred = ["CPUExecutionProvider"]
                self._providers = preferred

                if on_status is not None:
                    on_status(
                        f"Loading ONNX ASR model '{self._model_name}' "
                        f"(providers={','.join(self._providers)})..."
                    )
                try:
                    self._model = onnx_asr.load_model(
                        self._model_name,
                        providers=self._providers,
                    )
                    self._probe_inference(self._model)
                except Exception as e:
                    last_error = e
                    self._model = None
                    if (
                        attempt == 0
                        and _looks_like_gpu_oom(e)
                        and not self._is_cpu_only_providers()
                    ):
                        if on_status is not None:
                            on_status(
                                "DirectML/GPU ran out of memory for ONNX ASR; "
                                "switching to CPU (slower). "
                                "Set POTATO_STT_CPU_ONLY=1 to start on CPU and skip this step."
                            )
                        self._providers = ["CPUExecutionProvider"]
                        continue
                    raise

                if on_status is not None:
                    on_status(f"ONNX ASR ready ({self._providers[0]}).")
                return self._model

            assert last_error is not None
            raise last_error

    def warmup(self, on_status: Optional[Callable[[str], None]] = None) -> None:
        self._ensure_model(on_status=on_status)

    def transcribe_wav(self, wav_path: str | Path) -> str:
        try:
            model = self._ensure_model()
            text = model.recognize(str(wav_path))
        except Exception as e:
            if not _looks_like_gpu_oom(e) or not self._try_fallback_to_cpu_after_oom():
                raise
            model = self._ensure_model()
            text = model.recognize(str(wav_path))
        if isinstance(text, str):
            return text.strip()
        return str(text).strip()

    def transcribe_wav_timestamped(self, wav_path: str | Path) -> "TimestampedResult":
        try:
            model = self._ensure_model()
            return model.with_timestamps().recognize(str(wav_path))
        except Exception as e:
            if not _looks_like_gpu_oom(e) or not self._try_fallback_to_cpu_after_oom():
                raise
            model = self._ensure_model()
            return model.with_timestamps().recognize(str(wav_path))

