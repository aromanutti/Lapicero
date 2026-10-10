"""Infinite viewport, paper, lasso selection and shape tool contracts."""

import pytest
from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from lapicero.library import PAGE_WIDTH, PAGE_HEIGHT
from lapicero.model import Note, PlacedImage, Stroke
from lapicero.qt_canvas import CanvasView, InkCanvas
from lapicero.shapes import shape_points


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def canvas(app):
    widget = InkCanvas()
    widget.resize(600, 400)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def mouse(canvas, kind, x, y, button=Qt.MouseButton.LeftButton):
    event_type = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                  "release": QEvent.Type.MouseButtonRelease}[kind]
    point = QPointF(x, y)
    event = QMouseEvent(event_type, point, point, point,
                        Qt.MouseButton.NoButton if kind == "move" else button,
                        Qt.MouseButton.NoButton if kind == "release" else button,
                        Qt.KeyboardModifier.NoModifier)
    getattr(canvas, "mouse" + kind.title() + "Event")(event)


def drag(canvas, *points):
    mouse(canvas, "press", *points[0])
    for point in points[1:]:
        mouse(canvas, "move", *point)
    mouse(canvas, "release", *points[-1])


def wheel(canvas, dy, modifiers=Qt.KeyboardModifier.NoModifier, at=(100, 100)):
    point = QPointF(*at)
    canvas.wheelEvent(QWheelEvent(point, point, QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                                  modifiers, Qt.ScrollPhase.NoScrollPhase, False))


def render(canvas):
    image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
    canvas.render(image)
    return image


def test_canvas_is_not_fixed_to_a4_and_ink_is_not_clamped(canvas):
    assert canvas.minimumSize() != canvas.maximumSize()
    canvas.scroll_to(PAGE_WIDTH, PAGE_HEIGHT)
    drag(canvas, (10, 10), (50, 60))
    assert canvas.note.strokes[0].points == ((PAGE_WIDTH + 10, PAGE_HEIGHT + 10),
                                             (PAGE_WIDTH + 50, PAGE_HEIGHT + 60))


def test_scroll_never_goes_above_origin_and_wheel_scrolls_down_and_right(canvas):
    canvas.scroll_to(-50, -50)
    assert canvas.offset() == (0.0, 0.0)
    wheel(canvas, -120)
    assert canvas.offset()[1] > 0
    wheel(canvas, -120, Qt.KeyboardModifier.ShiftModifier)
    assert canvas.offset()[0] > 0


def test_ctrl_wheel_zooms_around_pointer_and_ctrl0_resets(canvas):
    canvas.scroll_to(100, 100)
    before = canvas.to_document(QPointF(200, 150))
    wheel(canvas, 120, Qt.KeyboardModifier.ControlModifier, at=(200, 150))
    assert canvas.zoom > 1
    after = canvas.to_document(QPointF(200, 150))
    assert after == pytest.approx(before)
    drag(canvas, (200, 150), (200, 170))
    assert canvas.note.strokes[0].points[0] == pytest.approx(before)
    for _ in range(80):
        wheel(canvas, 120, Qt.KeyboardModifier.ControlModifier)
    assert canvas.zoom == InkCanvas.MAX_ZOOM
    canvas.reset_zoom()
    assert canvas.zoom == 1


def test_grid_and_plain_paper_render(canvas):
    canvas.set_paper("grid")
    spacing = InkCanvas.GRID
    assert render(canvas).pixelColor(spacing, spacing + 7) != QColor(Qt.GlobalColor.white)
    canvas.set_paper("plain")
    assert render(canvas).pixelColor(spacing, spacing + 7) == QColor(Qt.GlobalColor.white)
    with pytest.raises(ValueError):
        canvas.set_paper("dots")


def test_highlighter_renders_translucent(canvas):
    canvas.set_paper("plain")
    canvas.set_pen_color("#ffe60080")
    canvas.set_pen_width(16)
    drag(canvas, (20, 100), (200, 100))
    assert canvas.note.strokes[0].color == "#ffe60080"
    pixel = render(canvas).pixelColor(100, 100)
    assert pixel != QColor("#ffe600") and pixel != QColor(Qt.GlobalColor.white)


