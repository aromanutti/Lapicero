"""Offscreen Qt pointer and vector rendering contracts (no pytest-qt)."""

import pytest
from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent, QPainter, QPainterPath
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from lapicero.library import PAGE_WIDTH, PAGE_HEIGHT
from lapicero.model import Note, Stroke
from lapicero.qt_canvas import InkCanvas
from lapicero.shapes import normalize_shape


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def canvas(app):
    widget = InkCanvas()
    widget.resize(800, 600)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def mouse(canvas, kind, x, y, source=Qt.MouseEventSource.MouseEventNotSynthesized):
    event_type = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                  "release": QEvent.Type.MouseButtonRelease}[kind]
    button = Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == "release" else Qt.MouseButton.LeftButton
    point = QPointF(x, y)
    event = QMouseEvent(event_type, point, point, point, button, buttons,
                        Qt.KeyboardModifier.NoModifier, source)
    getattr(canvas, "mouse" + kind.title() + "Event")(event)


class TabletSample:
    """Minimal QTabletEvent interface with true floating-point local positions."""

    def __init__(self, kind, x, y):
        self.kind = kind
        self.point = QPointF(x, y)
        self.accepted = False

    def type(self):
        return {"press": QEvent.Type.TabletPress, "move": QEvent.Type.TabletMove,
                "release": QEvent.Type.TabletRelease}[self.kind]

    def position(self):
        return self.point

    def accept(self):
        self.accepted = True


def tablet(canvas, kind, x, y):
    event = TabletSample(kind, x, y)
    canvas.tabletEvent(event)
    assert event.accepted


def test_page_and_antialias_and_vector_render(app):
    class InspectCanvas(InkCanvas):
        hints = []

        def _paint_stroke(self, painter, stroke, path=None):
            self.hints.append(bool(painter.renderHints() & QPainter.RenderHint.Antialiasing))
            super()._paint_stroke(painter, stroke, path)

    note = Note(strokes=[Stroke(((20.25, 20.75), (110.5, 90.25), (175.125, 22.5)),
                                "#205bb5", 3)])
    canvas = InspectCanvas(note)
    canvas.set_paper("plain")
    canvas.resize(500, 450)
    canvas.show()
    app.processEvents()
    image = canvas.grab().toImage()
    assert canvas.hints and all(canvas.hints)
    path = canvas._path(note.strokes[0])
    assert any(path.elementAt(i).type == QPainterPath.ElementType.CurveToElement
               for i in range(path.elementCount()))
    assert image.pixelColor(20, 21) != image.pixelColor(400, 400)
    assert note.strokes[0].points[0] == (20.25, 20.75)
    canvas.set_note(Note(strokes=list(note.strokes)))
    app.processEvents()
    assert canvas.grab().toImage() == image
    canvas.close()


def test_live_preview_tap_dot_settings_and_page_switch(canvas, app):
    changes = []
    canvas.changed.connect(lambda: changes.append(True))
    canvas.set_pen_color("#b73535")
    canvas.set_pen_width(7)
    mouse(canvas, "press", 42.25, 48.75)
    assert canvas.note.strokes == []
    app.processEvents()
    assert canvas.grab().toImage().pixelColor(42, 49).red() < 255
    mouse(canvas, "release", 42.25, 48.75)
    first = canvas.note
    assert first.strokes == [Stroke(((42.25, 48.75),), "#b73535", 7)]
    assert changes == [True]
    second = Note()
    canvas.set_note(second)
    assert not second.strokes and len(first.strokes) == 1
    mouse(canvas, "press", 32, 30)
    canvas.set_pen_color("#205bb5")
    canvas.set_pen_width(2)
    mouse(canvas, "move", 70, 65)
    mouse(canvas, "release", 90, 70)
    assert len(second.strokes) == 1 and first.strokes[0].points == ((42.25, 48.75),)
    assert (second.strokes[0].color, second.strokes[0].width) == ("#b73535", 7)
    assert canvas.undo() and second.strokes == []
    assert canvas.redo() and len(second.strokes) == 1
    assert len(changes) == 4


def test_finalize_pen_before_note_and_tool_switch_commits_once(canvas):
    first = canvas.note
    changes = []
    canvas.changed.connect(lambda: changes.append(True))
    mouse(canvas, "press", 20, 30)
    mouse(canvas, "move", 50, 60)
    second = Note()
    canvas.set_note(second)
    assert first.strokes == [Stroke(((20, 30), (50, 60)))]
    assert not second.strokes and changes == [True]
    mouse(canvas, "release", 80, 90)  # A late release must not ink the new page.
    canvas.finalize_current_gesture()
    assert first.strokes == [Stroke(((20, 30), (50, 60)))]
    assert not second.strokes and changes == [True]
    mouse(canvas, "press", 10, 15)
    canvas.set_mode("eraser")
    assert second.strokes == [Stroke(((10, 15),))]
    assert changes == [True, True]
    mouse(canvas, "release", 90, 95)
    canvas.finalize_current_gesture()
    assert second.strokes == [Stroke(((10, 15),))] and changes == [True, True]
    assert second.undo() and not second.strokes and not second.undo()


