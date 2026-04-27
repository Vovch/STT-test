"""App icon rendered in code (no image files)."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def build_app_icon() -> QIcon:
    """Raster icon for window + tray: microphone on a rounded tile."""
    icon = QIcon()
    bg = QColor("#4f46e5")
    edge = QColor("#312e81")
    mic = QColor("#f8fafc")

    def _render(size: int) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        margin = max(1, round(size * 0.0625))
        inner = float(size - 2 * margin)
        rr = max(2.0, inner * 0.2)
        p.setBrush(bg)
        p.setPen(QPen(edge, max(1.0, size / 32.0)))
        p.drawRoundedRect(
            float(margin),
            float(margin),
            inner,
            inner,
            rr,
            rr,
        )

        cx = size * 0.5
        head_r = inner * (0.19 if size >= 20 else 0.21)
        head_cy = margin + inner * 0.29

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mic)
        p.drawEllipse(QRectF(cx - head_r, head_cy - head_r, 2.0 * head_r, 2.0 * head_r))

        body_w = max(3.0, inner * 0.24)
        body_h = max(4.0, inner * 0.30)
        body_top = head_cy + head_r * 0.55
        p.drawRoundedRect(
            QRectF(cx - body_w / 2.0, body_top, body_w, body_h),
            body_w * 0.42,
            body_w * 0.42,
        )

        stem_w = max(1.5, inner * 0.08)
        stem_h = max(2.0, inner * 0.11)
        stem_top = body_top + body_h
        p.drawRoundedRect(QRectF(cx - stem_w / 2.0, stem_top, stem_w, stem_h), 1.0, 1.0)

        stem_bottom = stem_top + stem_h
        arm = inner * 0.19
        lw = max(1.2, size * 0.085)
        p.setBrush(Qt.BrushStyle.NoBrush)
        mic_pen = QPen(mic)
        mic_pen.setWidthF(lw)
        mic_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        mic_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(mic_pen)
        p.drawLine(QLineF(cx, stem_bottom, cx - arm, stem_bottom + arm * 0.95))
        p.drawLine(QLineF(cx, stem_bottom, cx + arm, stem_bottom + arm * 0.95))

        if size >= 48:
            cy = margin + inner * 0.52
            wave_col = QColor(248, 250, 252)
            wave_col.setAlpha(140)
            wave_pen = QPen(wave_col)
            wave_pen.setWidthF(max(1.0, size / 48.0))
            wave_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(wave_pen)
            wx0 = cx + head_r + inner * 0.06
            for i, h in enumerate((inner * 0.07, inner * 0.11, inner * 0.08)):
                x = wx0 + i * inner * 0.065
                p.drawLine(QLineF(x, cy - h / 2.0, x, cy + h / 2.0))

        p.end()
        return pm

    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render(s))
    return icon