def test_lasso_selects_moves_as_one_undo_and_deletes(canvas):
    inside = Stroke(((50, 50), (60, 60)))
    outside = Stroke(((300, 300), (310, 310)))
    canvas.set_note(Note(strokes=[inside, outside]))
    emitted = []
    canvas.changed.connect(lambda: emitted.append(1))
    canvas.set_mode("select")
    drag(canvas, (30, 30), (100, 30), (100, 100), (30, 100))
    assert canvas.selection == [inside]
    assert emitted == [] and canvas.note.strokes == [inside, outside]
    drag(canvas, (55, 55), (75, 65), (105, 75))
    assert canvas.note.strokes[0].points == ((100, 70), (110, 80))
    assert canvas.note.strokes[1] is outside
    assert emitted == [1] and canvas.selection == [canvas.note.strokes[0]]
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))
    assert canvas.note.strokes == [outside] and canvas.selection == [] and emitted == [1, 1]
    assert canvas.undo() and canvas.note.strokes[0].points == ((100, 70), (110, 80))
    assert canvas.undo() and canvas.note.strokes == [inside, outside]


def test_lasso_outside_selection_clears_it(canvas):
    stroke = Stroke(((50, 50), (60, 60)))
    canvas.set_note(Note(strokes=[stroke]))
    canvas.set_mode("select")
    drag(canvas, (30, 30), (100, 30), (100, 100), (30, 100))
    drag(canvas, (300, 300), (350, 300), (350, 350))
    assert canvas.selection == []


@pytest.mark.parametrize("kind", InkCanvas.SHAPES)
def test_shape_tool_drag_commits_one_stroke(canvas, kind):
    canvas.set_mode("shape")
    canvas.set_shape(kind)
    drag(canvas, (40, 40), (90, 70), (140, 120))
    assert canvas.note.strokes[0].points == shape_points(kind, (40, 40), (140, 120))
    assert len(canvas.note.strokes) == 1


def test_shape_tool_ignores_click_without_drag(canvas):
    canvas.set_mode("shape")
    drag(canvas, (40, 40), (40, 40))
    assert canvas.note.strokes == []


def test_shape_points_geometry():
    assert shape_points("line", (0, 0), (10, 5)) == ((0, 0), (10, 5))
    assert shape_points("rectangle", (10, 0), (0, 5)) == ((0, 0), (10, 0), (10, 5), (0, 5), (0, 0))
    assert shape_points("triangle", (0, 0), (10, 8)) == ((0, 8), (5, 0), (10, 8), (0, 8))
    arrow = shape_points("arrow", (0, 0), (100, 0))
    assert len(arrow) == 5 and arrow[1] == arrow[3] == (100, 0)
    ellipse = shape_points("ellipse", (0, 0), (20, 10))
    assert ellipse[0] == ellipse[-1]
    assert all(0 <= x <= 20 and 0 <= y <= 10 for x, y in ellipse)
    with pytest.raises(ValueError):
        shape_points("star", (0, 0), (1, 1))


def test_view_scrollbars_follow_canvas(app):
    view = CanvasView()
    view.resize(500, 400)
    view.show()
    app.processEvents()
    view.canvas.scroll_to(0, 900)
    assert view.vertical.value() == 900
    view.horizontal.setValue(40)
    assert view.canvas.offset() == (40.0, 900.0)
    view.close()


def test_copy_paste_selection_offsets_selects_and_undoes_in_one_step(canvas):
    first = Stroke(((50, 50), (60, 60)), "#205bb5", 3)
    canvas.set_note(Note(strokes=[first]))
    canvas.set_mode("select")
    drag(canvas, (30, 30), (100, 30), (100, 100), (30, 100))
    emitted = []
    canvas.changed.connect(lambda: emitted.append(1))
    assert canvas.copy_selection()
    assert canvas.paste()
    pasted = canvas.note.strokes[1]
    assert pasted.points == ((70, 70), (80, 80)) and pasted.color == "#205bb5" and pasted.width == 3
    assert canvas.selection == [pasted] and emitted == [1]
    assert canvas.paste()
    assert canvas.note.strokes[2].points == ((90, 90), (100, 100))
    assert canvas.undo() and canvas.note.strokes == [first, pasted]


def test_paste_into_other_note_and_offscreen_copy_lands_in_view(canvas):
    far = Stroke(((5000, 5000), (5010, 5010)))
    canvas.set_note(Note(strokes=[far]))
    canvas.scroll_to(4900, 4900)
    canvas.set_mode("select")
    drag(canvas, (50, 50), (200, 50), (200, 200), (50, 200))
    assert canvas.copy_selection()
    other = Note()
    canvas.set_note(other)
    canvas.scroll_to(0, 0)
    assert canvas.paste()
    (x, y), _ = other.strokes[0].points
    assert canvas.visible_rect().contains(QPointF(x, y))
    assert canvas.mode == "select" and canvas.selection == [other.strokes[0]]


