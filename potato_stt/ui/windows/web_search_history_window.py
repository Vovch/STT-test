"""Browse past web search queries and Markdown summaries."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtGui import QBrush, QColor, QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
    QWidget,
)

from potato_stt.i18n import tr
from potato_stt.ui.markdown import web_search_dialog_markdown
from potato_stt.web_search.history import (
    load_history_entries,
    mark_history_entry,
)


class WebSearchHistoryWindow(QWidget):
    """Browse past web search queries and Markdown summaries."""

    def __init__(
        self,
        qsettings: QSettings,
        parent: Optional[QWidget] = None,
        *,
        on_history_mutated: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = qsettings
        self._on_history_mutated = on_history_mutated
        self.setWindowTitle(tr("Web search history"))
        self.setMinimumSize(720, 480)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)

        split = QHBoxLayout(self)
        self._list = QListWidget()
        self._list.setMinimumWidth(220)
        self._browser = QTextBrowser()
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(True)
        self._browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        split.addWidget(self._list, 0)
        split.addWidget(self._browser, 1)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._reload_list(select_first=True)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._reload_list(preserve_ts=self._selected_ts())

    def refresh_from_settings(self, *, preserve_ts: Optional[float] = None) -> None:
        self._reload_list(preserve_ts=preserve_ts if preserve_ts is not None else self._selected_ts())

    def focus_last_unread(self) -> None:
        self._reload_list(focus_last_unread=True)

    def _selected_ts(self) -> Optional[float]:
        row = self._list.currentRow()
        if row < 0:
            return None
        item = self._list.item(row)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return None
        ts = data.get("ts")
        return float(ts) if isinstance(ts, (int, float)) else None

    def _reload_list(
        self,
        *,
        select_first: bool = False,
        preserve_ts: Optional[float] = None,
        focus_last_unread: bool = False,
    ) -> None:
        prev_ts = preserve_ts
        self._list.blockSignals(True)
        self._list.clear()
        entries = load_history_entries(self._settings)
        for e in reversed(entries):
            ts = float(e.get("ts", 0))
            q = str(e.get("query", ""))[:80]
            tstr = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            read = bool(e.get("read", True))
            label = ("● " if not read else "   ") + f"{tstr} — {q}"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, e)
            tip = (
                tr("Unread — open to mark as read.")
                if not read
                else tr("Opened before (read).")
            )
            it.setToolTip(tip)
            if not read:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setForeground(QBrush(QColor("#fbbf24")))
            else:
                it.setForeground(QBrush(QColor("#94a3b8")))
            self._list.addItem(it)
        self._list.blockSignals(False)

        target_row = -1
        if focus_last_unread:
            for row in range(self._list.count()):
                item = self._list.item(row)
                if item is None:
                    continue
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and not bool(data.get("read", True)):
                    target_row = row
                    break
        elif prev_ts is not None:
            for row in range(self._list.count()):
                item = self._list.item(row)
                if item is None:
                    continue
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, dict) and float(data.get("ts", 0)) == float(prev_ts):
                    target_row = row
                    break

        if target_row >= 0:
            self._list.setCurrentRow(target_row)
        elif select_first and self._list.count() > 0:
            self._list.setCurrentRow(0)
        elif self._list.count() > 0 and prev_ts is None and not focus_last_unread:
            self._list.setCurrentRow(0)
        else:
            self._list.setCurrentRow(-1)
            self._browser.clear()

    def _mark_row_read(self, data: dict[str, Any]) -> None:
        ts = data.get("ts")
        if not isinstance(ts, (int, float)):
            return
        ts_f = float(ts)

        def _match(e: dict[str, Any]) -> bool:
            ets = e.get("ts")
            return isinstance(ets, (int, float)) and float(ets) == ts_f

        if mark_history_entry(self._settings, _match, read=True) > 0 and self._on_history_mutated is not None:
            self._on_history_mutated()
        read_now = True
        data["read"] = read_now
        data.setdefault("opened_ts", time.time())
        row = self._list.currentRow()
        if row >= 0:
            item = self._list.item(row)
            if item is not None:
                cur = item.data(Qt.ItemDataRole.UserRole)
                cur_ts = cur.get("ts") if isinstance(cur, dict) else None
                if isinstance(cur_ts, (int, float)) and cur_ts == ts_f:
                    ts_disp = float(data.get("ts", 0))
                    q = str(data.get("query", ""))[:80]
                    tstr = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts_disp))
                    item.setText("   " + f"{tstr} — {q}")
                    item.setToolTip(tr("Opened before (read)."))
                    f = item.font()
                    f.setBold(False)
                    item.setFont(f)
                    item.setForeground(QBrush(QColor("#94a3b8")))
                    item.setData(Qt.ItemDataRole.UserRole, data)

    @Slot(int)
    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            self._browser.clear()
            return
        item = self._list.item(row)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        if not bool(data.get("read", True)):
            self._mark_row_read(data)
        q = str(data.get("query", ""))
        s = str(data.get("summary_md", ""))
        self._browser.setMarkdown(web_search_dialog_markdown(q, s))
