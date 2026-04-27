"""Local Russian → English translation coordinator.

Encapsulates the consent dialog flow, optional pip install of the translation runtime, the
background Marian preload, and a `translate(text)` helper used by the transcription pipeline.
"""

from __future__ import annotations

import importlib
import sys
import threading
from typing import Callable

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from potato_stt.settings_keys import (
    TRANSLATE_RU_EN_ENABLED,
    TRANSLATION_MODEL_FETCH_APPROVED,
    TRANSLATION_MODEL_FETCH_APPROVED_DEFAULT,
)
from potato_stt.ui.dialogs.translation_consent import (
    show_local_translation_consent_warning,
)
from potato_stt.ui.signals import AppSignals


def _marian_module():
    """Lazy import of the Marian translation module (keeps optional startup cost low)."""
    return importlib.import_module("potato_stt.core.marian_ru_en")


def runtime_ready() -> bool:
    return _marian_module().is_translation_runtime_ready()


class TranslationCoordinator:
    """Wires the consent dialog → optional install → preload pipeline."""

    def __init__(
        self,
        *,
        parent: QWidget,
        qsettings: QSettings,
        signals: AppSignals,
        sync_options_checkbox: Callable[[], None],
        ptt_status_phrase: Callable[[], str],
    ) -> None:
        self._parent = parent
        self._qsettings = qsettings
        self._signals = signals
        self._sync_options_checkbox = sync_options_checkbox
        self._ptt_status_phrase = ptt_status_phrase

    # --- public API -----------------------------------------------------------

    def show_consent_warning(self) -> bool:
        return show_local_translation_consent_warning(self._parent)

    def continue_enable_after_consent(self) -> bool:
        """Install runtime if missing, then finish enable. Returns False if user cancels or setup fails."""
        if runtime_ready():
            self._finish_enabling()
            return True

        if getattr(sys, "frozen", False):
            QMessageBox.warning(
                self._parent,
                "Translation unavailable",
                "PyTorch or transformers could not be loaded from this installation. "
                "Try reinstalling Potato STT or run from source with `pip install -r requirements.txt` "
                "and a CPU PyTorch wheel.",
            )
            return False

        pip_ask = QMessageBox(self._parent)
        pip_ask.setIcon(QMessageBox.Icon.Question)
        pip_ask.setWindowTitle("Install translation packages?")
        pip_ask.setText(
            "PyTorch (CPU) and related packages are not installed in this Python environment.\n\n"
            "Install them now with pip? This needs internet access and may download several hundred MB "
            f"into the environment used by:\n{sys.executable}"
        )
        pip_ask.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        pip_ask.setDefaultButton(QMessageBox.StandardButton.No)
        if pip_ask.exec() != QMessageBox.StandardButton.Yes:
            return False

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            code, log = _marian_module().install_translation_runtime_packages()
        finally:
            QApplication.restoreOverrideCursor()

        if code != 0 or not runtime_ready():
            fail = QMessageBox(self._parent)
            fail.setIcon(QMessageBox.Icon.Warning)
            fail.setWindowTitle("Installation failed")
            fail.setText(
                "pip could not install the translation stack, or imports still fail after install. "
                "See details below."
            )
            fail.setDetailedText(log[:12000] if log else "(no log)")
            fail.exec()
            return False

        self._finish_enabling()
        return True

    def start_preload(self) -> None:
        """Background Hugging Face download + Marian load; finishes via `translationModelPreloadFinished`."""
        # Consent to fetch weights — must be True before load finishes so transcription can translate
        # while this download runs (second load path serializes on the Marian module lock).
        self._qsettings.setValue(TRANSLATION_MODEL_FETCH_APPROVED, True)

        signals = self._signals

        def run() -> None:
            ok = True
            err = ""
            try:
                m = _marian_module()

                def on_status(s: str) -> None:
                    signals.statusChanged.emit(s)

                m.preload_translation_model(on_status=on_status)
            except Exception as e:
                ok = False
                err = f"{type(e).__name__}: {e}"
            signals.translationModelPreloadFinished.emit(ok, err)

        threading.Thread(target=run, daemon=True).start()

    def on_preload_finished(self, ok: bool, err: str) -> None:
        if ok:
            self._signals.statusChanged.emit(
                f"Translation model ready. Hold {self._ptt_status_phrase()} to talk."
            )
            return
        QMessageBox.warning(
            self._parent,
            "Translation model",
            f"The translation model could not be downloaded or loaded:\n{err}\n\n"
            "Local translation stays enabled. In **Options**, turn the translation checkbox off and on "
            "again to retry the download, or speak again — the next run will retry loading the model.",
        )

    # Helpers used by the transcription worker thread (no Qt access here).

    @staticmethod
    def translate(
        text: str,
        *,
        on_status: Callable[[str], None],
        model_fetch_allowed: bool,
    ) -> str:
        return _marian_module().translate_ru_en(
            text,
            on_status=on_status,
            model_fetch_allowed=model_fetch_allowed,
        )

    def fetch_approved(self) -> bool:
        return bool(
            self._qsettings.value(
                TRANSLATION_MODEL_FETCH_APPROVED,
                TRANSLATION_MODEL_FETCH_APPROVED_DEFAULT,
                type=bool,
            )
        )

    def _finish_enabling(self) -> None:
        self._qsettings.setValue(TRANSLATE_RU_EN_ENABLED, True)
        self._sync_options_checkbox()
        self.start_preload()
