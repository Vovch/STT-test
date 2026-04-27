"""Block until the user presses a key or mouse button (for PTT binding)."""
from __future__ import annotations

import threading
import time
from typing import Optional

from pynput import keyboard, mouse

from potato_stt.input.ptt_keys import (
    build_chord_spec,
    keyboard_event_to_capture_spec,
    keyboard_modifier_for_event,
    mouse_button_to_spec,
)


def capture_ptt_binding(
    cancel_event: Optional[threading.Event] = None,
    timeout_seconds: float = 120.0,
) -> Optional[str]:
    """
    Wait for the first keyboard key (Escape = cancel) or mouse button press.
    Returns a canonical spec string, or None if cancelled / timeout.
    """
    out: list[Optional[str]] = [None]
    done = threading.Event()
    kb_box: list[Optional[keyboard.Listener]] = [None]
    ms_box: list[Optional[mouse.Listener]] = [None]
    pressed_modifiers: set[str] = set()
    saw_chord_candidate = False

    def cleanup() -> None:
        for box in (kb_box, ms_box):
            lst = box[0]
            if lst is not None:
                try:
                    lst.stop()
                except Exception:
                    pass
                box[0] = None

    def finish(val: Optional[str]) -> None:
        if out[0] is not None:
            return
        out[0] = val
        done.set()
        cleanup()

    def on_press(key) -> None:  # type: ignore[no-untyped-def]
        nonlocal saw_chord_candidate
        if out[0] is not None:
            return
        vk = getattr(key, "vk", None)
        if vk == 27:
            finish(None)
            return
        mod = keyboard_modifier_for_event(key)
        if mod is not None:
            pressed_modifiers.add(mod)
            if len(pressed_modifiers) >= 2:
                saw_chord_candidate = True
            return
        spec = keyboard_event_to_capture_spec(key)
        if spec is not None:
            if pressed_modifiers:
                finish(build_chord_spec(set(pressed_modifiers), spec))
                return
            finish(spec)

    def on_release(key) -> None:  # type: ignore[no-untyped-def]
        nonlocal saw_chord_candidate
        if out[0] is not None:
            return
        mod = keyboard_modifier_for_event(key)
        if mod is None:
            return
        if saw_chord_candidate and len(pressed_modifiers) >= 2:
            finish(build_chord_spec(set(pressed_modifiers), None))
            return
        pressed_modifiers.discard(mod)
        if not pressed_modifiers:
            spec = keyboard_event_to_capture_spec(key)
            if spec is not None:
                finish(spec)

    def on_click(x, y, button, pressed) -> None:  # type: ignore[no-untyped-def]
        if not pressed or out[0] is not None:
            return
        spec = mouse_button_to_spec(button)
        if spec is not None:
            finish(spec)

    kb = keyboard.Listener(on_press=on_press, on_release=on_release)
    ms = mouse.Listener(on_click=on_click)
    kb_box[0] = kb
    ms_box[0] = ms
    kb.start()
    ms.start()

    deadline = time.monotonic() + timeout_seconds
    while not done.is_set():
        if cancel_event is not None and cancel_event.is_set():
            finish(None)
            break
        if time.monotonic() >= deadline:
            finish(None)
            break
        done.wait(0.05)

    cleanup()
    return out[0]
