"""Confirmation/launch dialog for the Windows local-data cleanup script."""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from potato_stt.core.data_cleanup import clear_data_script_path
from potato_stt.i18n import tr


def show_clear_local_data_dialog(parent: QWidget) -> None:
    """Show 'Clear local data' UX. No-op on non-Windows; mirrors the original MainWindow body."""
    if sys.platform != "win32":
        return
    script = clear_data_script_path()
    if not script.is_file():
        QMessageBox.warning(
            parent,
            tr("Clear local data"),
            tr("Cleanup script not found:\n{script}\n\nFrom source, run scripts\\Clear-PotatoSTTData.ps1 from the repository root.").format(script=script),
        )
        return
    tip = (
        tr(
            "This removes the Parakeet install folder, Hugging Face ONNX model downloads, saved options (push-to-talk keys, etc.), and Windows startup Run entries for Potato STT / Pipit Clone.\n\nQuit Potato STT first; the script will try to stop PotatoSTT.exe if it is still running."
        )
    )
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(tr("Clear local data"))
    box.setText(tip)
    box.setInformativeText(tr("Script path:\n{script}").format(script=script))
    btn_open = box.addButton(tr("Open folder"), QMessageBox.ButtonRole.ActionRole)
    btn_run = box.addButton(tr("Run in PowerShell"), QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    clicked = box.clickedButton()
    if clicked == btn_open:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(script.parent.resolve())))
    elif clicked == btn_run:
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                cwd=str(script.parent.resolve()),
                creationflags=flags,
            )
        except OSError as e:
            QMessageBox.critical(
                parent,
                tr("Clear local data"),
                tr("Could not start PowerShell:\n{e}").format(e=e),
            )
