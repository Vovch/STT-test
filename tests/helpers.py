from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from potato_stt.core.audio_utils import write_wav_from_int16_pcm


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def write_silence_wav_16k(path: Path, seconds: float) -> Path:
    samples = int(seconds * 16000)
    pcm = np.zeros(samples, dtype=np.int16)
    write_wav_from_int16_pcm(pcm, path, sample_rate=16000)
    return path


def ffmpeg_and_ffprobe_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def ffmpeg_encode_wav_for_test_format(src_wav: Path, dest: Path, *, timeout: float = 120) -> None:
    """
    Encode a 16 kHz mono PCM WAV into dest (.mp3, .ogg, .mp4, .avi) for media_decode tests.
    Requires FFmpeg on PATH with typical codecs (libmp3lame, libvorbis, aac).
    """
    ext = dest.suffix.lower()
    if ext == ".mp3":
        audio_args = ["-c:a", "libmp3lame", "-b:a", "64k"]
    elif ext == ".ogg":
        audio_args = ["-c:a", "libvorbis", "-q:a", "3"]
    elif ext == ".mp4":
        audio_args = ["-c:a", "aac", "-b:a", "64k", "-vn"]
    elif ext == ".avi":
        audio_args = ["-c:a", "pcm_s16le"]
    else:
        raise ValueError(f"unsupported extension for test encode: {ext}")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not on PATH")

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src_wav),
        *audio_args,
        str(dest),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"ffmpeg encode to {ext} failed: {err}")


_USER_MEDIA_EXTS = frozenset(
    {
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
        ".opus",
        ".wma",
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".avi",
        ".aif",
        ".aiff",
    }
)


def user_test_media_paths() -> list[Path]:
    """Audio/video samples under repo-root ``test_file/`` or ``test_files/`` (sorted, deduped)."""
    root = repo_root()
    candidates: list[Path] = []
    for name in ("test_file", "test_files"):
        folder = root / name
        if not folder.is_dir():
            continue
        candidates.extend(
            p
            for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _USER_MEDIA_EXTS
        )
    # Stable order: by path string; dedupe same file resolved (e.g. junction)
    seen: set[str] = set()
    out: list[Path] = []
    for p in sorted(candidates, key=lambda x: str(x).lower()):
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def first_user_test_media() -> Path | None:
    paths = user_test_media_paths()
    return paths[0] if paths else None
