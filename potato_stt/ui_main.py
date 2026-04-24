from __future__ import annotations

import math
import os
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
    event_matches_any_spec_keyboard,
    event_matches_any_spec_mouse,
    keyboard_token_for_event,
    load_ptt_specs,
    mouse_token_for_button,
    needs_keyboard_listener,
    needs_mouse_listener,
    save_ptt_specs,
    spec_label,
    specs_summary_phrase,
)
from potato_stt.win32_startup import (
    is_run_at_startup_enabled,
    set_run_at_startup_enabled,
)

# QSettings keys (same org/app as push-to-talk keys).
START_MINIMIZED_SETTING = "ui/start_minimized"
TRANSCRIPT_FILTER_ENABLED = "ui/transcript_filter_enabled"
TRANSCRIPT_FILTER_WORDS = "ui/transcript_filter_words"
TRANSLATE_RU_EN_ENABLED = "ui/translate_ru_en_enabled"
TRANSLATION_MODEL_FETCH_APPROVED = "ui/translation_model_fetch_approved"
# First-run defaults (used when keys are absent; existing QSettings win once saved).
TRANSCRIPT_FILTER_ENABLED_DEFAULT = True
TRANSCRIPT_FILTER_WORDS_DEFAULT = "uh\num"
TRANSLATE_RU_EN_ENABLED_DEFAULT = False
TRANSLATION_MODEL_FETCH_APPROVED_DEFAULT = False


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
    """Modal capture: first key or mouse button wins; Cancel / Escape abort."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add push-to-talk key")
        self.setModal(True)
        self._cancel = threading.Event()
        self._notifier = _CaptureNotifier(self)
        self._notifier.finished.connect(self._on_capture_finished)
        self._captured_spec = ""
        self._capture_started = False
        v = QVBoxLayout(self)
        v.addWidget(
            QLabel(
                "Press a keyboard key or click a mouse button.\n"
                "Escape cancels. The first input is saved."
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

    def _populate_ptt_list(self) -> None:
        self._ptt_list.clear()
        for spec in load_ptt_specs(self._settings):
            it = QListWidgetItem(spec_label(spec))
            it.setData(Qt.ItemDataRole.UserRole, spec)
            self._ptt_list.addItem(it)

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
        self._stt_engine_ready = False
        # True only for File → Quit / tray Quit so closeEvent exits instead of hiding to tray.
        self._requesting_full_quit = False

        self._status_label = QLabel("Initializing...")
        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFormat("Starting...")

        self._options_win: Optional[OptionsWindow] = None

        root = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self._status_label)
        layout.addWidget(self._progress)
        layout.addLayout(QHBoxLayout())
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

        self._recording_overlay = RecordingOverlay()
        self._recording_overlay.hide()

        # Microphone state.
        self._sample_rate = 16000
        self._channels = 1
        self._pcm_lock = threading.Lock()
        self._pcm_blocks: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._recording = False
        self._transcribing = False
        self._ptt_hold_tokens: set[str] = set()
        self._onnx_engine: Optional[OnnxAsrEngine] = None
        # Window that had focus when push-to-talk started (for paste target).
        self._paste_target_hwnd: Optional[int] = None

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
            if sys.platform == "win32":
                act_tray_clear = QAction("Clear local data…", self)
                act_tray_clear.triggered.connect(self._on_clear_local_data)
                tray_menu.addAction(act_tray_clear)
            act_quit = QAction("Quit", self)
            act_quit.triggered.connect(self._quit_application)
            tray_menu.addAction(act_quit)
            tray.setContextMenu(tray_menu)
            tray.activated.connect(self._on_tray_activated)
            tray.show()
            self._tray_icon = tray

        self._sync_tray_ptt_tooltip()

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
        if self._options_win is not None:
            self._options_win.close()
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
            if self._options_win is not None:
                self._options_win.hide()
            self.hide()
            return
        if not self._requesting_full_quit:
            self._shutdown()
        super().closeEvent(event)

    def _stop_hotkey_listeners(self) -> None:
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
            "",
            "Use File → Transcribe media file… to transcribe an existing audio or video file.",
            "Use Settings → Options… (Ctrl+,) to change push-to-talk keys, startup behavior, filters, "
            "and optional translation.",
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
        if self._transcribing:
            QMessageBox.information(
                self,
                "Transcribe file",
                "A transcription is already in progress.",
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
        if self._transcribing:
            return
        self._transcribing = True
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
                self._transcribing = False

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

    @Slot(bool)
    def _on_recording_overlay(self, active: bool) -> None:
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
        before = len(self._ptt_hold_tokens)
        self._ptt_hold_tokens.add(token)
        if before == 0 and len(self._ptt_hold_tokens) > 0:
            self.signals.statusChanged.emit(
                f"{specs_summary_phrase(self._ptt_specs)} — recording..."
            )
            self._start_recording()

    def _remove_ptt_token(self, token: str) -> None:
        self._ptt_hold_tokens.discard(token)
        if len(self._ptt_hold_tokens) == 0:
            self._stop_recording_and_transcribe()

    def _register_hotkey(self) -> None:
        self._stop_hotkey_listeners()
        self._ptt_hold_tokens.clear()
        self._ptt_specs = load_ptt_specs(self._qsettings)
        specs = self._ptt_specs

        try:
            if needs_keyboard_listener(specs):

                def on_press(key) -> None:  # type: ignore[no-untyped-def]
                    if not event_matches_any_spec_keyboard(specs, key):
                        return
                    self._add_ptt_token(keyboard_token_for_event(key))

                def on_release(key) -> None:  # type: ignore[no-untyped-def]
                    if not event_matches_any_spec_keyboard(specs, key):
                        return
                    self._remove_ptt_token(keyboard_token_for_event(key))

                self._keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
                self._keyboard_listener.daemon = True
                self._keyboard_listener.start()

            if needs_mouse_listener(specs):

                def on_click(x, y, button, pressed) -> None:  # type: ignore[no-untyped-def]
                    if not event_matches_any_spec_mouse(specs, button):
                        return
                    tok = mouse_token_for_button(button)
                    if pressed:
                        self._add_ptt_token(tok)
                    else:
                        self._remove_ptt_token(tok)

                self._mouse_listener = mouse.Listener(on_click=on_click)
                self._mouse_listener.daemon = True
                self._mouse_listener.start()
        except Exception as e:
            self.signals.errorOccurred.emit(f"Hotkey init failed: {type(e).__name__}: {e}")

    def _start_recording(self) -> None:
        if self._recording or self._transcribing:
            return

        try:
            self._paste_target_hwnd = get_foreground_hwnd()
        except Exception:
            self._paste_target_hwnd = None

        self._pcm_blocks = []
        self._recording = True
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
        play_recording_started_cue()
        self._stream.start()
        self.signals.recordingActive.emit(True)

    def _stop_recording(self, *, play_stop_cue: bool = True) -> None:
        if not self._recording:
            return
        self._recording = False
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
        if play_stop_cue:
            play_recording_stopped_cue()

    def _stop_recording_and_transcribe(self) -> None:
        if not self._recording:
            return

        if self._transcribing:
            # If we are already transcribing, just stop recording and drop audio.
            self._stop_recording()
            self.signals.statusChanged.emit("Transcription busy; try again.")
            return

        self._stop_recording()

        with self._pcm_lock:
            blocks = self._pcm_blocks
            self._pcm_blocks = []

        if not blocks:
            self.signals.statusChanged.emit("No audio captured.")
            return

        pcm = np.concatenate(blocks)
        # Skip extremely short clips (accidental ctrl taps).
        if pcm.shape[0] < int(self._sample_rate * 0.35):
            self.signals.statusChanged.emit(
                f"Too short; hold {specs_summary_phrase(self._ptt_specs)} and speak more."
            )
            return

        self._transcribing = True
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

        def _job(pcm_data: np.ndarray) -> None:
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
            except Exception as e:
                self.signals.errorOccurred.emit(f"{type(e).__name__}: {e}")
            finally:
                self._transcribing = False

        threading.Thread(target=_job, args=(pcm,), daemon=True).start()


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

