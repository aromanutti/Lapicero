"""Offscreen Qt library window integration tests (no pytest-qt dependency)."""

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from lapicero.app import LapiceroWindow
from lapicero.library import Library
from lapicero.model import Note, Stroke


@pytest.fixture(scope="module")
def qt():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt, tmp_path):
    widget = LapiceroWindow(library_path=tmp_path / "folder" / "library.json", autosave_delay_ms=0)
    widget.show()
    qt.processEvents()
    yield widget
    # Immediate autosave keeps assertions synchronous; debounced saving has its own tests.
    # Tests explicitly resolve dirty work; cleanup must never trigger a modal dialog.
    widget.library._saved = widget.library._data()
    widget.close()


def names(monkeypatch, *values):
    choices = iter(values)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: (next(choices), True))


def populate(window, monkeypatch):
    names(monkeypatch, "Physics", "Vectors", "Page 1")
    window.new_subject()
    window.new_section()
    window.new_page()
    subject = window.library.subjects[0]
    return subject, subject.sections[0], subject.sections[0].pages[0]


def tap(window, x=40, y=50):
    from PySide6.QtCore import QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        point = QPointF(x, y)
        event = QMouseEvent(kind, point, point, point, Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier)
        (window.canvas.mousePressEvent if kind == QEvent.Type.MouseButtonPress else window.canvas.mouseReleaseEvent)(event)


def test_create_rename_select_visible_controls_and_infinite_view(window, monkeypatch):
    assert not window.canvas.isEnabled() and not window.canvas.isVisible()
    assert window.placeholder.isVisible()
    assert window.canvas.minimumSize() != window.canvas.maximumSize()
    assert not window.new_page_button.isEnabled() and not window.import_button.isEnabled()
    assert not window.undo_button.isEnabled()
    subject, section, page = populate(window, monkeypatch)
    assert window.canvas.isEnabled() and window.canvas.isVisible()
    assert window._page_id == page.id
    assert window.library.path.exists()
    assert window.tree.topLevelItem(0).child(0).child(0).text(0) == "Page 1"
    assert all(button.isVisible() for button in (window.new_subject_button, window.new_section_button,
               window.new_page_button, window.rename_button, window.import_button, window.pen_button,
               window.eraser_button, window.undo_button, window.redo_button, window.select_button,
               window.shape_button, window.fullscreen_button, window.paper_combo, window.size_combo,
               *window.pen_buttons))
    for setting in (window.paper_combo, window.size_combo):
        assert window.settings_box.isAncestorOf(setting) and window.sidebar.isAncestorOf(setting)
        assert not window.toolbar.isAncestorOf(setting)
    assert all(not button.icon().isNull() for button in window.pen_buttons)
    assert not window.placeholder.isVisible()
    names(monkeypatch, "Renamed page", "Renamed section", "Renamed subject")
    window.rename_selected()
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0))
    window.rename_selected()
    window.tree.setCurrentItem(window.tree.topLevelItem(0))
    window.rename_selected()
    assert (subject.name, section.name, page.name) == ("Renamed subject", "Renamed section", "Renamed page")
    assert not window.canvas.isEnabled()
    assert not window.new_page_button.isEnabled()
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0).child(0))
    assert window.canvas.note is page.note
    reopened = Library.load(window.library.path)
    assert (reopened.subjects[0].name, reopened.subjects[0].sections[0].pages[0].name) == (subject.name, page.name)


def test_page_isolation_autosave_and_reopen(window, monkeypatch):
    subject, section, first = populate(window, monkeypatch)
    tap(window)
    assert len(first.note.strokes) == 1 and not window.library.dirty
    names(monkeypatch, "Page 2")
    window.new_page()
    second = section.pages[1]
    assert not window.canvas.note.strokes
    tap(window, 80, 90)
    assert len(second.note.strokes) == 1
    assert first.note.strokes != second.note.strokes
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0).child(0))
    assert window.canvas.note is first.note
    window.canvas.set_mode("eraser")
    tap(window)
    assert not first.note.strokes and len(second.note.strokes) == 1
    assert not window.library.dirty
    window.canvas.undo()
    assert first.note.strokes and not window.library.dirty
    reopened = Library.load(window.library.path)
    assert reopened.subjects[0].sections[0].pages[0].note.strokes == first.note.strokes
    assert reopened.subjects[0].sections[0].pages[1].note.strokes == second.note.strokes
    assert window.library.path.parent.is_dir()


