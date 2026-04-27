from __future__ import annotations

import re
from typing import Sequence

# Rough Netflix-style line length; group shorter cues for readability.
_DEFAULT_MAX_CHARS = 42
_DEFAULT_MAX_SPAN_SEC = 7.0
_SENTENCE_END = re.compile(r"[.!?…]\s*$")
# Do not break a cue before this many extra characters while waiting for a word boundary.
_SOFT_CHAR_OVERFLOW = 22
# Force a break if we exceed max_chars by this much even mid-word (avoids runaway lines).
_HARD_CHAR_OVERFLOW = 36


def _continues_previous_word(buf: list[str], piece: str) -> bool:
    """
    Heuristic: ASR/BPE often splits one surface word across tokens (e.g. Hel+lo, or SentencePiece).
    """
    if not buf or not piece:
        return False
    prev_core = "".join(buf).rstrip()
    if not prev_core:
        return False
    last = prev_core[-1]
    if not (last.isalnum() or last in ("'", "\u2019")):
        return False
    if piece.startswith("▁") or piece.startswith(" "):
        return False
    stripped = piece.lstrip()
    if not stripped:
        return False
    return bool(stripped[0].isalnum())


def _safe_to_break_after_buf(buf: list[str]) -> bool:
    """True if the last token in buf likely ends a word (or whitespace / punctuation)."""
    if not buf:
        return True
    s = "".join(buf)
    if not s.strip():
        return True
    if len(s) > len(s.rstrip()):
        return True
    t = s.rstrip()
    last = t[-1]
    if last.isalnum() or last in ("'", "\u2019"):
        return False
    return True


def polish_cues_merge_short_fragments(
    cues: list[tuple[float, float, str]],
    *,
    max_orphan_words: int = 2,
    max_orphan_chars: int = 32,
) -> list[tuple[float, float, str]]:
    """
    Merge very short cues into neighbors so we avoid dangling one–two word lines.

    - Trailing short cues merge into the previous line (unless previous ends a sentence).
    - If the first cue is still a short fragment, merge it into the next.
    """
    if len(cues) <= 1:
        return cues

    def _ends_sentence(txt: str) -> bool:
        t = txt.rstrip()
        return bool(t) and t[-1] in ".!?…"

    out: list[tuple[float, float, str]] = []
    for start, end, text in cues:
        t = _sanitize_cue_text(text)
        if not t:
            continue
        wc = len(t.split())
        is_short = wc <= max_orphan_words and len(t) <= max_orphan_chars
        if is_short and out and not _ends_sentence(out[-1][2]):
            ps, _pe, pt = out[-1]
            out[-1] = (ps, end, _sanitize_cue_text(pt + " " + t))
        else:
            out.append((start, end, t))

    while len(out) >= 2:
        s0, e0, t0 = out[0]
        if len(t0.split()) <= max_orphan_words and len(t0) <= max_orphan_chars and not _ends_sentence(t0):
            s1, e1, t1 = out[1]
            out[0] = (s0, e1, _sanitize_cue_text(t0 + " " + t1))
            del out[1]
        else:
            break

    return out