def test_press_outside_view_ignored_and_ink_beyond_view_kept(canvas):
    mouse(canvas, "press", -10, 10)
    mouse(canvas, "release", 10, 10)
    assert not canvas.note.strokes
    mouse(canvas, "press", 100, 100)
    mouse(canvas, "move", PAGE_WIDTH + 30, PAGE_HEIGHT + 30)
    mouse(canvas, "release", PAGE_WIDTH + 30, PAGE_HEIGHT + 30)
    assert canvas.note.strokes[0].points[-1] == (PAGE_WIDTH + 30, PAGE_HEIGHT + 30)
    canvas.set_note(Note(strokes=[Stroke(((100, 200),), width=4),
                                  Stroke(((200, 200),), width=4)]))
    canvas.set_mode("eraser")
    mouse(canvas, "press", 80, 200)
    mouse(canvas, "move", 220, 200)
    mouse(canvas, "release", 220, 200)
    assert canvas.note.strokes == []
    assert canvas.undo() and len(canvas.note.strokes) == 2
    assert not canvas.undo()


def test_eraser_hits_visible_curve_not_raw_chords(canvas, app):
    stroke = Stroke(((20, 20), (100, 140), (180, 20)), width=2)
    canvas.set_note(Note(strokes=[stroke]))
    # First quadratic passes through (90, 95); both raw chords miss by > 10 px.
    assert canvas.grab().toImage().pixelColor(90, 95).red() < 255
    canvas.set_mode("eraser")
    mouse(canvas, "press", 100, 140)  # Raw vertex lies far off the painted curve.
    mouse(canvas, "release", 100, 140)
    assert canvas.note.strokes == [stroke]
    mouse(canvas, "press", 90, 95)
    assert canvas.note.strokes == []
    mouse(canvas, "release", 90, 95)
    assert canvas.undo() and canvas.note.strokes == [stroke]


def test_eraser_drag_redraws_live_but_emits_once_on_release(canvas, app):
    strokes = [Stroke(((40, 70),)), Stroke(((100, 70),))]
    canvas.set_note(Note(strokes=list(strokes)))
    canvas.set_mode("eraser")
    changes = []
    canvas.changed.connect(lambda: changes.append(True))
    mouse(canvas, "press", 40, 70)
    assert canvas.note.strokes == [strokes[1]] and not changes
    app.processEvents()
    assert canvas.grab().toImage().pixelColor(40, 70).red() == 255
    mouse(canvas, "move", 100, 70)
    assert canvas.note.strokes == [] and not changes
    mouse(canvas, "release", 100, 70)
    assert changes == [True]
    assert canvas.undo() and canvas.note.strokes == strokes
    assert not canvas.undo()


def test_eraser_context_switch_flushes_only_changed_gestures(canvas):
    stroke = Stroke(((30, 30),))
    old_note = Note(strokes=[stroke])
    canvas.set_note(old_note)
    canvas.set_mode("eraser")
    changes = []
    canvas.changed.connect(lambda: changes.append(True))
    mouse(canvas, "press", 300, 300)
    canvas.set_mode("pen")
    assert not changes and not old_note.undo()
    canvas.set_mode("eraser")
    mouse(canvas, "press", 30, 30)
    assert old_note.strokes == [] and not changes
    canvas.set_note(Note())
    assert changes == [True] and old_note.undo() and old_note.strokes == [stroke]
    mouse(canvas, "release", 30, 30)
    canvas.finalize_current_gesture()
    canvas.set_mode("pen")
    assert changes == [True]


def test_eraser_uses_dot_width_and_no_op_release_preserves_redo(canvas):
    stroke = Stroke(((50, 50),), width=20)
    canvas.set_note(Note(strokes=[stroke]))
    canvas.set_mode("eraser")
    changes = []
    canvas.changed.connect(lambda: changes.append(True))
    mouse(canvas, "press", 70, 50)  # 10 px eraser + 10 px dot radius.
    mouse(canvas, "release", 70, 50)
    assert not canvas.note.strokes and changes == [True]
    assert canvas.undo() and canvas.note.strokes == [stroke]
    mouse(canvas, "press", 300, 300)
    mouse(canvas, "release", 300, 300)
    assert changes == [True, True]
    assert canvas.redo() and canvas.note.strokes == []


