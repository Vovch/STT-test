"""Web search subprocess invocation and concurrency limiting.

`MainWindow` keeps the post-ready UI handling (`_on_web_search_ready`, `_show_web_summary_nonmodal`)
because tests rely on those names being patchable on the window. The coordinator owns the
underlying OpenCode invocation, the OpenCode concurrency semaphore, and the pending tray summary
state used when a summary arrives while the window is hidden/minimized.
"""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QSettings

from potato_stt.config import Settings
from potato_stt.settings_keys import (
    WEB_OPENCODE_MAX_CONCURRENT,
    WEB_SEARCH_ARGV_LINE,
    WEB_SEARCH_USE_SHELL,
)
from potato_stt.web_search.runner import run_web_search_cli


class WebSearchCoordinator:
    """Owns the OpenCode CLI invocation and the OpenCode concurrency semaphore."""

    def __init__(self, *, qsettings: QSettings, settings: Settings) -> None:
        self._qsettings = qsettings
        self._settings = settings
        self.semaphore = threading.Semaphore(WEB_OPENCODE_MAX_CONCURRENT)
        self.pending_tray_summary: Optional[tuple[float, str, str]] = None

    def run_command(self, query: str) -> str:
        """Execute the configured web-search CLI synchronously; returns its stdout."""
        line = self._qsettings.value(WEB_SEARCH_ARGV_LINE, "", type=str)
        if not isinstance(line, str):
            line = ""
        use_shell = bool(self._qsettings.value(WEB_SEARCH_USE_SHELL, False, type=bool))
        timeout_s = max(45, int(self._settings.stt_timeout_seconds) * 6)
        return run_web_search_cli(
            line.strip() or None,
            query=query,
            use_shell=use_shell,
            timeout_seconds=timeout_s,
        )
