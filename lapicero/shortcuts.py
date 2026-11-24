"""Keyboard shortcuts: the actions that have one, their defaults and the user's changes.

A binding is one key combination in Qt's portable text ("Ctrl+S", "E", "F11"), or ""
when the user removed it. Only changes from the defaults are saved, so a later default
reaches everyone who never touched that shortcut.
"""

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence

CANVAS = "canvas"  # Only while the page has keyboard focus: plain letters stay free elsewhere.
WINDOW = "window"  # Anywhere in the main window.

# (id, label, default, scope), in the order Settings lists them.
ACTIONS = (
    ("pen", "Last pen", "P", CANVAS),
    ("eraser", "Eraser", "E", CANVAS),
    ("lasso", "Lasso select", "L", CANVAS),
    ("hand", "Hand select", "H", CANVAS),
    ("shapes", "Shapes", "S", CANVAS),
    ("ask", "Ask Claude", "A", CANVAS),
    ("width_up", "Thicker pen", "Ctrl+Up", CANVAS),
    ("width_down", "Thinner pen", "Ctrl+Down", CANVAS),
    ("undo", "Undo", "Ctrl+Z", WINDOW),
    ("redo", "Redo", "Ctrl+Y", WINDOW),
    ("copy", "Copy", "Ctrl+C", WINDOW),
    ("paste", "Paste", "Ctrl+V", WINDOW),
    ("new_page", "New page", "Ctrl+N", WINDOW),
    ("import_note", "Import note", "Ctrl+O", WINDOW),
    ("save", "Save", "Ctrl+S", WINDOW),
    ("reset_zoom", "Reset zoom", "Ctrl+0", WINDOW),
    ("fullscreen", "Fullscreen", "F11", WINDOW),
    ("escape", "Cancel / leave fullscreen", "Esc", WINDOW),
)
DEFAULTS = {action: default for action, _, default, _ in ACTIONS}
LABELS = {action: label for action, label, _, _ in ACTIONS}
SCOPES = {action: scope for action, _, _, scope in ACTIONS}

_PORTABLE = QKeySequence.SequenceFormat.PortableText


def _text(combination):
    """Portable text of one key combination, ignoring the keypad flag (arrows carry it on macOS)."""
    modifiers = combination.keyboardModifiers() & ~Qt.KeyboardModifier.KeypadModifier
    return QKeySequence(QKeyCombination(modifiers, combination.key())).toString(_PORTABLE)


def normalize(value):
    """One key combination as portable text, "" for none, or None when it is not a shortcut."""
    if not isinstance(value, str):
        return None
    if not value.strip():
        return ""
    sequence = QKeySequence(value, _PORTABLE)
    if sequence.isEmpty() or sequence[0].key() == Qt.Key.Key_unknown:
        return None
    return _text(sequence[0]) or None


def event_text(event):
    """The portable text a key press would have as a shortcut."""
    return _text(event.keyCombination())


def assign(bindings, action, key):
    """Give action this key (or none with ""); any other action holding it loses it.

    Returns the new bindings and the ids of the actions that lost the key.
    """
    if action not in DEFAULTS:
        raise KeyError(action)
    key = normalize(key)
    if key is None:
        raise ValueError("Not a keyboard shortcut")
    result = dict(bindings)
    displaced = [other for other, held in result.items() if key and other != action and held == key]
    for other in displaced:
        result[other] = ""
    result[action] = key
    return result, displaced


def load(saved):
    """Bindings from saved changes; unknown actions and unusable keys keep their defaults."""
    bindings = dict(DEFAULTS)
    if isinstance(saved, dict):
        for action, value in saved.items():
            if action in DEFAULTS and normalize(value) is not None:
                bindings, _ = assign(bindings, action, value)
    return bindings


def changes(bindings):
    """What differs from the defaults: the part worth saving."""
    return {action: key for action, key in bindings.items() if DEFAULTS.get(action) != key}


def bound(bindings, scope):
    """key -> action for the bound actions of one scope."""
    return {key: action for action, key in bindings.items() if key and SCOPES[action] == scope}
