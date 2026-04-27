from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


TARGET_SAMPLE_RATE = 16000

# Official builds page (shown as a button in the UI when FFmpeg is missing).
FFMPEG_DOWNLOAD_URL = "https://ffmpeg.org/download.html"

# winget argv after the `winget` executable (UI copy + Windows install button use the same flags).
FFMPEG_WINGET_INSTALL_ARGV = [
    "install",
    "-e",
    "--id",
    "Gyan.FFmpeg",
    "--accept-package-agreements",
    "--accept-source-agreements",
]
FFMPEG_WINGET_INSTALL_CLI = "winget " + " ".join(FFMPEG_WINGET_INSTALL_ARGV)

# Body text shown around the command in the FFmpeg-required dialog (exception message matches).
FFMPEG_MISSING_CONTEXT_BEFORE_CLI = (
    "Proposal: install FFmpeg (it includes ffprobe) so you can transcribe MP3, MP4, and most "
    "other formats.\n\n"
    "On Windows, open PowerShell or Command Prompt and run:"
)
FFMPEG_MISSING_CONTEXT_AFTER_CLI = (
    "When the installer finishes, close and reopen Potato STT (or sign out of Windows) so "
    "your PATH includes ffmpeg and ffprobe.\n\n"
    "If you prefer a manual install, use the download page button below and add the "
    "extracted bin folder to your PATH.\n\n"
    "Without FFmpeg you can still use uncompressed 16 kHz mono PCM .wav files."
)

FFMPEG_MISSING_USER_MESSAGE = (
    FFMPEG_MISSING_CONTEXT_BEFORE_CLI
    + "\n\n    "
    + FFMPEG_WINGET_INSTALL_CLI
    + "\n\n"
    + FFMPEG_MISSING_CONTEXT_AFTER_CLI
)


class FFmpegNotFoundError(RuntimeError):
    """Raised when FFmpeg or ffprobe is required for the media path but not available."""


def which_ffmpeg() -> Path | None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        return None
    return Path(exe)


def which_ffprobe() -> Path | None:
    exe = shutil.which("ffprobe")
    if exe is not None:
        return Path(exe)
    ffmpeg = which_ffmpeg()
    if ffmpeg is None:
        return None
    for name in ("ffprobe.exe", "ffprobe"):
        candidate = ffmpeg.parent / name
        if candidate.is_file():
            return candidate
    return None


