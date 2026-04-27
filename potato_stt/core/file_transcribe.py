from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional

from potato_stt.media_decode import (
    decode_to_temp_wav_16k_mono,
    extract_chunk_wav_16k_mono,
    probe_media_duration_seconds,
)
from potato_stt.onnx_asr_engine import OnnxAsrEngine
from potato_stt.stt_client import transcribe_wav_with_segments
from potato_stt.subtitle_export import (
    segments_even_split_to_cues,
    single_cue,
    tokens_to_cues,
)
from potato_stt.transcript_utils import normalize_phrase_spacing


def _clamp_chunk_seconds(raw: float) -> float:
    return max(30.0, min(float(raw), 600.0))


def _offset_cues(
    cues: list[tuple[float, float, str]],
    delta: float,
) -> list[tuple[float, float, str]]:
    return [(s + delta, e + delta, t) for s, e, t in cues]


def _transcribe_wav_onnx_chunk(
    engine: OnnxAsrEngine,
    wav_path: Path,
    chunk_dur: float,
) -> tuple[str, list[tuple[float, float, str]]]:
    tr = engine.transcribe_wav_timestamped(wav_path)
    raw = (tr.text or "").strip()
    tokens = tr.tokens or []
    timestamps = tr.timestamps or []
    td = max(chunk_dur, 0.04)
    cues = tokens_to_cues(tokens, timestamps, total_duration=td)
    if not cues and raw:
        cues = segments_even_split_to_cues(raw, total_duration=td)
    if not cues and raw:
        cues = single_cue(raw, total_duration=td)
    return raw, cues


def _transcribe_wav_http_chunk(
    wav_path: Path,
    *,
    api_url: str,
    model: Optional[str],
    response_format: Optional[str],
    timeout_seconds: int,
    chunk_dur: float,
) -> tuple[str, list[tuple[float, float, str]]]:
    text, api_cues = transcribe_wav_with_segments(
        wav_path,
        api_url=api_url,
        model=model,
        response_format=response_format,
        timeout_seconds=timeout_seconds,
    )
    raw = (text or "").strip()
    td = max(chunk_dur, 0.04)
    if api_cues:
        return raw, list(api_cues)
    cues: list[tuple[float, float, str]] = []
    if raw:
        cues = segments_even_split_to_cues(raw, total_duration=td)
    if not cues and raw:
        cues = single_cue(raw, total_duration=td)
    return raw, cues


def transcribe_file_to_text_and_cues(
    source_path: Path,
    *,
    chunk_seconds: float,
    stt_backend: str,
    onnx_engine: Optional[OnnxAsrEngine],
    stt_api_url: str,
    stt_model: Optional[str],
    stt_response_format: Optional[str],
    stt_timeout_seconds: int,
    on_progress: Optional[Callable[[str], None]] = None,
) -> tuple[str, list[tuple[float, float, str]]]:
    """
    Transcribe a media file with bounded memory: long inputs are split into temporal chunks.

    Returns (normalized_full_transcript, subtitle_cues_in_global_time).
    """
    source_path = Path(source_path).resolve()
    stride = _clamp_chunk_seconds(chunk_seconds)
    duration = probe_media_duration_seconds(source_path)

    def _one_wav(wav: Path, meas_dur: float) -> tuple[str, list[tuple[float, float, str]]]:
        if stt_backend.lower() == "onnx_asr":
            if onnx_engine is None:
                raise RuntimeError("ONNX ASR engine is not initialized.")
            return _transcribe_wav_onnx_chunk(onnx_engine, wav, meas_dur)
        return _transcribe_wav_http_chunk(
            wav,
            api_url=stt_api_url,
            model=stt_model,
            response_format=stt_response_format,
            timeout_seconds=stt_timeout_seconds,
            chunk_dur=meas_dur,
        )

    if duration <= stride + 1e-6:
        tmp, meas = decode_to_temp_wav_16k_mono(source_path)
        try:
            raw, cues = _one_wav(tmp, max(meas, 0.04))
            full = normalize_phrase_spacing(raw) if raw.strip() else ""
            if not cues and full.strip():
                cues = segments_even_split_to_cues(full, total_duration=max(meas, duration, 0.04))
            if not cues and full.strip():
                cues = single_cue(full, total_duration=max(meas, duration, 0.04))
            return full, cues
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    parts: list[str] = []
    all_cues: list[tuple[float, float, str]] = []
    start = 0.0
    part_idx = 0
    total_parts = max(1, int(math.ceil(duration / stride)))

    while start < duration - 1e-6:
        part_idx += 1
        piece_dur = min(stride, duration - start)
        if on_progress is not None:
            on_progress(f"part {part_idx}/{total_parts}")
        chunk_path, chunk_meas = extract_chunk_wav_16k_mono(
            source_path,
            start,
            piece_dur,
        )
        try:
            raw, chunk_cues = _one_wav(chunk_path, max(chunk_meas, piece_dur, 0.04))
            if raw.strip():
                parts.append(raw.strip())
            all_cues.extend(_offset_cues(chunk_cues, start))
        finally:
            try:
                chunk_path.unlink(missing_ok=True)
            except OSError:
                pass
        start += stride

    full = normalize_phrase_spacing(" ".join(parts))
    if not all_cues and full.strip():
        all_cues = segments_even_split_to_cues(full, total_duration=max(duration, 0.04))
    if not all_cues and full.strip():
        all_cues = single_cue(full, total_duration=max(duration, 0.04))
    return full, all_cues
