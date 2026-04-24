# Potato STT — manual test cases

Structured checks for **Windows** desktop validation. Record **Pass / Fail / Blocked**, build or Git revision, backend (`onnx_asr` vs `http`), and notes (especially for subjective STT quality).

**Prerequisites (typical):** microphone, default or known-good audio device, network on first run (model/package download). Optional: **FFmpeg** and **ffprobe** on `PATH` for non-WAV media and long-file duration probing.

**Environments to rotate (when possible):** `python -m potato_stt` from a venv; `dist\PotatoSTT\PotatoSTT.exe` full folder; `PotatoSTTCPU.bat` (CPU-only ONNX).

---

## 1. Install, launch, and shutdown

| ID | Steps | Expected |
|----|--------|----------|
| TC-01 | Create venv, `pip install -r requirements.txt`, run `python -m potato_stt`. | App window opens; no immediate traceback in console (if console visible). |
| TC-02 | Close via **Quit**; relaunch. | Second launch reaches ready state; prior session does not corrupt startup. |
| TC-03 | From built bundle, run `PotatoSTT.exe` from **`dist\PotatoSTT\`** (entire folder present). | Same as TC-01; no missing-DLL errors. |
| TC-04 | Tray available: use tray **Quit** (if shown). | App exits; tray icon disappears. |

---

## 2. Startup and STT readiness

| ID | Steps | Expected |
|----|--------|----------|
| TC-10 | Watch status text and progress bar from cold start (first run or after clearing caches). | Progress reflects download / setup when applicable; ends in a **ready** state (not stuck on “Working” / loading forever). |
| TC-11 | Default backend **`POTATO_STT_BACKEND=onnx_asr`** (or unset). | Status indicates ONNX ASR loading then ready (or CPU fallback message if GPU OOM). |
| TC-12 | Set `POTATO_STT_BACKEND=http`, restart app. | Parakeet HTTP path prepares (may download/install long-running); eventually ready or clear failure message. |
| TC-13 | Launch with `POTATO_STT_CPU_ONLY=1` or **`PotatoSTTCPU.bat`**. | ONNX path avoids GPU; app becomes ready; transcription still works (slower acceptable). |

---

## 3. Push-to-talk (core)

| ID | Steps | Expected |
|----|--------|----------|
| TC-20 | Open Notepad; focus caret; hold **Right Ctrl**, speak clearly, release. | Transcript appears in Potato STT; **same text pasted** into Notepad (normalize spacing if needed). |
| TC-21 | Focus Potato STT transcript area; PTT in another app without focusing Notepad. | Paste targets the app that had focus **when PTT was pressed** (per product behavior). |
| TC-22 | Hold PTT for under one second with silence; release. | No crash; empty or minimal transcript handled gracefully. |
| TC-23 | Rapid press/release PTT several times. | No deadlock; listeners recover; no duplicate stuck recording state. |

---

## 4. Options — push-to-talk keys and startup

| ID | Steps | Expected |
|----|--------|----------|
| TC-30 | **Settings → Options…**: add a second PTT key; hold **either** key; release. | Recording stops when **last** binding is released; transcription runs once. |
| TC-31 | Remove all custom keys (empty list behavior per product). | Default **Right Ctrl** still works, or UI explains default. |
| TC-32 | **Add key…**; capture a non-modifier key; save. | New key triggers capture as expected; summary/help text updates. |
| TC-33 | **Add key…**; capture a mouse button; save. | Mouse hold/release behaves like a key binding. |
| TC-34 | **Launch Potato STT at Windows startup** (if shown): enable, sign out/in or reboot. | App starts at logon; disable removes Run entry (verify in Task Manager / Startup or registry if needed). |
| TC-35 | **Start minimized** with tray available. | No main window on launch; tray icon present; **Show** restores window. |
| TC-36 | **Start minimized** without tray (if reproducible). | Window minimized or behavior matches README; no silent failure. |

---

## 5. File → Transcribe media file

| ID | Steps | Expected |
|----|--------|----------|
| TC-40 | **File → Transcribe media file…** (or tray): choose a short **16 kHz mono PCM WAV**. | Transcript **appends** in Potato STT only; **nothing pasted** to previously focused app. |
| TC-41 | Choose **MP4** or **MP3** with FFmpeg on PATH. | Decode succeeds; transcript appears; finish message includes **Ready** (progress not stuck). |
| TC-42 | Same flow **without** FFmpeg: use only WAV. | Non-WAV fails with clear error; WAV still works. |
| TC-43 | File longer than **`POTATO_STT_TRANSCRIBE_CHUNK_SECONDS`** (default 120 s). | Chunked progress; completion without freezing OS; full transcript appended. |
| TC-44 | Trigger transcribe while engine still **not ready**. | Informative dialog; no crash. |

---

## 6. Subtitle export

| ID | Steps | Expected |
|----|--------|----------|
| TC-50 | After successful file transcribe, save **.srt**. | File created; opens in a text editor; cues and timestamps look plausible. |
| TC-51 | Save **.vtt**. | Valid WebVTT structure; timestamps plausible. |
| TC-52 | Cancel save dialog. | No file written; app stable. |

---

## 7. UI, menus, and Help

| ID | Steps | Expected |
|----|--------|----------|
| TC-59 | **Help → Using Potato STT…** | Modal opens with usage text (PTT, File/Settings, tray if applicable); **OK** closes it. |
| TC-60 | Use **File** and **Settings** menus (transcribe, options). | Actions work; no duplicate toolbar controls. |
| TC-61 | **Help → Clear local data (uninstall caches)…**: read text; **Open folder**. | Explorer opens to folder containing `Clear-PotatoSTTData.ps1` (dev: `scripts\`; frozen: next to EXE). |
| TC-62 | Same dialog: **Run in PowerShell** (quit app first in real cleanup). | New console opens; script runs (or prompts); no silent failure. |

---

## 8. Paste and elevation (optional)

| ID | Steps | Expected |
|----|--------|----------|
| TC-70 | Target app **not** elevated; Potato STT normal. | Paste works (TC-20). |
| TC-71 | Target app **Run as administrator**; Potato STT normal. | Paste may be blocked by Windows; transcript still in Potato STT window (document as expected limitation). |

---

## 9. Regression / stability

| ID | Steps | Expected |
|----|--------|----------|
| TC-80 | 30-minute session: mix PTT and 2–3 file transcribes. | Stable memory; no progressive slowdown requiring kill. |
| TC-81 | Close (**X**) to tray (with tray available); PTT from another app. | Still records and pastes when rules allow. |
| TC-82 | Unicode and punctuation in dictated text. | Sensible output; clipboard/paste not corrupted. |

---

## 10. Automated checks (supplement)

These are **not** manual UI tests but quick gates before/after a release:

```powershell
# Import smoke (from repo root, venv active)
.\.venv\Scripts\python.exe -c "import potato_stt.ui_main; print('ok')"

# Unit tests (stdlib runner; excludes pytest-qt UI tests)
.\.venv\Scripts\python.exe tests\run_tests.py

# Optional: pytest + UI e2e (mocked STT; install requirements-dev.txt first)
.\.venv\Scripts\python.exe -m pytest tests\test_ui_e2e.py -v
```

---

## Test log template

| Date | Build / commit | Tester | Backend | Environment | TC IDs run | Result | Notes |
|------|----------------|--------|---------|-------------|------------|--------|-------|
| | | | onnx_asr / http | venv / exe / CPU bat | | Pass/Fail | |
