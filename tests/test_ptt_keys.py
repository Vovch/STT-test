from __future__ import annotations

from pynput import keyboard

from potato_stt.input.ptt_keys import (
    build_chord_spec,
    keyboard_chord_matches_spec,
    normalize_spec,
    spec_label,
)


def test_normalize_chord_orders_modifiers_and_labels_terminal() -> None:
    spec = normalize_spec("chord:shift+ctrl+f9")
    assert spec == "chord:ctrl+shift+vk:120"
    assert spec_label(spec) == "Ctrl+Shift+F9"


def test_modifier_only_chord_matches_exact_modifier_set() -> None:
    spec = build_chord_spec({"shift", "ctrl"})
    assert spec == "chord:ctrl+shift"
    assert keyboard_chord_matches_spec(spec, keyboard.Key.shift_l, {"ctrl", "shift"})
    assert not keyboard_chord_matches_spec(spec, keyboard.Key.shift_l, {"ctrl", "shift", "alt"})


def test_modifier_plus_key_chord_matches_terminal_key() -> None:
    spec = normalize_spec("chord:ctrl+caps_lock")
    assert spec == "chord:ctrl+vk:20"
    assert spec_label(spec) == "Ctrl+Caps Lock"
    assert keyboard_chord_matches_spec(spec, keyboard.KeyCode.from_vk(20), {"ctrl"})
    assert not keyboard_chord_matches_spec(spec, keyboard.KeyCode.from_vk(20), {"ctrl", "shift"})
