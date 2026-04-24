# Release notes

## Potato STT v1.6 — 2026-04-25

**Subject:** Recording **audio cues** and **animated overlay**, **tray-aware window chrome**, **Help** usage dialog, **mic app icon**, leaner **main window** (no toolbar / no footer Quit), packaging for bundled sounds.

### New behavior

- **Recording cues (Windows):** Short **UI sounds** when push-to-talk **starts** and **stops**, using bundled **CC0** samples from Kenney *Interface Sounds* (`bong_001` for both cues). Playback uses **`winsound`** (`SND_ASYNC`). Cues are skipped when quitting during an active recording. New module **`potato_stt/recording_cues.py`** and folder **`potato_stt/assets/sounds/`** (license + `SOURCES.txt` provenance).
- **Recording overlay:** Replaced the static red bullet with a **`RecordingPulseWidget`** — a **timer-driven** pulsing halo, ring, and solid core so “recording” is easier to see at a glance.
- **System tray vs. window controls:** With a tray icon, the title-bar **close (X)** **hides** the main window to the tray (does not quit). **Minimize** uses the **taskbar** normally (no longer auto-sent to tray). **File → Quit** (**Ctrl+Q**) and tray **Quit** perform a full exit (`_quit_application`). **Options** is hidden when sending the main window to the tray from **X**.
- **Help → Using Potato STT…** (all platforms): Opens a **modal** read-only summary (PTT, paste behavior, File/Settings pointers, tray bullets when applicable). **Help** is always available; **Help → Clear local data…** remains **Windows-only** after a separator. Inline help text was **removed** from the main window.
- **Main window layout:** Removed the bottom **Quit** button (quit remains in **File** and tray). Removed the **toolbar** (**Transcribe file** / **Options**); use **File** and **Settings** menus (and tray) instead.
- **App icon:** Programmatic **microphone** tile (multi-resolution `QIcon`) for the window and tray, replacing the blue “T” tile.

### Packaging and tests

- **`potato_stt.spec`:** Adds **`potato_stt/assets/sounds`** to **`datas`** so frozen builds ship cue WAVs.
- **`tests/test_recording_cues.py`:** Covers frozen vs. dev paths, missing files, and Windows `PlaySound` wiring.

### Docs

- **`README.md`** and **`MANUAL_TEST_CASES.md`** updated for cues, tray/close/minimize, toolbar removal, Help dialog, and manual cases (e.g. TC-59, TC-81).

---

## Potato STT v1.5 — 2026-04-05 (commit `a26e74a`)

**Subject:** Optional **local Russian → English** translation after push-to-talk (Marian / PyTorch CPU), streamlined **Options-only** enablement, main-window **English** line, packaging and reliability fixes for model download.

### New behavior

- **Local translation (RU → EN):** After each push-to-talk utterance, optionally **paste English** into the app that had focus when recording started. The main transcript still shows the **recognized** text and, when translation is on and the wording **differs**, an **`English:`** line is appended for that utterance. Uses **Helsinki-NLP OPUS-MT** (`opus-mt-ru-en`) via **`transformers`** and **CPU PyTorch**; override the model id with **`POTATO_STT_MARIAN_RU_EN_MODEL`** if needed.
- **Enable under Options:** Check **Translate push-to-talk transcripts to English**. A single **notice** dialog (**Agree** / **Refuse**, Refuse default) explains behavior, **~300 MB** download from **Hugging Face** when the model is **not already** in the user’s HF cache, and CPU use. **Agree** turns the feature on and **starts background download/load** immediately (no second confirmation, no separate **Settings** menu item for translation).
- **From source without torch:** The app can offer **pip** to install the translation stack into the current interpreter (frozen EXE builds bundle the stack via **`build_windows_exe.ps1`** / **`requirements.txt`**).

### Reliability and UX

- **Fetch consent timing:** Permission to download Marian weights is recorded **when the background preload starts**, so translation does not fail with “model not loaded” while the first download is still running or after a transient error; failed preload no longer forces translation off—retry via **Options** (toggle off/on) or the next utterance.
- **Worker → UI:** **`AppSignals`** slots use **queued connections** so status, errors, transcript lines, and preload completion always run on the **GUI thread** (reduces apparent freezes during download/load).
- **Marian load:** **`TOKENIZERS_PARALLELISM`**, bounded **PyTorch** thread counts during load, and **cleanup of partial tokenizer/model state** on load failure for cleaner retries.

