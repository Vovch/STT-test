"""Push-to-talk: canonical specs, matching, labels, and settings load/save."""
from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QSettings
from pynput import keyboard, mouse

# Legacy single-key setting (migrated to PTT_KEYS_SETTING)
PTT_KEY_SETTING = "push_to_talk_key"
PTT_KEYS_SETTING = "push_to_talk_keys"
WEB_SEARCH_KEYS_SETTING = "web_search_keys"
COMMAND_TAP_KEYS_SETTING = "command_tap_keys"

PTT_KEY_DEFAULT = "right_ctrl"
DEFAULT_PTT_SPECS: list[str] = [PTT_KEY_DEFAULT]

_PRESET_CHOICES: list[tuple[str, str]] = [
    ("right_ctrl", "Right Ctrl"),
    ("left_ctrl", "Left Ctrl"),
    ("right_alt", "Right Alt"),
    ("left_alt", "Left Alt"),
    ("left_shift", "Left Shift"),
    ("right_shift", "Right Shift"),
    ("space", "Space"),
    ("mouse_x1", "Mouse button 4 (side / back)"),
    ("mouse_x2", "Mouse button 5 (side / forward)"),
    ("mouse_middle", "Middle mouse button"),
]
_PRESET_IDS = frozenset(p[0] for p in _PRESET_CHOICES)
_PRESET_LABELS = dict(_PRESET_CHOICES)
_MODIFIER_ORDER = ("ctrl", "shift", "alt", "win", "fn")
_MODIFIER_LABELS = {
    "ctrl": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "win": "Win",
    "fn": "Fn",
}
_NAMED_KEY_VKS = {
    "caps_lock": 20,
    "capslock": 20,
    "caps": 20,
    **{f"f{i}": 111 + i for i in range(1, 13)},
}
_VK_LABELS = {
    20: "Caps Lock",
    **{111 + i: f"F{i}" for i in range(1, 13)},
}


def ptt_key_choices() -> list[tuple[str, str]]:
    return list(_PRESET_CHOICES)


def normalize_spec(spec: str) -> str:
    """Canonical form: preset id, vk:NNN, mouse:..., or chord:ctrl+shift+vk:N."""
    s = str(spec).strip().lower()
    if not s:
        return PTT_KEY_DEFAULT
    if s.startswith("chord:"):
        return normalize_chord_spec(s)
    if s.startswith("mouse:"):
        tail = s.split(":", 1)[1].lower()
        return f"mouse:{tail}"
    # Legacy mouse_* preset ids
    if s.startswith("mouse_"):
        tail = s.replace("mouse_", "", 1).lower()
        return f"mouse:{tail}"
    if s.startswith("vk:"):
        try:
            n = int(s.split(":", 1)[1].strip(), 0)
            return f"vk:{n}"
        except ValueError:
            return PTT_KEY_DEFAULT
    if s in _NAMED_KEY_VKS:
        return f"vk:{_NAMED_KEY_VKS[s]}"
    if s in _PRESET_IDS:
        return s
    return PTT_KEY_DEFAULT


def is_chord_spec(spec: str) -> bool:
    return str(spec).strip().lower().startswith("chord:")


def normalize_chord_spec(spec: str) -> str:
    raw = str(spec).strip().lower()
    body = raw.split(":", 1)[1] if raw.startswith("chord:") else raw
    parts = [p.strip() for p in body.split("+") if p.strip()]
    mods: set[str] = set()
    terminal: Optional[str] = None
    for part in parts:
        if part in _MODIFIER_ORDER:
            mods.add(part)
            continue
        if terminal is not None:
            return PTT_KEY_DEFAULT
        terminal = normalize_spec(part)
        if terminal == PTT_KEY_DEFAULT and part != PTT_KEY_DEFAULT:
            return PTT_KEY_DEFAULT
    if terminal is None and len(mods) < 2:
        return PTT_KEY_DEFAULT
    ordered = [m for m in _MODIFIER_ORDER if m in mods]
    if terminal is not None:
        ordered.append(terminal)
    return "chord:" + "+".join(ordered)


def build_chord_spec(modifiers: set[str], terminal_spec: Optional[str] = None) -> str:
    """Build a canonical chord spec from normalized modifiers plus an optional terminal key."""
    mods = {m for m in modifiers if m in _MODIFIER_ORDER}
    term = normalize_spec(terminal_spec) if terminal_spec else None
    ordered = [m for m in _MODIFIER_ORDER if m in mods]
    if term is not None:
        ordered.append(term)
    return normalize_chord_spec("chord:" + "+".join(ordered))


def chord_required_modifiers(spec: str) -> set[str]:
    ns = normalize_spec(spec)
    if not ns.startswith("chord:"):
        return set()
    parts = ns.split(":", 1)[1].split("+")
    return {p for p in parts if p in _MODIFIER_ORDER}


def chord_terminal_spec(spec: str) -> Optional[str]:
    ns = normalize_spec(spec)
    if not ns.startswith("chord:"):
        return None
    for part in ns.split(":", 1)[1].split("+"):
        if part not in _MODIFIER_ORDER:
            return part
    return None


