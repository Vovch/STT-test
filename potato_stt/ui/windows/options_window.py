"""Options window: persistent app settings (PTT keys, web search, cues, translation)."""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QEvent, QSettings, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from potato_stt.input.ptt_keys import (
    DEFAULT_PTT_SPECS,
    load_command_tap_specs,
    load_ptt_specs,
    load_web_search_specs,
    save_command_tap_specs,
    save_ptt_specs,
    save_web_search_specs,
    spec_label,
)
from potato_stt.i18n import tr
from potato_stt.platform.win32_startup import (
    is_run_at_startup_enabled,
    set_run_at_startup_enabled,
)
from potato_stt.settings_keys import (
    AUDIO_CUES_ENABLED,
    AUDIO_CUES_ENABLED_DEFAULT,
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
    DOUBLE_TAP_WINDOW_MS_MAX,
    DOUBLE_TAP_WINDOW_MS_MIN,
    START_MINIMIZED_SETTING,
    TRANSCRIPT_FILTER_ENABLED,
    TRANSCRIPT_FILTER_ENABLED_DEFAULT,
    TRANSCRIPT_FILTER_WORDS,
    TRANSCRIPT_FILTER_WORDS_DEFAULT,
    TRANSLATE_RU_EN_ENABLED,
    TRANSLATE_RU_EN_ENABLED_DEFAULT,
    TRANSLATION_MODEL_FETCH_APPROVED,
    VISUAL_CUES_ENABLED,
    VISUAL_CUES_ENABLED_DEFAULT,
    WEB_DOUBLE_TAP_ENABLED,
    WEB_DOUBLE_TAP_ENABLED_DEFAULT,
    WEB_DOUBLE_TAP_WINDOW_MS,
    WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT,
    WEB_MULTI_TAP_DOUBLE_PTT_TRIPLE_WEB,
    WEB_MULTI_TAP_MODE,
    WEB_MULTI_TAP_MODE_DEFAULT,
    WEB_MULTI_TAP_SECOND_PRESS_WEB,
    WEB_SEARCH_ARGV_LINE,
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_ENABLED_DEFAULT,
    WEB_SEARCH_USE_SHELL,
    UI_LANGUAGE,
    UI_LANGUAGE_AUTO,
    UI_LANGUAGE_EN,
    UI_LANGUAGE_RU,
)
from potato_stt.ui.dialogs.ptt_capture import PttCaptureDialog