### Packaging and repo

- **`potato_stt/marian_ru_en.py`**, **`requirements-translate.txt`** (optional reinstall of translation wheels), **`requirements.txt`** / **`potato_stt.spec`** / **`build_windows_exe.ps1`** updates for frozen bundles.
- **Tests:** **`tests/test_marian_ru_en.py`** (helpers, no full model download in CI).
- **Docs:** **`README.md`** and **`AGENTS.md`** aligned with the new flow.

---

## Potato STT v1.4 — 2026-04-01 (commit `b83bdfe`)

**Subject:** Filler-word cleanup, FFmpeg install guidance (winget), reliable tray quit on Windows, media tests, pre-commit fix, `.gitignore` hygiene.

Application changes for this release are in commit **`b83bdfe`**; release notes were committed separately so the documented hash stays stable.

### Reliability (Windows)

- **Quit from system tray:** **Quit** in the tray menu now exits the process reliably. `QApplication.quit()` is scheduled for the **next event-loop tick** so it runs after the native context menu closes (a synchronous quit from that menu was often ignored, leaving Potato STT running after the tray icon disappeared). Shutdown also hides the **recording** overlay, closes **Options** if it is open, and calls **`sounddevice.stop()`** so PortAudio capture does not keep the interpreter alive.

### New behavior

- **Filler words (Options):** Remove configured **whole words / phrases** (case-insensitive) from finished text after normalization. Applies to **push-to-talk**, **file transcription**, and **exported subtitles** (empty cues dropped). **Default for new installs:** filter **enabled** with **`uh`** and **`um`**; change or turn off under **Options**.
- **FFmpeg missing:** If FFmpeg/ffprobe are required but not on `PATH`, the app raises a dedicated error and shows a **dialog** with copy-friendly text. The suggested Windows command uses **`winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements`** (same argv as the **Install FFmpeg (winget)** button). An **Open FFmpeg download page…** button links to `https://ffmpeg.org/download.html`.

### Tests and repo layout

- **Optional media regression tests** read samples from repo-root **`test_files/`** or **`test_file/`** (see `tests/helpers.py`: `user_test_media_paths()`). Extensions include **`.aiff` / `.aif`**. Committed samples: **`test_files/dear_shadows.*`** (multiple formats).
- **New tests:** `tests/test_transcript_utils.py` (phrase parsing, word filter, subtitle cue filtering).

### Tooling

- **Git pre-commit:** Hook prefers **`.venv/Scripts/python.exe`** (Windows) or **`.venv/bin/python`** before `python3`/`python`, so commits are not blocked when the only `python` on `PATH` is the Microsoft Store alias. Reinstall with `.\.venv\Scripts\python.exe scripts\run_commit_tests.py --install-hook` (or `.\scripts\install_git_hooks.ps1`).

### Housekeeping

- **`.gitignore`:** `**/*.srt` and `**/*.vtt` for local subtitle exports; `.pytest_cache/`; common Python/tooling noise (`.coverage`, `htmlcov/`, `.mypy_cache/`, `.ruff_cache/`, `*.egg-info/`, etc.); OS/IDE junk (`.DS_Store`, `Thumbs.db`, `.idea/`). The old blanket ignore of `test_file/` was removed earlier so local or tracked test media can live beside **`test_files/`** as you prefer.

---

## Potato STT v1.3 — 2026-03-28 (commit `8b77d78`)

**Subject:** Rename to Potato STT; file transcription, tests, and UI polish.

### Breaking changes and migration (from Pipit Clone)

