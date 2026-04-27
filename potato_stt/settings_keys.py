"""Single source of truth for QSettings keys and first-run defaults.

QSettings uses org/app `PotatoSTT` / `PotatoSTT` everywhere; keep keys in sync with
existing values so persisted UI state survives the refactor.
"""

from __future__ import annotations


START_MINIMIZED_SETTING = "ui/start_minimized"
UI_LANGUAGE = "ui/language"
UI_LANGUAGE_AUTO = "auto"
UI_LANGUAGE_EN = "en"
UI_LANGUAGE_RU = "ru"
AUDIO_CUES_ENABLED = "ui/audio_cues_enabled"
VISUAL_CUES_ENABLED = "ui/visual_cues_enabled"
TRANSCRIPT_FILTER_ENABLED = "ui/transcript_filter_enabled"
TRANSCRIPT_FILTER_WORDS = "ui/transcript_filter_words"
TRANSLATE_RU_EN_ENABLED = "ui/translate_ru_en_enabled"
TRANSLATION_MODEL_FETCH_APPROVED = "ui/translation_model_fetch_approved"

WEB_SEARCH_ENABLED = "web_search/enabled"
WEB_DOUBLE_TAP_ENABLED = "web_search/double_tap_enabled"
WEB_DOUBLE_TAP_WINDOW_MS = "web_search/double_tap_window_ms"
WEB_SEARCH_ARGV_LINE = "web_search/argv_line"
WEB_SEARCH_USE_SHELL = "web_search/use_shell"
WEB_MULTI_TAP_MODE = "web_search/multi_tap_mode"
WEB_MULTI_TAP_SECOND_PRESS_WEB = "second_press_web"
WEB_MULTI_TAP_DOUBLE_PTT_TRIPLE_WEB = "double_ptt_triple_web"

# First-run defaults (used when a key is absent; existing QSettings win once saved).
AUDIO_CUES_ENABLED_DEFAULT = True
VISUAL_CUES_ENABLED_DEFAULT = True
TRANSCRIPT_FILTER_ENABLED_DEFAULT = True
TRANSCRIPT_FILTER_WORDS_DEFAULT = "uh\num"
TRANSLATE_RU_EN_ENABLED_DEFAULT = False
TRANSLATION_MODEL_FETCH_APPROVED_DEFAULT = False
WEB_SEARCH_ENABLED_DEFAULT = True
WEB_DOUBLE_TAP_ENABLED_DEFAULT = False
WEB_DOUBLE_TAP_WINDOW_MS_DEFAULT = 300
WEB_MULTI_TAP_MODE_DEFAULT = WEB_MULTI_TAP_SECOND_PRESS_WEB

# Max concurrent web-search subprocesses (STT still one-at-a-time per mic).
WEB_OPENCODE_MAX_CONCURRENT = 2
DOUBLE_TAP_WINDOW_MS_MIN = 150
DOUBLE_TAP_WINDOW_MS_MAX = 1500

# Tray balloon when the main window is not visible (OS may still cap duration).
WEB_TRAY_MESSAGE_MS_WHEN_HIDDEN = 25000