def format_timestamp_srt(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    whole = int(secs)
    ms = int(round((secs - whole) * 1000))
    if ms >= 1000:
        whole += 1
        ms = 0
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{ms:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    whole = int(secs)
    ms = int(round((secs - whole) * 1000))
    if ms >= 1000:
        whole += 1
        ms = 0
    return f"{hours:02d}:{minutes:02d}:{whole:02d}.{ms:03d}"


def _sanitize_cue_text(text: str) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    return t.replace("\n", " ").replace("\r", "")


def tokens_to_cues(
    tokens: Sequence[str] | None,
    timestamps: Sequence[float] | None,
    *,
    total_duration: float,
    max_chars: int = _DEFAULT_MAX_CHARS,
    max_span_sec: float = _DEFAULT_MAX_SPAN_SEC,
) -> list[tuple[float, float, str]]:
    """
    Build (start_sec, end_sec, text) cues from ASR token timestamps.
    """
    if not tokens or not timestamps:
        return []

    n = min(len(tokens), len(timestamps))
    if n == 0:
        return []

    ts = [float(timestamps[i]) for i in range(n)]
    toks = [str(tokens[i]) for i in range(n)]

    spans: list[tuple[float, float, str]] = []
    td = max(0.0, float(total_duration))
    for i in range(n):
        t0 = ts[i]
        if i + 1 < n:
            t1 = ts[i + 1]
        else:
            t1 = min(t0 + 0.35, td if td > t0 else t0 + 0.35)
        if t1 <= t0:
            t1 = t0 + 0.04
        spans.append((t0, t1, toks[i]))

    cues: list[tuple[float, float, str]] = []
    buf: list[str] = []
    cue_start: float | None = None
    cue_end: float = 0.0
    soft_char_limit = max_chars + _SOFT_CHAR_OVERFLOW
    hard_char_limit = max_chars + _HARD_CHAR_OVERFLOW

    def flush() -> None:
        nonlocal buf, cue_start, cue_end
        if not buf or cue_start is None:
            buf = []
            cue_start = None
            return
        text = _sanitize_cue_text("".join(buf))
        if text:
            end = min(max(cue_end, cue_start + 0.04), td if td > cue_start else cue_end)
            if end <= cue_start:
                end = cue_start + 0.04
            cues.append((cue_start, end, text))
        buf = []
        cue_start = None

    for t0, t1, piece in spans:
        if cue_start is None:
            cue_start = t0
        piece_stripped = piece.strip()
        prospective = _sanitize_cue_text("".join(buf) + piece)
        span_width = t1 - (cue_start if cue_start is not None else t0)
        joined_buf = "".join(buf)
        force_sentence = bool(
            buf and _SENTENCE_END.search(joined_buf.rstrip()) and piece_stripped
        )
        over_soft_chars = len(prospective) >= soft_char_limit
        over_hard_chars = len(prospective) >= hard_char_limit
        over_span = span_width >= max_span_sec
        over_nominal_chars = len(prospective) >= max_chars
        continues = _continues_previous_word(buf, piece)

        should_break = False
        if buf and force_sentence:
            should_break = True
        elif buf and over_hard_chars:
            should_break = True
        elif buf and over_span:
            should_break = not continues
        elif buf and (over_nominal_chars or over_soft_chars):
            if continues:
                should_break = False
            elif _safe_to_break_after_buf(buf):
                should_break = True
            else:
                should_break = False

        if should_break:
            flush()
            cue_start = t0
        buf.append(piece)
        cue_end = t1

    flush()

    cues = polish_cues_merge_short_fragments(cues)

    if not cues and spans:
        full = _sanitize_cue_text("".join(toks))
        if full:
            t0, _, _ = spans[0]
            end = td if td > t0 else t0 + 1.0
            cues.append((t0, max(end, t0 + 0.2), full))

    return cues


def segments_even_split_to_cues(
    text: str,
    *,
    total_duration: float,
) -> list[tuple[float, float, str]]:
    """
    Split plain text into sentences and spread them evenly across total_duration.
    Used when the STT API does not return timings.
    """
    t = _sanitize_cue_text(text)
    if not t or total_duration <= 0:
        return []

    parts = re.split(r"(?<=[.!?…])\s+", t)
    parts = [p for p in parts if p.strip()]
    if not parts:
        parts = [t]

    n = len(parts)
    step = total_duration / n
    cues = []
    for i, p in enumerate(parts):
        start = i * step
        end = (i + 1) * step if i < n - 1 else total_duration
        if end <= start:
            end = start + 0.1
        cues.append((start, end, _sanitize_cue_text(p)))
    return cues


def single_cue(text: str, *, total_duration: float) -> list[tuple[float, float, str]]:
    t = _sanitize_cue_text(text)
    if not t:
        return []
    td = max(0.04, float(total_duration))
    return [(0.0, td, t)]


def cues_to_srt(cues: Sequence[tuple[float, float, str]]) -> str:
    lines: list[str] = []
    for i, (start, end, text) in enumerate(cues, start=1):
        if end <= start:
            end = start + 0.04
        lines.append(str(i))
        lines.append(f"{format_timestamp_srt(start)} --> {format_timestamp_srt(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + ("\n" if cues else "")


def cues_to_vtt(cues: Sequence[tuple[float, float, str]]) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for i, (start, end, text) in enumerate(cues, start=1):
        if end <= start:
            end = start + 0.04
        lines.append(str(i))
        lines.append(f"{format_timestamp_vtt(start)} --> {format_timestamp_vtt(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + ("\n" if cues else "")
