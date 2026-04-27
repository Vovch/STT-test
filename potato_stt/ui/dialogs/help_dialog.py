"""'Using Potato STT' help dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from potato_stt.i18n import tr


def using_help_text(*, ptt_phrase: str, has_tray: bool) -> str:
    """Plain-text body for the 'Using Potato STT' dialog."""
    lines = [
        tr(
            "Hold {ptt_phrase} to record. Release when you are done; the text is transcribed and pasted into the application that had keyboard focus when you pressed the key (and also appears in this window)."
        ).format(ptt_phrase=ptt_phrase),
        tr(
            "Use the Hold to Ask Web button (or optional shortcuts in Options) to record a web query; a small on-screen cue shows while recording and while OpenCode searches."
        ),
        "",
        tr("Use File → Transcribe media file… to transcribe an existing audio or video file."),
        tr(
            "Use Settings → Options… (Ctrl+,) to change push-to-talk keys, startup behavior, filters, audio/visual cues, web search, and optional translation."
        ),
    ]
    if has_tray:
        lines.extend(
            [
                "",
                tr("When a system tray icon is available:"),
                tr(
                    "• The window close button (X) hides this window to the tray without quitting; minimize uses the taskbar as usual."
                ),
                tr("• Double-click the tray icon to show the window again."),
                tr("• Use File → Quit (Ctrl+Q) or the tray menu Quit to exit completely."),
            ]
        )
    else:
        lines.extend(
            [
                "",
                tr("No system tray icon is available on this session; use File → Quit (Ctrl+Q) to exit."),
            ]
        )
    return "\n".join(lines)


def show_using_help_dialog(parent: QWidget, *, ptt_phrase: str, has_tray: bool) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Using Potato STT"))
    dlg.setModal(True)
    dlg.setMinimumWidth(520)
    body = QTextEdit()
    body.setReadOnly(True)
    body.setPlainText(using_help_text(ptt_phrase=ptt_phrase, has_tray=has_tray))
    body.setMinimumHeight(280)
    body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
    bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    bbox.accepted.connect(dlg.accept)
    root = QVBoxLayout(dlg)
    root.addWidget(body)
    root.addWidget(bbox)
    dlg.exec()