- **Python package:** `pipit_clone` → `potato_stt`. Run with `python -m potato_stt`.
- **Windows bundle:** `dist\PotatoSTT\PotatoSTT.exe` (ship the whole folder). Launcher **`PotatoSTTCPU.bat`** replaces `PipitCloneCPU.bat` (CPU-only ONNX for this process).
- **Environment variables:** prefer **`POTATO_STT_*`**; legacy **`PIPIT_*`** is still read by `potato_stt/config.py` where documented in README.
- **Saved settings and startup:** `QSettings` org/app **`PotatoSTT` / `PotatoSTT`**; Run value name **`PotatoSTT`**. After upgrading, open **Options** again and re-enable “Launch at startup” if you use it.
- **Parakeet install path (default):** `%LOCALAPPDATA%\potato_stt\` (legacy installs may still live under `%LOCALAPPDATA%\pipit_clone\`).

### New and changed behavior

- **File → Transcribe media file…** (also toolbar and tray): transcribe an existing audio/video file; transcript is **appended only in the Potato STT window** (no paste into the previously focused app).
- **Long files:** time-based chunking using **`POTATO_STT_TRANSCRIBE_CHUNK_SECONDS`** (default 120s, clamped in code) to limit RAM and avoid full-file ONNX loads. **FFmpeg/ffprobe** on `PATH` needed for non–16 kHz mono WAV and for duration probing on long media.
- **Subtitles:** after a successful run, save **`.srt`** or **`.vtt`**. Subtitle cue layout uses improved word-boundary heuristics. ONNX backend uses token timestamps when available; HTTP backend prefers timed segments from the service, with an even-split fallback.
- **ONNX ASR:** if DirectML/GPU runs out of memory during model load, the app **falls back to CPU** and surfaces a status message. Set **`POTATO_STT_CPU_ONLY=1`** (or **`PIPIT_CPU_ONLY`**) to skip the GPU path from the start.
- **UI:** **File** and **Settings** menus, **QToolBar** (“Transcribe file”, “Options”); file-transcribe completion returns to a clear **Ready** state (fixes progress stuck on “Working” after a successful run).
- **Parakeet Windows installer:** child-process env includes **`POTATO_STT_DISABLE_PARAKEET_WEBOPEN`** (legacy **`PIPIT_DISABLE_PARAKEET_WEBOPEN`** still honored where applicable).

### Tests and tooling

- **Unit tests:** `tests/run_tests.py` (stdlib **unittest** discovery), with `tests/test_media_decode.py`, `tests/test_subtitle_export.py`, `tests/test_file_transcribe.py`, and `tests/helpers.py`.
- **`requirements-dev.txt`** and **`pytest.ini`** for optional pytest workflows.
- **`.gitignore`:** at the time of v1.3, optional local media under `test_file/` could be ignored (layout evolved in v1.4; see v1.4 notes).

### Packaging

- **PyInstaller:** `potato_stt.spec`; **`build_windows_exe.ps1`** builds `dist\PotatoSTT\` and copies **`PotatoSTTCPU.bat`** next to the executable.

---

## v1.2 — 2026-03-25

### Push-to-talk

- Configurable **push-to-talk keys** stored in `QSettings` (`push_to_talk_keys` JSON list).
- **Options** window: list of bindings, **Add key…** (capture any keyboard key or mouse button), **Remove selected**.
- Support for **multiple keys at once**: hold any configured key/button; recording continues while at least one binding is held; stops when the last one is released.
- **Default** when the list is empty: **Right Ctrl** (same as a fresh install).
- New modules: `pipit_clone/ptt_keys.py` (spec strings, matching, labels), `pipit_clone/ptt_capture.py` (modal capture via pynput).

### Windows startup

- **Launch Pipit Clone at Windows startup** (user logon) via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (`PipitClone` value).
- New module: `pipit_clone/win32_startup.py` (build launch command for frozen exe or `pythonw -m pipit_clone`).

### STT / language

- Removed **language / prompt** wiring that did not match the current Parakeet ONNX workflow: dropped `PIPIT_STT_PROMPT` / `stt_prompt`, HTTP `prompt` / `language` fields in `stt_client`, and the `language` argument to ONNX `transcribe_wav`.
- README and examples updated accordingly.

### UI / docs

- Main window **Options** (gear control), help/tray copy aligned with configurable PTT.
- `AGENTS.md` and `README.md` updated for push-to-talk and STT configuration.

### Technical

- Large updates in `pipit_clone/ui_main.py` (options UI, PTT listeners, startup checkbox, styling fixes as staged).

---

*Previous tags in this repo: `v1`, `v1.1`. **v1.3**, **v1.4**, and **v1.5** are documented above with dates; tag **`v1.5`** when you publish this build.*
