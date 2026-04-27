from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def float_to_int16_pcm(audio_float: np.ndarray) -> np.ndarray:
    """
    Convert float audio in [-1, 1] to int16 PCM.
    Expect shape: (frames,) or (frames, channels).
    """
    if audio_float.dtype.kind != "f":
        audio_float = audio_float.astype(np.float32, copy=False)

    pcm = np.clip(audio_float, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    if pcm.ndim == 2:
        # Use first channel (mono).
        pcm = pcm[:, 0]
    return pcm


def write_wav_from_int16_pcm(
    pcm_int16: np.ndarray,
    wav_path: str | Path,
    *,
    sample_rate: int,
) -> None:
    pcm_int16 = np.asarray(pcm_int16, dtype=np.int16)
    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_int16.tobytes())

