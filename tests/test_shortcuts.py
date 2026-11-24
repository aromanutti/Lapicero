"""Keyboard shortcut bindings: parsing, conflicts and what gets saved."""

import pytest
from PySide6.QtWidgets import QApplication

from lapicero import shortcuts


@pytest.fixture(scope="module", autouse=True)
def qt():
    yield QApplication.instance() or QApplication([])


def test_defaults_are_already_in_saved_form_and_unique():
    assert all(shortcuts.normalize(key) == key for key in shortcuts.DEFAULTS.values())
    assert len(set(shortcuts.DEFAULTS.values())) == len(shortcuts.DEFAULTS)


@pytest.mark.parametrize("value, expected", [
    ("ctrl+s", "Ctrl+S"), ("Shift+Ctrl+P", "Ctrl+Shift+P"), ("Escape", "Esc"),
    ("Ctrl+K, Ctrl+C", "Ctrl+K"), ("", ""), ("  ", ""), ("garbage", None), (5, None), (None, None)])
def test_normalize(value, expected):
    assert shortcuts.normalize(value) == expected


def test_assign_moves_a_key_already_in_use():
    bindings, displaced = shortcuts.assign(shortcuts.DEFAULTS, "eraser", "ctrl+s")
    assert bindings["eraser"] == "Ctrl+S" and bindings["save"] == "" and displaced == ["save"]
    assert shortcuts.DEFAULTS["save"] == "Ctrl+S"  # The defaults are never changed.


def test_assign_removes_with_an_empty_key_and_rejects_bad_input():
    bindings, displaced = shortcuts.assign(shortcuts.DEFAULTS, "undo", "")
    assert bindings["undo"] == "" and displaced == []
    with pytest.raises(ValueError):
        shortcuts.assign(shortcuts.DEFAULTS, "undo", "garbage")
    with pytest.raises(KeyError):
        shortcuts.assign(shortcuts.DEFAULTS, "bogus", "X")


def test_load_keeps_defaults_for_unusable_entries_and_saves_only_changes():
    bindings = shortcuts.load({"eraser": "Ctrl+S", "lasso": "???", "bogus": "X", "undo": 3, "redo": ""})
    assert bindings["eraser"] == "Ctrl+S" and bindings["save"] == ""
    assert bindings["lasso"] == "L" and bindings["undo"] == "Ctrl+Z" and bindings["redo"] == ""
    assert shortcuts.changes(bindings) == {"eraser": "Ctrl+S", "save": "", "redo": ""}
    assert shortcuts.load("nope") == shortcuts.DEFAULTS
    assert shortcuts.changes(shortcuts.DEFAULTS) == {}
