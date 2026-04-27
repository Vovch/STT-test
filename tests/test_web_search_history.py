"""Tests for web search history helpers (plain excerpt + persistence)."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtCore import QSettings

from potato_stt.web_search_history import (
    HISTORY_SETTING_KEY,
    append_history_entry,
    count_unread_entries,
    load_history_entries,
    mark_history_entry,
    tray_message_body,
)


class WebSearchHistoryTests(unittest.TestCase):
    def test_tray_message_body_truncates(self) -> None:
        long_md = "## Title\n\n" + ("word " * 80)
        body = tray_message_body(long_md, max_chars=100)
        self.assertIn("click to read all", body)
        self.assertLessEqual(len(body), 100)

    def test_tray_message_body_default_respects_platform_budget(self) -> None:
        def utf16_units(s: str) -> int:
            return len(s.encode("utf-16-le")) // 2

        long_md = "## Title\n\n" + ("word " * 200)
        body = tray_message_body(long_md)
        if sys.platform == "win32":
            self.assertLessEqual(utf16_units(body), 248, msg=repr(body[:80]))
        else:
            self.assertLessEqual(len(body), 220)

    def test_append_and_load_roundtrip(self) -> None:
        s = QSettings("PotatoSTT_Test", "WebSearchHistoryTest")
        s.remove(HISTORY_SETTING_KEY)
        ts1 = append_history_entry(s, query="q1", summary_md="**a** summary", max_entries=10)
        ts2 = append_history_entry(s, query="q2", summary_md="second", max_entries=10)
        self.assertIsInstance(ts1, float)
        self.assertIsInstance(ts2, float)
        entries = load_history_entries(s)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["query"], "q1")
        self.assertEqual(entries[1]["query"], "q2")
        self.assertFalse(entries[0]["read"])
        self.assertFalse(entries[1]["read"])
        self.assertEqual(count_unread_entries(entries), 2)

        def _match_second(e: dict) -> bool:
            return float(e["ts"]) == ts2

        mark_history_entry(s, _match_second, read=True)
        entries2 = load_history_entries(s)
        self.assertFalse(entries2[0]["read"])
        self.assertTrue(entries2[1]["read"])
        self.assertIn("opened_ts", entries2[1])
        self.assertEqual(count_unread_entries(entries2), 1)
        s.remove(HISTORY_SETTING_KEY)


if __name__ == "__main__":
    unittest.main()
