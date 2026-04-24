from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestRecordingCues(unittest.TestCase):
    def test_sounds_dir_unfrozen(self) -> None:
        import potato_stt.recording_cues as rc

        d = rc._sounds_dir()
        self.assertTrue(str(d).replace("\\", "/").endswith("potato_stt/assets/sounds"))

    def test_sounds_dir_frozen(self) -> None:
        import potato_stt.recording_cues as rc

        fake_meipass = Path("/tmp/fake_meipass")
        with patch.object(rc.sys, "frozen", True, create=True):
            with patch.object(rc.sys, "_MEIPASS", str(fake_meipass), create=True):
                d = rc._sounds_dir()
        self.assertEqual(d, fake_meipass / "potato_stt" / "assets" / "sounds")

    def test_non_windows_no_crash(self) -> None:
        import potato_stt.recording_cues as rc

        if sys.platform == "win32":
            self.skipTest("Windows uses winsound")
        with patch.object(rc.sys, "platform", "linux"):
            rc.play_recording_started_cue()
            rc.play_recording_stopped_cue()

    @unittest.skipUnless(sys.platform == "win32", "requires winsound")
    def test_windows_play_sound_when_file_exists(self) -> None:
        import winsound

        import potato_stt.recording_cues as rc

        repo = Path(__file__).resolve().parents[1]
        src = repo / "potato_stt" / "assets" / "sounds" / "recording_start.wav"
        if not src.is_file():
            self.skipTest("Bundled cue WAV missing")

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            shutil.copy2(src, tdp / "recording_start.wav")
            with patch.object(rc.sys, "platform", "win32"):
                with patch("winsound.PlaySound") as ps:
                    with patch.object(rc, "_sounds_dir", return_value=tdp):
                        rc.play_recording_started_cue()
            ps.assert_called_once()
            args, _kw = ps.call_args
            self.assertEqual(Path(args[0]).name, "recording_start.wav")
            self.assertEqual(args[1], winsound.SND_FILENAME | winsound.SND_ASYNC)

    @unittest.skipUnless(sys.platform == "win32", "requires winsound")
    def test_missing_file_no_playsound(self) -> None:
        import potato_stt.recording_cues as rc

        empty = Path(__file__).resolve().parent / "nonexistent_cues_dir_xyz"
        with patch("winsound.PlaySound") as ps:
            with patch.object(rc, "_sounds_dir", return_value=empty):
                rc.play_recording_started_cue()
                rc.play_recording_stopped_cue()
            ps.assert_not_called()
