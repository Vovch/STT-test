from __future__ import annotations

import unittest

from potato_stt.core.transcript_utils import (
    apply_word_filter,
    apply_word_filter_after_normalize,
    filter_subtitle_cues,
    parse_filter_phrases,
    postprocess_transcript_text,
)


class TestParseFilterPhrases(unittest.TestCase):
    def test_lines_and_commas(self) -> None:
        raw = "um, uh\nyou know\n# ignored\nlike"
        self.assertEqual(
            parse_filter_phrases(raw),
            ["um", "uh", "you know", "like"],
        )

    def test_empty(self) -> None:
        self.assertEqual(parse_filter_phrases(""), [])
        self.assertEqual(parse_filter_phrases("  \n#x\n"), [])


class TestApplyWordFilter(unittest.TestCase):
    def test_single_word_case_insensitive(self) -> None:
        t = apply_word_filter("Well um hello UM there.", ["um"])
        self.assertEqual(t, "Well hello there.")

    def test_longer_phrase_first(self) -> None:
        t = apply_word_filter("you know I mean well", ["you know", "you"])
        self.assertEqual(t, "I mean well")

    def test_mult_word_phrase(self) -> None:
        t = apply_word_filter("So you know what happened.", ["you know"])
        self.assertEqual(t, "So what happened.")

    def test_no_substring_inside_word(self) -> None:
        t = apply_word_filter("The umbral arc.", ["um"])
        self.assertEqual(t, "The umbral arc.")


class TestPostprocessTranscriptText(unittest.TestCase):
    def test_normalize_only_when_no_filter(self) -> None:
        t = postprocess_transcript_text("Hello.How are you", filter_phrases=None)
        self.assertTrue(t.startswith("Hello. How are you"))

    def test_with_filter(self) -> None:
        t = postprocess_transcript_text("Hello um world.", filter_phrases=["um"])
        self.assertIn("Hello", t)
        self.assertIn("world", t)
        self.assertNotIn("um", t.lower())


class TestFilterSubtitleCues(unittest.TestCase):
    def test_drops_empty_cues(self) -> None:
        cues = [(0.0, 1.0, "um"), (1.0, 2.0, "hello")]
        out = filter_subtitle_cues(cues, ["um"])
        self.assertEqual(out, [(1.0, 2.0, "hello")])


class TestApplyWordFilterAfterNormalize(unittest.TestCase):
    def test_strips_filler_after_normalize(self) -> None:
        t = apply_word_filter_after_normalize("Hello um world.", ["um"])
        self.assertNotIn("um", t.lower())
        self.assertIn("Hello", t)
        self.assertIn("world", t)


if __name__ == "__main__":
    unittest.main()
