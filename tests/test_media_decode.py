from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import (
    ffmpeg_and_ffprobe_available,
    ffmpeg_encode_wav_for_test_format,
    first_user_test_media,
    user_test_media_paths,
    write_silence_wav_16k,
)

from potato_stt.core.media_decode import (
    FFMPEG_MISSING_USER_MESSAGE,
    FFmpegNotFoundError,
    decode_to_temp_wav_16k_mono,
    extract_chunk_wav_16k_mono,
    probe_media_duration_seconds,
)


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


class TestMediaDecode(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_probe_16k_wav_duration(self) -> None:
        p = write_silence_wav_16k(self.tmp / "silence.wav", 0.5)
        d = probe_media_duration_seconds(p)
        self.assertTrue(0.45 <= d <= 0.55)

    @patch("potato_stt.core.media_decode.which_ffprobe", return_value=None)
    def test_probe_non_wav_raises_ffmpeg_not_found_when_ffprobe_missing(
        self, _mock: object
    ) -> None:
        p = self.tmp / "clip.mp3"
        p.write_bytes(b"\xff\xfb\x90\x00")
        with self.assertRaises(FFmpegNotFoundError) as ctx:
            probe_media_duration_seconds(p)
        self.assertEqual(str(ctx.exception), FFMPEG_MISSING_USER_MESSAGE)

    def test_decode_to_temp_preserves_format(self) -> None:
        src = write_silence_wav_16k(self.tmp / "in.wav", 0.5)
        tmp, meas = decode_to_temp_wav_16k_mono(src)
        try:
            self.assertTrue(tmp.is_file())
            self.assertTrue(0.45 <= meas <= 0.55)
            d2 = probe_media_duration_seconds(tmp)
            self.assertLess(abs(d2 - meas), 0.05)
        finally:
            tmp.unlink(missing_ok=True)

    def test_extract_chunk_mid_file(self) -> None:
        src = write_silence_wav_16k(self.tmp / "long.wav", 35.0)
        chunk, meas = extract_chunk_wav_16k_mono(src, start_sec=10.0, duration_sec=5.0)
        try:
            self.assertTrue(chunk.is_file())
            self.assertTrue(4.8 <= meas <= 5.2)
            d = probe_media_duration_seconds(chunk)
            self.assertTrue(4.8 <= d <= 5.2)
        finally:
            chunk.unlink(missing_ok=True)


@unittest.skipUnless(
    ffmpeg_and_ffprobe_available(),
    "FFmpeg and ffprobe on PATH required for mp3/mp4/avi/ogg decode tests",
)
class TestFfmpegMediaFormats(unittest.TestCase):
    """Round-trip probe, full decode, and chunk extract for common non-WAV extensions."""

    _silence_seconds = 0.5

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.base_wav = write_silence_wav_16k(self.tmp / "base.wav", self._silence_seconds)

    def tearDown(self) -> None:
        self._td.cleanup()

    def _encode_or_skip(self, ext: str) -> Path:
        dest = self.tmp / f"clip{ext}"
        try:
            ffmpeg_encode_wav_for_test_format(self.base_wav, dest)
        except RuntimeError as e:
            self.skipTest(str(e))
        return dest

    def _assert_probe_decode_and_chunk(self, ext: str) -> None:
        src = self._encode_or_skip(ext)
        probed = probe_media_duration_seconds(src)
        self.assertTrue(
            0.25 <= probed <= 0.75,
            f"probe_media_duration_seconds for {ext} expected ~{self._silence_seconds}s, got {probed}",
        )
        tmp, meas = decode_to_temp_wav_16k_mono(src)
        try:
            self.assertTrue(
                0.25 <= meas <= 0.75,
                f"decode_to_temp_wav_16k_mono for {ext} expected ~{self._silence_seconds}s, got {meas}",
            )
        finally:
            _unlink(tmp)

        chunk, cmeas = extract_chunk_wav_16k_mono(src, start_sec=0.0, duration_sec=0.2)
        try:
            self.assertTrue(
                0.12 <= cmeas <= 0.28,
                f"extract_chunk for {ext} expected ~0.2s, got {cmeas}",
            )
        finally:
            _unlink(chunk)

    def test_mp3_probe_decode_chunk(self) -> None:
        self._assert_probe_decode_and_chunk(".mp3")

    def test_ogg_probe_decode_chunk(self) -> None:
        self._assert_probe_decode_and_chunk(".ogg")

    def test_mp4_probe_decode_chunk(self) -> None:
        self._assert_probe_decode_and_chunk(".mp4")

    def test_avi_probe_decode_chunk(self) -> None:
        self._assert_probe_decode_and_chunk(".avi")


class TestUserTestFileMedia(unittest.TestCase):
    """Runs when repo-root ``test_file/`` or ``test_files/`` contains media samples."""

    def test_user_media_probe_if_available(self) -> None:
        media = first_user_test_media()
        if media is None:
            self.skipTest(
                "No media in test_file/ or test_files/ (add audio/video there to run this check)"
            )
        d = probe_media_duration_seconds(media)
        self.assertGreater(d, 0.01)

    def test_user_media_extract_short_segment(self) -> None:
        media = first_user_test_media()
        if media is None:
            self.skipTest(
                "No media in test_file/ or test_files/ (add audio/video there to run this check)"
            )
        dur = probe_media_duration_seconds(media)
        take = min(2.0, max(0.5, dur * 0.1))
        try:
            chunk, meas = extract_chunk_wav_16k_mono(media, start_sec=0.0, duration_sec=take)
        except RuntimeError as e:
            if "ffmpeg" in str(e).lower():
                self.skipTest(f"FFmpeg required: {e}")
            raise
        try:
            self.assertTrue(chunk.is_file())
            self.assertGreater(meas, 0.1)
        finally:
            chunk.unlink(missing_ok=True)

    def test_each_user_media_probe_decode_and_short_chunk(self) -> None:
        paths = user_test_media_paths()
        if not paths:
            self.skipTest(
                "No media in test_file/ or test_files/ (add audio/video there to run this check)"
            )
        for media in paths:
            with self.subTest(path=media.name):
                d = probe_media_duration_seconds(media)
                self.assertGreater(d, 0.01)
                tmp, meas = decode_to_temp_wav_16k_mono(media)
                try:
                    self.assertTrue(tmp.is_file())
                    self.assertGreater(meas, 0.01)
                finally:
                    tmp.unlink(missing_ok=True)
                take = min(2.0, max(0.3, d * 0.05))
                try:
                    chunk, cmeas = extract_chunk_wav_16k_mono(
                        media, start_sec=0.0, duration_sec=take
                    )
                except RuntimeError as e:
                    if "ffmpeg" in str(e).lower():
                        self.skipTest(f"FFmpeg required: {e}")
                    raise
                try:
                    self.assertTrue(chunk.is_file())
                    self.assertGreater(cmeas, 0.05)
                finally:
                    chunk.unlink(missing_ok=True)
