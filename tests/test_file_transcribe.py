from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

from helpers import write_silence_wav_16k

from potato_stt.core.file_transcribe import transcribe_file_to_text_and_cues


@dataclass
class _FakeTimestampedResult:
    text: str
    tokens: list[str] | None = None
    timestamps: list[float] | None = None

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = []
        if self.timestamps is None:
            self.timestamps = []


def _http_kw() -> dict:
    return {
        "stt_api_url": "http://127.0.0.1:9/v1/audio/transcriptions",
        "stt_model": "test-model",
        "stt_response_format": "json",
        "stt_timeout_seconds": 5,
    }


class TestFileTranscribeOnnxMock(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_short_wav_single_chunk(self) -> None:
        wav = write_silence_wav_16k(self.tmp / "s.wav", 0.5)
        eng = MagicMock()
        eng.transcribe_wav_timestamped.return_value = _FakeTimestampedResult(
            "Hello from the test.",
            tokens=["Hello", " ", "from", " ", "the", " ", "test", "."],
            timestamps=[0.0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4],
        )
        text, cues = transcribe_file_to_text_and_cues(
            wav,
            chunk_seconds=120.0,
            stt_backend="onnx_asr",
            onnx_engine=eng,
            on_progress=None,
            **_http_kw(),
        )
        self.assertIn("hello", text.lower())
        eng.transcribe_wav_timestamped.assert_called_once()
        self.assertGreaterEqual(len(cues), 1)

    def test_long_wav_multi_chunk(self) -> None:
        wav = write_silence_wav_16k(self.tmp / "long.wav", 35.0)
        eng = MagicMock()
        eng.transcribe_wav_timestamped.side_effect = [
            _FakeTimestampedResult("First segment text."),
            _FakeTimestampedResult("Second segment text."),
        ]
        progress: list[str] = []
        text, _cues = transcribe_file_to_text_and_cues(
            wav,
            chunk_seconds=30.0,
            stt_backend="onnx_asr",
            onnx_engine=eng,
            on_progress=lambda m: progress.append(m),
            **_http_kw(),
        )
        self.assertEqual(eng.transcribe_wav_timestamped.call_count, 2)
        self.assertIn("first", text.lower())
        self.assertIn("second", text.lower())
        self.assertTrue(any("part 1/" in p for p in progress))
        self.assertTrue(any("part 2/" in p for p in progress))

    def test_requires_onnx_engine(self) -> None:
        wav = write_silence_wav_16k(self.tmp / "x.wav", 0.5)
        with self.assertRaisesRegex(RuntimeError, "ONNX ASR engine"):
            transcribe_file_to_text_and_cues(
                wav,
                chunk_seconds=120.0,
                stt_backend="onnx_asr",
                onnx_engine=None,
                on_progress=None,
                **_http_kw(),
            )
