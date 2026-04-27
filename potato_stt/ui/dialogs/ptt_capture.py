"""Modal capture dialog for binding a single key/button or a keyboard chord."""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QEvent, QObject, Signal, Slot
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from potato_stt.input.ptt_capture import capture_ptt_binding
from potato_stt.i18n import tr


class _CaptureNotifier(QObject):
    """Marshals capture result to the UI thread."""

    finished = Signal(object)


class PttCaptureDialog(QDialog):
    """Modal capture: single key/button or keyboard chord; Cancel / Escape abort."""

    def __init__(self, parent: Optional[QWidget] = None, *, title: Optional[str] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or tr("Add push-to-talk key"))
        self.setModal(True)
        self._cancel = threading.Event()
        self._notifier = _CaptureNotifier(self)
        self._notifier.finished.connect(self._on_capture_finished)
        self._captured_spec = ""
        self._capture_started = False
        v = QVBoxLayout(self)
        v.addWidget(
            QLabel(
                tr(
                    "Press a keyboard key, click a mouse button, or hold modifiers then press a key.\nFor modifier-only chords, hold both modifiers (for example Ctrl+Shift) and release one.\nEscape cancels."
                )
            )
        )
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        bb.rejected.connect(self._on_cancel_clicked)
        v.addWidget(bb)

    def reject(self) -> None:
        self._cancel.set()
        super().reject()

    def closeEvent(self, event: QEvent) -> None:
        self._cancel.set()
        super().closeEvent(event)

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        if not self._capture_started:
            self._capture_started = True
            threading.Thread(target=self._run_capture, daemon=True).start()

    def _run_capture(self) -> None:
        spec = capture_ptt_binding(cancel_event=self._cancel, timeout_seconds=120.0)
        self._notifier.finished.emit(spec)

    @Slot()
    def _on_cancel_clicked(self) -> None:
        self._cancel.set()

    @Slot(object)
    def _on_capture_finished(self, spec: object) -> None:
        if isinstance(spec, str) and spec:
            self._captured_spec = spec
            self.accept()
        else:
            self.reject()

    def captured_spec(self) -> Optional[str]:
        return self._captured_spec or None