def test_copy_without_selection_and_paste_foreign_clipboard_do_nothing(canvas):
    QApplication.clipboard().setText("hello")
    assert not canvas.copy_selection()
    assert QApplication.clipboard().text() == "hello"
    assert not canvas.paste()
    assert canvas.note.strokes == []


class MemoryStore:
    """Image store stand-in: keeps PNG bytes by content key."""

    def __init__(self, tmp_path):
        self.directory = tmp_path
        self.saved = {}

    def store_image(self, data):
        import hashlib
        key = hashlib.sha256(data).hexdigest() + ".png"
        (self.directory / key).write_bytes(data)
        self.saved[key] = data
        return key

    def image_path(self, key):
        return self.directory / key


def solid_image(width, height, color="#ff0000"):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


@pytest.fixture
def stored(canvas, tmp_path):
    canvas.image_store = MemoryStore(tmp_path)
    canvas.set_paper("plain")
    return canvas


def test_paste_clipboard_image_places_it_in_view_selected_one_undo(stored):
    QApplication.clipboard().setImage(solid_image(120, 80))
    stored.scroll_to(300, 500)
    emitted = []
    stored.changed.connect(lambda: emitted.append(1))
    assert stored.paste()
    (image,) = stored.note.images
    assert (image.width, image.height) == (120, 80)
    assert stored.visible_rect().contains(QPointF(image.x, image.y))
    assert stored.selection == [image] and stored.mode == "select" and emitted == [1]
    assert stored.image_store.saved[image.key]
    assert stored.undo() and stored.note.images == []


def test_large_pasted_image_is_scaled_to_fit_view_keeping_aspect(stored):
    QApplication.clipboard().setImage(solid_image(3000, 1500))
    assert stored.paste()
    image = stored.note.images[0]
    assert image.width <= stored.visible_rect().width() and image.width / image.height == pytest.approx(2)


def test_ink_is_drawn_over_images_and_eraser_keeps_image(stored):
    QApplication.clipboard().setImage(solid_image(200, 200))
    stored.paste()
    image = stored.note.images[0]
    stored.set_mode("pen")
    stored.set_pen_color("#0000ff")
    stored.set_pen_width(6)
    x, y = image.x + 100 - stored.offset()[0], image.y + 100 - stored.offset()[1]
    drag(stored, (x - 50, y), (x + 50, y))
    assert render(stored).pixelColor(int(x), int(y)) == QColor("#0000ff")
    assert render(stored).pixelColor(int(x), int(y) + 40) == QColor("#ff0000")
    stored.set_mode("eraser")
    drag(stored, (x, y - 30), (x, y + 30))
    assert stored.note.strokes == [] and stored.note.images == [image]


def test_tap_selects_image_then_drag_moves_and_delete_removes(stored):
    image = PlacedImage("b" * 64 + ".png", 100, 100, 100, 60)
    stored.set_note(Note(images=[image]))
    stored.set_mode("select")
    drag(stored, (150, 130), (150, 130))
    assert stored.selection == [image]
    drag(stored, (150, 130), (180, 150))
    assert stored.note.images == [PlacedImage(image.key, 130, 120, 100, 60)]
    stored.delete_selection()
    assert stored.note.images == []
    assert stored.undo() and stored.note.images[0].x == 130


def test_lasso_selects_image_by_center_with_strokes_and_copy_paste_duplicates(stored):
    image = PlacedImage("b" * 64 + ".png", 100, 100, 100, 60)
    stroke = Stroke(((120, 120), (140, 140)))
    stored.set_note(Note(strokes=[stroke], images=[image]))
    stored.set_mode("select")
    drag(stored, (90, 90), (220, 90), (220, 200), (90, 200))
    assert set(map(id, stored.selection)) == {id(stroke), id(image)}
    assert stored.copy_selection() and stored.paste()
    assert stored.note.images[1] == PlacedImage(image.key, 120, 120, 100, 60)
    assert stored.note.strokes[1].points == ((140, 140), (160, 160))


def test_resize_handle_scales_single_image_keeping_aspect(stored):
    image = PlacedImage("b" * 64 + ".png", 100, 100, 100, 50)
    stored.set_note(Note(images=[image]))
    stored.set_mode("select")
    drag(stored, (150, 125), (150, 125))
    drag(stored, (200, 150), (250, 200))
    resized = stored.note.images[0]
    # Picture corners keep proportions: scale 1.6 projects the (1.5, 2) drag on the diagonal.
    assert (resized.x, resized.y) == (100, 100)
    assert resized.width == pytest.approx(160) and resized.height == pytest.approx(80)
    assert stored.selection == [resized]


