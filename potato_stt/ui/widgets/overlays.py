"""Always-on-top recording / web-search overlays."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from potato_stt.ui.widgets.pulse import RecordingPulseWidget, WebSearchPulseWidget


class RecordingOverlay(QWidget):
    """Small always-on-top marker; does not take focus or block mouse input."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # Frameless top-level windows often ignore root border stylesheets on Windows;
        # translucent outer + bordered inner QFrame paints reliably.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("RecordingOverlay")
        self.setStyleSheet("#RecordingOverlay { background: transparent; }")

        outer = QVBoxLayout(self)
        # Inset so the panel border is not clipped by the native window edge.
        outer.setContentsMargins(4, 4, 4, 4)

        panel = QFrame()
        panel.setObjectName("RecordingOverlayPanel")
        panel.setFrameShape(QFrame.Shape.NoFrame)
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(panel)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._pulse = RecordingPulseWidget(panel)
        label = QLabel("Recording")
        label.setStyleSheet("color: #f0f0f0; font-size: 14px; font-weight: bold;")
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._pulse, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

        panel.setStyleSheet(
            "#RecordingOverlayPanel { background-color: rgba(30, 30, 35, 230); "
            "border-radius: 8px; border: 2px solid #ffffff; }"
        )


class WebSearchOverlay(QWidget):
    """Always-on-top cue for hold-to-ask-web: recording label or loading spinner."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("WebSearchOverlay")
        self.setStyleSheet("#WebSearchOverlay { background: transparent; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)

        panel = QFrame()
        panel.setObjectName("WebSearchOverlayPanel")
        panel.setFrameShape(QFrame.Shape.NoFrame)
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(panel)

        root = QVBoxLayout(panel)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(6)

        row_rec = QHBoxLayout()
        row_rec.setSpacing(8)
        row_rec.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._pulse = WebSearchPulseWidget(panel)
        self._label_rec = QLabel("Web search")
        self._label_rec.setStyleSheet("color: #ecfeff; font-size: 14px; font-weight: bold;")
        self._label_rec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_rec.addWidget(self._pulse, 0, Qt.AlignmentFlag.AlignVCenter)
        row_rec.addWidget(self._label_rec, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(row_rec)

        self._load_row = QWidget(panel)
        load_lay = QVBoxLayout(self._load_row)
        load_lay.setContentsMargins(0, 0, 0, 0)
        load_lay.setSpacing(6)
        load_lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._label_load = QLabel("Searching web…")
        self._label_load.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_load.setStyleSheet("color: #cffafe; font-size: 13px; font-weight: bold;")
        self._spinner = QProgressBar(self._load_row)
        self._spinner.setRange(0, 0)
        self._spinner.setTextVisible(False)
        self._spinner.setFixedHeight(6)
        self._spinner.setStyleSheet(
            "QProgressBar { border: 0px; border-radius: 3px; background: rgba(255,255,255,40); }"
            "QProgressBar::chunk { background-color: #22d3ee; border-radius: 3px; }"
        )
        load_lay.addWidget(self._label_load)
        load_lay.addWidget(self._spinner)
        root.addWidget(self._load_row)
        self._load_row.hide()

        panel.setStyleSheet(
            "#WebSearchOverlayPanel { background-color: rgba(15, 23, 42, 230); "
            "border-radius: 8px; border: 2px solid #22d3ee; }"
        )

    def set_mode_recording(self) -> None:
        self._load_row.hide()
        self._pulse.show()
        self._label_rec.show()

    def set_mode_loading(self, active_jobs: int = 1) -> None:
        self._pulse.hide()
        self._label_rec.hide()
        if active_jobs > 1:
            self._label_load.setText(f"Searching web… ({active_jobs})")
        else:
            self._label_load.setText("Searching web…")
        self._load_row.show()