def test_hold_preview_quick_release_move_cancellation_and_exact_paths(canvas):
    rectangle = [(20, 20), (170, 20), (170, 100), (20, 100), (20, 20)]
    points = []
    for a, b in zip(rectangle, rectangle[1:]):
        points += [(a[0] + (b[0] - a[0]) * i / 8,
                    a[1] + (b[1] - a[1]) * i / 8) for i in range(8)]
    points.append(rectangle[-1])
    assert normalize_shape(points)[0] == "rectangle"

    def trace():
        mouse(canvas, "press", *points[0])
        for point in points[1:]:
            mouse(canvas, "move", *point)

    trace()
    assert canvas._snapped is None
    mouse(canvas, "release", *points[-1])
    assert canvas.note.strokes[-1].points == tuple(points)
    trace()
    QTest.qWait(650)  # Leave slack for the Windows/Qt coarse timer.
    assert canvas._snapped is not None and canvas.note.strokes[-1].points == tuple(points)
    clean = canvas._snapped
    path = canvas._path(Stroke(clean))
    assert all(path.elementAt(i).type != QPainterPath.ElementType.CurveToElement
               for i in range(path.elementCount()))
    mouse(canvas, "move", 21, 21)
    assert canvas._snapped is None and canvas._points == points + [(21, 21)]
    mouse(canvas, "release", 21, 21)
    assert canvas.note.strokes[-1].points == tuple(points + [(21, 21)])
    trace()
    QTest.qWait(650)
    mouse(canvas, "release", *points[-1])
    assert canvas.note.strokes[-1].points == clean
    assert canvas.undo() and canvas.note.strokes[-1].points[-1] == (21, 21)


def test_arrow_geometry_remains_straight(canvas):
    arrow = [(12, 83), (174, 79), (139, 51), (173, 80), (138, 111)]
    points = []
    for a, b in zip(arrow, arrow[1:]):
        points.extend((a[0] + (b[0] - a[0]) * i / 7,
                       a[1] + (b[1] - a[1]) * i / 7) for i in range(7))
    points.append(arrow[-1])
    clean = normalize_shape(points)[1]
    assert clean[1] == clean[3]
    canvas.set_note(Note(strokes=[Stroke(clean, "#202020", 5)]))
    path = canvas._path(canvas.note.strokes[0])
    image = canvas.grab().toImage()
    assert image.pixelColor(174, 79) != image.pixelColor(400, 400)
    assert path.elementCount() == 5
    assert all(path.elementAt(i).type != QPainterPath.ElementType.CurveToElement
               for i in range(path.elementCount()))


def test_tablet_precision_and_mouse_duplicate_suppression(canvas):
    changes = []
    canvas.changed.connect(lambda: changes.append(True))
    synthesized = Qt.MouseEventSource.MouseEventSynthesizedByQt
    mouse(canvas, "press", 20, 20, synthesized)
    mouse(canvas, "release", 20, 20, synthesized)
    assert not canvas.note.strokes
    mouse(canvas, "press", 30, 30)
    tablet(canvas, "press", 40.125, 41.375)
    mouse(canvas, "move", 200, 200)
    tablet(canvas, "move", 50.5, 54.25)
    mouse(canvas, "release", 200, 200)
    tablet(canvas, "release", 60.75, 65.5)
    mouse(canvas, "press", 70, 70)
    mouse(canvas, "release", 70, 70)
    assert len(canvas.note.strokes) == 1 and changes == [True]
    assert canvas.note.strokes[0].points == ((40.125, 41.375), (50.5, 54.25), (60.75, 65.5))
    canvas._tablet_time = float("-inf")
    mouse(canvas, "press", 70, 70)
    mouse(canvas, "release", 70, 70)
    assert len(canvas.note.strokes) == 2 and changes == [True, True]


def test_pen_cursor_is_a_translucent_dot_in_the_ink_color(canvas):
    canvas.set_mode("pen")
    canvas.set_pen_color("#b73535")
    canvas.set_pen_width(10)
    cursor = canvas.cursor()
    assert cursor.shape() == Qt.CursorShape.BitmapCursor
    image = cursor.pixmap().toImage()
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    assert (center.red(), center.green(), center.blue()) == (0xb7, 0x35, 0x35)
    assert 60 < center.alpha() < 200  # See-through, not solid.
    assert image.width() >= 10
    canvas.set_pen_color("#205bb5")
    image = canvas.cursor().pixmap().toImage()
    assert image.pixelColor(image.width() // 2, image.height() // 2).blue() == 0xb5


def test_no_tool_uses_the_crosshair(canvas):
    for mode in InkCanvas.MODES:
        canvas.set_mode(mode)
        assert canvas.cursor().shape() != Qt.CursorShape.CrossCursor
    canvas.set_mode("pen")
    small = canvas.cursor().pixmap().width()
    canvas.set_zoom(3.0)
    assert canvas.cursor().pixmap().width() > small  # The tip follows zoom.
