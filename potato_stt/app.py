"""Potato STT process entry point.

Owns the application bootstrap: single-instance lock, default font normalization, top-level
icon/window construction, and the Qt event loop. The actual `MainWindow` class lives in
`potato_stt.ui.windows.main_window`.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QSettings, QSharedMemory, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from potato_stt.platform.win32_paste import set_windows_app_user_model_id
from potato_stt.i18n import init_localization, tr
from potato_stt.settings_keys import START_MINIMIZED_SETTING
from potato_stt.ui.icon import build_app_icon
from potato_stt.ui.windows.main_window import MainWindow


# Held for the process lifetime so the single-instance shared segment stays mapped.
_single_instance_memory: QSharedMemory | None = None


def _acquire_single_instance() -> bool:
    """Return True if this process should run; False if another instance is already active."""
    global _single_instance_memory
    mem = QSharedMemory("PotatoSTT_SingleInstance")
    if mem.attach():
        mem.detach()
        return False
    if not mem.create(1):
        return False
    _single_instance_memory = mem
    return True


def _normalize_application_font(app: QApplication) -> None:
    """Windows high-DPI defaults sometimes leave QFont.pointSize() at -1; Qt then warns if
    something calls setPointSize with that value. Force a positive point size.
    """
    f = QFont(app.font())
    if f.pointSize() > 0:
        return
    px = f.pixelSize()
    if px > 0:
        f.setPointSize(max(1, int(round(px * 72.0 / 96.0))))
    else:
        f.setPointSize(9)
    app.setFont(f)


def main() -> None:
    if sys.platform == "win32":
        set_windows_app_user_model_id()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication([])
    init_localization(QSettings("PotatoSTT", "PotatoSTT"))
    if not _acquire_single_instance():
        QMessageBox.warning(
            None,
            tr("Potato STT"),
            tr("Another instance of Potato STT is already running."),
        )
        raise SystemExit(0)
    _normalize_application_font(app)
    app_icon = build_app_icon()
    app.setWindowIcon(app_icon)
    w = MainWindow(app_icon=app_icon)
    start_minimized = bool(
        w._qsettings.value(START_MINIMIZED_SETTING, False, type=bool)
    )
    if start_minimized:
        if not w.has_system_tray():
            w.showMinimized()
        # else: tray is already shown in MainWindow.__init__; main window stays hidden
    else:
        w.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