def _wav_duration_seconds(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        if rate <= 0:
            return 0.0
        return frames / float(rate)


def _is_direct_16k_mono_pcm_wav(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as wf:
            if wf.getnchannels() != 1:
                return False
            if wf.getsampwidth() != 2:
                return False
            if wf.getcomptype() != "NONE":
                return False
            return wf.getframerate() == TARGET_SAMPLE_RATE
    except (wave.Error, OSError):
        return False


def probe_media_duration_seconds(source: Path) -> float:
    """
    Duration in seconds. Uses the wave module for .wav when possible, otherwise ffprobe.
    """
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if source.suffix.lower() == ".wav":
        try:
            d = _wav_duration_seconds(source)
            if d > 0:
                return d
        except (wave.Error, OSError, ValueError, ZeroDivisionError):
            pass

    ffprobe = which_ffprobe()
    if ffprobe is None:
        raise FFmpegNotFoundError(FFMPEG_MISSING_USER_MESSAGE)
    cmd = [
        str(ffprobe),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"ffprobe failed: {err}")
    raw = (proc.stdout or "").strip()
    if not raw or raw.upper() == "N/A":
        raise RuntimeError("ffprobe returned no duration for this file.")
    return float(raw)


def _skip_wave_frames(wf: wave.Wave_read, nframes: int) -> None:
    remaining = max(0, nframes)
    while remaining > 0:
        chunk = min(remaining, 65536)
        wf.readframes(chunk)
        remaining -= chunk


def _extract_wav_chunk_pcm16_mono_16k(
    source: Path,
    start_sec: float,
    duration_sec: float,
    *,
    prefix: str,
) -> tuple[Path, float]:
    if not _is_direct_16k_mono_pcm_wav(source):
        raise ValueError("internal: source is not 16 kHz mono PCM WAV")

    fd, tmp_name = tempfile.mkstemp(suffix=".wav", prefix=prefix)
    tmp = Path(tmp_name)
    try:
        os.close(fd)
    except OSError:
        pass

    try:
        with wave.open(str(source), "rb") as wf_in, wave.open(str(tmp), "wb") as wf_out:
            rate = wf_in.getframerate()
            start_frame = int(max(0.0, start_sec) * rate)
            want_frames = int(max(0.0, duration_sec) * rate)
            total = wf_in.getnframes()
            if start_frame >= total:
                wf_out.setnchannels(1)
                wf_out.setsampwidth(2)
                wf_out.setframerate(TARGET_SAMPLE_RATE)
                wf_out.writeframes(b"")
                return tmp, 0.0

            _skip_wave_frames(wf_in, start_frame)
            available = total - start_frame
            n_read = min(want_frames, available)
            pcm = wf_in.readframes(n_read)
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)
            wf_out.setframerate(TARGET_SAMPLE_RATE)
            wf_out.writeframes(pcm)
        return tmp, _wav_duration_seconds(tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def extract_chunk_wav_16k_mono(
    source: Path,
    start_sec: float,
    duration_sec: float,
    *,
    prefix: str = "potato-stt-chunk-",
) -> tuple[Path, float]:
    """
    Decode/extract [start_sec, start_sec + duration_sec) into a temp mono 16 kHz PCM16 WAV.

    Returns (temp_path, measured_duration_seconds). Caller must delete temp_path.
    """
    if duration_sec <= 0:
        raise ValueError("Chunk duration must be positive.")
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))

    if _is_direct_16k_mono_pcm_wav(source):
        return _extract_wav_chunk_pcm16_mono_16k(source, start_sec, duration_sec, prefix=prefix)

    ffmpeg = which_ffmpeg()
    if ffmpeg is None:
        raise FFmpegNotFoundError(FFMPEG_MISSING_USER_MESSAGE)

    fd, tmp_name = tempfile.mkstemp(suffix=".wav", prefix=prefix)
    tmp = Path(tmp_name)
    try:
        os.close(fd)
    except OSError:
        pass

    try:
        # -ss after -i: accurate cuts (slower than input seeking, avoids multi-hour RAM spikes).
        cmd = [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-ss",
            f"{max(0.0, start_sec):.3f}",
            "-t",
            f"{duration_sec:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(TARGET_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(tmp),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg failed: {err}")
        return tmp, _wav_duration_seconds(tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def decode_to_temp_wav_16k_mono(source: Path, *, prefix: str = "potato-stt-media-") -> tuple[Path, float]:
    """
    Produce a mono 16 kHz PCM16 WAV suitable for onnx-asr / STT.

    Returns (path_to_temp_wav, duration_seconds).

    Raises FileNotFoundError if source is missing; FFmpegNotFoundError if FFmpeg is required
    but not installed (with install hint).
    """
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))

    fd, tmp_name = tempfile.mkstemp(suffix=".wav", prefix=prefix)
    tmp = Path(tmp_name)
    try:
        os.close(fd)
    except OSError:
        pass

    try:
        if _is_direct_16k_mono_pcm_wav(source):
            shutil.copyfile(source, tmp)
            duration = _wav_duration_seconds(tmp)
            return tmp, duration

        ffmpeg = which_ffmpeg()
        if ffmpeg is None:
            tmp.unlink(missing_ok=True)
            raise FFmpegNotFoundError(FFMPEG_MISSING_USER_MESSAGE)

        cmd = [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(TARGET_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(tmp),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg failed: {err}")

        duration = _wav_duration_seconds(tmp)
        return tmp, duration
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