def test_page_switch_mid_pen_autosaves_original_page_once(window, monkeypatch):
    from PySide6.QtCore import QPointF

    _, section, first = populate(window, monkeypatch)
    names(monkeypatch, "Page 2")
    window.new_page()
    second = section.pages[1]
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0).child(0))
    writes = []
    original = window.library.save

    def counted():
        writes.append(True)
        original()

    monkeypatch.setattr(window.library, "save", counted)
    window.canvas._press(QPointF(10, 20), "mouse")
    window.canvas._move(QPointF(30, 40), "mouse")
    assert not writes and not first.note.strokes
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0).child(1))
    assert first.note.strokes == [Stroke(((10, 20), (30, 40)))]
    assert window.canvas.note is second.note and not second.note.strokes
    window.canvas._release(QPointF(50, 60), "mouse")
    assert writes == [True] and not window.library.dirty and not second.note.strokes
    stored = Library.load(window.library.path)
    assert stored.subjects[0].sections[0].pages[0].note.strokes == first.note.strokes
    assert not stored.subjects[0].sections[0].pages[1].note.strokes


def test_import_standalone_v1_copies_into_selected_section(window, monkeypatch, tmp_path):
    _, section, _ = populate(window, monkeypatch)
    source = tmp_path / "old.json"
    original = Note()
    original.add_stroke(Stroke(((20.5, 40.25),), "#205bb5", 4))
    original.save(source)
    before = source.read_bytes()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    window.import_note()
    assert len(section.pages) == 2
    assert section.pages[1].note.strokes == original.strokes
    assert window.canvas.note is section.pages[1].note
    assert source.read_bytes() == before
    assert Library.load(window.library.path).subjects[0].sections[0].pages[1].note.strokes == original.strokes
    bad = tmp_path / "bad.json"
    bad.write_text("not JSON", encoding="utf-8")
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: errors.append(a))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(bad), ""))
    window.import_note()
    assert len(section.pages) == 2 and errors and bad.read_text(encoding="utf-8") == "not JSON"


