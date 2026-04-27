"""FFmpeg-missing notice dialog with a copy-friendly winget command."""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from potato_stt.core.media_decode import (
    FFMPEG_DOWNLOAD_URL,
    FFMPEG_MISSING_CONTEXT_AFTER_CLI,
    FFMPEG_MISSING_CONTEXT_BEFORE_CLI,
    FFMPEG_WINGET_INSTALL_CLI,
)
from potato_stt.i18n import tr


def show_ffmpeg_missing_dialog(
    parent: QWidget,
    *,
    try_start_winget_install: Optional[callable] = None,
) -> None:
    """FFmpeg notice with copy-able winget command. Optional installer kicker for Windows."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("FFmpeg required"))
    dlg.setMinimumWidth(520)
    style = dlg.style()
    assert style is not None
    icon_lbl = QLabel()
    icon_lbl.setPixmap(
        style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(48, 48)
    )
    summary = QLabel(
        tr(
            "FFmpeg is not installed or not on PATH. It is needed for most audio and video file formats."
        )
    )
    summary.setWordWrap(True)
    f_sum = QFont(summary.font())
    f_sum.setBold(True)
    summary.setFont(f_sum)

    before = QLabel(FFMPEG_MISSING_CONTEXT_BEFORE_CLI)
    before.setWordWrap(True)

    cmd_caption = QLabel(tr("Command (select and copy):"))
    f_cap = QFont(cmd_caption.font())
    f_cap.setBold(True)
    cmd_caption.setFont(f_cap)

    cmd_edit = QPlainTextEdit(FFMPEG_WINGET_INSTALL_CLI)
    cmd_edit.setReadOnly(True)
    cmd_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    cmd_edit.setTabChangesFocus(True)
    cmd_font = QFont()
    cmd_font.setStyleHint(QFont.StyleHint.Monospace)
    cmd_font.setBold(True)
    if cmd_font.pointSize() > 0:
        cmd_font.setPointSize(cmd_font.pointSize() + 1)
    cmd_edit.setFont(cmd_font)
    lh = cmd_edit.fontMetrics().height()
    cmd_edit.setFixedHeight(min(160, max(lh * 3, lh + 24)))
    cmd_edit.setStyleSheet(
        "QPlainTextEdit { background-color: palette(alternate-base); "
        "border: 1px solid palette(mid); border-radius: 4px; padding: 6px; }"
    )

    after = QLabel(FFMPEG_MISSING_CONTEXT_AFTER_CLI)
    after.setWordWrap(True)

    text_col = QVBoxLayout()
    text_col.addWidget(summary)
    text_col.addWidget(before)
    text_col.addWidget(cmd_caption)
    text_col.addWidget(cmd_edit)
    text_col.addWidget(after)

    top_row = QHBoxLayout()
    top_row.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)
    top_row.addLayout(text_col, 1)

    bbox = QDialogButtonBox()
    install_btn = None
    if sys.platform == "win32":
        install_btn = bbox.addButton(
            tr("Install FFmpeg with winget…"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
    open_btn = bbox.addButton(
        tr("Open FFmpeg download page..."),
        QDialogButtonBox.ButtonRole.ActionRole,
    )
    bbox.addButton(QDialogButtonBox.StandardButton.Ok)

    root = QVBoxLayout(dlg)
    root.addLayout(top_row)
    root.addWidget(bbox)

    # Avoid 0/1: QDialog.Rejected/Accepted would collide with our branches.
    _DONE_INSTALL = 100
    _DONE_OPEN = 101
    _DONE_OK = 102

    if install_btn is not None:
        install_btn.clicked.connect(lambda: dlg.done(_DONE_INSTALL))
    open_btn.clicked.connect(lambda: dlg.done(_DONE_OPEN))
    ok_btn = bbox.button(QDialogButtonBox.StandardButton.Ok)
    assert ok_btn is not None
    ok_btn.clicked.connect(lambda: dlg.done(_DONE_OK))

    def _focus_cmd() -> None:
        cmd_edit.setFocus()
        cmd_edit.selectAll()

    QTimer.singleShot(0, _focus_cmd)

    code = dlg.exec()
    if code == _DONE_INSTALL and install_btn is not None:
        started = bool(try_start_winget_install()) if try_start_winget_install else False
        if started:
            QMessageBox.information(
                parent,
                tr("FFmpeg install"),
                tr(
                    "A command window should open to install FFmpeg via winget.\n\nWhen it finishes successfully, restart Potato STT (or sign out of Windows) so ffmpeg and ffprobe are picked up from PATH."
                ),
            )
        else:
            QMessageBox.warning(
                parent,
                tr("FFmpeg install"),
                tr(
                    "Could not start winget. Install FFmpeg manually from the download page, or run in a terminal:\n\n{cmd}"
                ).format(cmd=FFMPEG_WINGET_INSTALL_CLI),
            )
    elif code == _DONE_OPEN:
        QDesktopServices.openUrl(QUrl(FFMPEG_DOWNLOAD_URL))
