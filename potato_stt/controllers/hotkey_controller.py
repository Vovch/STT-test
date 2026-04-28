"""Global keyboard/mouse hotkey listeners for push-to-talk and web search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from pynput import keyboard, mouse

from potato_stt.input.ptt_keys import (
    chord_required_modifiers,
    event_matches_any_spec_mouse,
    is_chord_spec,
    keyboard_modifier_for_event,
    keyboard_token_for_event,
    matching_keyboard_specs,
    mouse_token_for_button,
    needs_keyboard_listener,
    needs_mouse_listener,
)


def spec_hold_token(spec: str) -> str:
    return f"spec:{spec}"


@dataclass
class HotkeyCallbacks:
    """Callbacks the listener invokes on key/mouse events. All run on listener threads."""

    add_ptt: Callable[[str], None]
    remove_ptt: Callable[[str], None]
    add_web: Callable[[str], None]
    remove_web: Callable[[str], None]
    handle_multi_tap_press: Callable[[str], bool]
    handle_multi_tap_release: Callable[[str], bool]
    has_ptt_token: Callable[[str], bool]
    has_web_token: Callable[[str], bool]
    on_error: Callable[[str], None]
    handle_command_tap_press: Callable[[str], bool]
    handle_command_tap_release: Callable[[str], bool]


class HotkeyController:
    """Owns the keyboard/mouse listeners. Composed by `MainWindow`; no Qt dependencies here."""

    def __init__(self, callbacks: HotkeyCallbacks) -> None:
        self._cb = callbacks
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._modifiers_down: set[str] = set()
        self._ptt_specs: list[str] = []
        self._web_specs: list[str] = []
        self._command_tap_specs: list[str] = []

    def stop(self) -> None:
        for attr in ("_keyboard_listener", "_mouse_listener"):
            lst = getattr(self, attr)
            if lst is not None:
                try:
                    lst.stop()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._modifiers_down.clear()

    def start(
        self,
        *,
        ptt_specs: list[str],
        web_specs: list[str],
        command_tap_specs: list[str],
    ) -> None:
        """Stop any active listeners, then register fresh ones for the given specs."""
        self.stop()
        self._ptt_specs = list(ptt_specs)
        self._web_specs = list(web_specs)
        self._command_tap_specs = list(command_tap_specs)
        ptt = self._ptt_specs
        web = self._web_specs
        cmd = self._command_tap_specs
        try:
            if (
                needs_keyboard_listener(ptt)
                or needs_keyboard_listener(web)
                or needs_keyboard_listener(cmd)
            ):
                self._keyboard_listener = keyboard.Listener(
                    on_press=self._on_press,
                    on_release=self._on_release,
                )
                self._keyboard_listener.daemon = True
                self._keyboard_listener.start()
            if needs_mouse_listener(ptt) or needs_mouse_listener(web) or needs_mouse_listener(cmd):
                self._mouse_listener = mouse.Listener(on_click=self._on_click)
                self._mouse_listener.daemon = True
                self._mouse_listener.start()
        except Exception as e:
            self._cb.on_error(f"Hotkey init failed: {type(e).__name__}: {e}")

    def _on_press(self, key) -> None:  # type: ignore[no-untyped-def]
        mod = keyboard_modifier_for_event(key)
        if mod is not None:
            self._modifiers_down.add(mod)
        command_matches = matching_keyboard_specs(
            self._command_tap_specs, key, set(self._modifiers_down)
        )
        if command_matches:
            if len(command_matches) == 1 and not is_chord_spec(command_matches[0]):
                if self._cb.handle_command_tap_press(keyboard_token_for_event(key)):
                    return
        ptt_matches = matching_keyboard_specs(self._ptt_specs, key, set(self._modifiers_down))
        if ptt_matches:
            if len(ptt_matches) == 1 and not is_chord_spec(ptt_matches[0]):
                if self._cb.handle_multi_tap_press(keyboard_token_for_event(key)):
                    return
            for spec in ptt_matches:
                tok = (
                    spec_hold_token(spec)
                    if is_chord_spec(spec)
                    else keyboard_token_for_event(key)
                )
                self._cb.add_ptt(tok)
            return
        if self._web_specs:
            web_matches = matching_keyboard_specs(self._web_specs, key, set(self._modifiers_down))
            if web_matches:
                for spec in web_matches:
                    tok = (
                        spec_hold_token(spec)
                        if is_chord_spec(spec)
                        else keyboard_token_for_event(key)
                    )
                    self._cb.add_web(tok)

    def _on_release(self, key) -> None:  # type: ignore[no-untyped-def]
        mod = keyboard_modifier_for_event(key)
        command_matches = matching_keyboard_specs(
            self._command_tap_specs, key, set(self._modifiers_down)
        )
        if command_matches:
            if len(command_matches) == 1 and not is_chord_spec(command_matches[0]):
                handled = self._cb.handle_command_tap_release(keyboard_token_for_event(key))
                if mod is not None:
                    self._modifiers_down.discard(mod)
                if handled:
                    return
        ptt_matches = matching_keyboard_specs(self._ptt_specs, key, set(self._modifiers_down))
        if ptt_matches:
            if len(ptt_matches) == 1 and not is_chord_spec(ptt_matches[0]):
                handled = self._cb.handle_multi_tap_release(keyboard_token_for_event(key))
                if mod is not None:
                    self._modifiers_down.discard(mod)
                if handled:
                    return
            for spec in ptt_matches:
                tok = (
                    spec_hold_token(spec)
                    if is_chord_spec(spec)
                    else keyboard_token_for_event(key)
                )
                self._cb.remove_ptt(tok)
        if self._web_specs:
            web_matches = matching_keyboard_specs(self._web_specs, key, set(self._modifiers_down))
            if web_matches:
                for spec in web_matches:
                    tok = (
                        spec_hold_token(spec)
                        if is_chord_spec(spec)
                        else keyboard_token_for_event(key)
                    )
                    self._cb.remove_web(tok)
        if mod is not None:
            self._release_chords_with_modifier(mod, self._ptt_specs, mode="ptt")
            self._release_chords_with_modifier(mod, self._web_specs, mode="web")
            self._modifiers_down.discard(mod)

    def _release_chords_with_modifier(self, mod: str, specs: list[str], *, mode: str) -> None:
        for spec in specs:
            if not is_chord_spec(spec):
                continue
            if mod not in chord_required_modifiers(spec):
                continue
            tok = spec_hold_token(spec)
            if mode == "ptt" and self._cb.has_ptt_token(tok):
                self._cb.remove_ptt(tok)
            elif mode == "web" and self._cb.has_web_token(tok):
                self._cb.remove_web(tok)

    def _on_click(self, x, y, button, pressed) -> None:  # type: ignore[no-untyped-def]
        tok = mouse_token_for_button(button)
        if event_matches_any_spec_mouse(self._command_tap_specs, button):
            if pressed:
                if self._cb.handle_command_tap_press(tok):
                    return
            else:
                if self._cb.handle_command_tap_release(tok):
                    return
        if event_matches_any_spec_mouse(self._ptt_specs, button):
            if pressed:
                if self._cb.handle_multi_tap_press(tok):
                    return
                self._cb.add_ptt(tok)
            else:
                if self._cb.handle_multi_tap_release(tok):
                    return
                self._cb.remove_ptt(tok)
            return
        if self._web_specs and event_matches_any_spec_mouse(self._web_specs, button):
            if pressed:
                self._cb.add_web(tok)
            else:
                self._cb.remove_web(tok)
