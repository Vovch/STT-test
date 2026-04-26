"""Persisted web search history (query + Markdown summary) for Potato STT."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from PySide6.QtCore import QSettings

HISTORY_SETTING_KEY = "web_search/history_entries_v1"
MAX_ENTRIES_DEFAULT = 50
MAX_TRAY_BODY_CHARS_DEFAULT = 220


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


def tray_message_body(summary_md: str, *, max_chars: int = MAX_TRAY_BODY_CHARS_DEFAULT) -> str:
    plain = _strip_markdown_to_plain(summary_md)
    if len(plain) <= max_chars:
        return plain
    return plain[: max_chars - 24].rstrip() + "\n… (click to read all)"


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
            out.append({"query": q, "summary_md": s, "ts": float(ts)})
    return out


def save_history_entries(qsettings: QSettings, entries: list[dict[str, Any]], *, max_entries: int) -> None:
    trimmed = entries[-max_entries:] if len(entries) > max_entries else entries
    qsettings.setValue(HISTORY_SETTING_KEY, json.dumps(trimmed, ensure_ascii=False))


def append_history_entry(
    qsettings: QSettings,
    *,
    query: str,
    summary_md: str,
    max_entries: int = MAX_ENTRIES_DEFAULT,
) -> None:
    cur = load_history_entries(qsettings)
    cur.append({"query": query, "summary_md": summary_md, "ts": time.time()})
    save_history_entries(qsettings, cur, max_entries=max_entries)
