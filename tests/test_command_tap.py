from __future__ import annotations

import unittest
import time

from potato_stt.input.command_tap import CommandTapStateMachine
from potato_stt.commands.runner import build_command_args


class CommandTapTests(unittest.TestCase):
    def test_quadruple_tap_hold_resolves_tap_count(self) -> None:
        started: list[tuple[str, int]] = []
        stopped: list[str] = []
        sm = CommandTapStateMachine(
            is_enabled=lambda: True,
            delay_seconds=lambda: 0.02,
            begin_capture=lambda tok, taps: started.append((tok, taps)),
            end_capture=lambda tok: stopped.append(tok),
        )
        try:
            tok = "vk:163"
            self.assertTrue(sm.handle_press(tok))
            self.assertTrue(sm.handle_release(tok))
            self.assertTrue(sm.handle_press(tok))
            self.assertTrue(sm.handle_release(tok))
            self.assertTrue(sm.handle_press(tok))
            self.assertTrue(sm.handle_release(tok))
            self.assertTrue(sm.handle_press(tok))
            time.sleep(0.05)
            self.assertEqual(started, [(tok, 4)])
            self.assertTrue(sm.handle_release(tok))
            self.assertEqual(stopped, [tok])
        finally:
            sm.cancel_all()

    def test_build_command_args_substitutes_transcript(self) -> None:
        argv, shell = build_command_args(
            'python -c "print({transcript_json})"',
            transcript="hello world",
            use_shell=False,
        )
        self.assertFalse(shell)
        assert isinstance(argv, list)
        self.assertIn('"hello world"', " ".join(argv))


if __name__ == "__main__":
    unittest.main()
