from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import sounddevice as sd
from PySide6.QtCore import (
    QSettings,
    Qt,
    Slot,
    QTimer,
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from potato_stt.config import Settings
from potato_stt.controllers.ffmpeg_install_helper import (
    try_start_ffmpeg_winget_install as _try_start_ffmpeg_winget_install,
)
from potato_stt.controllers.file_transcribe_controller import FileTranscribeController
from potato_stt.controllers.hotkey_controller import (
    HotkeyCallbacks,
    HotkeyController,
)
from potato_stt.controllers.recording_controller import RecordingController
from potato_stt.controllers.transcription_controller import TranscriptionController
from potato_stt.controllers.translation_coordinator import TranslationCoordinator
from potato_stt.controllers.web_search_coordinator import WebSearchCoordinator
from potato_stt.core.onnx_asr_engine import OnnxAsrEngine
from potato_stt.core.parakeet_windows_installer import ensure_parakeet_service
from potato_stt.core.transcript_utils import (
    finalize_sentence_for_clipboard,
    parse_filter_phrases,
)
from potato_stt.input.multi_tap import MultiTapStateMachine
from potato_stt.input.command_tap import CommandTapStateMachine
from potato_stt.input.ptt_keys import (
    load_command_tap_specs,
    load_ptt_specs,
    load_web_search_specs,
    specs_summary_phrase,
)
from potato_stt.platform.win32_paste import (
    is_window,
    send_ctrl_v_keybd_event,
    set_foreground_hwnd,
)
from potato_stt.i18n import init_localization, tr
from potato_stt.settings_keys import (
    AUDIO_CUES_ENABLED,
    AUDIO_CUES_ENABLED_DEFAULT,
    DOUBLE_TAP_WINDOW_MS_MAX,
    DOUBLE_TAP_WINDOW_MS_MIN,
    COMMAND_TAPS_ARGV_DOUBLE,
    COMMAND_TAPS_ARGV_QUADRUPLE,
    COMMAND_TAPS_ARGV_SINGLE,
    COMMAND_TAPS_ARGV_TRIPLE,
    COMMAND_TAPS_ENABLED,
    COMMAND_TAPS_ENABLED_DEFAULT,
    COMMAND_TAPS_USE_SHELL,
    COMMAND_TAPS_USE_SHELL_DEFAULT,
    COMMAND_TAPS_WINDOW_MS,
    COMMAND_TAPS_WINDOW_MS_DEFAULT,
    TRANSCRIPT_FILTER_ENABLED,
    TRANSCRIPT_FILTER_ENABLED_DEFAULT,
    TRANSCRIPT_FILTER_WORDS,
    TRANSCRIPT_FILTER_WORDS_DEFAULT,
    VISUAL_CUES_ENABLED,
    VISUAL_CUES_ENABLED_DEFAULT,
    WEB_DOUBLE_TAP_ENABLED,
    WEB_DOUBLE_TAP_ENABLED_DEFAULT,
    WEB_DOUBLE_TAP_WINDOW_MS,
    WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT,
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_ENABLED_DEFAULT,
    WEB_TRAY_MESSAGE_MS_WHEN_HIDDEN,
)
from potato_stt.ui.dialogs.clear_data import show_clear_local_data_dialog
from potato_stt.ui.dialogs.ffmpeg_missing import show_ffmpeg_missing_dialog
from potato_stt.ui.dialogs.help_dialog import show_using_help_dialog
from potato_stt.ui.dialogs.web_summary import WebSummaryDialog
from potato_stt.ui.icon import build_app_icon
from potato_stt.ui.signals import AppSignals
from potato_stt.ui.status_format import format_status_to_progress
from potato_stt.ui.widgets.overlays import RecordingOverlay, WebSearchOverlay
from potato_stt.ui.windows.options_window import OptionsWindow
from potato_stt.ui.windows.web_search_history_window import WebSearchHistoryWindow
from potato_stt.web_search.history import (
    append_history_entry,
    count_unread_entries,
    load_history_entries,
    mark_history_entry,
    tray_message_body,
)
from potato_stt.commands.runner import run_transcript_command


class MainWindow(QMainWindow):
    def __init__(self, app_icon: Optional[QIcon] = None) -> None:
        super().__init__()
        self._qsettings = QSettings("PotatoSTT", "PotatoSTT")
        init_localization(self._qsettings)
        self.setWindowTitle(tr("Potato STT — Push-to-talk"))
        self.setMinimumWidth(820)

        self._app_icon = app_icon if app_icon is not None else build_app_icon()
        self.setWindowIcon(self._app_icon)

        self.settings = Settings()
        self._ptt_specs: list[str] = load_ptt_specs(self._qsettings)
        self._web_search_specs: list[str] = load_web_search_specs(self._qsettings)
        self._command_tap_specs: list[str] = load_command_tap_specs(self._qsettings)
        self._stt_engine_ready = False
        # True only for File → Quit / tray Quit so closeEvent exits instead of hiding to tray.
        self._requesting_full_quit = False

        self._status_label = QLabel(tr("Initializing..."))
        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._web_search_btn = QPushButton(tr("Hold to Ask Web"))
        self._web_search_btn.setToolTip(
            tr(
                "Press and hold to record a web search query. Release to transcribe and ask OpenCode for a web summary."
            )
        )
        self._web_search_btn.pressed.connect(self._on_web_search_button_pressed)
        self._web_search_btn.released.connect(self._on_web_search_button_released)
        self._web_hist_btn = QPushButton(tr("Web history"))
        self._web_hist_btn.setToolTip(
            tr("Open past web searches. Highlights when there are unread results.")
        )
        self._web_hist_btn.clicked.connect(self._open_web_search_history_from_button)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFormat(tr("Starting..."))

        self._options_win: Optional[OptionsWindow] = None

        root = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self._status_label)
        layout.addWidget(self._progress)
        web_btn_row = QHBoxLayout()
        web_btn_row.addWidget(self._web_search_btn, 0, Qt.AlignmentFlag.AlignLeft)
        web_btn_row.addWidget(self._web_hist_btn, 0, Qt.AlignmentFlag.AlignLeft)
        web_btn_row.addStretch(1)
        layout.addLayout(web_btn_row)
        layout.addWidget(self._transcript)
        root.setLayout(layout)
        self.setCentralWidget(root)

        _file_menu = self.menuBar().addMenu(tr("&File"))
        act_transcribe_file = QAction(tr("Transcribe media file…"), self)
        act_transcribe_file.triggered.connect(self._on_transcribe_file_chosen)
        _file_menu.addAction(act_transcribe_file)
        _file_menu.addSeparator()
        act_quit_menu = QAction(tr("&Quit"), self)
        act_quit_menu.setShortcut("Ctrl+Q")
        act_quit_menu.triggered.connect(self._quit_application)
        _file_menu.addAction(act_quit_menu)

        _settings_menu = self.menuBar().addMenu(tr("&Settings"))
        act_options_menu = QAction(tr("&Options…"), self)
        act_options_menu.setShortcut("Ctrl+,")
        act_options_menu.triggered.connect(self._open_options)
        _settings_menu.addAction(act_options_menu)
        act_web_hist = QAction(tr("Web search &history…"), self)
        act_web_hist.triggered.connect(self._open_web_search_history_menu)
        _settings_menu.addAction(act_web_hist)

        _help_menu = self.menuBar().addMenu(tr("&Help"))
        act_using_help = QAction(tr("Using Potato STT…"), self)
        act_using_help.triggered.connect(self._show_using_help_dialog)
        _help_menu.addAction(act_using_help)
        if sys.platform == "win32":
            _help_menu.addSeparator()
            act_clear_data = QAction(tr("Clear local data (uninstall caches)…"), self)
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

        self._sample_rate = 16000
        self._channels = 1
        self._web_search_pipeline_jobs = 0
        self._ptt_hold_tokens: set[str] = set()
        self._web_search_hold_tokens: set[str] = set()
        self._onnx_engine: Optional[OnnxAsrEngine] = None

        self._recording_ctrl = RecordingController(
            signals=self.signals,
            sample_rate=self._sample_rate,
            channels=self._channels,
            audio_cues_enabled=self._audio_cues_enabled,
            ptt_status_phrase=lambda: specs_summary_phrase(self._ptt_specs),
        )
        self._web_search_ctrl = WebSearchCoordinator(
            qsettings=self._qsettings,
            settings=self.settings,
        )
        self._translation_ctrl = TranslationCoordinator(
            parent=self,
            qsettings=self._qsettings,
            signals=self.signals,
            sync_options_checkbox=self._sync_options_translate_checkbox,
            ptt_status_phrase=lambda: specs_summary_phrase(self._ptt_specs),
        )
        self._file_transcribe_ctrl = FileTranscribeController(
            qsettings=self._qsettings,
            settings=self.settings,
            signals=self.signals,
            onnx_engine_provider=lambda: self._onnx_engine,
            ptt_specs_provider=lambda: list(self._ptt_specs),
            filter_phrases_provider=self._effective_filter_phrases,
        )
        self._transcribe_ctrl = TranscriptionController(
            qsettings=self._qsettings,
            settings=self.settings,
            signals=self.signals,
            recording=self._recording_ctrl,
            translation=self._translation_ctrl,
            web_search=self._web_search_ctrl,
            onnx_engine_provider=lambda: self._onnx_engine,
            ptt_specs_provider=lambda: list(self._ptt_specs),
            filter_phrases_provider=self._effective_filter_phrases,
            command_handler=self._run_tap_command_capture,
        )
        self._multi_tap = MultiTapStateMachine(
            is_enabled=self._web_double_tap_enabled,
            delay_seconds=self._double_tap_delay_seconds,
            mode=self._multi_tap_mode,
            add_ptt=self._add_ptt_token,
            remove_ptt=self._remove_ptt_token,
            add_web=lambda tok: self._add_web_search_token(tok, allow_unconfigured=True),
            remove_web=self._remove_web_search_token,
            is_web_active=self._is_token_web_active,
        )
        self._command_tap = CommandTapStateMachine(
            is_enabled=self._command_taps_enabled,
            delay_seconds=self._command_tap_delay_seconds,
            begin_capture=self._begin_command_tap_capture,
            end_capture=self._end_command_tap_capture,
        )
        self._command_tap_capture_by_token: dict[str, int] = {}
        self._hotkey_ctrl = HotkeyController(
            HotkeyCallbacks(
                add_ptt=self._add_ptt_token,
                remove_ptt=self._remove_ptt_token,
                add_web=self._add_web_search_token,
                remove_web=self._remove_web_search_token,
                handle_multi_tap_press=self._handle_double_tap_press,
                handle_multi_tap_release=self._handle_double_tap_release,
                has_ptt_token=lambda tok: tok in self._ptt_hold_tokens,
                has_web_token=lambda tok: tok in self._web_search_hold_tokens,
                on_error=lambda msg: self.signals.errorOccurred.emit(msg),
                handle_command_tap_press=self._handle_command_tap_press,
                handle_command_tap_release=self._handle_command_tap_release,
            )
        )

        self._web_summary_dialog: Optional[WebSummaryDialog] = None
        self._web_search_history_win: Optional[WebSearchHistoryWindow] = None

        self._tray_icon: Optional[QSystemTrayIcon] = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon(self)
            tray.setIcon(self._app_icon)
            tray.setToolTip(
                tr("Ready. Hold {ptt} to talk.").format(ptt=specs_summary_phrase(self._ptt_specs))
            )
            tray_menu = QMenu()
            act_show = QAction(tr("Show"), self)
            act_show.triggered.connect(self._show_from_tray)
            tray_menu.addAction(act_show)
            act_tray_file = QAction(tr("Transcribe media file…"), self)
            act_tray_file.triggered.connect(self._on_transcribe_file_chosen)
            tray_menu.addAction(act_tray_file)
            act_tray_web_hist = QAction(tr("Web search &history…"), self)
            act_tray_web_hist.triggered.connect(self._open_web_search_history_menu)
            tray_menu.addAction(act_tray_web_hist)
            if sys.platform == "win32":
                act_tray_clear = QAction(tr("Clear local data…"), self)
                act_tray_clear.triggered.connect(self._on_clear_local_data)
                tray_menu.addAction(act_tray_clear)
            act_quit = QAction(tr("Quit"), self)
            act_quit.triggered.connect(self._quit_application)
            tray_menu.addAction(act_quit)
            tray.setContextMenu(tray_menu)
            tray.activated.connect(self._on_tray_activated)
            tray.messageClicked.connect(self._on_tray_message_clicked)
            tray.show()
            self._tray_icon = tray

        self._sync_tray_ptt_tooltip()
        self._web_search_btn.setEnabled(self._web_search_enabled())
        self._web_hist_btn.setEnabled(self._web_search_enabled())
        self._refresh_web_history_unread_ui()

        # Start engine ensure in background, then register hotkey.
        threading.Thread(target=self._ensure_engine_and_start_hotkey, daemon=True).start()

    def has_system_tray(self) -> bool:
        return self._tray_icon is not None

    # --- compatibility properties bridging to controllers ---------------------

    @property
    def _recording(self) -> bool:
        return self._recording_ctrl.is_recording

    @property
    def _mic_stt_busy(self) -> bool:
        return self._recording_ctrl.mic_stt_busy

    @_mic_stt_busy.setter
    def _mic_stt_busy(self, value: bool) -> None:
        self._recording_ctrl.mic_stt_busy = value

    @property
    def _capture_mode(self) -> Optional[str]:
        return self._recording_ctrl.capture_mode

    @_capture_mode.setter
    def _capture_mode(self, value: Optional[str]) -> None:
        self._recording_ctrl.capture_mode = value

    @property
    def _paste_target_hwnd(self) -> Optional[int]:
        return self._recording_ctrl.paste_target_hwnd

    @property
    def _file_transcribe_busy(self) -> bool:
        return self._file_transcribe_ctrl.busy

    @property
    def _web_opencode_semaphore(self) -> threading.Semaphore:
        return self._web_search_ctrl.semaphore

    @property
    def _pending_tray_web_summary(self) -> Optional[tuple[float, str, str]]:
        return self._web_search_ctrl.pending_tray_summary

    @_pending_tray_web_summary.setter
    def _pending_tray_web_summary(self, value: Optional[tuple[float, str, str]]) -> None:
        self._web_search_ctrl.pending_tray_summary = value

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
        self._hotkey_ctrl.stop()

    @Slot()
    def _show_using_help_dialog(self) -> None:
        show_using_help_dialog(
            self,
            ptt_phrase=specs_summary_phrase(self._ptt_specs),
            has_tray=self._tray_icon is not None,
        )

    def _sync_tray_ptt_tooltip(self) -> None:
        ptt = specs_summary_phrase(self._ptt_specs)
        if self._tray_icon is not None:
            self._tray_icon.setToolTip(tr("Ready. Hold {ptt} to talk.").format(ptt=ptt))

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
    def _on_command_tap_key_setting_changed(self) -> None:
        self._command_tap_specs = load_command_tap_specs(self._qsettings)
        self.restart_ptt_listeners()

    @Slot()
    def _on_visual_cue_setting_changed(self) -> None:
        if not self._visual_cues_enabled():
            self._recording_overlay.hide()
            self._web_search_overlay.hide()
        else:
            self._sync_web_search_overlay()
        self._refresh_web_history_unread_ui()

    @Slot()
    def _on_web_search_enabled_changed(self) -> None:
        self._web_search_btn.setEnabled(self._web_search_enabled())
        self._web_hist_btn.setEnabled(self._web_search_enabled())
        if not self._web_search_enabled():
            self._web_search_hold_tokens.clear()
            self._cancel_double_tap_timers()
            if self._recording and self._capture_mode == "web":
                self._stop_recording(play_stop_cue=True)
                self._capture_mode = None
            self._web_search_overlay.hide()
        self.restart_ptt_listeners()

    def _refresh_web_history_unread_ui(self) -> None:
        n = count_unread_entries(load_history_entries(self._qsettings))
        base = tr("Open past web searches.")
        unread_tip = tr("Open past web searches. ({unread} unread.)").format(unread=n)
        self._web_hist_btn.setToolTip(unread_tip if n else base)
        if not self._visual_cues_enabled():
            self._web_hist_btn.setStyleSheet("")
            return
        if n > 0:
            self._web_hist_btn.setStyleSheet(
                "QPushButton { padding: 4px 10px; border-radius: 4px; "
                "border: 2px solid #f59e0b; color: #fbbf24; font-weight: 600; }"
            )
        else:
            self._web_hist_btn.setStyleSheet("")

    def _on_web_history_store_changed(self) -> None:
        self._refresh_web_history_unread_ui()
        win = self._web_search_history_win
        if win is not None and win.isVisible():
            win.refresh_from_settings()

    def _mark_web_history_read(self, ts: float, query: str, summary: str) -> None:
        qn = query.strip()
        sn = summary.strip()

        def _match(e: dict[str, Any]) -> bool:
            ets = e.get("ts")
            if not isinstance(ets, (int, float)) or float(ets) != float(ts):
                return False
            if str(e.get("query", "")).strip() != qn:
                return False
            return str(e.get("summary_md", "")).strip() == sn

        if mark_history_entry(self._qsettings, _match, read=True) > 0:
            self._on_web_history_store_changed()

    @Slot()
    def _open_web_search_history_from_button(self) -> None:
        self._open_web_search_history(focus_last_unread=True)

    @Slot()
    def _open_web_search_history_menu(self) -> None:
        self._open_web_search_history(focus_last_unread=False)

    @Slot()
    def _open_web_search_history(self, *, focus_last_unread: bool = False) -> None:
        if self._web_search_history_win is None:
            self._web_search_history_win = WebSearchHistoryWindow(
                self._qsettings,
                self,
                on_history_mutated=self._on_web_history_store_changed,
            )
        self._web_search_history_win.show()
        self._web_search_history_win.raise_()
        self._web_search_history_win.activateWindow()
        if focus_last_unread:
            self._web_search_history_win.focus_last_unread()

    def restart_ptt_listeners(self) -> None:
        if not self._stt_engine_ready:
            return
        self._stop_hotkey_listeners()
        self._register_hotkey()

    @Slot()
    def _open_options(self) -> None:
        if self._options_win is None:
            self._options_win = OptionsWindow(self, self._qsettings)
        self._options_win.sync_ptt_from_settings()
        self._options_win.sync_web_search_from_settings()
        self._options_win.sync_cues_from_settings()
        self._options_win.sync_translate_from_settings()
        self._options_win.show()
        self._options_win.raise_()
        self._options_win.activateWindow()

    def _show_local_translation_consent_warning(self) -> bool:
        return self._translation_ctrl.show_consent_warning()

    def _continue_local_translation_enable_after_consent(self) -> bool:
        return self._translation_ctrl.continue_enable_after_consent()

    def _sync_options_translate_checkbox(self) -> None:
        if self._options_win is not None:
            self._options_win.sync_translate_from_settings()

    @Slot()
    def _on_language_setting_changed(self) -> None:
        init_localization(self._qsettings)
        QMessageBox.information(
            self,
            tr("Options"),
            tr("Language preference saved. Restart Potato STT to apply all labels."),
        )

    def _start_translation_model_preload(self) -> None:
        self._translation_ctrl.start_preload()

    @Slot(bool, str)
    def _on_translation_model_preload_finished(self, ok: bool, err: str) -> None:
        self._translation_ctrl.on_preload_finished(ok, err)

    @Slot()
    def _on_clear_local_data(self) -> None:
        show_clear_local_data_dialog(self)

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
                tr("Transcribe file"),
                tr(
                    "The speech engine is still getting ready. Wait until startup finishes, then try again."
                ),
            )
            return
        if self._file_transcribe_busy:
            QMessageBox.information(
                self,
                tr("Transcribe file"),
                tr("A file transcription is already in progress."),
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Open audio or video"),
            "",
            tr("Media (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mkv *.webm *.mov *.avi);;All files (*.*)"),
        )
        if not path:
            return
        self._start_file_transcribe(Path(path))

    def _start_file_transcribe(self, source_path: Path) -> None:
        self._file_transcribe_ctrl.start(source_path)

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
            tr("Save subtitles"),
            default_path,
            tr("SubRip (*.srt);;WebVTT (*.vtt)"),
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
    def _on_tray_message_clicked(self) -> None:
        payload = self._pending_tray_web_summary
        if payload is None:
            return
        ts, q, s = payload
        self._show_web_summary_nonmodal(q, summary=s, history_ts=ts)

    def _show_web_summary_nonmodal(
        self, query: str, *, summary: str, history_ts: Optional[float] = None
    ) -> None:
        if self._web_summary_dialog is None:
            self._web_summary_dialog = WebSummaryDialog(self)
        self._web_summary_dialog.show(query=query, summary=summary)
        if history_ts is not None:
            self._mark_web_history_read(history_ts, query, summary)

    def _should_auto_show_web_summary_window(self) -> bool:
        """Show the in-app summary only when the main window is actually on screen."""
        if not self.isVisible():
            return False
        if self.windowState() & Qt.WindowState.WindowMinimized:
            return False
        return True

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
        show_ffmpeg_missing_dialog(
            self,
            try_start_winget_install=_try_start_ffmpeg_winget_install,
        )

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat(tr("Failed"))

    @Slot(str)
    def _on_status_update(self, msg: str) -> None:
        self._status_label.setText(msg)
        state = format_status_to_progress(msg)
        self._progress.setRange(state.range_min, state.range_max)
        if state.value is not None:
            self._progress.setValue(state.value)
        self._progress.setFormat(state.fmt)

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
                _on_status(tr("Preparing ONNX ASR engine (first model load may take time)..."))
                self._onnx_engine.warmup(on_status=_on_status)
            else:
                api_url = self.settings.stt_api_url
                # stt_api_url is .../v1/audio/transcriptions
                api_base = api_url.rsplit("/audio/transcriptions", 1)[0]
                api_host = "127.0.0.1"
                api_port = 5092
                _on_status(
                    tr("Preparing Parakeet HTTP STT engine (download/first model load may take time)...")
                )
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
        _on_status(
            tr("Ready. Hold {ptt} to talk.").format(ptt=specs_summary_phrase(self._ptt_specs))
        )
        self._register_hotkey()

    def _add_ptt_token(self, token: str) -> None:
        if self._recording and self._capture_mode == "web":
            return
        before = len(self._ptt_hold_tokens)
        self._ptt_hold_tokens.add(token)
        if before == 0 and len(self._ptt_hold_tokens) > 0:
            self.signals.statusChanged.emit(
                tr("{ptt} — recording...").format(ptt=specs_summary_phrase(self._ptt_specs))
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
                self.signals.statusChanged.emit(tr("Speech engine is still initializing."))
                return
            self.signals.statusChanged.emit(tr("Recording web query... release key to search."))
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

    def _double_tap_delay_seconds(self) -> float:
        raw = int(
            self._qsettings.value(
                WEB_DOUBLE_TAP_WINDOW_MS,
                WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT,
                type=int,
            )
        )
        ms = max(DOUBLE_TAP_WINDOW_MS_MIN, min(DOUBLE_TAP_WINDOW_MS_MAX, raw))
        return ms / 1000.0

    def _cancel_double_tap_timers(self) -> None:
        self._multi_tap.cancel_all()
        self._command_tap.cancel_all()

    def _command_taps_enabled(self) -> bool:
        return bool(
            self._qsettings.value(
                COMMAND_TAPS_ENABLED,
                COMMAND_TAPS_ENABLED_DEFAULT,
                type=bool,
            )
        )

    def _command_tap_delay_seconds(self) -> float:
        raw = int(
            self._qsettings.value(
                COMMAND_TAPS_WINDOW_MS,
                COMMAND_TAPS_WINDOW_MS_DEFAULT,
                type=int,
            )
        )
        ms = max(DOUBLE_TAP_WINDOW_MS_MIN, min(DOUBLE_TAP_WINDOW_MS_MAX, raw))
        return ms / 1000.0

    def _multi_tap_mode(self) -> str:
        return OptionsWindow._stored_multi_tap_mode(self._qsettings)

    def _is_token_web_active(self, token: str) -> bool:
        return (
            token in self._web_search_hold_tokens
            and self._recording
            and self._capture_mode == "web"
        )

    def _handle_double_tap_press(self, token: str) -> bool:
        return self._multi_tap.handle_press(token)

    def _handle_double_tap_release(self, token: str) -> bool:
        return self._multi_tap.handle_release(token)

    def _handle_command_tap_press(self, token: str) -> bool:
        return self._command_tap.handle_press(token)

    def _handle_command_tap_release(self, token: str) -> bool:
        return self._command_tap.handle_release(token)

    def _begin_command_tap_capture(self, token: str, tap_count: int) -> None:
        if self._recording or self._mic_stt_busy:
            return
        self._command_tap_capture_by_token[token] = tap_count
        self.signals.statusChanged.emit(f"Recording command ({tap_count} tap) …")
        self._start_recording(mode=f"command:{tap_count}")

    def _end_command_tap_capture(self, token: str) -> None:
        tap_count = self._command_tap_capture_by_token.pop(token, None)
        if tap_count is None:
            return
        if self._recording and self._capture_mode == f"command:{tap_count}":
            self._stop_recording_and_transcribe(mode=f"command:{tap_count}")

    def _run_tap_command_capture(self, transcript: str, tap_count: int) -> None:
        key_map = {
            1: COMMAND_TAPS_ARGV_SINGLE,
            2: COMMAND_TAPS_ARGV_DOUBLE,
            3: COMMAND_TAPS_ARGV_TRIPLE,
            4: COMMAND_TAPS_ARGV_QUADRUPLE,
        }
        argv_key = key_map.get(tap_count, COMMAND_TAPS_ARGV_SINGLE)
        line = self._qsettings.value(argv_key, "", type=str)
        if not isinstance(line, str) or not line.strip():
            self.signals.statusChanged.emit(f"No command configured for {tap_count} tap(s).")
            return
        use_shell = bool(
            self._qsettings.value(
                COMMAND_TAPS_USE_SHELL,
                COMMAND_TAPS_USE_SHELL_DEFAULT,
                type=bool,
            )
        )
        timeout_s = max(20, int(self.settings.stt_timeout_seconds) * 3)
        try:
            out = run_transcript_command(
                line,
                transcript=transcript,
                use_shell=use_shell,
                timeout_seconds=timeout_s,
            )
            if out:
                self.signals.transcriptAppend.emit(out)
        except Exception as e:
            self.signals.errorOccurred.emit(f"{type(e).__name__}: {e}")

    @Slot()
    def _on_web_search_button_pressed(self) -> None:
        if not self._web_search_enabled():
            self.signals.statusChanged.emit(tr("Web search is disabled in Options."))
            return
        if not self._stt_engine_ready:
            self.signals.statusChanged.emit(tr("Speech engine is still initializing."))
            return
        if self._mic_stt_busy:
            self.signals.statusChanged.emit(tr("Busy transcribing; try again in a moment."))
            return
        self.signals.statusChanged.emit(tr("Recording web query... release button to search."))
        self._start_recording(mode="web")

    @Slot()
    def _on_web_search_button_released(self) -> None:
        self._stop_recording_and_transcribe(mode="web")

    def _register_hotkey(self) -> None:
        self._hotkey_ctrl.stop()
        self._cancel_double_tap_timers()
        self._ptt_hold_tokens.clear()
        self._web_search_hold_tokens.clear()
        self._ptt_specs = load_ptt_specs(self._qsettings)
        self._web_search_specs = load_web_search_specs(self._qsettings)
        self._command_tap_specs = load_command_tap_specs(self._qsettings)
        ptt_specs = self._ptt_specs
        web_specs = self._web_search_specs if self._web_search_enabled() else []
        command_specs = self._command_tap_specs if self._command_taps_enabled() else []
        self._hotkey_ctrl.start(
            ptt_specs=ptt_specs,
            web_specs=web_specs,
            command_tap_specs=command_specs,
        )

    def _start_recording(self, *, mode: str) -> None:
        self._recording_ctrl.start(mode=mode)

    def _stop_recording(self, *, play_stop_cue: bool = True) -> None:
        self._recording_ctrl.stop(play_stop_cue=play_stop_cue)

    def _stop_recording_and_transcribe(self, *, mode: str) -> None:
        self._transcribe_ctrl.stop_and_transcribe(mode=mode)

    def _run_web_search_command(self, query: str) -> str:
        return self._web_search_ctrl.run_command(query)

    @Slot(str, str)
    def _on_web_search_ready(self, query: str, summary: str) -> None:
        ts = append_history_entry(self._qsettings, query=query, summary_md=summary)
        show_window = self._should_auto_show_web_summary_window()
        if show_window:
            self._show_web_summary_nonmodal(query, summary=summary, history_ts=ts)
        else:
            self._refresh_web_history_unread_ui()
            win = self._web_search_history_win
            if win is not None and win.isVisible():
                win.refresh_from_settings()
        if self._tray_icon is not None:
            qtitle = query.strip().replace("\n", " ")
            if len(qtitle) > 64:
                qtitle = qtitle[:61] + "…"
            self._pending_tray_web_summary = (ts, query, summary)
            tray_ms = WEB_TRAY_MESSAGE_MS_WHEN_HIDDEN if not show_window else 8000
            self._tray_icon.showMessage(
                qtitle or tr("Web search"),
                tray_message_body(summary),
                QSystemTrayIcon.MessageIcon.Information,
                tray_ms,
            )
        self.signals.webSearchOverlaySyncRequest.emit()