def normalize_spec_list(raw: Optional[list]) -> list[str]:
    if not raw:
        return list(DEFAULT_PTT_SPECS)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        n = normalize_spec(item)
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out if out else list(DEFAULT_PTT_SPECS)


def load_ptt_specs(qsettings: QSettings) -> list[str]:
    raw_json = qsettings.value(PTT_KEYS_SETTING, None)
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            data = json.loads(raw_json)
            if isinstance(data, list):
                return normalize_spec_list(data)
        except json.JSONDecodeError:
            pass
    # Migrate legacy single value
    legacy = qsettings.value(PTT_KEY_SETTING, None)
    if isinstance(legacy, str) and legacy.strip():
        return normalize_spec_list([legacy])
    return list(DEFAULT_PTT_SPECS)


def save_ptt_specs(qsettings: QSettings, specs: list[str]) -> None:
    norm = normalize_spec_list(specs)
    qsettings.setValue(PTT_KEYS_SETTING, json.dumps(norm))
    # Clear legacy so new code path is authoritative
    qsettings.remove(PTT_KEY_SETTING)


def normalize_web_search_spec_list(raw: Optional[list]) -> list[str]:
    """Like normalize_spec_list but allows an empty list (no shortcut)."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        n = normalize_spec(item)
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def load_web_search_specs(qsettings: QSettings) -> list[str]:
    raw_json = qsettings.value(WEB_SEARCH_KEYS_SETTING, None)
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            data = json.loads(raw_json)
            if isinstance(data, list):
                return normalize_web_search_spec_list(data)
        except json.JSONDecodeError:
            pass
    return []


def save_web_search_specs(qsettings: QSettings, specs: list[str]) -> None:
    norm = normalize_web_search_spec_list(specs)
    qsettings.setValue(WEB_SEARCH_KEYS_SETTING, json.dumps(norm))


def load_command_tap_specs(qsettings: QSettings) -> list[str]:
    raw_json = qsettings.value(COMMAND_TAP_KEYS_SETTING, None)
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            data = json.loads(raw_json)
            if isinstance(data, list):
                return normalize_web_search_spec_list(data)
        except json.JSONDecodeError:
            pass
    return []


def save_command_tap_specs(qsettings: QSettings, specs: list[str]) -> None:
    norm = normalize_web_search_spec_list(specs)
    qsettings.setValue(COMMAND_TAP_KEYS_SETTING, json.dumps(norm))


def mouse_button_to_spec(btn: mouse.Button) -> Optional[str]:
    if btn == mouse.Button.x1:
        return "mouse:x1"
    if btn == mouse.Button.x2:
        return "mouse:x2"
    if btn == mouse.Button.middle:
        return "mouse:middle"
    if btn == mouse.Button.left:
        return "mouse:left"
    if btn == mouse.Button.right:
        return "mouse:right"
    return None


def mouse_spec_to_button(spec: str) -> Optional[mouse.Button]:
    ns = normalize_spec(spec)
    if not ns.startswith("mouse:"):
        return None
    tail = ns.split(":", 1)[1]
    m = {
        "x1": mouse.Button.x1,
        "x2": mouse.Button.x2,
        "middle": mouse.Button.middle,
        "left": mouse.Button.left,
        "right": mouse.Button.right,
    }
    return m.get(tail)


def keyboard_matches_preset(preset_id: str, key) -> bool:  # type: ignore[no-untyped-def]
    vk = getattr(key, "vk", None)
    if preset_id == "right_ctrl":
        return key == keyboard.Key.ctrl_r or vk == 163
    if preset_id == "left_ctrl":
        return key == keyboard.Key.ctrl_l or vk == 162
    if preset_id == "right_alt":
        return key == keyboard.Key.alt_r or vk == 165
    if preset_id == "left_alt":
        return key == keyboard.Key.alt_l or vk == 164
    if preset_id == "left_shift":
        return key == keyboard.Key.shift_l or vk == 160
    if preset_id == "right_shift":
        return key == keyboard.Key.shift_r or vk == 161
    if preset_id == "space":
        return key == keyboard.Key.space or vk == 32
    return False


def keyboard_matches_spec(spec: str, key) -> bool:  # type: ignore[no-untyped-def]
    ns = normalize_spec(spec)
    if ns.startswith("chord:"):
        return False
    if ns.startswith("mouse:"):
        return False
    if ns.startswith("vk:"):
        try:
            want = int(ns.split(":", 1)[1], 0)
        except ValueError:
            return False
        return getattr(key, "vk", None) == want
    return keyboard_matches_preset(ns, key)


def keyboard_modifier_for_event(key) -> Optional[str]:  # type: ignore[no-untyped-def]
    vk = getattr(key, "vk", None)
    if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r) or vk in (162, 163):
        return "ctrl"
    if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r) or vk in (160, 161):
        return "shift"
    alt_gr = getattr(keyboard.Key, "alt_gr", None)
    if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, alt_gr) or vk in (164, 165):
        return "alt"
    cmd = getattr(keyboard.Key, "cmd", None)
    cmd_l = getattr(keyboard.Key, "cmd_l", None)
    cmd_r = getattr(keyboard.Key, "cmd_r", None)
    if key in (cmd, cmd_l, cmd_r) or vk in (91, 92):
        return "win"
    name = str(getattr(key, "name", "") or "").lower()
    if name == "fn" or vk == 255:
        return "fn"
    return None


def keyboard_chord_matches_spec(
    spec: str,
    key,  # type: ignore[no-untyped-def]
    modifiers_down: set[str],
) -> bool:
    ns = normalize_spec(spec)
    if not ns.startswith("chord:"):
        return False
    required = chord_required_modifiers(ns)
    if set(modifiers_down) != required:
        return False
    terminal = chord_terminal_spec(ns)
    if terminal is None:
        return keyboard_modifier_for_event(key) in required
    return keyboard_matches_spec(terminal, key)


def mouse_matches_spec(spec: str, button: mouse.Button) -> bool:
    return mouse_spec_to_button(spec) == button


def keyboard_token_for_event(key) -> str:  # type: ignore[no-untyped-def]
    vk = getattr(key, "vk", None)
    if vk is not None:
        return f"vk:{int(vk)}"
    return f"key:{repr(key)}"


def mouse_token_for_button(button: mouse.Button) -> str:
    s = mouse_button_to_spec(button)
    return s if s is not None else f"mouse:{repr(button)}"


def spec_label(spec: str) -> str:
    ns = normalize_spec(spec)
    if ns.startswith("chord:"):
        labels: list[str] = []
        terminal = chord_terminal_spec(ns)
        for m in _MODIFIER_ORDER:
            if m in chord_required_modifiers(ns):
                labels.append(_MODIFIER_LABELS[m])
        if terminal is not None:
            labels.append(spec_label(terminal))
        return "+".join(labels)
    if ns.startswith("vk:"):
        try:
            n = int(ns.split(":", 1)[1], 0)
        except ValueError:
            return ns
        if n in _VK_LABELS:
            return _VK_LABELS[n]
        return f"Key (virtual key {n})"
    if ns.startswith("mouse:"):
        tail = ns.split(":", 1)[1]
        pretty = {
            "x1": "Mouse button 4 (back)",
            "x2": "Mouse button 5 (forward)",
            "middle": "Middle mouse",
            "left": "Left mouse",
            "right": "Right mouse",
        }.get(tail, tail)
        return pretty
    return _PRESET_LABELS.get(ns, ns)


def specs_summary_phrase(specs: list[str]) -> str:
    """Short phrase for help/tooltip (e.g. one key vs several)."""
    norm = normalize_spec_list(specs)
    if len(norm) == 1:
        return spec_label(norm[0])
    parts = [spec_label(s) for s in norm[:4]]
    if len(norm) > 4:
        parts.append("…")
    return " or ".join(parts)


def matching_keyboard_specs(
    specs: list[str],
    key,  # type: ignore[no-untyped-def]
    modifiers_down: set[str],
) -> list[str]:
    out: list[str] = []
    for s in specs:
        ns = normalize_spec(s)
        if ns.startswith("chord:"):
            if keyboard_chord_matches_spec(ns, key, modifiers_down):
                out.append(ns)
        elif keyboard_matches_spec(ns, key):
            out.append(ns)
    return out


def event_matches_any_spec_keyboard(
    specs: list[str],
    key,  # type: ignore[no-untyped-def]
    modifiers_down: Optional[set[str]] = None,
) -> bool:
    if modifiers_down is not None:
        return bool(matching_keyboard_specs(specs, key, modifiers_down))
    for s in specs:
        if keyboard_matches_spec(s, key):
            return True
    return False


def event_matches_any_spec_mouse(specs: list[str], button: mouse.Button) -> bool:
    for s in specs:
        if mouse_matches_spec(s, button):
            return True
    return False


def needs_keyboard_listener(specs: list[str]) -> bool:
    for s in specs:
        ns = normalize_spec(s)
        if ns.startswith("chord:") or not ns.startswith("mouse:"):
            return True
    return False


def needs_mouse_listener(specs: list[str]) -> bool:
    for s in specs:
        if normalize_spec(s).startswith("mouse:"):
            return True
    return False


def keyboard_event_to_capture_spec(key) -> Optional[str]:  # type: ignore[no-untyped-def]
    """Prefer a named preset when the key matches; else vk:NN."""
    vk = getattr(key, "vk", None)
    if vk == 27:  # Escape — cancel in capture UI, not stored
        return None
    for preset, _label in _PRESET_CHOICES:
        if keyboard_matches_preset(preset, key):
            return preset
    if vk is not None:
        return f"vk:{int(vk)}"
    try:
        from pynput.keyboard import KeyCode

        if isinstance(key, KeyCode) and key.vk is not None:
            return f"vk:{int(key.vk)}"
    except Exception:
        pass
    return None
