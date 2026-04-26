from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
from PySide6.QtCore import (
    QEvent,
    QObject,
    QLineF,
    QProcess,
    QRectF,
    QSettings,
    QSharedMemory,
    Qt,
    QUrl,
    Signal,
    Slot,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from pynput import keyboard, mouse

from potato_stt.audio_utils import float_to_int16_pcm, write_wav_from_int16_pcm
from potato_stt.config import Settings
from potato_stt.data_cleanup import clear_data_script_path
from potato_stt.file_transcribe import transcribe_file_to_text_and_cues
from potato_stt.media_decode import (
    FFMPEG_DOWNLOAD_URL,
    FFMPEG_MISSING_CONTEXT_AFTER_CLI,
    FFMPEG_MISSING_CONTEXT_BEFORE_CLI,
    FFMPEG_WINGET_INSTALL_ARGV,
    FFMPEG_WINGET_INSTALL_CLI,
    FFmpegNotFoundError,
)
from potato_stt.onnx_asr_engine import OnnxAsrEngine
from potato_stt.parakeet_windows_installer import ensure_parakeet_service
from potato_stt.recording_cues import play_recording_started_cue, play_recording_stopped_cue
from potato_stt.stt_client import transcribe_wav
from potato_stt.subtitle_export import cues_to_srt, cues_to_vtt
from potato_stt.web_search_history import (
    append_history_entry,
    load_history_entries,
    tray_message_body,
)
from potato_stt.transcript_utils import (
    apply_word_filter_after_normalize,
    filter_subtitle_cues,
    finalize_sentence_for_clipboard,
    parse_filter_phrases,
    postprocess_transcript_text,
)
from potato_stt.win32_paste import (
    get_foreground_hwnd,
    is_window,
    send_ctrl_v_keybd_event,
    set_foreground_hwnd,
    set_windows_app_user_model_id,
)
from potato_stt.ptt_capture import capture_ptt_binding
from potato_stt.ptt_keys import (
    DEFAULT_PTT_SPECS,
    chord_required_modifiers,
    event_matches_any_spec_mouse,
    is_chord_spec,
    keyboard_token_for_event,
    keyboard_modifier_for_event,
    load_ptt_specs,
    load_web_search_specs,
    matching_keyboard_specs,
    mouse_token_for_button,
    needs_keyboard_listener,
    needs_mouse_listener,
    save_ptt_specs,
    save_web_search_specs,
    spec_label,
    specs_summary_phrase,
)
from potato_stt.win32_startup import (
    is_run_at_startup_enabled,
    set_run_at_startup_enabled,
)

# QSettings keys (same org/app as push-to-talk keys).
START_MINIMIZED_SETTING = "ui/start_minimized"
AUDIO_CUES_ENABLED = "ui/audio_cues_enabled"
VISUAL_CUES_ENABLED = "ui/visual_cues_enabled"
TRANSCRIPT_FILTER_ENABLED = "ui/transcript_filter_enabled"
TRANSCRIPT_FILTER_WORDS = "ui/transcript_filter_words"
TRANSLATE_RU_EN_ENABLED = "ui/translate_ru_en_enabled"
TRANSLATION_MODEL_FETCH_APPROVED = "ui/translation_model_fetch_approved"
WEB_SEARCH_ENABLED = "web_search/enabled"
WEB_DOUBLE_TAP_ENABLED = "web_search/double_tap_enabled"
# First-run defaults (used when keys are absent; existing QSettings win once saved).
AUDIO_CUES_ENABLED_DEFAULT = True
VISUAL_CUES_ENABLED_DEFAULT = True
TRANSCRIPT_FILTER_ENABLED_DEFAULT = True
TRANSCRIPT_FILTER_WORDS_DEFAULT = "uh\num"
TRANSLATE_RU_EN_ENABLED_DEFAULT = False
TRANSLATION_MODEL_FETCH_APPROVED_DEFAULT = False
WEB_SEARCH_ENABLED_DEFAULT = True
WEB_DOUBLE_TAP_ENABLED_DEFAULT = False

# Max concurrent OpenCode subprocesses for web search (STT still one-at-a-time per mic).
WEB_OPENCODE_MAX_CONCURRENT = 2
DOUBLE_TAP_WINDOW_SECONDS = 0.45
DOUBLE_TAP_HOLD_THRESHOLD_SECONDS = 0.24


def _markdown_fence(text: str) -> str:
    """Wrap text in a Markdown fenced code block, lengthening the fence if the text contains ```."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    fence = "```"
    while fence in t:
        fence += "`"
    return f"{fence}\n{t}\n{fence}"


def _web_search_dialog_markdown(query: str, summary: str) -> str:
    """Build Markdown for the web-search result dialog (summary may contain Markdown from the model)."""
    q = query.strip()
    s = (summary or "").replace("\r\n", "\n").replace("\r", "\n")
    return "## Query\n\n" + _markdown_fence(q) + "\n\n---\n\n## Summary\n\n" + s


def _translation_marian_module():
    """Lazy import of the Marian translation module (keeps optional startup cost low)."""
    import importlib

    return importlib.import_module("potato_stt.marian_ru_en")


def _tr_runtime_ready() -> bool:
    return _translation_marian_module().is_translation_runtime_ready()


def _try_start_ffmpeg_winget_install() -> bool:
    """Windows: open a new console running winget to install FFmpeg (adds ffmpeg/ffprobe to PATH).

    Returns True if a detached process was started, False on non-Windows or launch failure.
    """
    if sys.platform != "win32":
        return False
    # `start "" …` — quoted empty title so `winget` is treated as the command, not the title.
    args = ["/c", "start", "", "winget", *FFMPEG_WINGET_INSTALL_ARGV]
    return QProcess.startDetached("cmd.exe", args)


def build_app_icon() -> QIcon:
    """Raster icon for window + tray: microphone on a rounded tile (drawn in code, no image files)."""
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


class _CaptureNotifier(QObject):
    """Marshals capture result to the UI thread."""

    finished = Signal(object)


class PttCaptureDialog(QDialog):
    """Modal capture: single key/button or keyboard chord; Cancel / Escape abort."""

    def __init__(self, parent: Optional[QWidget] = None, *, title: Optional[str] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or "Add push-to-talk key")
        self.setModal(True)
        self._cancel = threading.Event()
        self._notifier = _CaptureNotifier(self)
        self._notifier.finished.connect(self._on_capture_finished)
        self._captured_spec = ""
        self._capture_started = False
        v = QVBoxLayout(self)
        v.addWidget(
            QLabel(
                "Press a keyboard key, click a mouse button, or hold modifiers then press a key.\n"
                "For modifier-only chords, hold both modifiers (for example Ctrl+Shift) and release one.\n"
                "Escape cancels."
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


class OptionsWindow(QWidget):
    """Separate top-level window for app settings."""

    def __init__(self, main_window: QWidget, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._main = main_window
        self._settings = QSettings("PotatoSTT", "PotatoSTT")
        self._really_close = False
        self.setWindowTitle("Options")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        if sys.platform == "win32":
            self._startup_cb = QCheckBox("Launch Potato STT at Windows startup")
            self._startup_cb.setChecked(is_run_at_startup_enabled())
            self._startup_cb.toggled.connect(self._on_startup_toggled)
            layout.addWidget(self._startup_cb)
        else:
            _hint = QLabel("Launch at startup is only available on Windows.")
            _hint.setWordWrap(True)
            layout.addWidget(_hint)

        self._start_min_cb = QCheckBox("Start minimized")
        self._start_min_cb.setChecked(
            bool(self._settings.value(START_MINIMIZED_SETTING, False, type=bool))
        )
        self._start_min_cb.setToolTip(
            "When a system tray icon is available, the main window stays hidden until you open it from the tray. "
            "Otherwise the window opens minimized to the taskbar."
        )
        self._start_min_cb.toggled.connect(self._on_start_minimized_toggled)
        layout.addWidget(self._start_min_cb)

        self._audio_cues_cb = QCheckBox("Play start/stop audio cues")
        self._audio_cues_cb.setChecked(
            bool(
                self._settings.value(
                    AUDIO_CUES_ENABLED,
                    AUDIO_CUES_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._audio_cues_cb.setToolTip("Play a short sound when microphone recording starts and stops.")
        self._audio_cues_cb.toggled.connect(self._on_audio_cues_toggled)
        layout.addWidget(self._audio_cues_cb)

        self._visual_cues_cb = QCheckBox("Show recording and web-search visual cues")
        self._visual_cues_cb.setChecked(
            bool(
                self._settings.value(
                    VISUAL_CUES_ENABLED,
                    VISUAL_CUES_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._visual_cues_cb.setToolTip("Show the small on-screen overlays while recording or searching.")
        self._visual_cues_cb.toggled.connect(self._on_visual_cues_toggled)
        layout.addWidget(self._visual_cues_cb)

        layout.addWidget(QLabel("Push-to-talk keys (hold any of these):"))
        self._ptt_list = QListWidget()
        self._ptt_list.setMinimumHeight(120)
        layout.addWidget(self._ptt_list)
        _btn_row = QHBoxLayout()
        self._add_ptt_btn = QPushButton("Add key…")
        self._add_ptt_btn.clicked.connect(self._on_add_ptt_clicked)
        self._remove_ptt_btn = QPushButton("Remove selected")
        self._remove_ptt_btn.clicked.connect(self._on_remove_ptt_clicked)
        _btn_row.addWidget(self._add_ptt_btn)
        _btn_row.addWidget(self._remove_ptt_btn)
        _btn_row.addStretch(1)
        layout.addLayout(_btn_row)
        _ptt_help = QLabel(
            "Recording continues while at least one bound key or button is held. "
            "If you remove every key, Right Ctrl is used again."
        )
        _ptt_help.setWordWrap(True)
        _ptt_help.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(_ptt_help)

        self._web_search_enabled_cb = QCheckBox("Enable web search")
        self._web_search_enabled_cb.setChecked(
            bool(
                self._settings.value(
                    WEB_SEARCH_ENABLED,
                    WEB_SEARCH_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._web_search_enabled_cb.setToolTip(
            "Controls Hold to Ask Web, web-search hotkeys, and double-tap web search."
        )
        self._web_search_enabled_cb.toggled.connect(self._on_web_search_enabled_toggled)
        layout.addWidget(self._web_search_enabled_cb)

        layout.addWidget(QLabel("Hold to Ask Web — shortcut keys (hold any of these):"))
        self._web_search_list = QListWidget()
        self._web_search_list.setMinimumHeight(100)
        layout.addWidget(self._web_search_list)
        _ws_btn_row = QHBoxLayout()
        self._add_web_search_btn = QPushButton("Add key…")
        self._add_web_search_btn.clicked.connect(self._on_add_web_search_clicked)
        self._remove_web_search_btn = QPushButton("Remove selected")
        self._remove_web_search_btn.clicked.connect(self._on_remove_web_search_clicked)
        _ws_btn_row.addWidget(self._add_web_search_btn)
        _ws_btn_row.addWidget(self._remove_web_search_btn)
        _ws_btn_row.addStretch(1)
        layout.addLayout(_ws_btn_row)
        _ws_help = QLabel(
            "Hold a bound key or mouse button to record a web query (same as the main-window button). "
            "Release to transcribe and run OpenCode. If the list is empty, only the button works. "
            "If a key is also a push-to-talk key, push-to-talk takes priority."
        )
        _ws_help.setWordWrap(True)
        _ws_help.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(_ws_help)

        self._web_double_tap_cb = QCheckBox("Double-tap a push-to-talk key/button for web search")
        self._web_double_tap_cb.setChecked(
            bool(
                self._settings.value(
                    WEB_DOUBLE_TAP_ENABLED,
                    WEB_DOUBLE_TAP_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._web_double_tap_cb.setToolTip(
            "When enabled, a normal hold records push-to-talk. "
            "Tap once, then press-and-hold the same key/button to record a web query."
        )
        self._web_double_tap_cb.toggled.connect(self._on_web_double_tap_toggled)
        layout.addWidget(self._web_double_tap_cb)

        self._sync_web_search_controls_enabled()

        self._filter_cb = QCheckBox("Remove filler words and phrases from transcripts")
        self._filter_cb.setChecked(
            bool(
                self._settings.value(
                    TRANSCRIPT_FILTER_ENABLED,
                    TRANSCRIPT_FILTER_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._filter_cb.setToolTip(
            "Case-insensitive whole-word or whole-phrase removal after normalization. "
            "Affects push-to-talk, file transcription, and subtitle export."
        )
        self._filter_cb.toggled.connect(self._on_transcript_filter_enabled_toggled)
        layout.addWidget(self._filter_cb)

        layout.addWidget(QLabel("Words/phrases to strip (one per line or comma-separated):"))
        self._filter_words = QPlainTextEdit()
        self._filter_words.setPlaceholderText("um\nyou know")
        self._filter_words.setMinimumHeight(80)
        self._filter_words.setPlainText(
            str(
                self._settings.value(TRANSCRIPT_FILTER_WORDS, TRANSCRIPT_FILTER_WORDS_DEFAULT)
                or ""
            )
        )
        self._filter_words.textChanged.connect(self._on_transcript_filter_words_changed)
        layout.addWidget(self._filter_words)
        _filter_help = QLabel(
            "Lines starting with # are ignored. Longer phrases are removed before shorter ones."
        )
        _filter_help.setWordWrap(True)
        _filter_help.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(_filter_help)

        self._translate_ru_en_cb = QCheckBox(
            "Translate push-to-talk transcripts to English (Russian → English, local model)"
        )
        self._translate_ru_en_cb.setChecked(
            bool(
                self._settings.value(
                    TRANSLATE_RU_EN_ENABLED,
                    TRANSLATE_RU_EN_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._translate_ru_en_cb.setToolTip(
            "After each utterance, paste English into the target app. This window shows the recognition "
            "and an English line when the translation differs. After you agree in the notice dialog, "
            "the Marian model (~300 MB) downloads from Hugging Face in the background if it is not "
            "already on this PC. Uses PyTorch on the CPU."
        )
        self._translate_ru_en_cb.toggled.connect(self._on_translate_ru_en_toggled)
        layout.addWidget(self._translate_ru_en_cb)

        layout.addStretch(1)
        self._populate_ptt_list()
        self._populate_web_search_list()

    def closeEvent(self, event: QEvent) -> None:
        if self._really_close:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def close_for_shutdown(self) -> None:
        self._really_close = True
        self.close()

    def _populate_ptt_list(self) -> None:
        self._ptt_list.clear()
        for spec in load_ptt_specs(self._settings):
            it = QListWidgetItem(spec_label(spec))
            it.setData(Qt.ItemDataRole.UserRole, spec)
            self._ptt_list.addItem(it)

    def _populate_web_search_list(self) -> None:
        self._web_search_list.clear()
        for spec in load_web_search_specs(self._settings):
            it = QListWidgetItem(spec_label(spec))
            it.setData(Qt.ItemDataRole.UserRole, spec)
            self._web_search_list.addItem(it)

    def _sync_web_search_controls_enabled(self) -> None:
        enabled = bool(
            self._settings.value(
                WEB_SEARCH_ENABLED,
                WEB_SEARCH_ENABLED_DEFAULT,
                type=bool,
            )
        )
        for w in (
            self._web_search_list,
            self._add_web_search_btn,
            self._remove_web_search_btn,
            self._web_double_tap_cb,
        ):
            w.setEnabled(enabled)

    def _save_web_search_list_from_ui(self) -> None:
        specs: list[str] = []
        for i in range(self._web_search_list.count()):
            item = self._web_search_list.item(i)
            d = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(d, str):
                specs.append(d)
        save_web_search_specs(self._settings, specs)
        fn = getattr(self._main, "_on_web_search_key_setting_changed", None)
        if fn is not None:
            fn()
        self._populate_web_search_list()

    def _save_ptt_list_from_ui(self) -> None:
        specs: list[str] = []
        for i in range(self._ptt_list.count()):
            item = self._ptt_list.item(i)
            d = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(d, str):
                specs.append(d)
        if not specs:
            specs = list(DEFAULT_PTT_SPECS)
        save_ptt_specs(self._settings, specs)
        fn = getattr(self._main, "_on_ptt_key_setting_changed", None)
        if fn is not None:
            fn()
        self._populate_ptt_list()

    @Slot()
    def _on_add_web_search_clicked(self) -> None:
        dlg = PttCaptureDialog(self, title="Add hold-to-ask-web key")
        dlg.resize(420, 140)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dlg.captured_spec()
        if not spec:
            return
        for i in range(self._web_search_list.count()):
            if self._web_search_list.item(i).data(Qt.ItemDataRole.UserRole) == spec:
                QMessageBox.information(self, "Hold to Ask Web", "That key is already in the list.")
                return
        it = QListWidgetItem(spec_label(spec))
        it.setData(Qt.ItemDataRole.UserRole, spec)
        self._web_search_list.addItem(it)
        self._save_web_search_list_from_ui()

    @Slot()
    def _on_remove_web_search_clicked(self) -> None:
        row = self._web_search_list.currentRow()
        if row < 0:
            return
        self._web_search_list.takeItem(row)
        self._save_web_search_list_from_ui()

    @Slot()
    def _on_add_ptt_clicked(self) -> None:
        dlg = PttCaptureDialog(self)
        dlg.resize(420, 140)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dlg.captured_spec()
        if not spec:
            return
        for i in range(self._ptt_list.count()):
            if self._ptt_list.item(i).data(Qt.ItemDataRole.UserRole) == spec:
                QMessageBox.information(self, "Push-to-talk", "That key is already in the list.")
                return
        it = QListWidgetItem(spec_label(spec))
        it.setData(Qt.ItemDataRole.UserRole, spec)
        self._ptt_list.addItem(it)
        self._save_ptt_list_from_ui()

    @Slot()
    def _on_remove_ptt_clicked(self) -> None:
        row = self._ptt_list.currentRow()
        if row < 0:
            return
        self._ptt_list.takeItem(row)
        self._save_ptt_list_from_ui()

    def sync_ptt_from_settings(self) -> None:
        self._populate_ptt_list()

    def sync_web_search_from_settings(self) -> None:
        self._populate_web_search_list()
        self._web_search_enabled_cb.blockSignals(True)
        self._web_search_enabled_cb.setChecked(
            bool(
                self._settings.value(
                    WEB_SEARCH_ENABLED,
                    WEB_SEARCH_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._web_search_enabled_cb.blockSignals(False)
        self._sync_web_search_controls_enabled()

    def sync_cues_from_settings(self) -> None:
        self._audio_cues_cb.blockSignals(True)
        self._audio_cues_cb.setChecked(
            bool(
                self._settings.value(
                    AUDIO_CUES_ENABLED,
                    AUDIO_CUES_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._audio_cues_cb.blockSignals(False)
        self._visual_cues_cb.blockSignals(True)
        self._visual_cues_cb.setChecked(
            bool(
                self._settings.value(
                    VISUAL_CUES_ENABLED,
                    VISUAL_CUES_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._visual_cues_cb.blockSignals(False)

    def sync_translate_from_settings(self) -> None:
        v = bool(
            self._settings.value(
                TRANSLATE_RU_EN_ENABLED,
                TRANSLATE_RU_EN_ENABLED_DEFAULT,
                type=bool,
            )
        )
        self._translate_ru_en_cb.blockSignals(True)
        self._translate_ru_en_cb.setChecked(v)
        self._translate_ru_en_cb.blockSignals(False)

    @Slot(bool)
    def _on_startup_toggled(self, checked: bool) -> None:
        try:
            set_run_at_startup_enabled(checked)
        except OSError as e:
            self._startup_cb.blockSignals(True)
            self._startup_cb.setChecked(not checked)
            self._startup_cb.blockSignals(False)
            QMessageBox.warning(
                self,
                "Startup setting",
                f"Could not update the Windows startup entry:\n{e}",
            )

    @Slot(bool)
    def _on_start_minimized_toggled(self, checked: bool) -> None:
        self._settings.setValue(START_MINIMIZED_SETTING, bool(checked))

    @Slot(bool)
    def _on_audio_cues_toggled(self, checked: bool) -> None:
        self._settings.setValue(AUDIO_CUES_ENABLED, bool(checked))

    @Slot(bool)
    def _on_visual_cues_toggled(self, checked: bool) -> None:
        self._settings.setValue(VISUAL_CUES_ENABLED, bool(checked))
        fn = getattr(self._main, "_on_visual_cue_setting_changed", None)
        if fn is not None:
            fn()

    @Slot(bool)
    def _on_web_search_enabled_toggled(self, checked: bool) -> None:
        self._settings.setValue(WEB_SEARCH_ENABLED, bool(checked))
        self._sync_web_search_controls_enabled()
        fn = getattr(self._main, "_on_web_search_enabled_changed", None)
        if fn is not None:
            fn()

    @Slot(bool)
    def _on_web_double_tap_toggled(self, checked: bool) -> None:
        self._settings.setValue(WEB_DOUBLE_TAP_ENABLED, bool(checked))

    @Slot(bool)
    def _on_transcript_filter_enabled_toggled(self, checked: bool) -> None:
        self._settings.setValue(TRANSCRIPT_FILTER_ENABLED, bool(checked))

    @Slot()
    def _on_transcript_filter_words_changed(self) -> None:
        self._settings.setValue(TRANSCRIPT_FILTER_WORDS, self._filter_words.toPlainText())

    def _revert_translate_ru_en_checkbox(self) -> None:
        self._translate_ru_en_cb.blockSignals(True)
        self._translate_ru_en_cb.setChecked(False)
        self._translate_ru_en_cb.blockSignals(False)

    @Slot(bool)
    def _on_translate_ru_en_toggled(self, checked: bool) -> None:
        if not checked:
            self._settings.setValue(TRANSLATE_RU_EN_ENABLED, False)
            self._settings.setValue(TRANSLATION_MODEL_FETCH_APPROVED, False)
            return

        main = self._main
        show_warn = getattr(main, "_show_local_translation_consent_warning", None)
        continue_flow = getattr(main, "_continue_local_translation_enable_after_consent", None)
        if show_warn is None or continue_flow is None:
            self._revert_translate_ru_en_checkbox()
            return
        if not show_warn():
            self._revert_translate_ru_en_checkbox()
            return
        if not continue_flow():
            self._revert_translate_ru_en_checkbox()
            return


class AppSignals(QObject):
    statusChanged = Signal(str)
    transcriptAppend = Signal(str)
    transcriptReady = Signal(str)
    errorOccurred = Signal(str)
    ffmpegMissing = Signal(str)
    recordingActive = Signal(bool)
    fileTranscribeDone = Signal(str, str, str, str)
    translationModelPreloadFinished = Signal(bool, str)
    webSearchReady = Signal(str, str)
    webSearchOverlaySyncRequest = Signal()
    micSttBusy = Signal(bool)
    webSearchPipelineJobStarted = Signal()
    webSearchPipelineJobFinished = Signal()
    webSearchJobsChanged = Signal(int)


class RecordingPulseWidget(QWidget):
    """Soft pulsing red indicator (timer-driven repaint) for active recording."""

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

        # Soft outer glow (filled, alpha breathes)
        halo_r = 6.0 + pulse * 6.5
        halo_alpha = int(35 + pulse * 165)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 55, 55, halo_alpha))
        p.drawEllipse(QRectF(cx - halo_r, cy - halo_r, 2.0 * halo_r, 2.0 * halo_r))

        # Out-of-phase ring for extra motion
        ring_pulse = 0.5 + 0.5 * math.sin(t + 1.1)
        ring_r = 7.5 + ring_pulse * 5.0
        ring_pen = QPen(QColor(255, 140, 140, int(70 + ring_pulse * 150)))
        ring_pen.setWidthF(2.0)
        p.setPen(ring_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - ring_r, cy - ring_r, 2.0 * ring_r, 2.0 * ring_r))

        # Solid core
        core_r = 4.8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ff3333"))
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, 2.0 * core_r, 2.0 * core_r))
        p.end()


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


class WebSearchPulseWidget(QWidget):
    """Cyan pulse indicator while recording a web search query."""

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
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(34, 211, 238, halo_alpha))
        p.drawEllipse(QRectF(cx - halo_r, cy - halo_r, 2.0 * halo_r, 2.0 * halo_r))

        ring_pulse = 0.5 + 0.5 * math.sin(t + 1.1)
        ring_r = 7.5 + ring_pulse * 5.0
        ring_pen = QPen(QColor(125, 211, 252, int(70 + ring_pulse * 150)))
        ring_pen.setWidthF(2.0)
        p.setPen(ring_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - ring_r, cy - ring_r, 2.0 * ring_r, 2.0 * ring_r))

        core_r = 4.8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#22d3ee"))
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, 2.0 * core_r, 2.0 * core_r))
        p.end()


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


class WebSearchHistoryWindow(QWidget):
    """Browse past web search queries and Markdown summaries."""

    def __init__(self, qsettings: QSettings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = qsettings
        self.setWindowTitle("Web search history")
        self.setMinimumSize(720, 480)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)

        split = QHBoxLayout(self)
        self._list = QListWidget()
        self._list.setMinimumWidth(220)
        self._browser = QTextBrowser()
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(True)
        self._browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        split.addWidget(self._list, 0)
        split.addWidget(self._browser, 1)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._reload_list()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._reload_list()

    def _reload_list(self) -> None:
        self._list.clear()
        entries = load_history_entries(self._settings)
        for e in reversed(entries):
            ts = float(e.get("ts", 0))
            q = str(e.get("query", ""))[:80]
            tstr = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            it = QListWidgetItem(f"{tstr} — {q}")
            it.setData(Qt.ItemDataRole.UserRole, e)
            self._list.addItem(it)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    @Slot(int)
    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            self._browser.clear()
            return
        item = self._list.item(row)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        q = str(data.get("query", ""))
        s = str(data.get("summary_md", ""))
        self._browser.setMarkdown(_web_search_dialog_markdown(q, s))


class MainWindow(QMainWindow):
    def __init__(self, app_icon: Optional[QIcon] = None) -> None:
        super().__init__()
        self.setWindowTitle("Potato STT — Push-to-talk")
        self.setMinimumWidth(820)

        self._app_icon = app_icon if app_icon is not None else build_app_icon()
        self.setWindowIcon(self._app_icon)

        self.settings = Settings()
        self._qsettings = QSettings("PotatoSTT", "PotatoSTT")
        self._ptt_specs: list[str] = load_ptt_specs(self._qsettings)
        self._web_search_specs: list[str] = load_web_search_specs(self._qsettings)
        self._stt_engine_ready = False
        # True only for File → Quit / tray Quit so closeEvent exits instead of hiding to tray.
        self._requesting_full_quit = False

        self._status_label = QLabel("Initializing...")
        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._web_search_btn = QPushButton("Hold to Ask Web")
        self._web_search_btn.setToolTip(
            "Press and hold to record a web search query. Release to transcribe and ask OpenCode for a web summary."
        )
        self._web_search_btn.pressed.connect(self._on_web_search_button_pressed)
        self._web_search_btn.released.connect(self._on_web_search_button_released)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFormat("Starting...")

        self._options_win: Optional[OptionsWindow] = None

        root = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self._status_label)
        layout.addWidget(self._progress)
        web_btn_row = QHBoxLayout()
        web_btn_row.addWidget(self._web_search_btn, 0, Qt.AlignmentFlag.AlignLeft)
        web_btn_row.addStretch(1)
        layout.addLayout(web_btn_row)
        layout.addWidget(self._transcript)
        root.setLayout(layout)
        self.setCentralWidget(root)

        _file_menu = self.menuBar().addMenu("&File")
        act_transcribe_file = QAction("Transcribe media file…", self)
        act_transcribe_file.triggered.connect(self._on_transcribe_file_chosen)
        _file_menu.addAction(act_transcribe_file)
        _file_menu.addSeparator()
        act_quit_menu = QAction("&Quit", self)
        act_quit_menu.setShortcut("Ctrl+Q")
        act_quit_menu.triggered.connect(self._quit_application)
        _file_menu.addAction(act_quit_menu)

        _settings_menu = self.menuBar().addMenu("&Settings")
        act_options_menu = QAction("&Options…", self)
        act_options_menu.setShortcut("Ctrl+,")
        act_options_menu.triggered.connect(self._open_options)
        _settings_menu.addAction(act_options_menu)
        act_web_hist = QAction("Web search &history…", self)
        act_web_hist.triggered.connect(self._open_web_search_history)
        _settings_menu.addAction(act_web_hist)

        _help_menu = self.menuBar().addMenu("&Help")
        act_using_help = QAction("Using Potato STT…", self)
        act_using_help.triggered.connect(self._show_using_help_dialog)
        _help_menu.addAction(act_using_help)
        if sys.platform == "win32":
            _help_menu.addSeparator()
            act_clear_data = QAction("Clear local data (uninstall caches)…", self)
            act_clear_data.triggered.connect(self._on_clear_local_data)
            _help_menu.addAction(act_clear_data)

        self.signals = AppSignals()
        # Queued so slots always run on the GUI thread when workers emit (avoids blocking/freezes).
        qc = Qt.ConnectionType.QueuedConnection
        self.signals.statusChanged.connect(self._on_status_update, qc)
        self.signals.transcriptAppend.connect(self._append_transcript, qc)
        self.signals.transcriptReady.connect(self._paste_transcript_to_active_app, qc)
        self.signals.errorOccurred.connect(self._on_error, qc)
        self.signals.ffmpegMissing.connect(self._on_ffmpeg_missing_notice, qc)
        self.signals.recordingActive.connect(self._on_recording_overlay, qc)
        self.signals.fileTranscribeDone.connect(self._on_file_transcribe_done, qc)
        self.signals.translationModelPreloadFinished.connect(
            self._on_translation_model_preload_finished, qc
        )
        self.signals.webSearchReady.connect(self._on_web_search_ready, qc)
        self.signals.webSearchOverlaySyncRequest.connect(self._sync_web_search_overlay, qc)
        self.signals.micSttBusy.connect(self._on_mic_stt_busy, qc)
        self.signals.webSearchPipelineJobStarted.connect(self._on_web_search_pipeline_job_started, qc)
        self.signals.webSearchPipelineJobFinished.connect(self._on_web_search_pipeline_job_finished, qc)

        self._recording_overlay = RecordingOverlay()
        self._recording_overlay.hide()
        self._web_search_overlay = WebSearchOverlay()
        self._web_search_overlay.hide()

        # Microphone state.
        self._sample_rate = 16000
        self._channels = 1
        self._pcm_lock = threading.Lock()
        self._pcm_blocks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._recording = False
        self._mic_stt_busy = False
        self._file_transcribe_busy = False
        self._web_search_pipeline_jobs = 0
        self._web_opencode_semaphore = threading.Semaphore(WEB_OPENCODE_MAX_CONCURRENT)
        self._capture_mode: Optional[str] = None
        self._ptt_hold_tokens: set[str] = set()
        self._web_search_hold_tokens: set[str] = set()
        self._keyboard_modifiers_down: set[str] = set()
        self._double_tap_lock = threading.Lock()
        self._double_tap_down_at: dict[str, float] = {}
        self._double_tap_last_up: dict[str, float] = {}
        self._double_tap_ptt_timers: dict[str, threading.Timer] = {}
        self._double_tap_ptt_started: set[str] = set()
        self._onnx_engine: Optional[OnnxAsrEngine] = None
        # Window that had focus when push-to-talk started (for paste target).
        self._paste_target_hwnd: Optional[int] = None

        self._pending_tray_web_summary: Optional[tuple[str, str]] = None
        self._web_summary_dialog: Optional[QDialog] = None
        self._web_search_history_win: Optional[WebSearchHistoryWindow] = None

        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None

        self._tray_icon: Optional[QSystemTrayIcon] = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon(self)
            tray.setIcon(self._app_icon)
            tray.setToolTip(f"Potato STT — hold {specs_summary_phrase(self._ptt_specs)} to talk")
            tray_menu = QMenu()
            act_show = QAction("Show", self)
            act_show.triggered.connect(self._show_from_tray)
            tray_menu.addAction(act_show)
            act_tray_file = QAction("Transcribe media file…", self)
            act_tray_file.triggered.connect(self._on_transcribe_file_chosen)
            tray_menu.addAction(act_tray_file)
            act_tray_web_hist = QAction("Web search history…", self)
            act_tray_web_hist.triggered.connect(self._open_web_search_history)
            tray_menu.addAction(act_tray_web_hist)
            if sys.platform == "win32":
                act_tray_clear = QAction("Clear local data…", self)
                act_tray_clear.triggered.connect(self._on_clear_local_data)
                tray_menu.addAction(act_tray_clear)
            act_quit = QAction("Quit", self)
            act_quit.triggered.connect(self._quit_application)
            tray_menu.addAction(act_quit)
            tray.setContextMenu(tray_menu)
            tray.activated.connect(self._on_tray_activated)
            tray.messageClicked.connect(self._on_tray_message_clicked)
            tray.show()
            self._tray_icon = tray

        self._sync_tray_ptt_tooltip()
        self._web_search_btn.setEnabled(self._web_search_enabled())

        # Start engine ensure in background, then register hotkey.
        threading.Thread(target=self._ensure_engine_and_start_hotkey, daemon=True).start()

    def has_system_tray(self) -> bool:
        return self._tray_icon is not None

    @Slot()
    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    @Slot()
    def _quit_application(self) -> None:
        # Quit must run after the tray context menu returns on Windows; a synchronous
        # QApplication.quit() from the menu action is often ignored and leaves the process running.
        self._requesting_full_quit = True
        self._shutdown()
        QTimer.singleShot(0, QApplication.quit)

    def _shutdown(self) -> None:
        self._recording_overlay.hide()
        self._web_search_overlay.hide()
        if self._options_win is not None:
            self._options_win.close_for_shutdown()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self._stop_hotkey_listeners()
        try:
            self._stop_recording(play_stop_cue=False)
        except Exception:
            pass
        try:
            sd.stop()
        except Exception:
            pass

    def closeEvent(self, event):  # type: ignore[no-untyped-def]
        if self._tray_icon is not None and not self._requesting_full_quit:
            event.ignore()
            self._recording_overlay.hide()
            self._web_search_overlay.hide()
            if self._options_win is not None:
                self._options_win.hide()
            self.hide()
            return
        if not self._requesting_full_quit:
            self._shutdown()
        super().closeEvent(event)

    def _stop_hotkey_listeners(self) -> None:
        self._cancel_double_tap_timers()
        for attr in ("_keyboard_listener", "_mouse_listener"):
            lst = getattr(self, attr, None)
            if lst is not None:
                try:
                    lst.stop()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _using_help_text(self) -> str:
        ptt = specs_summary_phrase(self._ptt_specs)
        lines = [
            f"Hold {ptt} to record. Release when you are done; the text is transcribed and pasted into "
            "the application that had keyboard focus when you pressed the key (and also appears in "
            "this window).",
            "Use the Hold to Ask Web button (or optional shortcuts in Options) to record a web query; "
            "a small on-screen cue shows while recording and while OpenCode searches.",
            "",
            "Use File → Transcribe media file… to transcribe an existing audio or video file.",
            "Use Settings → Options… (Ctrl+,) to change push-to-talk keys, startup behavior, filters, "
            "audio/visual cues, web search, and optional translation.",
        ]
        if self._tray_icon is not None:
            lines.extend(
                [
                    "",
                    "When a system tray icon is available:",
                    "• The window close button (X) hides this window to the tray without quitting; "
                    "minimize uses the taskbar as usual.",
                    "• Double-click the tray icon to show the window again.",
                    "• Use File → Quit (Ctrl+Q) or the tray menu Quit to exit completely.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "No system tray icon is available on this session; use File → Quit (Ctrl+Q) to exit.",
                ]
            )
        return "\n".join(lines)

    @Slot()
    def _show_using_help_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Using Potato STT")
        dlg.setModal(True)
        dlg.setMinimumWidth(520)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(self._using_help_text())
        body.setMinimumHeight(280)
        body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bbox.accepted.connect(dlg.accept)
        root = QVBoxLayout(dlg)
        root.addWidget(body)
        root.addWidget(bbox)
        dlg.exec()

    def _sync_tray_ptt_tooltip(self) -> None:
        ptt = specs_summary_phrase(self._ptt_specs)
        if self._tray_icon is not None:
            self._tray_icon.setToolTip(f"Potato STT — hold {ptt} to talk")

    @Slot()
    def _on_ptt_key_setting_changed(self) -> None:
        self._ptt_specs = load_ptt_specs(self._qsettings)
        self._sync_tray_ptt_tooltip()
        self.restart_ptt_listeners()

    @Slot()
    def _on_web_search_key_setting_changed(self) -> None:
        self._web_search_specs = load_web_search_specs(self._qsettings)
        self.restart_ptt_listeners()

    @Slot()
    def _on_visual_cue_setting_changed(self) -> None:
        if not self._visual_cues_enabled():
            self._recording_overlay.hide()
            self._web_search_overlay.hide()
        else:
            self._sync_web_search_overlay()

    @Slot()
    def _on_web_search_enabled_changed(self) -> None:
        self._web_search_btn.setEnabled(self._web_search_enabled())
        if not self._web_search_enabled():
            self._web_search_hold_tokens.clear()
            self._cancel_double_tap_timers()
            if self._recording and self._capture_mode == "web":
                self._stop_recording(play_stop_cue=True)
                self._capture_mode = None
            self._web_search_overlay.hide()
        self.restart_ptt_listeners()

    def restart_ptt_listeners(self) -> None:
        if not self._stt_engine_ready:
            return
        self._stop_hotkey_listeners()
        self._register_hotkey()

    @Slot()
    def _open_options(self) -> None:
        if self._options_win is None:
            self._options_win = OptionsWindow(self)
        self._options_win.sync_ptt_from_settings()
        self._options_win.sync_web_search_from_settings()
        self._options_win.sync_cues_from_settings()
        self._options_win.sync_translate_from_settings()
        self._options_win.show()
        self._options_win.raise_()
        self._options_win.activateWindow()

    def _show_local_translation_consent_warning(self) -> bool:
        """Warning dialog with explicit Agree / Refuse (default Refuse). Returns True if user agrees."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Local translation — notice")
        msg.setText(
            "Local Russian → English translation will:\n"
            "• Paste English into the app that had focus; this window lists the recognized text and "
            "the English wording (when it differs).\n"
            "• After you choose **Agree**, the Marian model (~300 MB from the internet) downloads in the "
            "background if it is not already on this PC (saved in your Hugging Face cache). "
            "Watch the main window status line for progress.\n"
            "• Run on your PC using PyTorch on the CPU.\n\n"
            "Choose **Agree** to enable translation and start the download when needed, or **Refuse** to cancel."
        )
        refuse_btn = msg.addButton("Refuse", QMessageBox.ButtonRole.RejectRole)
        agree_btn = msg.addButton("Agree", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(refuse_btn)
        msg.exec()
        return msg.clickedButton() == agree_btn

    def _continue_local_translation_enable_after_consent(self) -> bool:
        """After Agree on the warning: install deps if needed, finish enable. Returns False if user cancels or setup fails."""
        if _tr_runtime_ready():
            self._finish_enabling_local_translation()
            return True

        if getattr(sys, "frozen", False):
            QMessageBox.warning(
                self,
                "Translation unavailable",
                "PyTorch or transformers could not be loaded from this installation. "
                "Try reinstalling Potato STT or run from source with `pip install -r requirements.txt` "
                "and a CPU PyTorch wheel.",
            )
            return False

        pip_ask = QMessageBox(self)
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
            code, log = _translation_marian_module().install_translation_runtime_packages()
        finally:
            QApplication.restoreOverrideCursor()

        if code != 0 or not _tr_runtime_ready():
            fail = QMessageBox(self)
            fail.setIcon(QMessageBox.Icon.Warning)
            fail.setWindowTitle("Installation failed")
            fail.setText(
                "pip could not install the translation stack, or imports still fail after install. "
                "See details below."
            )
            fail.setDetailedText(log[:12000] if log else "(no log)")
            fail.exec()
            return False

        self._finish_enabling_local_translation()
        return True

    def _finish_enabling_local_translation(self) -> None:
        self._qsettings.setValue(TRANSLATE_RU_EN_ENABLED, True)
        self._sync_options_translate_checkbox()
        self._start_translation_model_preload()

    def _sync_options_translate_checkbox(self) -> None:
        if self._options_win is not None:
            self._options_win.sync_translate_from_settings()

    def _start_translation_model_preload(self) -> None:
        """Background Hugging Face download + Marian load; finishes on the GUI thread via signal."""
        # Consent to fetch weights — must be True before load finishes so transcription can translate
        # while this download runs (second load path serializes on the Marian module lock).
        self._qsettings.setValue(TRANSLATION_MODEL_FETCH_APPROVED, True)

        def run() -> None:
            ok = True
            err = ""
            try:
                m = _translation_marian_module()

                def on_status(s: str) -> None:
                    self.signals.statusChanged.emit(s)

                m.preload_translation_model(on_status=on_status)
            except Exception as e:
                ok = False
                err = f"{type(e).__name__}: {e}"
            self.signals.translationModelPreloadFinished.emit(ok, err)

        threading.Thread(target=run, daemon=True).start()

    @Slot(bool, str)
    def _on_translation_model_preload_finished(self, ok: bool, err: str) -> None:
        if ok:
            self.signals.statusChanged.emit(
                f"Translation model ready. Hold {specs_summary_phrase(self._ptt_specs)} to talk."
            )
            return
        QMessageBox.warning(
            self,
            "Translation model",
            f"The translation model could not be downloaded or loaded:\n{err}\n\n"
            "Local translation stays enabled. In **Options**, turn the translation checkbox off and on "
            "again to retry the download, or speak again — the next run will retry loading the model.",
        )

    @Slot()
    def _on_clear_local_data(self) -> None:
        if sys.platform != "win32":
            return
        script = clear_data_script_path()
        if not script.is_file():
            QMessageBox.warning(
                self,
                "Clear local data",
                f"Cleanup script not found:\n{script}\n\n"
                "From source, run scripts\\Clear-PotatoSTTData.ps1 from the repository root.",
            )
            return
        tip = (
            "This removes the Parakeet install folder, Hugging Face ONNX model downloads, saved options "
            "(push-to-talk keys, etc.), and Windows startup Run entries for Potato STT / Pipit Clone.\n\n"
            "Quit Potato STT first; the script will try to stop PotatoSTT.exe if it is still running."
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Clear local data")
        box.setText(tip)
        box.setInformativeText(f"Script path:\n{script}")
        btn_open = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        btn_run = box.addButton("Run in PowerShell", QMessageBox.ButtonRole.ActionRole)
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
                    self,
                    "Clear local data",
                    f"Could not start PowerShell:\n{e}",
                )

    def _effective_filter_phrases(self) -> list[str] | None:
        """Phrases to strip from transcripts when the Options toggle is on; main thread only."""
        if not bool(
            self._qsettings.value(
                TRANSCRIPT_FILTER_ENABLED,
                TRANSCRIPT_FILTER_ENABLED_DEFAULT,
                type=bool,
            )
        ):
            return None
        raw = str(
            self._qsettings.value(TRANSCRIPT_FILTER_WORDS, TRANSCRIPT_FILTER_WORDS_DEFAULT) or ""
        )
        phrases = parse_filter_phrases(raw)
        return phrases if phrases else None

    @Slot(str)
    def _append_transcript(self, text: str) -> None:
        current = self._transcript.toPlainText().strip()
        line = finalize_sentence_for_clipboard(text)
        if not current:
            self._transcript.setPlainText(line + "\n")
        else:
            self._transcript.setPlainText(current + "\n" + line + "\n")
        self._transcript.ensureCursorVisible()

    @Slot()
    def _on_transcribe_file_chosen(self) -> None:
        if not self._stt_engine_ready:
            QMessageBox.information(
                self,
                "Transcribe file",
                "The speech engine is still getting ready. Wait until startup finishes, then try again.",
            )
            return
        if self._file_transcribe_busy:
            QMessageBox.information(
                self,
                "Transcribe file",
                "A file transcription is already in progress.",
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open audio or video",
            "",
            "Media (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mkv *.webm *.mov *.avi);;"
            "All files (*.*)",
        )
        if not path:
            return
        self._start_file_transcribe(Path(path))

    def _start_file_transcribe(self, source_path: Path) -> None:
        if self._file_transcribe_busy:
            return
        self._file_transcribe_busy = True
        self.signals.statusChanged.emit(f"Transcribing file: {source_path.name} …")
        src_str = str(source_path.resolve())
        ptt_specs_snapshot = list(self._ptt_specs)
        filter_phrases = self._effective_filter_phrases()

        def job() -> None:
            try:
                t0 = time.time()

                def _progress(part: str) -> None:
                    self.signals.statusChanged.emit(
                        f"Transcribing file: {source_path.name} — {part} …"
                    )

                cleaned, cues = transcribe_file_to_text_and_cues(
                    source_path,
                    chunk_seconds=self.settings.transcribe_chunk_seconds,
                    stt_backend=self.settings.stt_backend,
                    onnx_engine=self._onnx_engine,
                    stt_api_url=self.settings.stt_api_url,
                    stt_model=self.settings.stt_model,
                    stt_response_format=self.settings.stt_response_format,
                    stt_timeout_seconds=self.settings.stt_timeout_seconds,
                    on_progress=_progress,
                )
                fp = filter_phrases
                if fp:
                    cleaned = apply_word_filter_after_normalize(cleaned, fp)
                    cues = filter_subtitle_cues(list(cues), fp)
                took = time.time() - t0
                srt_body = cues_to_srt(cues) if cues else ""
                vtt_body = cues_to_vtt(cues) if cues else ""
                self.signals.fileTranscribeDone.emit(src_str, cleaned, srt_body, vtt_body)
                self.signals.statusChanged.emit(
                    f"File transcribed in {took:.1f}s. Transcript added (not pasted). Ready. Hold "
                    f"{specs_summary_phrase(ptt_specs_snapshot)} to talk."
                )
            except FFmpegNotFoundError as e:
                self.signals.errorOccurred.emit(
                    f"{type(e).__name__}: FFmpeg is not installed or not on PATH."
                )
                self.signals.ffmpegMissing.emit(str(e))
                self.signals.statusChanged.emit(
                    f"Ready. Hold {specs_summary_phrase(ptt_specs_snapshot)} to talk."
                )
            except Exception as e:
                self.signals.errorOccurred.emit(f"{type(e).__name__}: {e}")
                self.signals.statusChanged.emit(
                    f"Ready. Hold {specs_summary_phrase(ptt_specs_snapshot)} to talk."
                )
            finally:
                self._file_transcribe_busy = False

        threading.Thread(target=job, daemon=True).start()

    @Slot(str, str, str, str)
    def _on_file_transcribe_done(self, source_path: str, transcript: str, srt_body: str, vtt_body: str) -> None:
        t = transcript.strip()
        if t:
            self.signals.transcriptAppend.emit(t)
        if not (srt_body.strip() or vtt_body.strip()):
            return
        default_path = str(Path(source_path).with_suffix(".srt"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save subtitles",
            default_path,
            "SubRip (*.srt);;WebVTT (*.vtt)",
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() == ".vtt":
            p.write_text(vtt_body, encoding="utf-8", newline="\n")
        else:
            if p.suffix.lower() != ".srt":
                p = p.with_suffix(".srt")
            p.write_text(srt_body, encoding="utf-8", newline="\n")

    def _position_recording_overlay(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self._recording_overlay.adjustSize()
        w = self._recording_overlay.width()
        h = self._recording_overlay.height()
        margin = 24
        x = geo.left() + (geo.width() - w) // 2
        y = geo.top() + geo.height() - h - margin
        self._recording_overlay.move(x, y)

    def _position_web_search_overlay(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self._web_search_overlay.adjustSize()
        w = self._web_search_overlay.width()
        h = self._web_search_overlay.height()
        margin = 24
        x = geo.left() + (geo.width() - w) // 2
        y = geo.top() + geo.height() - h - margin - 72
        self._web_search_overlay.move(max(geo.left(), x), max(geo.top(), y))

    def _audio_cues_enabled(self) -> bool:
        return bool(
            self._qsettings.value(
                AUDIO_CUES_ENABLED,
                AUDIO_CUES_ENABLED_DEFAULT,
                type=bool,
            )
        )

    def _visual_cues_enabled(self) -> bool:
        return bool(
            self._qsettings.value(
                VISUAL_CUES_ENABLED,
                VISUAL_CUES_ENABLED_DEFAULT,
                type=bool,
            )
        )

    def _web_search_enabled(self) -> bool:
        return bool(
            self._qsettings.value(
                WEB_SEARCH_ENABLED,
                WEB_SEARCH_ENABLED_DEFAULT,
                type=bool,
            )
        )

    @Slot()
    def _sync_web_search_overlay(self) -> None:
        if not self._visual_cues_enabled():
            self._web_search_overlay.hide()
            return
        if self._recording and self._capture_mode == "web":
            self._position_web_search_overlay()
            self._web_search_overlay.set_mode_recording()
            self._web_search_overlay.show()
            return
        n = self._web_search_pipeline_jobs
        if n > 0:
            self._position_web_search_overlay()
            self._web_search_overlay.set_mode_loading(n)
            self._web_search_overlay.show()
            return
        self._web_search_overlay.hide()

    @Slot(bool)
    def _on_mic_stt_busy(self, busy: bool) -> None:
        self._mic_stt_busy = busy

    @Slot()
    def _on_web_search_pipeline_job_started(self) -> None:
        self._web_search_pipeline_jobs += 1
        self.signals.webSearchJobsChanged.emit(self._web_search_pipeline_jobs)
        self._sync_web_search_overlay()

    @Slot()
    def _on_web_search_pipeline_job_finished(self) -> None:
        self._web_search_pipeline_jobs = max(0, self._web_search_pipeline_jobs - 1)
        self.signals.webSearchJobsChanged.emit(self._web_search_pipeline_jobs)
        self._sync_web_search_overlay()

    @Slot()
    def _open_web_search_history(self) -> None:
        if self._web_search_history_win is None:
            self._web_search_history_win = WebSearchHistoryWindow(self._qsettings, self)
        self._web_search_history_win.show()
        self._web_search_history_win.raise_()
        self._web_search_history_win.activateWindow()

    @Slot()
    def _on_tray_message_clicked(self) -> None:
        payload = self._pending_tray_web_summary
        if payload is None:
            return
        q, s = payload
        self._show_web_summary_nonmodal(q, s)

    def _show_web_summary_nonmodal(self, query: str, summary: str) -> None:
        if self._web_summary_dialog is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Web search summary")
            dlg.setModal(False)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            dlg.setMinimumWidth(680)
            dlg.setMinimumHeight(420)
            body = QTextBrowser()
            body.setReadOnly(True)
            body.setOpenExternalLinks(True)
            body.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
            bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            bbox.accepted.connect(dlg.hide)
            root = QVBoxLayout(dlg)
            root.addWidget(body)
            root.addWidget(bbox)
            dlg._web_summary_body = body  # type: ignore[attr-defined]
            self._web_summary_dialog = dlg
        dlg2 = self._web_summary_dialog
        assert dlg2 is not None
        body_w = getattr(dlg2, "_web_summary_body", None)
        assert isinstance(body_w, QTextBrowser)
        dlg2.setWindowTitle("Web search summary")
        body_w.setMarkdown(_web_search_dialog_markdown(query, summary))
        dlg2.show()
        dlg2.raise_()
        dlg2.activateWindow()

    @Slot(bool)
    def _on_recording_overlay(self, active: bool) -> None:
        if not self._visual_cues_enabled():
            self._recording_overlay.hide()
            return
        if active:
            self._position_recording_overlay()
            self._recording_overlay.show()
        else:
            self._recording_overlay.hide()

    @Slot(str)
    def _on_ffmpeg_missing_notice(self, message: str) -> None:
        # message matches FFMPEG_MISSING_USER_MESSAGE; dialog mirrors it with a copy-friendly command.
        _ = message
        dlg = QDialog(self)
        dlg.setWindowTitle("FFmpeg required")
        dlg.setMinimumWidth(520)
        style = dlg.style()
        assert style is not None
        icon_lbl = QLabel()
        icon_lbl.setPixmap(
            style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(48, 48)
        )
        summary = QLabel(
            "FFmpeg is not installed or not on PATH. "
            "It is needed for most audio and video file formats."
        )
        summary.setWordWrap(True)
        f_sum = QFont(summary.font())
        f_sum.setBold(True)
        summary.setFont(f_sum)

        before = QLabel(FFMPEG_MISSING_CONTEXT_BEFORE_CLI)
        before.setWordWrap(True)

        cmd_caption = QLabel("Command (select and copy):")
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
                "Install FFmpeg with winget…",
                QDialogButtonBox.ButtonRole.ActionRole,
            )
        open_btn = bbox.addButton(
            "Open FFmpeg download page...",
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
            if _try_start_ffmpeg_winget_install():
                QMessageBox.information(
                    self,
                    "FFmpeg install",
                    "A command window should open to install FFmpeg via winget.\n\n"
                    "When it finishes successfully, restart Potato STT (or sign out of Windows) "
                    "so ffmpeg and ffprobe are picked up from PATH.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "FFmpeg install",
                    "Could not start winget. Install FFmpeg manually from the download page, "
                    f"or run in a terminal:\n\n{FFMPEG_WINGET_INSTALL_CLI}",
                )
        elif code == _DONE_OPEN:
            QDesktopServices.openUrl(QUrl(FFMPEG_DOWNLOAD_URL))

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("Failed")

    @Slot(str)
    def _on_status_update(self, msg: str) -> None:
        self._status_label.setText(msg)
        lower = msg.lower()
        if lower.startswith("error:") or " exited " in lower or "failed" in lower:
            self._progress.setRange(0, 1)
            self._progress.setValue(0)
            self._progress.setFormat("Failed")
            return
        if "downloading..." in lower and "%" in msg:
            pct_str = msg.split("%", 1)[0].split()[-1]
            try:
                pct = int(float(pct_str))
                self._progress.setRange(0, 100)
                self._progress.setValue(max(0, min(100, pct)))
                self._progress.setFormat(f"Downloading from internet — {pct}%")
                return
            except Exception:
                pass
        if "model download" in lower and "%" in msg:
            pct_str = msg.split("%", 1)[0].split()[-1]
            try:
                pct = int(float(pct_str))
                self._progress.setRange(0, 100)
                self._progress.setValue(max(0, min(100, pct)))
                self._progress.setFormat(f"Downloading model from internet — {pct}%")
                return
            except Exception:
                pass
        # Indeterminate bar + label: network/model fetch without a numeric percent yet.
        if (
            "waiting for parakeet service to finish model download" in lower
            or "downloading parakeet windows package" in lower
            or "package url failed, downloading" in lower
        ):
            self._progress.setRange(0, 0)
            self._progress.setFormat("Downloading from internet...")
            return
        if "preparing parakeet http stt engine" in lower:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Preparing STT (may download from internet)...")
            return
        if "extracting package" in lower:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Extracting downloaded package...")
            return
        if "installing fallback dependencies" in lower:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Installing dependencies (downloading from internet)...")
            return
        if "loading onnx asr model" in lower:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Loading model...")
            return
        if "preparing onnx asr engine" in lower:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Preparing ONNX model...")
            return
        if "marian" in lower and "hugging face" in lower:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Downloading translation model...")
            return
        # PTT completion uses "Ready."; file transcription used to omit it and hit the
        # generic "Working..." branch (indeterminate bar looks like endless loading).
        if "ready." in lower or "file transcribed" in lower:
            self._progress.setRange(0, 1)
            self._progress.setValue(1)
            self._progress.setFormat("Ready")
        elif "transcribing" in lower:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Transcribing...")
        else:
            self._progress.setRange(0, 0)
            self._progress.setFormat("Working...")

    @Slot(str)
    def _paste_transcript_to_active_app(self, text: str) -> None:
        # Do not use strip() alone — it removes the trailing space after . ! ? that
        # normalize_phrase_spacing adds for continued typing after paste.
        text = finalize_sentence_for_clipboard(text)
        if not text:
            return

        # Save/restore clipboard so pasting doesn't permanently overwrite user clipboard.
        clipboard = QApplication.clipboard()
        previous = clipboard.text()
        clipboard.setText(text)
        QApplication.processEvents()
        time.sleep(0.02)

        try:
            # Put focus back on the app that was active when recording started (not this window).
            our_hwnd = int(self.winId()) if self.winId() else 0
            target = self._paste_target_hwnd
            if target and target != our_hwnd and is_window(target):
                set_foreground_hwnd(target)
            elif target == our_hwnd:
                # Recording started with our window focused; try paste without stealing focus.
                pass

            # Native Win32 injection is more reliable than pynput for cross-app paste.
            send_ctrl_v_keybd_event()
        except Exception as e:
            self.signals.errorOccurred.emit(f"Paste failed: {type(e).__name__}: {e}")
            return

        # Restore clipboard on Qt main thread to avoid COM initialization errors on Windows.
        QTimer.singleShot(400, lambda: clipboard.setText(previous))

    def _ensure_engine_and_start_hotkey(self) -> None:
        def _on_status(s: str) -> None:
            self.signals.statusChanged.emit(s)

        try:
            if self.settings.stt_backend.lower() == "onnx_asr":
                if self.settings.cpu_only:
                    providers = ["CPUExecutionProvider"]
                else:
                    providers = [
                        p.strip() for p in self.settings.onnx_asr_providers.split(",") if p.strip()
                    ]
                self._onnx_engine = OnnxAsrEngine(
                    model_name=self.settings.onnx_asr_model,
                    providers=providers,
                )
                _on_status("Preparing ONNX ASR engine (first model load may take time)...")
                self._onnx_engine.warmup(on_status=_on_status)
            else:
                api_url = self.settings.stt_api_url
                # stt_api_url is .../v1/audio/transcriptions
                api_base = api_url.rsplit("/audio/transcriptions", 1)[0]
                api_host = "127.0.0.1"
                api_port = 5092
                _on_status("Preparing Parakeet HTTP STT engine (download/first model load may take time)...")
                ensure_parakeet_service(
                    api_host=api_host,
                    api_port=api_port,
                    api_base_url=api_base,
                    parakeet_win_url=self.settings.parakeet_win_url,
                    install_dir=self.settings.parakeet_install_dir,
                    auto_download=self.settings.parakeet_auto_download,
                    source_fallback=self.settings.parakeet_source_fallback,
                    launch_timeout_seconds=self.settings.parakeet_launch_timeout_seconds,
                    on_status=_on_status,
                )
        except Exception as e:
            self.signals.errorOccurred.emit(f"{type(e).__name__}: {e}")
            return

        self._stt_engine_ready = True
        _on_status(f"Ready. Hold {specs_summary_phrase(self._ptt_specs)} to talk.")
        self._register_hotkey()

    def _add_ptt_token(self, token: str) -> None:
        if self._recording and self._capture_mode == "web":
            return
        before = len(self._ptt_hold_tokens)
        self._ptt_hold_tokens.add(token)
        if before == 0 and len(self._ptt_hold_tokens) > 0:
            self.signals.statusChanged.emit(
                f"{specs_summary_phrase(self._ptt_specs)} — recording..."
            )
            self._start_recording(mode="ptt")

    def _remove_ptt_token(self, token: str) -> None:
        self._ptt_hold_tokens.discard(token)
        if len(self._ptt_hold_tokens) == 0:
            self._stop_recording_and_transcribe(mode="ptt")

    def _add_web_search_token(self, token: str, *, allow_unconfigured: bool = False) -> None:
        if not self._web_search_enabled():
            return
        if not self._web_search_specs and not allow_unconfigured:
            return
        if self._recording and self._capture_mode == "ptt":
            return
        if self._mic_stt_busy:
            return
        before = len(self._web_search_hold_tokens)
        self._web_search_hold_tokens.add(token)
        if before == 0 and len(self._web_search_hold_tokens) > 0:
            if not self._stt_engine_ready:
                self._web_search_hold_tokens.discard(token)
                self.signals.statusChanged.emit("Speech engine is still initializing.")
                return
            self.signals.statusChanged.emit("Recording web query... release key to search.")
            self._start_recording(mode="web")

    def _remove_web_search_token(self, token: str) -> None:
        self._web_search_hold_tokens.discard(token)
        if len(self._web_search_hold_tokens) == 0 and self._recording and self._capture_mode == "web":
            self._stop_recording_and_transcribe(mode="web")

    def _web_double_tap_enabled(self) -> bool:
        if not self._web_search_enabled():
            return False
        return bool(
            self._qsettings.value(
                WEB_DOUBLE_TAP_ENABLED,
                WEB_DOUBLE_TAP_ENABLED_DEFAULT,
                type=bool,
            )
        )

    def _cancel_double_tap_timers(self) -> None:
        with self._double_tap_lock:
            timers = list(self._double_tap_ptt_timers.values())
            self._double_tap_ptt_timers.clear()
            self._double_tap_down_at.clear()
            self._double_tap_ptt_started.clear()
        for t in timers:
            try:
                t.cancel()
            except Exception:
                pass

    def _double_tap_hold_timer_fired(self, token: str) -> None:
        with self._double_tap_lock:
            if token not in self._double_tap_down_at:
                return
            self._double_tap_ptt_timers.pop(token, None)
            self._double_tap_ptt_started.add(token)
            self._double_tap_last_up.pop(token, None)
        self._add_ptt_token(token)

    def _handle_double_tap_press(self, token: str) -> bool:
        if not self._web_double_tap_enabled():
            return False
        now = time.monotonic()
        with self._double_tap_lock:
            last_up = self._double_tap_last_up.get(token)
            if last_up is not None and now - last_up <= DOUBLE_TAP_WINDOW_SECONDS:
                self._double_tap_last_up.pop(token, None)
                self._double_tap_down_at[token] = now
                self._double_tap_ptt_started.discard(token)
                start_web = True
            else:
                start_web = False
                if token in self._double_tap_down_at:
                    return True
                self._double_tap_down_at[token] = now
                self._double_tap_ptt_started.discard(token)
                timer = threading.Timer(
                    DOUBLE_TAP_HOLD_THRESHOLD_SECONDS,
                    self._double_tap_hold_timer_fired,
                    args=(token,),
                )
                timer.daemon = True
                self._double_tap_ptt_timers[token] = timer
                timer.start()
        if start_web:
            self._add_web_search_token(token, allow_unconfigured=True)
        return True

    def _handle_double_tap_release(self, token: str) -> bool:
        if not self._web_double_tap_enabled():
            return False
        if token in self._web_search_hold_tokens and self._recording and self._capture_mode == "web":
            with self._double_tap_lock:
                self._double_tap_down_at.pop(token, None)
                self._double_tap_ptt_started.discard(token)
            self._remove_web_search_token(token)
            return True

        now = time.monotonic()
        with self._double_tap_lock:
            down_at = self._double_tap_down_at.pop(token, None)
            timer = self._double_tap_ptt_timers.pop(token, None)
            ptt_started = token in self._double_tap_ptt_started
            self._double_tap_ptt_started.discard(token)
        if timer is not None:
            timer.cancel()
        if ptt_started:
            self._remove_ptt_token(token)
            return True
        if down_at is None:
            return False
        if now - down_at <= DOUBLE_TAP_HOLD_THRESHOLD_SECONDS:
            with self._double_tap_lock:
                self._double_tap_last_up[token] = now
        return True

    @staticmethod
    def _spec_hold_token(spec: str) -> str:
        return f"spec:{spec}"

    def _remove_active_chords_for_modifier(self, mod: str, specs: list[str], *, mode: str) -> None:
        for spec in specs:
            if not is_chord_spec(spec):
                continue
            if mod not in chord_required_modifiers(spec):
                continue
            tok = self._spec_hold_token(spec)
            if mode == "ptt" and tok in self._ptt_hold_tokens:
                self._remove_ptt_token(tok)
            elif mode == "web" and tok in self._web_search_hold_tokens:
                self._remove_web_search_token(tok)

    @Slot()
    def _on_web_search_button_pressed(self) -> None:
        if not self._web_search_enabled():
            self.signals.statusChanged.emit("Web search is disabled in Options.")
            return
        if not self._stt_engine_ready:
            self.signals.statusChanged.emit("Speech engine is still initializing.")
            return
        if self._mic_stt_busy:
            self.signals.statusChanged.emit("Busy transcribing; try again in a moment.")
            return
        self.signals.statusChanged.emit("Recording web query... release button to search.")
        self._start_recording(mode="web")

    @Slot()
    def _on_web_search_button_released(self) -> None:
        self._stop_recording_and_transcribe(mode="web")

    def _register_hotkey(self) -> None:
        self._stop_hotkey_listeners()
        self._ptt_hold_tokens.clear()
        self._web_search_hold_tokens.clear()
        self._keyboard_modifiers_down.clear()
        self._ptt_specs = load_ptt_specs(self._qsettings)
        self._web_search_specs = load_web_search_specs(self._qsettings)
        ptt_specs = self._ptt_specs
        web_specs = self._web_search_specs if self._web_search_enabled() else []

        try:
            if needs_keyboard_listener(ptt_specs) or needs_keyboard_listener(web_specs):

                def on_press(key) -> None:  # type: ignore[no-untyped-def]
                    mod = keyboard_modifier_for_event(key)
                    if mod is not None:
                        self._keyboard_modifiers_down.add(mod)
                    ptt_matches = matching_keyboard_specs(
                        ptt_specs, key, set(self._keyboard_modifiers_down)
                    )
                    if ptt_matches:
                        if len(ptt_matches) == 1 and not is_chord_spec(ptt_matches[0]):
                            if self._handle_double_tap_press(keyboard_token_for_event(key)):
                                return
                        for spec in ptt_matches:
                            tok = (
                                self._spec_hold_token(spec)
                                if is_chord_spec(spec)
                                else keyboard_token_for_event(key)
                            )
                            self._add_ptt_token(tok)
                        return
                    if web_specs:
                        web_matches = matching_keyboard_specs(
                            web_specs, key, set(self._keyboard_modifiers_down)
                        )
                        if web_matches:
                            for spec in web_matches:
                                tok = (
                                    self._spec_hold_token(spec)
                                    if is_chord_spec(spec)
                                    else keyboard_token_for_event(key)
                                )
                                self._add_web_search_token(tok)

                def on_release(key) -> None:  # type: ignore[no-untyped-def]
                    mod = keyboard_modifier_for_event(key)
                    ptt_matches = matching_keyboard_specs(
                        ptt_specs, key, set(self._keyboard_modifiers_down)
                    )
                    if ptt_matches:
                        if len(ptt_matches) == 1 and not is_chord_spec(ptt_matches[0]):
                            handled = self._handle_double_tap_release(
                                keyboard_token_for_event(key)
                            )
                            if mod is not None:
                                self._keyboard_modifiers_down.discard(mod)
                            if handled:
                                return
                        for spec in ptt_matches:
                            tok = (
                                self._spec_hold_token(spec)
                                if is_chord_spec(spec)
                                else keyboard_token_for_event(key)
                            )
                            self._remove_ptt_token(tok)
                    if web_specs:
                        web_matches = matching_keyboard_specs(
                            web_specs, key, set(self._keyboard_modifiers_down)
                        )
                        if web_matches:
                            for spec in web_matches:
                                tok = (
                                    self._spec_hold_token(spec)
                                    if is_chord_spec(spec)
                                    else keyboard_token_for_event(key)
                                )
                                self._remove_web_search_token(tok)
                    if mod is not None:
                        self._remove_active_chords_for_modifier(mod, ptt_specs, mode="ptt")
                        self._remove_active_chords_for_modifier(mod, web_specs, mode="web")
                        self._keyboard_modifiers_down.discard(mod)
                    if ptt_matches:
                        return

                self._keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
                self._keyboard_listener.daemon = True
                self._keyboard_listener.start()

            if needs_mouse_listener(ptt_specs) or needs_mouse_listener(web_specs):

                def on_click(x, y, button, pressed) -> None:  # type: ignore[no-untyped-def]
                    tok = mouse_token_for_button(button)
                    if event_matches_any_spec_mouse(ptt_specs, button):
                        if pressed:
                            if self._handle_double_tap_press(tok):
                                return
                            self._add_ptt_token(tok)
                        else:
                            if self._handle_double_tap_release(tok):
                                return
                            self._remove_ptt_token(tok)
                        return
                    if web_specs and event_matches_any_spec_mouse(web_specs, button):
                        if pressed:
                            self._add_web_search_token(tok)
                        else:
                            self._remove_web_search_token(tok)

                self._mouse_listener = mouse.Listener(on_click=on_click)
                self._mouse_listener.daemon = True
                self._mouse_listener.start()
        except Exception as e:
            self.signals.errorOccurred.emit(f"Hotkey init failed: {type(e).__name__}: {e}")

    def _start_recording(self, *, mode: str) -> None:
        if self._recording or self._mic_stt_busy:
            return

        if mode == "ptt":
            try:
                self._paste_target_hwnd = get_foreground_hwnd()
            except Exception:
                self._paste_target_hwnd = None
        else:
            self._paste_target_hwnd = None

        self._pcm_blocks = []
        self._recording = True
        self._capture_mode = mode
        if mode == "web":
            self.signals.statusChanged.emit("Recording web query... release button to search.")
        else:
            self.signals.statusChanged.emit(
                f"Recording... (release {specs_summary_phrase(self._ptt_specs)} to transcribe)"
            )

        def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
            if not self._recording:
                return
            if status:
                return
            pcm = float_to_int16_pcm(indata)
            with self._pcm_lock:
                self._pcm_blocks.append(pcm)

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            blocksize=1024,
            callback=callback,
        )
        if self._audio_cues_enabled():
            play_recording_started_cue()
        self._stream.start()
        if mode == "ptt":
            self.signals.recordingActive.emit(True)
        else:
            self.signals.webSearchOverlaySyncRequest.emit()

    def _stop_recording(self, *, play_stop_cue: bool = True) -> None:
        if not self._recording:
            return
        mode = self._capture_mode
        self._recording = False
        if mode == "ptt":
            self.signals.recordingActive.emit(False)

        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if play_stop_cue and self._audio_cues_enabled():
            play_recording_stopped_cue()

    def _stop_recording_and_transcribe(self, *, mode: str) -> None:
        if not self._recording:
            return

        if self._mic_stt_busy:
            # If we are already transcribing, just stop recording and drop audio.
            self._stop_recording()
            self.signals.webSearchOverlaySyncRequest.emit()
            self.signals.statusChanged.emit("Transcription busy; try again.")
            return

        self._stop_recording()

        with self._pcm_lock:
            blocks = self._pcm_blocks
            self._pcm_blocks = []

        if not blocks:
            self.signals.webSearchOverlaySyncRequest.emit()
            self.signals.statusChanged.emit("No audio captured.")
            return

        pcm = np.concatenate(blocks)
        # Skip extremely short clips (accidental ctrl taps).
        if pcm.shape[0] < int(self._sample_rate * 0.35):
            self.signals.webSearchOverlaySyncRequest.emit()
            self.signals.statusChanged.emit(
                f"Too short; hold {specs_summary_phrase(self._ptt_specs)} and speak more."
            )
            return

        self.signals.micSttBusy.emit(True)
        self.signals.statusChanged.emit("Transcribing...")
        filter_phrases = self._effective_filter_phrases()
        translate_ru_en_enabled = bool(
            self._qsettings.value(
                TRANSLATE_RU_EN_ENABLED,
                TRANSLATE_RU_EN_ENABLED_DEFAULT,
                type=bool,
            )
        )
        translation_fetch_ok = bool(
            self._qsettings.value(
                TRANSLATION_MODEL_FETCH_APPROVED,
                TRANSLATION_MODEL_FETCH_APPROVED_DEFAULT,
                type=bool,
            )
        )

        def _job(pcm_data: np.ndarray, capture_mode: str) -> None:
            if capture_mode == "web":
                self.signals.webSearchPipelineJobStarted.emit()
            try:
                with tempfile.TemporaryDirectory(prefix="potato-stt-audio-") as tmpdir:
                    wav_path = os.path.join(tmpdir, f"talk_{int(time.time()*1000)}.wav")
                    write_wav_from_int16_pcm(pcm_data, wav_path, sample_rate=self._sample_rate)

                    t0 = time.time()
                    if self.settings.stt_backend.lower() == "onnx_asr":
                        if self._onnx_engine is None:
                            raise RuntimeError("ONNX ASR engine is not initialized.")
                        text = self._onnx_engine.transcribe_wav(wav_path)
                    else:
                        text = transcribe_wav(
                            wav_path,
                            api_url=self.settings.stt_api_url,
                            model=self.settings.stt_model,
                            response_format=self.settings.stt_response_format,
                            timeout_seconds=self.settings.stt_timeout_seconds,
                        )
                    took = time.time() - t0
                    cleaned = postprocess_transcript_text(text, filter_phrases=filter_phrases)
                    if cleaned:
                        self.signals.transcriptAppend.emit(cleaned)
                        if capture_mode == "web":
                            self.signals.micSttBusy.emit(False)
                            self.signals.statusChanged.emit("Searching web with OpenCode...")
                            with self._web_opencode_semaphore:
                                summary = self._run_opencode_web_search(cleaned)
                            self.signals.webSearchReady.emit(cleaned, summary)
                            self.signals.statusChanged.emit(
                                f"Web summary ready in {took:.1f}s + search time. Ready. Hold "
                                f"{specs_summary_phrase(self._ptt_specs)} to talk."
                            )
                        else:
                            to_paste = cleaned
                            if translate_ru_en_enabled:
                                self.signals.statusChanged.emit("Translating to English…")

                                def _tr_status(msg: str) -> None:
                                    self.signals.statusChanged.emit(msg)

                                tr = _translation_marian_module().translate_ru_en
                                to_paste = tr(
                                    cleaned,
                                    on_status=_tr_status,
                                    model_fetch_allowed=translation_fetch_ok,
                                )
                                if to_paste.strip() != cleaned.strip():
                                    self.signals.transcriptAppend.emit(
                                        f"{to_paste.strip()}"
                                    )
                            self.signals.transcriptReady.emit(to_paste)
                            self.signals.statusChanged.emit(
                                f"Transcribed in {took:.1f}s. Ready. Hold "
                                f"{specs_summary_phrase(self._ptt_specs)} to talk."
                            )
                    else:
                        self.signals.webSearchOverlaySyncRequest.emit()
                        self.signals.statusChanged.emit("No speech recognized. Ready.")
            except Exception as e:
                self.signals.webSearchOverlaySyncRequest.emit()
                self.signals.errorOccurred.emit(f"{type(e).__name__}: {e}")
            finally:
                self.signals.micSttBusy.emit(False)
                if capture_mode == "web":
                    self.signals.webSearchPipelineJobFinished.emit()
                self._capture_mode = None

        threading.Thread(target=_job, args=(pcm, mode), daemon=True).start()

    def _run_opencode_web_search(self, query: str) -> str:
        opencode_bin = shutil.which("opencode")
        if not opencode_bin:
            raise RuntimeError(
                "OpenCode CLI not found in PATH. Install OpenCode or add it to PATH."
            )
        query = query.strip()
        if not query:
            raise RuntimeError("No search query was recognized from the recording.")
        prompt = (
            f"Search the web for this exact user query: {query}\n\n"
            f"User query: {query}\n\n"
            "Do not ask the user for another query. The query above is the complete query.\n"
            "Use OpenCode's websearch tool before answering.\n\n"
            "Return:\n"
            "- A concise answer in 4-8 bullets.\n"
            "- Practical takeaways first.\n"
            "- A final Sources section with clickable URLs.\n"
            "- A short uncertainty note if sources disagree or evidence is weak."
        )
        # Capture bytes: on some Windows setups `text=True` still wraps pipes with the system
        # code page (e.g. cp1251), which raises UnicodeDecodeError in subprocess._readerthread
        # and mojibakes UTF-8 output. Decode as UTF-8 in-process instead.
        _opencode_env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        try:
            proc = subprocess.run(
                [opencode_bin, "run", "--format", "default", prompt],
                capture_output=True,
                text=False,
                env=_opencode_env,
                timeout=max(45, int(self.settings.stt_timeout_seconds) * 6),
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                "OpenCode timed out while generating a web summary. "
                "Try a shorter query or check provider/auth setup."
            ) from e
        out_raw = proc.stdout if proc.stdout is not None else b""
        err_raw = proc.stderr if proc.stderr is not None else b""
        if proc.returncode != 0:
            detail = self._strip_ansi(
                (self._decode_cli_bytes(err_raw) + self._decode_cli_bytes(out_raw)).strip()
            )
            raise RuntimeError(f"OpenCode failed (exit {proc.returncode}): {detail}")
        out = self._strip_ansi(self._decode_cli_bytes(out_raw).strip())
        if not out:
            raise RuntimeError("OpenCode returned an empty response.")
        return out

    @staticmethod
    def _decode_cli_bytes(data: bytes | bytearray) -> str:
        if not data:
            return ""
        return bytes(data).decode("utf-8", errors="replace")

    @staticmethod
    def _strip_ansi(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)

    @Slot(str, str)
    def _on_web_search_ready(self, query: str, summary: str) -> None:
        append_history_entry(self._qsettings, query=query, summary_md=summary)
        self._show_web_summary_nonmodal(query, summary)
        if self._tray_icon is not None:
            qtitle = query.strip().replace("\n", " ")
            if len(qtitle) > 64:
                qtitle = qtitle[:61] + "…"
            self._pending_tray_web_summary = (query, summary)
            self._tray_icon.showMessage(
                qtitle or "Web search",
                tray_message_body(summary),
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )
        self.signals.webSearchOverlaySyncRequest.emit()


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
    if not _acquire_single_instance():
        QMessageBox.warning(
            None,
            "Potato STT",
            "Another instance of Potato STT is already running.",
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

