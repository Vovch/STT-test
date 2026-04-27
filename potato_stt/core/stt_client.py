from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import requests


def _coerce_to_text(payload: Any) -> Optional[str]:
    """
    Try to normalize different STT service response formats into a plain text string.
    """
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return None

    # OpenAI-style: {"text": "..."}
    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    # Some wrappers: {"segments": [{"text": "..."}]}
    segments = payload.get("segments")
    if isinstance(segments, list):
        parts: list[str] = []
        for seg in segments:
            if isinstance(seg, dict):
                seg_text = seg.get("text")
                if isinstance(seg_text, str) and seg_text.strip():
                    parts.append(seg_text.strip())
        if parts:
            return " ".join(parts).strip()

    # Fallback: dump JSON for debugging.
    return None


def _extract_timed_cues(payload: Any) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    if not isinstance(payload, dict):
        return cues
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return cues
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        seg_text = seg.get("text")
        if not isinstance(seg_text, str) or not seg_text.strip():
            continue
        raw_start = seg.get("start", seg.get("from", seg.get("offset")))
        raw_end = seg.get("end", seg.get("to"))
        try:
            start = float(raw_start) if raw_start is not None else 0.0
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(raw_end) if raw_end is not None else start
        except (TypeError, ValueError):
            end = start
        if end <= start:
            end = start + 0.2
        cues.append((start, end, seg_text.strip()))
    return cues


def _post_transcription(
    wav_path: Path,
    *,
    api_url: str,
    model: Optional[str],
    response_format: Optional[str],
    timeout_seconds: int,
) -> Any:
    with wav_path.open("rb") as f:
        files = {"file": (wav_path.name, f, "audio/wav")}
        data: dict[str, str] = {}
        if model is not None:
            data["model"] = model
        if response_format is not None:
            data["response_format"] = response_format

        resp = requests.post(
            api_url,
            files=files,
            data=data,
            timeout=timeout_seconds,
        )

    resp.raise_for_status()

    try:
        return resp.json()
    except json.JSONDecodeError:
        return resp.text


def transcribe_wav(
    wav_path: str | Path,
    *,
    api_url: str,
    model: Optional[str] = None,
    response_format: Optional[str] = None,
    timeout_seconds: int = 120,
) -> str:
    wav_path = Path(wav_path)
    if not wav_path.exists():
        raise FileNotFoundError(str(wav_path))

    payload = _post_transcription(
        wav_path,
        api_url=api_url,
        model=model,
        response_format=response_format,
        timeout_seconds=timeout_seconds,
    )

    text = _coerce_to_text(payload)
    if text is not None:
        return text

    if isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False)
    if isinstance(payload, str):
        return payload.strip()

    return str(payload)


def transcribe_wav_with_segments(
    wav_path: str | Path,
    *,
    api_url: str,
    model: Optional[str] = None,
    response_format: Optional[str] = None,
    timeout_seconds: int = 120,
) -> tuple[str, list[tuple[float, float, str]]]:
    """
    Transcribe via HTTP and return (full_text, timed_cues).

    Tries verbose_json first for segment timestamps; falls back to the configured
    response_format (or json) if the server rejects verbose_json.
    """
    wav_path = Path(wav_path)
    if not wav_path.exists():
        raise FileNotFoundError(str(wav_path))

    payload: Any = None
    try:
        payload = _post_transcription(
            wav_path,
            api_url=api_url,
            model=model,
            response_format="verbose_json",
            timeout_seconds=timeout_seconds,
        )
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        if resp is not None and resp.status_code in (400, 422, 415):
            payload = _post_transcription(
                wav_path,
                api_url=api_url,
                model=model,
                response_format=response_format or "json",
                timeout_seconds=timeout_seconds,
            )
        else:
            raise

    cues = _extract_timed_cues(payload)
    text = _coerce_to_text(payload)
    if text is None:
        if isinstance(payload, dict):
            text = json.dumps(payload, ensure_ascii=False)
        elif isinstance(payload, str):
            text = payload.strip()
        else:
            text = str(payload)

    return text, cues
