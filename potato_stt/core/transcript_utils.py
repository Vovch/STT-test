from __future__ import annotations

import re
from typing import Sequence

# ONNX ASR / SentencePiece often maps out-of-vocabulary Cyrillic "ё" to <unk>.
_UNK_TOKEN = re.compile(r"<unk>", re.IGNORECASE)


def repair_asr_unk_tokens(text: str) -> str:
    """
    Replace tokenizer <unk> placeholders with "ё" when the line contains Cyrillic.
    The Parakeet vocabulary commonly omits ё, so the model emits <unk> instead.
    """
    if not text or not re.search(r"[а-яёА-ЯЁ]", text):
        return text
    return _UNK_TOKEN.sub("ё", text)


def finalize_sentence_for_clipboard(text: str) -> str:
    """
    Trim outer whitespace, then ensure a space after final . ! ? so paste does not
    drop that space (plain strip() would remove it).
    """
    t = text.strip()
    if not t:
        return t
    if t[-1] in ".!?":
        return t + " "
    return t


def normalize_phrase_spacing(text: str) -> str:
    """
    Insert spaces between phrases when the model omits them after punctuation
    (e.g. 'Hello.How are you' -> 'Hello. How are you').

    Also ends the string with a space when it ends in . ! ? so after paste the
    caret can continue typing without the next word sticking to the period.
    """
    t = repair_asr_unk_tokens(text)
    t = t.strip()
    if not t:
        return t

    # . ! ? immediately before an opening quote (e.g. He said."Yes" -> ... said. "Yes")
    t = re.sub(r'([.!?])(["\'\u201c\u2018])', r"\1 \2", t)

    def _after_sentence_end(m: re.Match[str]) -> str:
        punct, nxt = m.group(1), m.group(2)
        if nxt.isalpha():
            return f"{punct} {nxt}"
        return m.group(0)

    # . ! ? followed immediately by a letter
    t = re.sub(r"([.!?])([^\s.!?])", _after_sentence_end, t)

    def _after_comma_semi(m: re.Match[str]) -> str:
        punct, nxt = m.group(1), m.group(2)
        if nxt.isalpha():
            return f"{punct} {nxt}"
        return m.group(0)

    # , ; before a word (avoid touching decimals like 1,234)
    t = re.sub(r"([,;])([^\s,;])", _after_comma_semi, t)

    t = re.sub(r" +", " ", t)
    return finalize_sentence_for_clipboard(t)


def parse_filter_phrases(raw: str) -> list[str]:
    """
    Parse user-edited filter list: one phrase per line; commas split extra entries on a line.
    Lines starting with # are ignored.
    """
    out: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            for part in line.split(","):
                p = part.strip()
                if p:
                    out.append(p)
        else:
            out.append(line)
    return out


def _filter_phrase_pattern(phrase: str) -> re.Pattern[str] | None:
    phrase = phrase.strip()
    if not phrase:
        return None
    parts = phrase.split()
    escaped = [re.escape(p) for p in parts]
    if len(parts) == 1:
        pat = r"(?<!\w)" + escaped[0] + r"(?!\w)"
    else:
        pat = r"(?<!\w)" + r"\s+".join(escaped) + r"(?!\w)"
    return re.compile(pat, re.IGNORECASE)


def apply_word_filter(text: str, phrases: Sequence[str]) -> str:
    """
    Remove whole-word (or whole-phrase) matches; case-insensitive. Longer phrases run first.
    """
    if not text or not phrases:
        return text.strip() if text else text
    uniq = {p.strip() for p in phrases if p.strip()}
    if not uniq:
        return text.strip() if text else text
    ordered = sorted(uniq, key=len, reverse=True)
    t = text
    for p in ordered:
        pat = _filter_phrase_pattern(p)
        if pat is None:
            continue
        t = pat.sub(" ", t)
    t = re.sub(r" +", " ", t).strip()
    return t


def apply_word_filter_after_normalize(text: str, phrases: Sequence[str]) -> str:
    """Apply :func:`apply_word_filter` then restore clipboard-style sentence ending spacing."""
    t = apply_word_filter(text, phrases)
    return finalize_sentence_for_clipboard(t)


def postprocess_transcript_text(raw: str, *, filter_phrases: Sequence[str] | None) -> str:
    """Normalize ASR output, then optionally strip configured filler words/phrases."""
    t = normalize_phrase_spacing(raw)
    if filter_phrases:
        t = apply_word_filter_after_normalize(t, filter_phrases)
    return t


def filter_subtitle_cues(
    cues: list[tuple[float, float, str]],
    phrases: Sequence[str],
) -> list[tuple[float, float, str]]:
    """Apply the same word filter to each cue; drop cues that become empty."""
    out: list[tuple[float, float, str]] = []
    for start, end, line in cues:
        filtered = apply_word_filter(line, phrases)
        if filtered:
            out.append((start, end, filtered))
    return out
