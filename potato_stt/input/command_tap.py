from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class CommandTapStateMachine:
    """Recognize 1x..4x taps ending with hold and trigger capture callbacks."""

    def __init__(
        self,
        *,
        is_enabled: Callable[[], bool],
        delay_seconds: Callable[[], float],
        begin_capture: Callable[[str, int], None],
        end_capture: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._is_enabled = is_enabled
        self._delay_s = delay_seconds
        self._begin_capture = begin_capture
        self._end_capture = end_capture
        self._clock = clock
        self._lock = threading.Lock()
        self._down_at: dict[str, float] = {}
        self._last_release_at: dict[str, float] = {}
        self._phase: dict[str, int] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._active: set[str] = set()

    def cancel_all(self) -> None:
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
            self._down_at.clear()
            self._last_release_at.clear()
            self._phase.clear()
            self._active.clear()
        for t in timers:
            try:
                t.cancel()
            except Exception:
                pass

    def _hold_fired(self, token: str) -> None:
        with self._lock:
            if token not in self._down_at:
                return
            phase = self._phase.get(token, 0) + 1
            taps = max(1, min(4, phase))
            self._timers.pop(token, None)
            self._active.add(token)
            self._phase.pop(token, None)
            self._last_release_at.pop(token, None)
        self._begin_capture(token, taps)

    def handle_press(self, token: str) -> bool:
        if not self._is_enabled():
            return False
        now = self._clock()
        with self._lock:
            if token in self._active or token in self._down_at:
                return True
            last_up = self._last_release_at.get(token)
            delay = self._delay_s()
            if last_up is None or now - last_up > delay:
                self._phase[token] = 0
            self._down_at[token] = now
            timer = threading.Timer(delay, self._hold_fired, args=(token,))
            timer.daemon = True
            self._timers[token] = timer
            timer.start()
        return True

    def handle_release(self, token: str) -> bool:
        if not self._is_enabled():
            return False
        with self._lock:
            down = self._down_at.pop(token, None)
            timer = self._timers.pop(token, None)
            active = token in self._active
            if active:
                self._active.discard(token)
        if active:
            self._end_capture(token)
            return True
        if down is None:
            return False
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
        with self._lock:
            phase = self._phase.get(token, 0)
            self._phase[token] = min(4, phase + 1)
            self._last_release_at[token] = self._clock()
        return True
