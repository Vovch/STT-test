"""Non-modal 'Web search summary' dialog (singleton factory)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from potato_stt.i18n import tr
from potato_stt.ui.markdown import web_search_dialog_markdown


class WebSummaryDialog:
    """Lazy non-modal singleton that displays Markdown-formatted web-search summaries.

    `MainWindow` previously inlined the QDialog construction and reused the same instance to
    avoid stacking dialogs; this class encapsulates that bookkeeping while keeping behavior
    identical (`hide()` on Ok, persistent dialog, raised/activated on each show).
    """

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._dlg: Optional[QDialog] = None
        self._body: Optional[QTextBrowser] = None

    def _ensure(self) -> None:
        if self._dlg is not None:
            return
        dlg = QDialog(self._parent)
        dlg.setWindowTitle(tr("Web search summary"))
        dlg.setModal(False)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        dlg.setMinimumWidth(680)
        dlg.setMinimumHeight(420)
        body = QTextBrowser()
        body.setReadOnly(True)
        body.setOpenExternalLinks(True)
        body.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bbox.accepted.connect(dlg.hide)
        root = QVBoxLayout(dlg)
        root.addWidget(body)
        root.addWidget(bbox)
        self._dlg = dlg
        self._body = body

    def show(self, *, query: str, summary: str) -> None:
        self._ensure()
        assert self._dlg is not None and self._body is not None
        self._dlg.setWindowTitle(tr("Web search summary"))
        self._body.setMarkdown(web_search_dialog_markdown(query, summary))
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
