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
    "potato_stt.ui_main",
    "potato_stt.marian_ru_en",
    "potato_stt.audio_utils",
    "potato_stt.config",
    "potato_stt.onnx_asr_engine",
    "potato_stt.parakeet_windows_installer",
    "potato_stt.stt_client",
    "potato_stt.media_decode",
    "potato_stt.file_transcribe",
    "potato_stt.subtitle_export",
    "potato_stt.win32_paste",
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