def test_shortcuts_focus_and_controls(window, monkeypatch, qt, tmp_path):
    _, section, page = populate(window, monkeypatch)
    window.canvas.setFocus()
    qt.processEvents()
    assert window.canvas.hasFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_E)
    assert window.canvas.mode == "eraser"
    QTest.keyClick(window.canvas, Qt.Key.Key_P)
    assert window.canvas.mode == "pen"
    QTest.keyClick(window.canvas, Qt.Key.Key_L)
    assert window.canvas.mode == "select" and window.select_button.isChecked()
    QTest.keyClick(window.canvas, Qt.Key.Key_S)
    assert window.canvas.mode == "shape" and window.shape_button.isChecked()
    QTest.keyClick(window.canvas, Qt.Key.Key_P)
    assert window.canvas.mode == "pen" and window.pen_button.isChecked()
    window.width_slider.setValue(40)
    QTest.keyClick(window.canvas, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert window.canvas.pen_width == 40
    window.width_slider.setValue(20)
    QTest.keyClick(window.canvas, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert window.canvas.pen_width == 19
    window.color_buttons["#b73535"].click()
    tap(window)
    assert page.note.strokes[0].color == "#b73535" and page.note.strokes[0].width == 19
    QTest.keyClick(window.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not page.note.strokes
    QTest.keyClick(window.canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert len(page.note.strokes) == 1
    window.tree.setFocus()
    qt.processEvents()
    QTest.keyClick(window.tree, Qt.Key.Key_E)
    QTest.keyClick(window.tree, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    assert window.canvas.mode == "pen" and window.canvas.pen_width == 19
    names(monkeypatch, "Shortcut page")
    QTest.keyClick(window.tree, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert len(section.pages) == 2
    source = tmp_path / "source.json"
    Note(strokes=[Stroke(((4, 5),))]).save(source)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    QTest.keyClick(window.tree, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    assert len(section.pages) == 3
    QTest.keyClick(window.tree, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert not window.library.dirty


def test_autosave_failure_is_bounded_and_close_requires_choice(window, monkeypatch):
    _, _, page = populate(window, monkeypatch)
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: errors.append(a))
    original_save = window.library.save
    monkeypatch.setattr(window.library, "save", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    tap(window)
    tap(window, 70, 80)
    assert len(errors) == 1 and window.library.dirty and len(page.note.strokes) == 2
    assert "disk full" in window.status.toolTip() and window.status.text() == "Not saved"
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    assert not window.close() and window.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Save)
    assert not window.close() and window.isVisible()
    monkeypatch.setattr(window.library, "save", original_save)
    assert window.save() and not window.library.dirty
    assert Library.load(window.library.path).subjects[0].sections[0].pages[0].note.strokes == page.note.strokes


def test_close_mid_pen_commits_and_autosaves_before_dirty_check(window, monkeypatch):
    from PySide6.QtCore import QPointF

    _, _, page = populate(window, monkeypatch)
    questions = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: questions.append(args))
    window.canvas._press(QPointF(15, 25), "mouse")
    window.canvas._move(QPointF(35, 45), "mouse")
    assert not page.note.strokes and not window.library.dirty
    assert window.close() and not questions
    assert page.note.strokes == [Stroke(((15, 25), (35, 45)))]
    assert not window.library.dirty
    assert Library.load(window.library.path).subjects[0].sections[0].pages[0].note.strokes == page.note.strokes
    window.canvas._release(QPointF(55, 65), "mouse")
    assert len(page.note.strokes) == 1


def test_close_mid_eraser_flushes_one_autosave(window, monkeypatch):
    from PySide6.QtCore import QPointF

    _, _, page = populate(window, monkeypatch)
    tap(window, 40, 50)
    tap(window, 80, 90)
    writes = []
    original_save = window.library.save

    def counted():
        writes.append(True)
        original_save()

    monkeypatch.setattr(window.library, "save", counted)
    window.canvas.set_mode("eraser")
    window.canvas._press(QPointF(40, 50), "mouse")
    window.canvas._move(QPointF(80, 90), "mouse")
    assert not page.note.strokes and not writes
    assert window.close() and writes == [True]
    window.canvas._release(QPointF(80, 90), "mouse")
    window.canvas.finalize_current_gesture()
    assert writes == [True]
    assert not Library.load(window.library.path).subjects[0].sections[0].pages[0].note.strokes
    assert page.note.undo() and len(page.note.strokes) == 2


def test_close_mid_pen_save_failure_keeps_window_and_ink(window, monkeypatch):
    from PySide6.QtCore import QPointF

    _, _, page = populate(window, monkeypatch)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    original_save = window.library.save
    monkeypatch.setattr(window.library, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Save)
    window.canvas._press(QPointF(15, 25), "mouse")
    assert not window.close() and window.isVisible()
    assert page.note.strokes == [Stroke(((15, 25),))]
    assert window.library.dirty and len(warnings) == 1
    window.canvas._release(QPointF(35, 45), "mouse")
    assert len(page.note.strokes) == 1
    monkeypatch.setattr(window.library, "save", original_save)
    assert window.save() and not window.library.dirty
    assert Library.load(window.library.path).subjects[0].sections[0].pages[0].note.strokes == page.note.strokes


def test_corrupt_or_unowned_file_never_replaced(qt, tmp_path, monkeypatch):
    path = tmp_path / "library.json"
    path.write_text("corrupt", encoding="utf-8")
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: errors.append(a))
    window = LapiceroWindow(library_path=path, autosave_delay_ms=0)
    names(monkeypatch, "Keep in memory")
    window.new_subject()
    assert path.read_text(encoding="utf-8") == "corrupt"
    assert window.library.dirty and errors
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    assert not window.close()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Discard)
    assert window.close()
    assert path.read_text(encoding="utf-8") == "corrupt"


def test_autosave_waits_for_completed_gesture(window, monkeypatch):
    from PySide6.QtCore import QPointF

    _, _, page = populate(window, monkeypatch)
    writes = []
    original = window.library.save

    def counted():
        writes.append(True)
        original()

    monkeypatch.setattr(window.library, "save", counted)
    window.canvas._press(QPointF(10, 10), "mouse")
    window.canvas._move(QPointF(30, 30), "mouse")
    window.canvas._move(QPointF(50, 50), "mouse")
    assert not writes and not page.note.strokes
    window.canvas._release(QPointF(70, 70), "mouse")
    assert len(writes) == 1 and len(page.note.strokes) == 1
    window.canvas.set_mode("eraser")
    window.canvas._press(QPointF(10, 10), "mouse")
    window.canvas._move(QPointF(40, 40), "mouse")
    assert len(writes) == 1
    window.canvas._release(QPointF(70, 70), "mouse")
    assert len(writes) == 2 and not page.note.strokes


def test_existing_standalone_note_not_overwritten(qt, tmp_path, monkeypatch):
    path = tmp_path / "note.json"
    path.write_text(json.dumps({"version": 1, "strokes": []}), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    window = LapiceroWindow(library_path=path, autosave_delay_ms=0)
    names(monkeypatch, "A subject")
    window.new_subject()
    assert window.library.dirty and path.read_bytes() == before
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Discard)
    window.close()


def test_pen_presets_keep_their_own_color_width_and_highlighter_alpha(window, monkeypatch):
    _, _, page = populate(window, monkeypatch)
    blue, highlighter = window.pen_buttons[1], window.pen_buttons[4]
    blue.click()
    assert window.canvas.pen_color == "#205bb5" and window.canvas.pen_width == 3
    highlighter.click()
    assert window.canvas.pen_color == "#ffe60080" and window.canvas.pen_width == 16
    window.color_buttons["#1aa3c9"].click()
    window.width_slider.setValue(24)
    tap(window)
    assert page.note.strokes[-1].color == "#1aa3c980" and page.note.strokes[-1].width == 24
    blue.click()
    assert window.canvas.pen_color == "#205bb5" and window.canvas.pen_width == 3
    highlighter.click()
    assert window.canvas.pen_color == "#1aa3c980" and window.canvas.pen_width == 24


def test_shape_menu_selects_kind_and_mode(window, monkeypatch):
    populate(window, monkeypatch)
    window.shape_actions["ellipse"].trigger()
    assert window.canvas.mode == "shape" and window.canvas.shape == "ellipse"
    assert window.shape_button.isChecked()


def test_paper_choice_is_per_page_and_persisted(window, monkeypatch):
    _, section, first = populate(window, monkeypatch)
    assert first.paper == "grid" and window.paper_combo.currentData() == "grid" and window.canvas.paper == "grid"
    window.paper_combo.setCurrentIndex(window.paper_combo.findData("plain"))
    assert first.paper == "plain" and window.canvas.paper == "plain"
    assert not window.library.dirty
    names(monkeypatch, "Page 2")
    window.new_page()
    assert section.pages[1].paper == "grid" and window.canvas.paper == "grid"
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0).child(0))
    assert window.canvas.paper == "plain" and window.paper_combo.currentData() == "plain"
    assert Library.load(window.library.path).page(first.id).paper == "plain"


def test_fullscreen_toggle_hides_sidebar_and_escape_leaves(window, monkeypatch, qt):
    populate(window, monkeypatch)
    window.fullscreen_button.click()
    qt.processEvents()
    assert window.isFullScreen() and not window.sidebar.isVisible()
    window._escape()
    qt.processEvents()
    assert not window.isFullScreen() and window.sidebar.isVisible()
    window.sidebar_button.click()
    assert not window.sidebar.isVisible()


def test_ctrl_c_ctrl_v_copy_and_paste_lasso_selection(window, monkeypatch, qt):
    _, _, page = populate(window, monkeypatch)
    tap(window, 60, 70)
    window.canvas.set_mode("select")
    window.canvas.selection = list(page.note.strokes)
    window.canvas.setFocus()
    qt.processEvents()
    QTest.keyClick(window.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(window.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert len(page.note.strokes) == 2 and page.note.strokes[1].points == ((80, 90),)
    assert window.select_button.isChecked()
    assert not window.library.dirty


def test_ctrl_v_pastes_screenshot_saved_with_library_and_reopened(window, monkeypatch, qt):
    from PySide6.QtGui import QColor, QImage
    _, _, page = populate(window, monkeypatch)
    image = QImage(64, 48, QImage.Format.Format_ARGB32)
    image.fill(QColor("#00aa00"))
    QApplication.clipboard().setImage(image)
    window.canvas.setFocus()
    qt.processEvents()
    QTest.keyClick(window.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    (placed,) = page.note.images
    assert window.select_button.isChecked() and not window.library.dirty
    assert window.library.image_path(placed.key).exists()
    assert Library.load(window.library.path).page(page.id).note.images == [placed]


def test_floating_compact_toolbar_and_no_status_bar(window, monkeypatch, qt):
    from PySide6.QtWidgets import QStatusBar, QToolBar
    populate(window, monkeypatch)
    window.resize(1400, 900)
    qt.processEvents()
    assert window.findChild(QStatusBar) is None and window.findChild(QToolBar) is None
    bar, view = window.toolbar, window.view.geometry()
    assert bar.isVisible() and bar.width() < view.width() * 0.75
    assert abs(bar.geometry().center().x() - view.center().x()) <= 1
    assert view.top() <= bar.y() <= view.top() + 12
    assert window.status.text() == "Saved" and window.status.parent() is bar
    window.sidebar_button.click()
    qt.processEvents()
    assert abs(window.toolbar.geometry().center().x() - window.view.geometry().center().x()) <= 1


def test_toolbar_size_cycles_stays_centered_and_is_remembered(window, monkeypatch, qt, tmp_path):
    populate(window, monkeypatch)
    window.resize(1400, 900)
    qt.processEvents()
    assert window.toolbar_size == "medium" and window.pen_button.iconSize().width() == 34
    widths = {}
    for expected in ("large", "small", "medium", "large"):
        window.size_combo.setCurrentIndex(window.size_combo.findData(expected))
        qt.processEvents()
        assert window.toolbar_size == expected
        widths[expected] = window.toolbar.width()
        assert abs(window.toolbar.geometry().center().x() - window.view.geometry().center().x()) <= 1
    assert widths["small"] < widths["medium"] < widths["large"]
    assert window.pen_button.iconSize().width() == 44
    again = LapiceroWindow(library_path=window.library.path)
    assert again.toolbar_size == "large" and again.pen_button.iconSize().width() == 44
    again.close()


def test_toolbar_fades_while_drawing(window, monkeypatch):
    from PySide6.QtCore import QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    populate(window, monkeypatch)
    assert window.toolbar_opacity() == 1
    point = QPointF(60, 300)
    window.canvas.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, point, point, point,
                                              Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                              Qt.KeyboardModifier.NoModifier))
    assert window.toolbar_opacity() < .5
    window.canvas.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, point, point, point,
                                                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                                Qt.KeyboardModifier.NoModifier))
    assert window.toolbar_opacity() == 1


def test_paper_setting_disabled_without_page(window):
    assert not window.paper_combo.isEnabled() and window.size_combo.isEnabled()


def test_pressure_only_for_pens_not_highlighters(window, monkeypatch):
    populate(window, monkeypatch)
    assert window.canvas.pressure_enabled
    window.pen_buttons[4].click()
    assert not window.canvas.pressure_enabled
    window.pen_buttons[1].click()
    assert window.canvas.pressure_enabled


@pytest.fixture
def debounced(qt, tmp_path):
    widget = LapiceroWindow(library_path=tmp_path / "library.json", autosave_delay_ms=150)
    widget.show()
    qt.processEvents()
    yield widget
    widget.library._saved = widget.library._data()
    widget._autosave.stop()
    widget.close()


def press(window, kind, x, y):
    from PySide6.QtCore import QPointF, QEvent
    from PySide6.QtGui import QMouseEvent
    event_type = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                  "release": QEvent.Type.MouseButtonRelease}[kind]
    point = QPointF(x, y)
    event = QMouseEvent(event_type, point, point, point,
                        Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton,
                        Qt.MouseButton.NoButton if kind == "release" else Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    getattr(window.canvas, "mouse" + kind.title() + "Event")(event)


def saved_strokes(window, page):
    return len(Library.load(window.library.path).page(page.id).note.strokes)


def test_ink_autosaves_after_a_pause_not_on_every_stroke(debounced, monkeypatch):
    _, _, page = populate(debounced, monkeypatch)
    tap(debounced, 40, 300)
    tap(debounced, 60, 300)
    assert len(page.note.strokes) == 2 and saved_strokes(debounced, page) == 0
    assert debounced.status.text() == "Saving…" and debounced.windowTitle().startswith("*")
    QTest.qWait(400)
    assert saved_strokes(debounced, page) == 2 and not debounced.library.dirty
    assert debounced.status.text() == "Saved" and not debounced.windowTitle().startswith("*")


def test_autosave_waits_while_pen_is_down(debounced, monkeypatch):
    _, _, page = populate(debounced, monkeypatch)
    tap(debounced, 40, 300)
    press(debounced, "press", 80, 300)
    QTest.qWait(400)
    assert saved_strokes(debounced, page) == 0
    press(debounced, "move", 120, 320)
    press(debounced, "release", 120, 320)
    QTest.qWait(400)
    assert saved_strokes(debounced, page) == 2


def test_close_and_ctrl_s_flush_pending_autosave_without_prompt(debounced, monkeypatch, qt):
    _, _, page = populate(debounced, monkeypatch)
    tap(debounced, 40, 300)
    debounced.canvas.setFocus()
    QTest.keyClick(debounced.canvas, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert saved_strokes(debounced, page) == 1 and not debounced._autosave.isActive()
    tap(debounced, 60, 300)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("close must not prompt"))
    assert debounced.close()
    assert saved_strokes(debounced, page) == 2


def test_save_rejects_invalid_direct_mutations_without_writing(window, monkeypatch):
    _, _, page = populate(window, monkeypatch)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    before = window.library.path.read_bytes()
    page.paper = "dots"
    assert not window.save() and window.library.path.read_bytes() == before
    page.paper = "grid"
    page.note.strokes.append("not a stroke")
    assert not window.save() and window.library.path.read_bytes() == before
    page.note.strokes.pop()
    page.name = "  padded  "
    assert not window.save() and window.library.path.read_bytes() == before
