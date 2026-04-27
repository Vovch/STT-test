"""Recording / web-search pulse indicator widgets (timer-driven repaint)."""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class _PulseWidgetBase(QWidget):
    """Common pulse animation; subclasses define core / halo / ring colors."""

    _CORE: QColor
    _HALO: QColor
    _RING: QColor

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._on_timer_tick)

    def _on_timer_tick(self) -> None:
        self._phase += 0.055
        if self._phase >= 1.0:
            self._phase -= 1.0
        self.update()

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event: QEvent) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event: QEvent) -> None:
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx = self.width() * 0.5
        cy = self.height() * 0.5
        t = self._phase * 2.0 * math.pi
        pulse = 0.5 + 0.5 * math.sin(t)

        halo_r = 6.0 + pulse * 6.5
        halo_alpha = int(35 + pulse * 165)
        halo_col = QColor(self._HALO)
        halo_col.setAlpha(halo_alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo_col)
        p.drawEllipse(QRectF(cx - halo_r, cy - halo_r, 2.0 * halo_r, 2.0 * halo_r))

        ring_pulse = 0.5 + 0.5 * math.sin(t + 1.1)
        ring_r = 7.5 + ring_pulse * 5.0
        ring_col = QColor(self._RING)
        ring_col.setAlpha(int(70 + ring_pulse * 150))
        ring_pen = QPen(ring_col)
        ring_pen.setWidthF(2.0)
        p.setPen(ring_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - ring_r, cy - ring_r, 2.0 * ring_r, 2.0 * ring_r))

        core_r = 4.8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._CORE)
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, 2.0 * core_r, 2.0 * core_r))
        p.end()


class RecordingPulseWidget(_PulseWidgetBase):
    """Soft pulsing red indicator for active dictation recording."""

    _CORE = QColor("#ff3333")
    _HALO = QColor(255, 55, 55)
    _RING = QColor(255, 140, 140)


class WebSearchPulseWidget(_PulseWidgetBase):
    """Cyan pulse indicator while recording a web search query."""

    _CORE = QColor("#22d3ee")
    _HALO = QColor(34, 211, 238)
    _RING = QColor(125, 211, 252)