def test_paste_image_file_url_and_without_store(stored, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    path = tmp_path / "snip.png"
    solid_image(40, 30).save(str(path))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    QApplication.clipboard().setMimeData(mime)
    assert stored.paste() and (stored.note.images[0].width, stored.note.images[0].height) == (40, 30)
    stored.image_store = None
    QApplication.clipboard().setImage(solid_image(10, 10))
    assert not stored.paste() and len(stored.note.images) == 1


def test_missing_image_file_renders_placeholder_without_crashing(stored):
    stored.set_note(Note(images=[PlacedImage("c" * 64 + ".png", 10, 10, 80, 60)]))
    assert render(stored).pixelColor(50, 40) != QColor(Qt.GlobalColor.white)


def press_drag(canvas, start, end, shift=False):
    """Drag with optional Shift held throughout."""
    modifiers = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
    for kind, point in (("press", start), ("move", end), ("release", end)):
        event_type = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                      "release": QEvent.Type.MouseButtonRelease}[kind]
        position = QPointF(*point)
        event = QMouseEvent(event_type, position, position, position,
                            Qt.MouseButton.NoButton if kind == "move" else Qt.MouseButton.LeftButton,
                            Qt.MouseButton.NoButton if kind == "release" else Qt.MouseButton.LeftButton,
                            modifiers)
        getattr(canvas, "mouse" + kind.title() + "Event")(event)


def tap_select(canvas, x, y):
    canvas.set_mode("select")
    canvas.clear_selection()
    drag(canvas, (x, y), (x, y))


@pytest.fixture
def rectangle(canvas):
    shape = Stroke(shape_points("rectangle", (100, 100), (200, 160)), "#202020", 3)
    canvas.set_note(Note(strokes=[shape]))
    canvas.set_paper("plain")
    tap_select(canvas, 100, 130)
    assert canvas.selection == [shape]
    return shape


def test_selection_shows_eight_handles_and_rotate_handle(canvas, rectangle):
    handles = canvas.selection_handles()
    assert set(handles) == {"nw", "n", "ne", "e", "se", "s", "sw", "w", "rotate"}
    (nx, ny), (sx, sy) = handles["n"], handles["s"]
    assert nx == pytest.approx(150) and sx == pytest.approx(150) and ny < 100 and sy > 160
    assert handles["rotate"][0] == pytest.approx(150) and handles["rotate"][1] < ny - 10
    assert handles["w"][0] < 100 < 200 < handles["e"][0]


def test_edge_handle_stretches_one_axis_in_one_undo_step(canvas, rectangle):
    emitted = []
    canvas.changed.connect(lambda: emitted.append(1))
    ex, ey = canvas.selection_handles()["e"]
    press_drag(canvas, (ex, ey), (ex + 50, ey + 30))
    stretched = canvas.note.strokes[0]
    assert stretched.points == ((100, 100), (250, 100), (250, 160), (100, 160), (100, 100))
    assert canvas.selection == [stretched] and emitted == [1]
    assert canvas.undo() and canvas.note.strokes == [rectangle]


def test_corner_deforms_freely_and_shift_keeps_proportions(canvas, rectangle):
    x, y = canvas.selection_handles()["se"]
    press_drag(canvas, (x, y), (x + 100, y))
    assert canvas.note.strokes[0].points[2] == pytest.approx((300, 160))
    canvas.undo()
    tap_select(canvas, 100, 130)
    x, y = canvas.selection_handles()["se"]
    press_drag(canvas, (x, y), (x + 100, y), shift=True)
    (left, top), _, (right, bottom), *_ = canvas.note.strokes[0].points
    assert (left, top) == (100, 100)
    assert (right - left) / (bottom - top) == pytest.approx(100 / 60)


def test_handles_never_flip_or_collapse_the_shape(canvas, rectangle):
    x, y = canvas.selection_handles()["e"]
    press_drag(canvas, (x, y), (x - 500, y))
    xs = [px for px, _ in canvas.note.strokes[0].points]
    assert min(xs) == 100 and max(xs) - min(xs) >= 4


def test_rotate_handle_turns_around_center_and_shift_snaps_to_15_degrees(canvas, rectangle):
    import math
    x, y = canvas.selection_handles()["rotate"]
    press_drag(canvas, (x, y), (250, 130))  # From straight above the center to its right: +90 degrees.
    assert canvas.note.strokes[0].points[0] == pytest.approx((180, 80))
    canvas.undo()
    tap_select(canvas, 100, 130)
    x, y = canvas.selection_handles()["rotate"]
    angle = math.radians(-90 + 37)
    press_drag(canvas, (x, y), (150 + 100 * math.cos(angle), 130 + 100 * math.sin(angle)), shift=True)
    snapped = math.radians(30)
    px, py = 100 - 150, 100 - 130
    expected = (150 + px * math.cos(snapped) - py * math.sin(snapped),
                130 + px * math.sin(snapped) + py * math.cos(snapped))
    assert canvas.note.strokes[0].points[0] == pytest.approx(expected)


