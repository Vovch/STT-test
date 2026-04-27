"""Consent dialog shown before enabling local Russian → English translation."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from potato_stt.i18n import tr


def show_local_translation_consent_warning(parent: QWidget) -> bool:
    """Warning dialog with explicit Agree / Refuse (default Refuse). Returns True if user agrees."""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(tr("Local translation — notice"))
    msg.setText(
        tr(
            "Local Russian → English translation will:\n• Paste English into the app that had focus; this window lists the recognized text and the English wording (when it differs).\n• After you choose **Agree**, the Marian model (~300 MB from the internet) downloads in the background if it is not already on this PC (saved in your Hugging Face cache). Watch the main window status line for progress.\n• Run on your PC using PyTorch on the CPU.\n\nChoose **Agree** to enable translation and start the download when needed, or **Refuse** to cancel."
        )
    )
    refuse_btn = msg.addButton(tr("Refuse"), QMessageBox.ButtonRole.RejectRole)
    agree_btn = msg.addButton(tr("Agree"), QMessageBox.ButtonRole.AcceptRole)
    msg.setDefaultButton(refuse_btn)
    msg.exec()
    return msg.clickedButton() == agree_btn
