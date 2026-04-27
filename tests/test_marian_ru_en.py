"""Tests for local RU→EN translation helpers (no model download when only empty-path is used)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from potato_stt.core.marian_ru_en import (
    is_translation_runtime_ready,
    marian_model_id,
    preload_translation_model,
    translate_ru_en,
)


class TestMarianRuEn(unittest.TestCase):
    def test_marian_model_id_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POTATO_STT_MARIAN_RU_EN_MODEL", None)
            self.assertEqual(marian_model_id(), "Helsinki-NLP/opus-mt-ru-en")

    def test_translate_empty_returns_unchanged(self) -> None:
        self.assertEqual(translate_ru_en(""), "")
        self.assertEqual(translate_ru_en("   "), "   ")

    def test_is_translation_runtime_ready_is_bool(self) -> None:
        self.assertIsInstance(is_translation_runtime_ready(), bool)

    def test_preload_translation_model_callable(self) -> None:
        self.assertTrue(callable(preload_translation_model))


if __name__ == "__main__":
    unittest.main()
