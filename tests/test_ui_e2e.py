"""
UI-level end-to-end checks: real MainWindow + Qt event loop, mocked STT and no global hotkeys.

Also covers real engine startup with stubbed loads: ONNX calls into onnx_asr.load_model;
Parakeet uses a stubbed downloader when the Windows package is not installed.

Requires: pip install -r requirements-dev.txt (pytest + pytest-qt).
Run: python -m pytest tests/test_ui_e2e.py -v
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock
import subprocess
import time

import pytest

from potato_stt.config import Settings as RealSettings
from potato_stt.core.subtitle_export import cues_to_srt


@pytest.fixture
def main_window(qtbot, monkeypatch):
    """MainWindow with ONNX/Parakeet startup and pynput registration disabled."""

    def _skip_engine(self) -> None:
        self._stt_engine_ready = True

    monkeypatch.setattr(
        "potato_stt.ui.windows.main_window.MainWindow._ensure_engine_and_start_hotkey",
        _skip_engine,
    )
    monkeypatch.setattr(
        "potato_stt.ui.windows.main_window.MainWindow._register_hotkey",
        lambda self: None,
    )

    from potato_stt.ui.windows.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: w._stt_engine_ready, timeout=5000)
    return w


def test_main_window_smoke_visible(main_window) -> None:
    main_window.show()
    assert main_window.isVisible()
    assert "Potato STT" in main_window.windowTitle()


def test_file_transcribe_appends_transcript(main_window, qtbot, monkeypatch, tmp_path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")  # path only passed to mock

    def _fake_transcribe(*_args, **_kwargs):
        return "Synthetic line for e2e.", []

    monkeypatch.setattr(
        "potato_stt.controllers.file_transcribe_controller.transcribe_file_to_text_and_cues",
        _fake_transcribe,
    )

    main_window._start_file_transcribe(wav)

    def _done() -> bool:
        return "Synthetic line for e2e." in main_window._transcript.toPlainText()

    qtbot.waitUntil(_done, timeout=8000)
    assert "ready." in main_window._status_label.text().lower()


def test_file_transcribe_writes_subtitles_when_save_dialog_ok(
    main_window, qtbot, monkeypatch, tmp_path
) -> None:
    wav = tmp_path / "clip.wav"
    out_srt = tmp_path / "saved_subs.srt"
    cues = [(0.0, 1.0, "hello e2e")]
    srt_body = cues_to_srt(cues)

    def _fake_transcribe(*_args, **_kwargs):
        return "hello e2e", list(cues)

    monkeypatch.setattr(
        "potato_stt.controllers.file_transcribe_controller.transcribe_file_to_text_and_cues",
        _fake_transcribe,
    )

    dlg = MagicMock(
        side_effect=[
            (str(out_srt), "SubRip (*.srt)"),
        ]
    )
    monkeypatch.setattr("potato_stt.ui.windows.main_window.QFileDialog.getSaveFileName", dlg)

    main_window._start_file_transcribe(wav)

    def _saved() -> bool:
        return out_srt.is_file()

    qtbot.waitUntil(_saved, timeout=8000)
    text = out_srt.read_text(encoding="utf-8")
    assert "hello e2e" in text
    assert "00:00:00,000" in text
    dlg.assert_called_once()
    assert "ready." in main_window._status_label.text().lower()


def test_file_transcribe_error_resets_to_ready_status(main_window, qtbot, monkeypatch, tmp_path) -> None:
    wav = tmp_path / "clip.wav"

    def _boom(*_args, **_kwargs):
        raise RuntimeError("forced failure for e2e")

    monkeypatch.setattr(
        "potato_stt.controllers.file_transcribe_controller.transcribe_file_to_text_and_cues",
        _boom,
    )

    main_window._start_file_transcribe(wav)

    def _ready_after_error() -> bool:
        t = main_window._status_label.text().lower()
        return "ready." in t and "hold" in t

    qtbot.waitUntil(_ready_after_error, timeout=8000)


def test_options_window_opens(main_window, qtbot) -> None:
    main_window._open_options()
    assert main_window._options_win is not None
    qtbot.waitExposed(main_window._options_win)
    assert main_window._options_win.isVisible()


def test_options_window_reopens_after_close_button(main_window, qtbot) -> None:
    main_window._open_options()
    assert main_window._options_win is not None
    first = main_window._options_win
    qtbot.waitExposed(first)
    assert first.isVisible()

    first.close()
    qtbot.waitUntil(lambda: not first.isVisible(), timeout=2000)

    main_window._open_options()
    assert main_window._options_win is first
    qtbot.waitUntil(lambda: first.isVisible(), timeout=2000)


def test_web_search_dialog_markdown_structure() -> None:
    from potato_stt.ui.markdown import web_search_dialog_markdown

    md = web_search_dialog_markdown("What is **Exa**?", "## Answer\n\nBody with [link](https://exa.ai/).")
    assert "## Query" in md
    assert "## Summary" in md
    assert "```" in md
    assert "What is **Exa**?" in md
    assert "## Answer" in md


def test_markdown_fence_extends_when_query_contains_fence() -> None:
    from potato_stt.ui.markdown import markdown_fence

    inner = "code with ``` inside"
    f = markdown_fence(inner)
    assert f.startswith("````")
    assert f.endswith("````")
    assert inner in f


def test_default_web_search_invocation(main_window, monkeypatch) -> None:
    calls = {}

    def _fake_run(argv, **kwargs):
        calls["argv"] = list(argv)
        calls["kwargs"] = dict(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=b"Summary from OpenCode", stderr=b"")

    monkeypatch.setattr("potato_stt.web_search.runner.shutil.which", lambda _name: "opencode")
    monkeypatch.setattr("potato_stt.web_search.runner.subprocess.run", _fake_run)

    from potato_stt import settings_keys

    main_window._qsettings.setValue(settings_keys.WEB_SEARCH_ARGV_LINE, "")
    main_window._qsettings.setValue(settings_keys.WEB_SEARCH_USE_SHELL, False)
    out = main_window._run_web_search_command("latest TypeScript 6 changes")
    assert out == "Summary from OpenCode"
    assert calls["argv"][0] == "opencode"
    assert calls["argv"][1] == "run"
    assert "--format" in calls["argv"]
    assert calls["kwargs"].get("text") is False
    sent_prompt = calls["argv"][-1]
    assert sent_prompt.startswith(
        "Search the web for this exact user query: latest TypeScript 6 changes"
    )
    assert "User query: latest TypeScript 6 changes" in sent_prompt
    assert "Do not ask the user for another query." in sent_prompt
    assert "Use OpenCode's websearch tool before answering." in sent_prompt
    assert "Sources" in sent_prompt
    assert "latest TypeScript 6 changes" in sent_prompt


def test_double_tap_second_press_starts_web_search(main_window, monkeypatch) -> None:
    from potato_stt import settings_keys

    token = "vk:163"
    web_starts: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        main_window,
        "_add_web_search_token",
        lambda tok, *, allow_unconfigured=False: web_starts.append((tok, allow_unconfigured)),
    )
    main_window._qsettings.setValue(settings_keys.WEB_SEARCH_ENABLED, True)
    main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_ENABLED, True)
    main_window._qsettings.setValue(
        settings_keys.WEB_MULTI_TAP_MODE, settings_keys.WEB_MULTI_TAP_SECOND_PRESS_WEB
    )
    try:
        assert main_window._handle_double_tap_press(token)
        assert main_window._handle_double_tap_release(token)
        assert main_window._handle_double_tap_press(token)
        assert web_starts == [(token, True)]
    finally:
        main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_ENABLED, False)
        main_window._qsettings.setValue(
            settings_keys.WEB_MULTI_TAP_MODE, settings_keys.WEB_MULTI_TAP_MODE_DEFAULT
        )


def test_triple_tap_third_press_starts_web_search(main_window, monkeypatch) -> None:
    from potato_stt import settings_keys

    token = "vk:163"
    web_starts: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        main_window,
        "_add_web_search_token",
        lambda tok, *, allow_unconfigured=False: web_starts.append((tok, allow_unconfigured)),
    )
    main_window._qsettings.setValue(settings_keys.WEB_SEARCH_ENABLED, True)
    main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_ENABLED, True)
    main_window._qsettings.setValue(
        settings_keys.WEB_MULTI_TAP_MODE, settings_keys.WEB_MULTI_TAP_DOUBLE_PTT_TRIPLE_WEB
    )
    main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_WINDOW_MS, 5000)
    try:
        assert main_window._handle_double_tap_press(token)
        assert main_window._handle_double_tap_release(token)
        assert main_window._handle_double_tap_press(token)
        assert main_window._handle_double_tap_release(token)
        assert main_window._handle_double_tap_press(token)
        assert web_starts == [(token, True)]
    finally:
        main_window._cancel_double_tap_timers()
        main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_ENABLED, False)
        main_window._qsettings.setValue(
            settings_keys.WEB_MULTI_TAP_MODE, settings_keys.WEB_MULTI_TAP_MODE_DEFAULT
        )
        main_window._qsettings.setValue(
            settings_keys.WEB_DOUBLE_TAP_WINDOW_MS,
            settings_keys.WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT,
        )


def test_double_tap_delay_setting_controls_second_press_window(main_window, monkeypatch) -> None:
    from potato_stt import settings_keys

    token = "vk:163"
    web_starts: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        main_window,
        "_add_web_search_token",
        lambda tok, *, allow_unconfigured=False: web_starts.append((tok, allow_unconfigured)),
    )
    main_window._qsettings.setValue(settings_keys.WEB_SEARCH_ENABLED, True)
    main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_ENABLED, True)
    main_window._qsettings.setValue(
        settings_keys.WEB_MULTI_TAP_MODE, settings_keys.WEB_MULTI_TAP_SECOND_PRESS_WEB
    )
    try:
        main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_WINDOW_MS, 150)
        main_window._multi_tap.last_up[token] = time.monotonic() - 0.20
        assert main_window._handle_double_tap_press(token)
        assert web_starts == []
        assert main_window._handle_double_tap_release(token)

        main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_WINDOW_MS, 250)
        main_window._multi_tap.last_up[token] = time.monotonic() - 0.20
        assert main_window._handle_double_tap_press(token)
        assert web_starts == [(token, True)]
    finally:
        main_window._cancel_double_tap_timers()
        main_window._qsettings.setValue(
            settings_keys.WEB_DOUBLE_TAP_WINDOW_MS,
            settings_keys.WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT,
        )
        main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_ENABLED, False)
        main_window._qsettings.setValue(
            settings_keys.WEB_MULTI_TAP_MODE, settings_keys.WEB_MULTI_TAP_MODE_DEFAULT
        )


def test_double_tap_delay_setting_controls_ptt_hold_timer(main_window, monkeypatch) -> None:
    from potato_stt import settings_keys
    from potato_stt.input import multi_tap as multi_tap_mod

    intervals: list[float] = []

    class FakeTimer:
        daemon = False

        def __init__(self, interval, _callback, args=()):
            intervals.append(float(interval))

        def start(self) -> None:
            pass

        def cancel(self) -> None:
            pass

    monkeypatch.setattr(multi_tap_mod.threading, "Timer", FakeTimer)
    main_window._qsettings.setValue(settings_keys.WEB_SEARCH_ENABLED, True)
    main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_ENABLED, True)
    main_window._qsettings.setValue(
        settings_keys.WEB_MULTI_TAP_MODE, settings_keys.WEB_MULTI_TAP_SECOND_PRESS_WEB
    )
    main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_WINDOW_MS, 1500)
    try:
        assert main_window._handle_double_tap_press("vk:163")
        assert intervals == [1.5]
    finally:
        main_window._cancel_double_tap_timers()
        main_window._qsettings.setValue(
            settings_keys.WEB_DOUBLE_TAP_WINDOW_MS,
            settings_keys.WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT,
        )
        main_window._qsettings.setValue(settings_keys.WEB_DOUBLE_TAP_ENABLED, False)
        main_window._qsettings.setValue(
            settings_keys.WEB_MULTI_TAP_MODE, settings_keys.WEB_MULTI_TAP_MODE_DEFAULT
        )


def test_custom_web_search_argv_invocation(main_window, monkeypatch) -> None:
    calls = {}

    def _fake_run(argv, **kwargs):
        calls["argv"] = list(argv)
        calls["kwargs"] = dict(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=b"custom", stderr=b"")

    monkeypatch.setattr("potato_stt.web_search.runner.subprocess.run", _fake_run)
    from potato_stt import settings_keys

    main_window._qsettings.setValue(
        settings_keys.WEB_SEARCH_ARGV_LINE, 'python -c "print({query})"'
    )
    main_window._qsettings.setValue(settings_keys.WEB_SEARCH_USE_SHELL, False)
    try:
        out = main_window._run_web_search_command("hi")
        assert out == "custom"
        joined = " ".join(calls["argv"])
        assert "hi" in joined
    finally:
        main_window._qsettings.setValue(settings_keys.WEB_SEARCH_ARGV_LINE, "")


def test_web_search_ready_skips_window_when_main_hidden(main_window, monkeypatch) -> None:
    from potato_stt import settings_keys
    from PySide6.QtCore import Qt

    calls: list[tuple[str, int]] = []

    def _fake_show_message(title, body, icon, msecs):
        calls.append((title, int(msecs)))

    tray = MagicMock()
    tray.showMessage.side_effect = _fake_show_message
    monkeypatch.setattr(main_window, "_tray_icon", tray)
    monkeypatch.setattr(main_window, "_show_web_summary_nonmodal", MagicMock())

    monkeypatch.setattr(main_window, "isVisible", lambda: False)
    main_window._on_web_search_ready("q", "s")
    main_window._show_web_summary_nonmodal.assert_not_called()
    assert calls and calls[0][1] == settings_keys.WEB_TRAY_MESSAGE_MS_WHEN_HIDDEN

    monkeypatch.setattr(main_window, "isVisible", lambda: True)
    monkeypatch.setattr(main_window, "windowState", lambda: Qt.WindowState.WindowNoState)
    main_window._on_web_search_ready("q2", "s2")
    assert main_window._show_web_summary_nonmodal.call_count == 1
    assert any(c[1] == 8000 for c in calls)


def test_web_search_disabled_blocks_new_web_recordings(main_window, monkeypatch) -> None:
    from potato_stt import settings_keys

    starts: list[str] = []
    monkeypatch.setattr(main_window, "_start_recording", lambda *, mode: starts.append(mode))
    main_window._qsettings.setValue(settings_keys.WEB_SEARCH_ENABLED, False)
    try:
        main_window._add_web_search_token("vk:163", allow_unconfigured=True)
        main_window._on_web_search_button_pressed()
        assert starts == []
        assert not main_window._web_search_enabled()
    finally:
        main_window._qsettings.setValue(settings_keys.WEB_SEARCH_ENABLED, True)


def test_audio_cues_setting_suppresses_start_stop_sounds(main_window, monkeypatch) -> None:
    from potato_stt import settings_keys
    from potato_stt.controllers import recording_controller as rc

    calls: list[str] = []
    monkeypatch.setattr(rc, "play_recording_started_cue", lambda: calls.append("start"))
    monkeypatch.setattr(rc, "play_recording_stopped_cue", lambda: calls.append("stop"))

    class FakeStream:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(rc.sd, "InputStream", lambda **_kwargs: FakeStream())
    main_window._qsettings.setValue(settings_keys.AUDIO_CUES_ENABLED, False)
    try:
        main_window._start_recording(mode="ptt")
        main_window._stop_recording()
        assert calls == []
    finally:
        main_window._qsettings.setValue(settings_keys.AUDIO_CUES_ENABLED, True)


def test_visual_cues_setting_hides_overlays(main_window) -> None:
    from potato_stt import settings_keys

    main_window._qsettings.setValue(settings_keys.VISUAL_CUES_ENABLED, False)
    try:
        main_window._on_recording_overlay(True)
        main_window._sync_web_search_overlay()
        assert not main_window._recording_overlay.isVisible()
        assert not main_window._web_search_overlay.isVisible()
    finally:
        main_window._qsettings.setValue(settings_keys.VISUAL_CUES_ENABLED, True)


def test_onnx_backend_starts_model_load_when_model_missing(qtbot, monkeypatch) -> None:
    """Real _ensure_engine path: first ONNX load calls onnx_asr.load_model (simulated missing model)."""

    def _settings_onnx_missing_model():
        return replace(
            RealSettings(),
            stt_backend="onnx_asr",
            cpu_only=True,
            onnx_asr_model="missing-model-xyz-e2e",
        )

    monkeypatch.setattr("potato_stt.ui.windows.main_window.Settings", _settings_onnx_missing_model)

    load_calls: list[tuple[object, object]] = []

    def _fake_load_model(model_name, path=None, *, providers=None, **kwargs):
        load_calls.append((model_name, providers))
        raise RuntimeError("simulated model missing for e2e")

    monkeypatch.setattr(
        "potato_stt.core.onnx_asr_engine.onnx_asr.load_model",
        _fake_load_model,
    )
    monkeypatch.setattr(
        "potato_stt.ui.windows.main_window.MainWindow._register_hotkey",
        lambda self: None,
    )

    from potato_stt.ui.windows.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)

    def _load_started() -> bool:
        return len(load_calls) >= 1

    qtbot.waitUntil(_load_started, timeout=20000)
    assert load_calls[0][0] == "missing-model-xyz-e2e"
    assert list(load_calls[0][1] or []) == ["CPUExecutionProvider"]

    qtbot.waitUntil(
        lambda: "runtimeerror" in w._status_label.text().lower(),
        timeout=20000,
    )
    assert not w._stt_engine_ready


def test_parakeet_backend_starts_package_download_when_not_installed(
    qtbot, monkeypatch, tmp_path
) -> None:
    """No 启动.bat: app enters first-run download path (network stubbed)."""
    install = tmp_path / "parakeet-empty"
    install.mkdir()

    def _settings_parakeet_no_package():
        return replace(
            RealSettings(),
            stt_backend="parakeet",
            parakeet_install_dir=str(install),
            parakeet_auto_download=True,
            parakeet_source_fallback=False,
            parakeet_launch_timeout_seconds=5,
        )

    monkeypatch.setattr("potato_stt.ui.windows.main_window.Settings", _settings_parakeet_no_package)

    download_attempts: list[str] = []

    def _no_network_download(url: str, dest_path, *, on_progress=None):
        download_attempts.append(url)
        raise RuntimeError("e2e abort before HTTP")

    monkeypatch.setattr(
        "potato_stt.core.parakeet_windows_installer._is_port_open",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "potato_stt.core.parakeet_windows_installer._download_with_progress",
        _no_network_download,
    )
    monkeypatch.setattr(
        "potato_stt.ui.windows.main_window.MainWindow._register_hotkey",
        lambda self: None,
    )

    from potato_stt.ui.windows.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)

    def _download_started() -> bool:
        return len(download_attempts) >= 1

    qtbot.waitUntil(_download_started, timeout=20000)
    assert len(download_attempts) == 1

    qtbot.waitUntil(
        lambda: "timeouterror" in w._status_label.text().lower(),
        timeout=30000,
    )
    assert not w._stt_engine_ready