class OptionsWindow(QWidget):
    """Separate top-level window for app settings."""

    def __init__(
        self,
        main_window: QWidget,
        qsettings: QSettings,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._main = main_window
        self._settings = qsettings
        self._really_close = False
        self.setWindowTitle(tr("Options"))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel(tr("Language:")))
        self._language_combo = QComboBox()
        self._language_combo.addItem(tr("Auto (follow OS)"), UI_LANGUAGE_AUTO)
        self._language_combo.addItem(tr("English"), UI_LANGUAGE_EN)
        self._language_combo.addItem(tr("Russian"), UI_LANGUAGE_RU)
        OptionsWindow._select_combo_by_data(
            self._language_combo,
            str(self._settings.value(UI_LANGUAGE, UI_LANGUAGE_AUTO, type=str) or UI_LANGUAGE_AUTO),
        )
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        language_row.addWidget(self._language_combo)
        language_row.addStretch(1)
        layout.addLayout(language_row)

        if sys.platform == "win32":
            self._startup_cb = QCheckBox(tr("Launch Potato STT at Windows startup"))
            self._startup_cb.setChecked(is_run_at_startup_enabled())
            self._startup_cb.toggled.connect(self._on_startup_toggled)
            layout.addWidget(self._startup_cb)
        else:
            _hint = QLabel(tr("Launch at startup is only available on Windows."))
            _hint.setWordWrap(True)
            layout.addWidget(_hint)

        self._start_min_cb = QCheckBox(tr("Start minimized"))
        self._start_min_cb.setChecked(
            bool(self._settings.value(START_MINIMIZED_SETTING, False, type=bool))
        )
        self._start_min_cb.setToolTip(
            tr(
                "When a system tray icon is available, the main window stays hidden until you open it from the tray. Otherwise the window opens minimized to the taskbar."
            )
        )
        self._start_min_cb.toggled.connect(self._on_start_minimized_toggled)
        layout.addWidget(self._start_min_cb)

        self._audio_cues_cb = QCheckBox(tr("Play start/stop audio cues"))
        self._audio_cues_cb.setChecked(
            bool(
                self._settings.value(
                    AUDIO_CUES_ENABLED,
                    AUDIO_CUES_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._audio_cues_cb.setToolTip(
            tr("Play a short sound when microphone recording starts and stops.")
        )
        self._audio_cues_cb.toggled.connect(self._on_audio_cues_toggled)
        layout.addWidget(self._audio_cues_cb)

        self._visual_cues_cb = QCheckBox(tr("Show recording and web-search visual cues"))
        self._visual_cues_cb.setChecked(
            bool(
                self._settings.value(
                    VISUAL_CUES_ENABLED,
                    VISUAL_CUES_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._visual_cues_cb.setToolTip(
            tr("Show the small on-screen overlays while recording or searching.")
        )
        self._visual_cues_cb.toggled.connect(self._on_visual_cues_toggled)
        layout.addWidget(self._visual_cues_cb)

        layout.addWidget(QLabel(tr("Push-to-talk keys (hold any of these):")))
        self._ptt_list = QListWidget()
        self._ptt_list.setMinimumHeight(120)
        layout.addWidget(self._ptt_list)
        _btn_row = QHBoxLayout()
        self._add_ptt_btn = QPushButton(tr("Add key…"))
        self._add_ptt_btn.clicked.connect(self._on_add_ptt_clicked)
        self._remove_ptt_btn = QPushButton(tr("Remove selected"))
        self._remove_ptt_btn.clicked.connect(self._on_remove_ptt_clicked)
        _btn_row.addWidget(self._add_ptt_btn)
        _btn_row.addWidget(self._remove_ptt_btn)
        _btn_row.addStretch(1)
        layout.addLayout(_btn_row)
        _ptt_help = QLabel(
            tr(
                "Recording continues while at least one bound key or button is held. If you remove every key, Right Ctrl is used again."
            )
        )
        _ptt_help.setWordWrap(True)
        _ptt_help.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(_ptt_help)

        self._web_search_enabled_cb = QCheckBox(tr("Enable web search"))
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
            tr("Controls Hold to Ask Web, web-search hotkeys, and double-tap web search.")
        )
        self._web_search_enabled_cb.toggled.connect(self._on_web_search_enabled_toggled)
        layout.addWidget(self._web_search_enabled_cb)

        layout.addWidget(QLabel(tr("Hold to Ask Web — shortcut keys (hold any of these):")))
        self._web_search_list = QListWidget()
        self._web_search_list.setMinimumHeight(100)
        layout.addWidget(self._web_search_list)
        _ws_btn_row = QHBoxLayout()
        self._add_web_search_btn = QPushButton(tr("Add key…"))
        self._add_web_search_btn.clicked.connect(self._on_add_web_search_clicked)
        self._remove_web_search_btn = QPushButton(tr("Remove selected"))
        self._remove_web_search_btn.clicked.connect(self._on_remove_web_search_clicked)
        _ws_btn_row.addWidget(self._add_web_search_btn)
        _ws_btn_row.addWidget(self._remove_web_search_btn)
        _ws_btn_row.addStretch(1)
        layout.addLayout(_ws_btn_row)
        _ws_help = QLabel(
            tr(
                "Hold a bound key or mouse button to record a web query (same as the main-window button). Release to transcribe and run your configured web-search command (built-in OpenCode when empty). If the list is empty, only the button works. If a key is also a push-to-talk key, push-to-talk takes priority."
            )
        )
        _ws_help.setWordWrap(True)
        _ws_help.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(_ws_help)

        self._web_double_tap_cb = QCheckBox(
            tr("Multi-tap push-to-talk keys for web search (same physical key as dictation)")
        )
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
            tr(
                "When enabled, a push-to-talk key can also start a web query using the gesture you select below. The delay applies between taps/clicks and before dictation starts on a plain hold."
            )
        )
        self._web_double_tap_cb.toggled.connect(self._on_web_double_tap_toggled)
        layout.addWidget(self._web_double_tap_cb)

        dt_row = QHBoxLayout()
        dt_row.addWidget(QLabel(tr("Multi-tap delay (ms):")))
        self._web_double_tap_window_spin = QSpinBox()
        self._web_double_tap_window_spin.setRange(
            DOUBLE_TAP_WINDOW_MS_MIN,
            DOUBLE_TAP_WINDOW_MS_MAX,
        )
        self._web_double_tap_window_spin.setSingleStep(25)
        self._web_double_tap_window_spin.setSuffix(tr(" ms"))
        self._web_double_tap_window_spin.setToolTip(
            tr(
                "Maximum time between tap release and the next press (multi-tap), and how long to wait before treating a single hold as normal dictation."
            )
        )
        self._web_double_tap_window_spin.setValue(
            int(
                self._settings.value(
                    WEB_DOUBLE_TAP_WINDOW_MS,
                    WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT,
                    type=int,
                )
            )
        )
        self._web_double_tap_window_spin.valueChanged.connect(self._on_web_double_tap_window_changed)
        dt_row.addWidget(self._web_double_tap_window_spin)
        dt_row.addStretch(1)
        layout.addLayout(dt_row)

        layout.addWidget(QLabel(tr("Multi-tap gesture:")))
        self._web_multi_tap_combo = QComboBox()
        self._web_multi_tap_combo.addItem(
            tr("Once, release, then press-and-hold — web search (hold alone — dictation)"),
            WEB_MULTI_TAP_SECOND_PRESS_WEB,
        )
        self._web_multi_tap_combo.addItem(
            tr("Double-tap-then-hold — dictation; third tap — start web search"),
            WEB_MULTI_TAP_DOUBLE_PTT_TRIPLE_WEB,
        )
        OptionsWindow._select_combo_by_data(
            self._web_multi_tap_combo, OptionsWindow._stored_multi_tap_mode(self._settings)
        )
        self._web_multi_tap_combo.currentIndexChanged.connect(self._on_web_multi_tap_mode_changed)
        layout.addWidget(self._web_multi_tap_combo)

        self._web_search_cmd_label = QLabel(tr("Web search command (leave empty for built-in OpenCode):"))
        layout.addWidget(self._web_search_cmd_label)
        self._web_search_cmd_edit = QLineEdit()
        self._web_search_cmd_edit.setPlaceholderText(
            tr(
                'Example: opencode run --format default "{prompt}"   — placeholders: {query}, {prompt}, {query_json}'
            )
        )
        _cmd0 = self._settings.value(WEB_SEARCH_ARGV_LINE, "", type=str)
        self._web_search_cmd_edit.setText(_cmd0 if isinstance(_cmd0, str) else "")
        self._web_search_cmd_edit.editingFinished.connect(self._on_web_search_cmd_finished)
        layout.addWidget(self._web_search_cmd_edit)

        self._web_search_shell_cb = QCheckBox(
            tr("Run command through the system shell (cmd.exe) — less safe; enables pipes/redirection")
        )
        self._web_search_shell_cb.setChecked(
            bool(self._settings.value(WEB_SEARCH_USE_SHELL, False, type=bool))
        )
        self._web_search_shell_cb.toggled.connect(self._on_web_search_use_shell_toggled)
        layout.addWidget(self._web_search_shell_cb)

        self._sync_web_search_controls_enabled()

        self._command_taps_enabled_cb = QCheckBox(
            tr("Enable custom command taps (single/double/triple/quadruple)")
        )
        self._command_taps_enabled_cb.setChecked(
            bool(
                self._settings.value(
                    COMMAND_TAPS_ENABLED,
                    COMMAND_TAPS_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._command_taps_enabled_cb.toggled.connect(self._on_command_taps_enabled_toggled)
        layout.addWidget(self._command_taps_enabled_cb)
        layout.addWidget(QLabel(tr("Command tap keys (hold final tap to speak):")))
        self._command_tap_list = QListWidget()
        self._command_tap_list.setMinimumHeight(80)
        layout.addWidget(self._command_tap_list)
        cmd_btn_row = QHBoxLayout()
        self._add_command_tap_btn = QPushButton(tr("Add key…"))
        self._add_command_tap_btn.clicked.connect(self._on_add_command_tap_clicked)
        self._remove_command_tap_btn = QPushButton(tr("Remove selected"))
        self._remove_command_tap_btn.clicked.connect(self._on_remove_command_tap_clicked)
        cmd_btn_row.addWidget(self._add_command_tap_btn)
        cmd_btn_row.addWidget(self._remove_command_tap_btn)
        cmd_btn_row.addStretch(1)
        layout.addLayout(cmd_btn_row)

        cmd_delay_row = QHBoxLayout()
        cmd_delay_row.addWidget(QLabel(tr("Command tap delay (ms):")))
        self._command_tap_window_spin = QSpinBox()
        self._command_tap_window_spin.setRange(
            DOUBLE_TAP_WINDOW_MS_MIN,
            DOUBLE_TAP_WINDOW_MS_MAX,
        )
        self._command_tap_window_spin.setSingleStep(25)
        self._command_tap_window_spin.setSuffix(tr(" ms"))
        self._command_tap_window_spin.setValue(
            int(
                self._settings.value(
                    COMMAND_TAPS_WINDOW_MS,
                    COMMAND_TAPS_WINDOW_MS_DEFAULT,
                    type=int,
                )
            )
        )
        self._command_tap_window_spin.valueChanged.connect(self._on_command_tap_window_changed)
        cmd_delay_row.addWidget(self._command_tap_window_spin)
        cmd_delay_row.addStretch(1)
        layout.addLayout(cmd_delay_row)

        layout.addWidget(QLabel(tr("Single tap command:")))
        self._command_single_edit = QLineEdit()
        self._command_single_edit.setPlaceholderText(
            tr('Example: python my_script.py "{transcript}"')
        )
        self._command_single_edit.setText(
            str(self._settings.value(COMMAND_TAPS_ARGV_SINGLE, "", type=str) or "")
        )
        self._command_single_edit.editingFinished.connect(self._on_command_taps_finished)
        layout.addWidget(self._command_single_edit)
        layout.addWidget(QLabel(tr("Double tap command:")))
        self._command_double_edit = QLineEdit()
        self._command_double_edit.setText(
            str(self._settings.value(COMMAND_TAPS_ARGV_DOUBLE, "", type=str) or "")
        )
        self._command_double_edit.editingFinished.connect(self._on_command_taps_finished)
        layout.addWidget(self._command_double_edit)
        layout.addWidget(QLabel(tr("Triple tap command:")))
        self._command_triple_edit = QLineEdit()
        self._command_triple_edit.setText(
            str(self._settings.value(COMMAND_TAPS_ARGV_TRIPLE, "", type=str) or "")
        )
        self._command_triple_edit.editingFinished.connect(self._on_command_taps_finished)
        layout.addWidget(self._command_triple_edit)
        layout.addWidget(QLabel(tr("Quadruple tap command:")))
        self._command_quadruple_edit = QLineEdit()
        self._command_quadruple_edit.setText(
            str(self._settings.value(COMMAND_TAPS_ARGV_QUADRUPLE, "", type=str) or "")
        )
        self._command_quadruple_edit.editingFinished.connect(self._on_command_taps_finished)
        layout.addWidget(self._command_quadruple_edit)
        self._command_taps_shell_cb = QCheckBox(
            tr("Run command taps through shell (cmd.exe)")
        )
        self._command_taps_shell_cb.setChecked(
            bool(
                self._settings.value(
                    COMMAND_TAPS_USE_SHELL,
                    COMMAND_TAPS_USE_SHELL_DEFAULT,
                    type=bool,
                )
            )
        )
        self._command_taps_shell_cb.toggled.connect(self._on_command_taps_shell_toggled)
        layout.addWidget(self._command_taps_shell_cb)
        self._command_tap_help = QLabel(
            tr(
                "Placeholders: {transcript}, {text}, {transcript_json}, {text_json}. Gesture: tap N-1 times quickly, then press-and-hold the Nth tap while speaking."
            )
        )
        self._command_tap_help.setWordWrap(True)
        self._command_tap_help.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self._command_tap_help)

        self._filter_cb = QCheckBox(tr("Remove filler words and phrases from transcripts"))
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
            tr(
                "Case-insensitive whole-word or whole-phrase removal after normalization. Affects push-to-talk, file transcription, and subtitle export."
            )
        )
        self._filter_cb.toggled.connect(self._on_transcript_filter_enabled_toggled)
        layout.addWidget(self._filter_cb)

        layout.addWidget(QLabel(tr("Words/phrases to strip (one per line or comma-separated):")))
        self._filter_words = QPlainTextEdit()
        self._filter_words.setPlaceholderText(tr("um\nyou know"))
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
            tr("Lines starting with # are ignored. Longer phrases are removed before shorter ones.")
        )
        _filter_help.setWordWrap(True)
        _filter_help.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(_filter_help)

        self._translate_ru_en_cb = QCheckBox(
            tr("Translate push-to-talk transcripts to English (Russian → English, local model)")
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
            tr(
                "After each utterance, paste English into the target app. This window shows the recognition and an English line when the translation differs. After you agree in the notice dialog, the Marian model (~300 MB) downloads from Hugging Face in the background if it is not already on this PC. Uses PyTorch on the CPU."
            )
        )
        self._translate_ru_en_cb.toggled.connect(self._on_translate_ru_en_toggled)
        layout.addWidget(self._translate_ru_en_cb)

        layout.addStretch(1)
        self._populate_ptt_list()
        self._populate_web_search_list()
        self._populate_command_tap_list()
        self._sync_command_tap_controls_enabled()

    def closeEvent(self, event: QEvent) -> None:
        if self._really_close:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def close_for_shutdown(self) -> None:
        self._really_close = True
        self.close()

    @staticmethod
    def _stored_multi_tap_mode(settings: QSettings) -> str:
        v = settings.value(WEB_MULTI_TAP_MODE, WEB_MULTI_TAP_MODE_DEFAULT, type=str)
        if v == WEB_MULTI_TAP_DOUBLE_PTT_TRIPLE_WEB:
            return WEB_MULTI_TAP_DOUBLE_PTT_TRIPLE_WEB
        return WEB_MULTI_TAP_SECOND_PRESS_WEB

    @staticmethod
    def _select_combo_by_data(combo: QComboBox, data: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)

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

    def _populate_command_tap_list(self) -> None:
        self._command_tap_list.clear()
        for spec in load_command_tap_specs(self._settings):
            it = QListWidgetItem(spec_label(spec))
            it.setData(Qt.ItemDataRole.UserRole, spec)
            self._command_tap_list.addItem(it)

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
            self._web_double_tap_window_spin,
            self._web_multi_tap_combo,
            self._web_search_cmd_label,
            self._web_search_cmd_edit,
            self._web_search_shell_cb,
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

    def _sync_command_tap_controls_enabled(self) -> None:
        enabled = bool(
            self._settings.value(
                COMMAND_TAPS_ENABLED,
                COMMAND_TAPS_ENABLED_DEFAULT,
                type=bool,
            )
        )
        for w in (
            self._command_tap_list,
            self._add_command_tap_btn,
            self._remove_command_tap_btn,
            self._command_tap_window_spin,
            self._command_single_edit,
            self._command_double_edit,
            self._command_triple_edit,
            self._command_quadruple_edit,
            self._command_taps_shell_cb,
            self._command_tap_help,
        ):
            w.setEnabled(enabled)

    def _save_command_tap_list_from_ui(self) -> None:
        specs: list[str] = []
        for i in range(self._command_tap_list.count()):
            item = self._command_tap_list.item(i)
            d = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(d, str):
                specs.append(d)
        save_command_tap_specs(self._settings, specs)
        fn = getattr(self._main, "_on_command_tap_key_setting_changed", None)
        if fn is not None:
            fn()
        self._populate_command_tap_list()

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
        dlg = PttCaptureDialog(self, title=tr("Add hold-to-ask-web key"))
        dlg.resize(420, 140)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dlg.captured_spec()
        if not spec:
            return
        for i in range(self._web_search_list.count()):
            if self._web_search_list.item(i).data(Qt.ItemDataRole.UserRole) == spec:
                QMessageBox.information(
                    self, tr("Hold to Ask Web"), tr("That key is already in the list.")
                )
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
    def _on_add_command_tap_clicked(self) -> None:
        dlg = PttCaptureDialog(self, title=tr("Add command-tap key"))
        dlg.resize(420, 140)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dlg.captured_spec()
        if not spec:
            return
        for i in range(self._command_tap_list.count()):
            if self._command_tap_list.item(i).data(Qt.ItemDataRole.UserRole) == spec:
                QMessageBox.information(self, tr("Command taps"), tr("That key is already in the list."))
                return
        it = QListWidgetItem(spec_label(spec))
        it.setData(Qt.ItemDataRole.UserRole, spec)
        self._command_tap_list.addItem(it)
        self._save_command_tap_list_from_ui()

    @Slot()
    def _on_remove_command_tap_clicked(self) -> None:
        row = self._command_tap_list.currentRow()
        if row < 0:
            return
        self._command_tap_list.takeItem(row)
        self._save_command_tap_list_from_ui()

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
                QMessageBox.information(
                    self, tr("Push-to-talk"), tr("That key is already in the list.")
                )
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
        self._web_double_tap_cb.blockSignals(True)
        self._web_double_tap_cb.setChecked(
            bool(
                self._settings.value(
                    WEB_DOUBLE_TAP_ENABLED,
                    WEB_DOUBLE_TAP_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._web_double_tap_cb.blockSignals(False)
        self._web_double_tap_window_spin.blockSignals(True)
        self._web_double_tap_window_spin.setValue(
            int(
                self._settings.value(
                    WEB_DOUBLE_TAP_WINDOW_MS,
                    WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT,
                    type=int,
                )
            )
        )
        self._web_double_tap_window_spin.blockSignals(False)
        self._web_search_cmd_edit.blockSignals(True)
        _cmd = self._settings.value(WEB_SEARCH_ARGV_LINE, "", type=str)
        self._web_search_cmd_edit.setText(_cmd if isinstance(_cmd, str) else "")
        self._web_search_cmd_edit.blockSignals(False)
        self._web_search_shell_cb.blockSignals(True)
        self._web_search_shell_cb.setChecked(
            bool(self._settings.value(WEB_SEARCH_USE_SHELL, False, type=bool))
        )
        self._web_search_shell_cb.blockSignals(False)
        self._web_multi_tap_combo.blockSignals(True)
        OptionsWindow._select_combo_by_data(
            self._web_multi_tap_combo, OptionsWindow._stored_multi_tap_mode(self._settings)
        )
        self._web_multi_tap_combo.blockSignals(False)
        self._sync_web_search_controls_enabled()
        self._command_taps_enabled_cb.blockSignals(True)
        self._command_taps_enabled_cb.setChecked(
            bool(
                self._settings.value(
                    COMMAND_TAPS_ENABLED,
                    COMMAND_TAPS_ENABLED_DEFAULT,
                    type=bool,
                )
            )
        )
        self._command_taps_enabled_cb.blockSignals(False)
        self._command_tap_window_spin.blockSignals(True)
        self._command_tap_window_spin.setValue(
            int(
                self._settings.value(
                    COMMAND_TAPS_WINDOW_MS,
                    COMMAND_TAPS_WINDOW_MS_DEFAULT,
                    type=int,
                )
            )
        )
        self._command_tap_window_spin.blockSignals(False)
        self._command_single_edit.blockSignals(True)
        self._command_single_edit.setText(
            str(self._settings.value(COMMAND_TAPS_ARGV_SINGLE, "", type=str) or "")
        )
        self._command_single_edit.blockSignals(False)
        self._command_double_edit.blockSignals(True)
        self._command_double_edit.setText(
            str(self._settings.value(COMMAND_TAPS_ARGV_DOUBLE, "", type=str) or "")
        )
        self._command_double_edit.blockSignals(False)
        self._command_triple_edit.blockSignals(True)
        self._command_triple_edit.setText(
            str(self._settings.value(COMMAND_TAPS_ARGV_TRIPLE, "", type=str) or "")
        )
        self._command_triple_edit.blockSignals(False)
        self._command_quadruple_edit.blockSignals(True)
        self._command_quadruple_edit.setText(
            str(self._settings.value(COMMAND_TAPS_ARGV_QUADRUPLE, "", type=str) or "")
        )
        self._command_quadruple_edit.blockSignals(False)
        self._command_taps_shell_cb.blockSignals(True)
        self._command_taps_shell_cb.setChecked(
            bool(
                self._settings.value(
                    COMMAND_TAPS_USE_SHELL,
                    COMMAND_TAPS_USE_SHELL_DEFAULT,
                    type=bool,
                )
            )
        )
        self._command_taps_shell_cb.blockSignals(False)
        self._populate_command_tap_list()
        self._sync_command_tap_controls_enabled()

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
                tr("Startup setting"),
                tr("Could not update the Windows startup entry:\n{e}").format(e=e),
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
        self._settings.sync()

    @Slot(int)
    def _on_web_double_tap_window_changed(self, value: int) -> None:
        self._settings.setValue(WEB_DOUBLE_TAP_WINDOW_MS, int(value))
        self._settings.sync()

    @Slot()
    def _on_web_search_cmd_finished(self) -> None:
        self._settings.setValue(WEB_SEARCH_ARGV_LINE, self._web_search_cmd_edit.text().strip())
        self._settings.sync()

    @Slot(bool)
    def _on_web_search_use_shell_toggled(self, checked: bool) -> None:
        self._settings.setValue(WEB_SEARCH_USE_SHELL, bool(checked))
        self._settings.sync()

    @Slot()
    def _on_web_multi_tap_mode_changed(self) -> None:
        d = self._web_multi_tap_combo.currentData()
        if isinstance(d, str):
            self._settings.setValue(WEB_MULTI_TAP_MODE, d)
            self._settings.sync()

    @Slot(bool)
    def _on_command_taps_enabled_toggled(self, checked: bool) -> None:
        self._settings.setValue(COMMAND_TAPS_ENABLED, bool(checked))
        self._settings.sync()
        self._sync_command_tap_controls_enabled()
        fn = getattr(self._main, "_on_command_tap_key_setting_changed", None)
        if fn is not None:
            fn()

    @Slot(int)
    def _on_command_tap_window_changed(self, value: int) -> None:
        self._settings.setValue(COMMAND_TAPS_WINDOW_MS, int(value))
        self._settings.sync()

    @Slot()
    def _on_command_taps_finished(self) -> None:
        self._settings.setValue(COMMAND_TAPS_ARGV_SINGLE, self._command_single_edit.text().strip())
        self._settings.setValue(COMMAND_TAPS_ARGV_DOUBLE, self._command_double_edit.text().strip())
        self._settings.setValue(COMMAND_TAPS_ARGV_TRIPLE, self._command_triple_edit.text().strip())
        self._settings.setValue(
            COMMAND_TAPS_ARGV_QUADRUPLE, self._command_quadruple_edit.text().strip()
        )
        self._settings.sync()

    @Slot(bool)
    def _on_command_taps_shell_toggled(self, checked: bool) -> None:
        self._settings.setValue(COMMAND_TAPS_USE_SHELL, bool(checked))
        self._settings.sync()

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

    @Slot()
    def _on_language_changed(self) -> None:
        data = self._language_combo.currentData()
        if not isinstance(data, str):
            return
        self._settings.setValue(UI_LANGUAGE, data)
        fn = getattr(self._main, "_on_language_setting_changed", None)
        if fn is not None:
            fn()
