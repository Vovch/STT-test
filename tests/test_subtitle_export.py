from __future__ import annotations

import unittest

from potato_stt.core.subtitle_export import (
    cues_to_srt,
    polish_cues_merge_short_fragments,
    tokens_to_cues,
)


class TestSubtitleExport(unittest.TestCase):
    def test_tokens_to_cues_and_srt(self) -> None:
        cues = tokens_to_cues(
            ["Hi", ",", " ", "there"],
            [0.0, 0.2, 0.25, 0.3],
            total_duration=2.0,
        )
        self.assertTrue(cues)
        srt = cues_to_srt(cues)
        self.assertIn("Hi", srt)
        self.assertIn("-->", srt)

    def test_subword_stays_in_one_cue_with_tight_char_limit(self) -> None:
        # BPE-style split: second token continues the word (no leading space / ▁).
        cues = tokens_to_cues(
            ["Hel", "lo", " ", "world", "."],
            [0.0, 0.08, 0.12, 0.2, 0.28],
            total_duration=2.0,
            max_chars=4,
        )
        joined = " ".join(t for _, _, t in cues)
        self.assertIn("Hello", joined.replace(" ", ""))

    def test_polish_merges_trailing_two_word_fragment(self) -> None:
        raw = [
            (0.0, 1.0, "This is a longer subtitle line here"),
            (1.0, 2.0, "or not"),
        ]
        out = polish_cues_merge_short_fragments(raw)
        self.assertEqual(len(out), 1)
        self.assertIn("or not", out[0][2])
