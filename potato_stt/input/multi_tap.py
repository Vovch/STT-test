"""Multi-tap (double/triple) hotkey state machine — pure logic, no Qt.

Used by `MainWindow` to interpret successive presses of the push-to-talk hotkey as either:
  - "second_press_web": tap → tap-and-hold = web search; tap-and-hold once = PTT.
  - "double_ptt_triple_web": tap → tap → tap-and-hold = web search; tap-and-hold = PTT.

The class only depends on `threading` (so tests can monkeypatch `threading.Timer` globally) and a
monotonic clock (`time.monotonic` by default). Configuration and side effects come in via callables
so the state machine has no knowledge of QSettings, the recorder, or the UI.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

# Mirror the values used in `potato_stt.settings_keys` to avoid a hard dependency on the keys
# module from this pure-logic file. Callers translate their stored mode into one of these strings.
SECOND_PRESS_WEB = "second_press_web"
DOUBLE_PTT_TRIPLE_WEB = "double_ptt_triple_web"


class MultiTapStateMachine:
    """Track per-token press/release sequences and dispatch PTT vs web-search events."""

    def __init__(
        self,
        *,
        is_enabled: Callable[[], bool],
        delay_seconds: Callable[[], float],
        mode: Callable[[], str],
        add_ptt: Callable[[str], None],
        remove_ptt: Callable[[str], None],
        add_web: Callable[[str], None],
        remove_web: Callable[[str], None],
        is_web_active: Callable[[str], bool],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._is_enabled = is_enabled
        self._delay_s = delay_seconds
        self._mode = mode
        self._add_ptt = add_ptt
        self._remove_ptt = remove_ptt
        self._add_web = add_web
        self._remove_web = remove_web
        self._is_web_active = is_web_active
        self._clock = clock

        self._lock = threading.Lock()
        self.down_at: dict[str, float] = {}
        self.last_up: dict[str, float] = {}
        self._ptt_timers: dict[str, threading.Timer] = {}
        self._ptt_started: set[str] = set()
        self._mtp_phase: dict[str, int] = {}
        self._mtp_last_release: dict[str, float] = {}

    def cancel_all(self) -> None:
        with self._lock:
            timers = list(self._ptt_timers.values())
            self._ptt_timers.clear()
            self.down_at.clear()
            self._ptt_started.clear()
            self._mtp_phase.clear()
            self._mtp_last_release.clear()
        for t in timers:
            try:
                t.cancel()
            except Exception:
                pass

    def _hold_timer_fired(self, token: str) -> None:
        with self._lock:
            if token not in self.down_at:
                return
            self._ptt_timers.pop(token, None)
            self._ptt_started.add(token)
            self.last_up.pop(token, None)
            self._mtp_phase.pop(token, None)
            self._mtp_last_release.pop(token, None)
        self._add_ptt(token)

    def handle_press(self, token: str) -> bool:
        if not self._is_enabled():
            return False
        if self._mode() == DOUBLE_PTT_TRIPLE_WEB:
            return self._press_double_ptt_triple_web(token)
        return self._press_second_press_web(token)

    def _press_second_press_web(self, token: str) -> bool:
        now = self._clock()
        start_web = False
        with self._lock:
            last_up = self.last_up.get(token)
            if last_up is not None and now - last_up <= self._delay_s():
                self.last_up.pop(token, None)
                self.down_at[token] = now
                self._ptt_started.discard(token)
                start_web = True
            else:
                if token in self.down_at:
                    return True
                self.down_at[token] = now
                self._ptt_started.discard(token)
                timer = threading.Timer(
                    self._delay_s(),
                    self._hold_timer_fired,
                    args=(token,),
                )
                timer.daemon = True
                self._ptt_timers[token] = timer
                timer.start()
        if start_web:
            self._add_web(token)
        return True

    def _press_double_ptt_triple_web(self, token: str) -> bool:
        now = self._clock()
        T = self._delay_s()
        start_web = False
        cancel_timer: Optional[threading.Timer] = None
        with self._lock:
            last_rel = self._mtp_last_release.get(token)
            if last_rel is not None and now - last_rel > T:
                self._mtp_phase.pop(token, None)
                self._mtp_last_release.pop(token, None)
                last_rel = None

            phase = self._mtp_phase.get(token, 0)

            if phase == 2 and last_rel is not None and now - last_rel <= T:
                cancel_timer = self._ptt_timers.pop(token, None)
                self._mtp_phase.pop(token, None)
                self._mtp_last_release.pop(token, None)
                self.down_at.pop(token, None)
                start_web = True
            elif phase == 1 and last_rel is not None and now - last_rel <= T:
                if token in self.down_at:
                    return True
                self.down_at[token] = now
                self._ptt_started.discard(token)
                timer = threading.Timer(T, self._hold_timer_fired, args=(token,))
                timer.daemon = True
                self._ptt_timers[token] = timer
                timer.start()
            else:
                if token in self.down_at:
                    return True
                self.down_at[token] = now
                self._ptt_started.discard(token)
                timer = threading.Timer(T, self._hold_timer_fired, args=(token,))
                timer.daemon = True
                self._ptt_timers[token] = timer
                timer.start()

        if cancel_timer is not None:
            try:
                cancel_timer.cancel()
            except Exception:
                pass
        if start_web:
            self._add_web(token)
        return True

    def handle_release(self, token: str) -> bool:
        if not self._is_enabled():
            return False
        if self._is_web_active(token):
            with self._lock:
                self.down_at.pop(token, None)
                self._ptt_started.discard(token)
            self._remove_web(token)
            self._mtp_phase.pop(token, None)
            self._mtp_last_release.pop(token, None)
            return True
        if self._mode() == DOUBLE_PTT_TRIPLE_WEB:
            return self._release_double_ptt_triple_web(token)

        now = self._clock()
        with self._lock:
            down_at = self.down_at.pop(token, None)
            timer = self._ptt_timers.pop(token, None)
            ptt_started = token in self._ptt_started
            self._ptt_started.discard(token)
        if timer is not None:
            timer.cancel()
        if ptt_started:
            self._remove_ptt(token)
            return True
        if down_at is None:
            return False
        if now - down_at <= self._delay_s():
            with self._lock:
                self.last_up[token] = now
        return True

    def _release_double_ptt_triple_web(self, token: str) -> bool:
        now = self._clock()
        T = self._delay_s()
        with self._lock:
            down_at = self.down_at.pop(token, None)
            timer = self._ptt_timers.pop(token, None)
            ptt_started = token in self._ptt_started
            self._ptt_started.discard(token)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
        if ptt_started:
            self._remove_ptt(token)
            self._mtp_phase.pop(token, None)
            self._mtp_last_release.pop(token, None)
            return True
        if down_at is None:
            return False
        if now - down_at <= T:
            with self._lock:
                phase = self._mtp_phase.get(token, 0)
                if phase == 0:
                    self._mtp_phase[token] = 1
                elif phase == 1:
                    self._mtp_phase[token] = 2
                self._mtp_last_release[token] = now
            return True
        return False