def test_dragging_inside_shape_frame_still_moves_it(canvas, rectangle):
    press_drag(canvas, (150, 130), (170, 140))
    assert canvas.note.strokes[0].points[0] == (120, 110)


def test_selected_ink_has_gray_halo(canvas, rectangle):
    halo = render(canvas).pixelColor(150, 100 + 4)
    assert halo != QColor(Qt.GlobalColor.white) and halo.red() == halo.green() == halo.blue()
    canvas.clear_selection()
    assert render(canvas).pixelColor(150, 100 + 4) == QColor(Qt.GlobalColor.white)


def test_hover_over_handles_shows_resize_cursor(canvas, rectangle):
    canvas.setMouseTracking(True)
    x, y = canvas.selection_handles()["e"]
    position = QPointF(x, y)
    canvas.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, position, position, position,
                                      Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                      Qt.KeyboardModifier.NoModifier))
    assert canvas.cursor().shape() == Qt.CursorShape.SizeHorCursor


def test_picture_edge_stretch_and_rotation(stored):
    image = PlacedImage("b" * 64 + ".png", 100, 100, 100, 50)
    stored.set_note(Note(images=[image]))
    tap_select(stored, 150, 125)
    x, y = stored.selection_handles()["e"]
    press_drag(stored, (x, y), (x + 50, y))
    assert stored.note.images[0] == PlacedImage(image.key, 100, 100, 150, 50)
    x, y = stored.selection_handles()["rotate"]
    press_drag(stored, (x, y), (300, 125))
    rotated = stored.note.images[0]
    assert rotated.angle == pytest.approx(90)
    assert (rotated.x + rotated.width / 2, rotated.y + rotated.height / 2) == pytest.approx((175, 125))
    assert (rotated.width, rotated.height) == pytest.approx((150, 50))
    tap_select(stored, 175, 175)  # Inside the turned picture, outside its unrotated rectangle.
    assert stored.selection == [rotated]


def test_new_shape_stays_selected_and_handles_work_without_lasso(canvas):
    canvas.set_mode("shape")
    canvas.set_shape("rectangle")
    drag(canvas, (100, 100), (200, 160))
    shape = canvas.note.strokes[0]
    assert canvas.selection == [shape] and canvas.mode == "shape"
    x, y = canvas.selection_handles()["e"]
    press_drag(canvas, (x, y), (x + 50, y))
    assert len(canvas.note.strokes) == 1 and canvas.note.strokes[0].points[1] == (250, 100)
    drag(canvas, (400, 300), (450, 350))
    assert len(canvas.note.strokes) == 2 and canvas.selection == [canvas.note.strokes[1]]
    canvas.set_mode("pen")
    assert canvas.selection == []


@pytest.mark.parametrize("handle", ["nw", "ne", "sw", "se"])
def test_shift_corner_on_flat_line_scales_along_the_line_only(canvas, handle):
    line = Stroke(((100, 100), (200, 100)), "#000000", 3)
    canvas.set_note(Note(strokes=[line]))
    canvas.set_mode("select")
    canvas.selection = [line]
    x, y = canvas.selection_handles()[handle]
    outward = 10 if "e" in handle else -10
    press_drag(canvas, (x, y), (x + outward, y + 10), shift=True)
    (x0, y0), (x1, y1) = canvas.note.strokes[0].points
    assert y0 == y1 == 100 and 105 <= x1 - x0 <= 115


def test_shift_handles_on_a_dot_do_not_crash(canvas):
    dot = Stroke(((150, 150),), "#000000", 3)
    canvas.set_note(Note(strokes=[dot]))
    canvas.set_mode("select")
    canvas.selection = [dot]
    for name, (x, y) in canvas.selection_handles().items():
        press_drag(canvas, (x, y), (x - 10, y - 10), shift=True)
    assert len(canvas.note.strokes) == 1


def test_nearest_handle_wins_on_thin_selections(canvas):
    line = Stroke(((100, 100), (200, 101)), "#000000", 1)
    canvas.set_note(Note(strokes=[line]))
    canvas.set_mode("select")
    canvas.selection = [line]
    for name in ("e", "w", "n", "s"):
        assert canvas._handle_at(canvas.selection_handles()[name]) == name
