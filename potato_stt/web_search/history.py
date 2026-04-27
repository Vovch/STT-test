"""Persisted web search history (query + Markdown summary) for Potato STT."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Callable

from PySide6.QtCore import QSettings

HISTORY_SETTING_KEY = "web_search/history_entries_v1"
MAX_ENTRIES_DEFAULT = 50

# Legacy default for callers/tests that pass no budget; Windows uses UTF-16 shell limit instead.
MAX_TRAY_BODY_CHARS_DEFAULT = 220

# Shell_NotifyIcon balloon: NOTIFYICONDATA.szInfo is 256 WCHARs including the null terminator.
_MAX_TRAY_BODY_UTF16_UNITS_WIN32 = 248
_MAX_TRAY_BODY_CHARS_NON_WIN32 = 220
_TRAY_TRUNC_SUFFIX = "\n… (click to read all)"

EntryMatcher = Callable[[dict[str, Any]], bool]


def _strip_markdown_to_plain(md: str) -> str:
    """Best-effort plain text for tray balloons (no full CommonMark parser)."""
    if not md:
        return ""
    t = md.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"`[^`]*`", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"[_]{1,2}([^_]+)[_]{1,2}", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    return t


def _utf16_code_units(s: str) -> int:
    """Length in UTF-16 code units (what NOTIFYICONDATA.szInfo counts on Windows)."""
    return len(s.encode("utf-16-le")) // 2


def _clip_plain_to_utf16(plain: str, max_units: int) -> str:
    """Clip to at most max_units UTF-16 code units without splitting Unicode codepoints."""
    if max_units < 1:
        return ""
    if _utf16_code_units(plain) <= max_units:
        return plain
    lo, hi = 0, len(plain)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _utf16_code_units(plain[:mid]) <= max_units:
            lo = mid
        else:
            hi = mid - 1
    return plain[:lo]


def tray_message_max_payload() -> tuple[int, bool]:
    """Return (body_budget, measure_utf16).

    On Windows the tray balloon body is capped by the shell (~255 UTF-16 code units); we stay
    slightly below. Else use a conservative character count (Qt/shell varies).

    Optional override: ``POTATO_STT_WEB_TRAY_BODY_MAX_CHARS`` (integer, clamped).
    """
    raw = os.environ.get("POTATO_STT_WEB_TRAY_BODY_MAX_CHARS", "").strip()
    if sys.platform == "win32":
        cap = _MAX_TRAY_BODY_UTF16_UNITS_WIN32
        default = cap
    else:
        cap = 512
        default = _MAX_TRAY_BODY_CHARS_NON_WIN32
    if raw:
        try:
            n = int(raw, 10)
        except ValueError:
            n = default
        n = max(80, min(n, cap))
    else:
        n = default
    return (n, sys.platform == "win32")


def tray_message_body(summary_md: str, *, max_chars: int | None = None) -> str:
    plain = _strip_markdown_to_plain(summary_md)
    if max_chars is not None:
        budget = max_chars
        use_utf16 = False
    else:
        budget, use_utf16 = tray_message_max_payload()

    def size(s: str) -> int:
        return _utf16_code_units(s) if use_utf16 else len(s)

    if size(plain) <= budget:
        return plain

    suffix = _TRAY_TRUNC_SUFFIX
    body_budget = budget - size(suffix)
    if body_budget < 48:
        suffix = "\n…"
        body_budget = budget - size(suffix)
    if body_budget < 1:
        return suffix.lstrip()

    if use_utf16:
        clipped = _clip_plain_to_utf16(plain, body_budget).rstrip()
    else:
        clipped = plain[:body_budget].rstrip()
    return clipped + suffix


def _normalize_read_flag(item: dict[str, Any]) -> bool:
    """Entries without 'read' are treated as already seen (older schema)."""
    r = item.get("read")
    if r is None:
        return True
    return bool(r)


def load_history_entries(qsettings: QSettings) -> list[dict[str, Any]]:
    raw = qsettings.value(HISTORY_SETTING_KEY, None)
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        q = item.get("query")
        s = item.get("summary_md")
        ts = item.get("ts")
        if isinstance(q, str) and isinstance(s, str) and isinstance(ts, (int, float)):
            row: dict[str, Any] = {"query": q, "summary_md": s, "ts": float(ts), "read": _normalize_read_flag(item)}
            opened = item.get("opened_ts")
            if isinstance(opened, (int, float)):
                row["opened_ts"] = float(opened)
            out.append(row)
    return out


def save_history_entries(qsettings: QSettings, entries: list[dict[str, Any]], *, max_entries: int) -> None:
    trimmed = entries[-max_entries:] if len(entries) > max_entries else entries
    qsettings.setValue(HISTORY_SETTING_KEY, json.dumps(trimmed, ensure_ascii=False))


def count_unread_entries(entries: list[dict[str, Any]]) -> int:
    return sum(1 for e in entries if not _normalize_read_flag(e))


def mark_history_entry(
    qsettings: QSettings,
    matcher: EntryMatcher,
    *,
    read: bool,
    max_entries: int = MAX_ENTRIES_DEFAULT,
) -> int:
    """Update first matching entry. Returns number of rows changed (0 or 1)."""
    cur = load_history_entries(qsettings)
    changed = 0
    now = time.time()
    for e in reversed(cur):
        if not matcher(e):
            continue
        want_read = bool(read)
        if bool(e.get("read", True)) == want_read:
            return 0
        e["read"] = want_read
        if want_read and e.get("opened_ts") is None:
            e["opened_ts"] = now
        if not want_read:
            e.pop("opened_ts", None)
        changed = 1
        break
    if changed:
        save_history_entries(qsettings, cur, max_entries=max_entries)
    return changed


def append_history_entry(
    qsettings: QSettings,
    *,
    query: str,
    summary_md: str,
    max_entries: int = MAX_ENTRIES_DEFAULT,
) -> float:
    cur = load_history_entries(qsettings)
    ts = time.time()
    cur.append({"query": query, "summary_md": summary_md, "ts": ts, "read": False})
    save_history_entries(qsettings, cur, max_entries=max_entries)
    return ts
