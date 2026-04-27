from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget

from potato_stt import i18n
from potato_stt.settings_keys import UI_LANGUAGE, UI_LANGUAGE_AUTO, UI_LANGUAGE_EN, UI_LANGUAGE_RU
from potato_stt.ui.dialogs.help_dialog import using_help_text
from potato_stt.ui.windows.options_window import OptionsWindow


class _FakeLocale:
    def __init__(self, langs: list[str]) -> None:
        self._langs = langs

    def uiLanguages(self) -> list[str]:
        return list(self._langs)


class _DummyMain(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.language_change_calls = 0

    def _on_language_setting_changed(self) -> None:
        self.language_change_calls += 1


def _temp_settings(tmp_path: Path) -> QSettings:
    ini_path = tmp_path / "settings.ini"
    return QSettings(str(ini_path), QSettings.Format.IniFormat)


def _reset_language() -> None:
    i18n._current_language = UI_LANGUAGE_EN


@pytest.fixture(autouse=True)
def _isolate_i18n_language_state():
    _reset_language()
    yield
    _reset_language()


def test_resolved_language_respects_explicit_preference(monkeypatch) -> None:
    monkeypatch.setattr(i18n.QLocale, "system", lambda: _FakeLocale(["ru-RU"]))
    assert i18n.resolved_language(UI_LANGUAGE_EN) == UI_LANGUAGE_EN
    assert i18n.resolved_language(UI_LANGUAGE_RU) == UI_LANGUAGE_RU


def test_resolved_language_auto_uses_os_ui_languages(monkeypatch) -> None:
    monkeypatch.setattr(i18n.QLocale, "system", lambda: _FakeLocale(["ru-RU", "en-US"]))
    assert i18n.resolved_language(UI_LANGUAGE_AUTO) == UI_LANGUAGE_RU
    monkeypatch.setattr(i18n.QLocale, "system", lambda: _FakeLocale(["en-US"]))
    assert i18n.resolved_language(UI_LANGUAGE_AUTO) == UI_LANGUAGE_EN


def test_resolved_language_invalid_preference_falls_back_to_auto(monkeypatch) -> None:
    monkeypatch.setattr(i18n.QLocale, "system", lambda: _FakeLocale(["ru-RU"]))
    assert i18n.resolved_language("de") == UI_LANGUAGE_RU
    monkeypatch.setattr(i18n.QLocale, "system", lambda: _FakeLocale(["en-US"]))
    assert i18n.resolved_language("xx") == UI_LANGUAGE_EN


def test_init_localization_and_tr_for_russian(tmp_path, monkeypatch) -> None:
    settings = _temp_settings(tmp_path)
    settings.setValue(UI_LANGUAGE, UI_LANGUAGE_RU)
    monkeypatch.setattr(i18n.QLocale, "system", lambda: _FakeLocale(["en-US"]))
    assert i18n.init_localization(settings) == UI_LANGUAGE_RU
    assert i18n.tr("Options") == "Настройки"


def test_init_localization_invalid_preference_falls_back_to_auto(tmp_path, monkeypatch) -> None:
    settings = _temp_settings(tmp_path)
    settings.setValue(UI_LANGUAGE, "de")
    monkeypatch.setattr(i18n.QLocale, "system", lambda: _FakeLocale(["ru-RU"]))
    assert i18n.init_localization(settings) == UI_LANGUAGE_RU


def test_options_language_switcher_saves_setting_and_notifies_main(tmp_path, monkeypatch, qtbot) -> None:
    monkeypatch.setattr(
        "potato_stt.ui.windows.options_window.is_run_at_startup_enabled",
        lambda: False,
    )
    settings = _temp_settings(tmp_path)
    main = _DummyMain()
    qtbot.addWidget(main)
    w = OptionsWindow(main, settings)
    qtbot.addWidget(w)

    assert w._language_combo.currentData() == UI_LANGUAGE_AUTO
    for idx in range(w._language_combo.count()):
        if w._language_combo.itemData(idx) == UI_LANGUAGE_RU:
            w._language_combo.setCurrentIndex(idx)
            break
    assert settings.value(UI_LANGUAGE, UI_LANGUAGE_AUTO, type=str) == UI_LANGUAGE_RU
    assert main.language_change_calls == 1


def test_help_dialog_text_is_localized_when_russian_selected(tmp_path, monkeypatch) -> None:
    settings = _temp_settings(tmp_path)
    settings.setValue(UI_LANGUAGE, UI_LANGUAGE_RU)
    monkeypatch.setattr(i18n.QLocale, "system", lambda: _FakeLocale(["en-US"]))
    i18n.init_localization(settings)

    body = using_help_text(ptt_phrase="Right Ctrl", has_tray=False)
    assert "Удерживайте Right Ctrl" in body
