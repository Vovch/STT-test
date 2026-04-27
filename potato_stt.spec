# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Potato STT (Windows GUI).

Build from the repository root (prefer the project venv — see build_windows_exe.ps1):
  python -m PyInstaller potato_stt.spec --clean --noconfirm

Output: dist/PotatoSTT/PotatoSTT.exe (one-folder bundle; recommended for ONNX/Qt/DirectML).

The default build installs CPU PyTorch + transformers (see build_windows_exe.ps1) so local RU→EN translation works in the frozen app (Marian weights still download from Hugging Face when the user agrees).

Do not use collect_all(PySide6): it pulls every Qt module (3D, QML, …) and makes the build huge.
"""
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

block_cipher = None

spec_root = os.path.dirname(os.path.abspath(SPEC))

datas: list = []
binaries: list = []
hiddenimports = [
    "potato_stt",
    "potato_stt.app",
    "potato_stt.config",
    "potato_stt.settings_keys",
    "potato_stt.core.audio_utils",
    "potato_stt.core.data_cleanup",
    "potato_stt.core.file_transcribe",
    "potato_stt.core.marian_ru_en",
    "potato_stt.core.media_decode",
    "potato_stt.core.onnx_asr_engine",
    "potato_stt.core.parakeet_windows_installer",
    "potato_stt.core.stt_client",
    "potato_stt.core.subtitle_export",
    "potato_stt.core.transcript_utils",
    "potato_stt.platform.recording_cues",
    "potato_stt.platform.win32_paste",
    "potato_stt.platform.win32_startup",
    "potato_stt.input.multi_tap",
    "potato_stt.input.ptt_capture",
    "potato_stt.input.ptt_keys",
    "potato_stt.web_search.history",
    "potato_stt.web_search.runner",
    "potato_stt.ui.icon",
    "potato_stt.ui.markdown",
    "potato_stt.ui.signals",
    "potato_stt.ui.status_format",
    "potato_stt.ui.widgets.pulse",
    "potato_stt.ui.widgets.overlays",
    "potato_stt.ui.dialogs.ptt_capture",
    "potato_stt.ui.dialogs.ffmpeg_missing",
    "potato_stt.ui.dialogs.help_dialog",
    "potato_stt.ui.dialogs.translation_consent",
    "potato_stt.ui.dialogs.web_summary",
    "potato_stt.ui.dialogs.clear_data",
    "potato_stt.ui.windows.main_window",
    "potato_stt.ui.windows.options_window",
    "potato_stt.ui.windows.web_search_history_window",
    "potato_stt.controllers.recording_controller",
    "potato_stt.controllers.hotkey_controller",
    "potato_stt.controllers.transcription_controller",
    "potato_stt.controllers.translation_coordinator",
    "potato_stt.controllers.web_search_coordinator",
    "potato_stt.controllers.file_transcribe_controller",
    "potato_stt.controllers.ffmpeg_install_helper",
    "sounddevice",
    "_sounddevice_data",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "certifi",
    "onnx_asr",
    "onnxruntime",
    "py7zr",
    "transformers.models.marian.modeling_marian",
    "transformers.models.marian.configuration_marian",
    "transformers.models.marian.tokenization_marian",
]

try:
    binaries += collect_dynamic_libs("onnxruntime")
except Exception:
    pass

try:
    binaries += collect_dynamic_libs("torch")
except Exception:
    pass

try:
    datas += collect_data_files("certifi")
except Exception:
    pass

# onnx_asr reads __version__ via importlib.metadata.version("onnx-asr"); frozen apps need dist-info.
try:
    datas += copy_metadata("onnx-asr")
except Exception:
    pass

# Bundled preprocessor ONNX models (e.g. nemo128.onnx) live under onnx_asr/preprocessors/data/.
try:
    datas += collect_data_files("onnx_asr")
except Exception:
    pass

# Recording cues (Kenney Interface Sounds CC0 WAVs; see potato_stt/assets/sounds/).
datas += [
    (
        os.path.join(spec_root, "potato_stt", "assets", "sounds"),
        os.path.join("potato_stt", "assets", "sounds"),
    ),
]

# PotatoSTTCPU.bat is not listed here: PyInstaller places `datas` under _internal/,
# but the launcher must sit next to PotatoSTT.exe. build_windows_exe.ps1 copies it
# into dist/PotatoSTT/ after the build.

a = Analysis(
    [os.path.join(spec_root, "potato_stt", "__main__.py")],
    pathex=[spec_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PotatoSTT",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PotatoSTT",
)
