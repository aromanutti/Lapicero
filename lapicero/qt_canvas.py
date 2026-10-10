"""Infinite ink surface; stored coordinates are logical document units.

The view shows the document from ``offset`` (top-left, never negative) at
``zoom``. The document grows right and down without limit.
"""

import json
import math
import time

from PySide6.QtCore import (QBuffer, QIODevice, QMimeData, QPointF, QRectF, Qt, QEvent,
                            QTimer, Signal)
from PySide6.QtGui import (QColor, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QPixmap, QPointingDevice, QPolygonF)
from PySide6.QtWidgets import QApplication, QGridLayout, QScrollBar, QWidget

from .model import Note, NoteFormatError, PlacedImage, Stroke
from .shapes import SHAPE_KINDS, normalize_shape, shape_points


GRID_COLOR = "#cfe2f3"
CLIPBOARD_MIME = "application/x-lapicero-strokes"
PASTE_STEP = 20.0
PASTE_MARGIN = 40.0  # Distance from the view's top-left corner for pasted pictures.
HANDLE = 4.0  # Half-size of a selection handle, in screen pixels.
HANDLE_REACH = 9.0  # Pointer distance that grabs a handle, in screen pixels.
FRAME_PAD = 4.0  # Gap between the ink and its selection frame, in screen pixels.
ROTATE_OFFSET = 24.0  # Rotate handle distance above the frame, in screen pixels.
MIN_EXTENT = 4.0  # Smallest width/height a handle can squeeze a selection to.
SNAP_DEGREES = 15.0  # Shift-rotation step.
HALO_COLOR = QColor(150, 150, 150, 140)
FRAME_COLOR = "#7a7a7a"
# Edge/corner handle -> (horizontal direction, vertical direction).
HANDLES = {"nw": (-1, -1), "n": (0, -1), "ne": (1, -1), "e": (1, 0),
           "se": (1, 1), "s": (0, 1), "sw": (-1, 1), "w": (-1, 0)}
HANDLE_CURSORS = {"nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
                  "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
                  "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
                  "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
                  "rotate": Qt.CursorShape.PointingHandCursor}
PLACEHOLDER_COLOR = "#e6e6e6"
SELECTION_COLOR = "#2f7de1"


def qcolor(color):
    """Convert stored #RRGGBB or #RRGGBBAA to QColor (Qt reads 9 digits as #AARRGGBB)."""
    result = QColor(color[:7])
    if len(color) == 9:
        result.setAlpha(int(color[7:], 16))
    return result


class InkCanvas(QWidget):
    """Render vector notes and accept one mouse or tablet stream per gesture.

    Synthesized mouse events are always ignored. Native mouse events immediately
    after a tablet gesture are ignored too, for platforms reporting both streams.
    A mouse gesture already underway is discarded if a tablet press takes over.
    A tablet eraser tip erases regardless of the selected tool.
    """

    changed = Signal()
    view_changed = Signal()
    gesture_changed = Signal(bool)  # True while a pen/eraser/lasso/shape gesture is down.
    HOLD_MS = 500
    MOUSE_SUPPRESSION_SECONDS = .15
    ERASER_RADIUS = 10
    GRID = 24
    MIN_ZOOM, MAX_ZOOM = .25, 4.0
    WHEEL_STEP = 60
    MODES = ("pen", "eraser", "select", "shape")
    SHAPES = SHAPE_KINDS

    def __init__(self, note=None, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)  # Hover cursors over selection handles.
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.note = note if note is not None else Note()
        self.mode = "pen"
        self.shape = "rectangle"
        self.paper = "grid"
        self.pen_color = "#202020"
        self.pen_width = 3.0
        self.zoom = 1.0
        self.selection = []
        self._ox = self._oy = 0.0
        self._gesture = None  # Mode of the gesture in progress.
        self._points = None
        self._ink_color = None
        self._ink_width = None
        self._snapped = None
        self._source = None
        self._last_erase = None
        self._erase_changed = False
        self._lasso = None
        self._move_from = None
        self._shape_start = None
        self._shape_end = None
        self._pan_from = None
        self._cache = {}
        self._paste_count = 0
        self._handle = None  # Grabbed selection handle (see HANDLES, or "rotate").
        self._preview = None  # Transformed copies of the selection while dragging.
        self._shift = False
        # Optional Library-like object: store_image(bytes) -> key, image_path(key) -> Path.
        self.image_store = None
        self._pixmaps = {}
        self._tablet_time = float("-inf")
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._hold_end)

    # Settings ---------------------------------------------------------------

    def set_note(self, note):
        if not isinstance(note, Note):
            raise TypeError("Expected a Note")
        self.finalize_current_gesture()
        self.note = note
        self.selection = []
        self._cache.clear()
        self.update()
        self.view_changed.emit()

    def set_mode(self, mode):
        if mode not in self.MODES:
            raise ValueError("Unknown tool")
        self.finalize_current_gesture()
        self.mode = mode
        if mode not in ("select", "shape"):
            self.clear_selection()
        self._apply_cursor()

    def _apply_cursor(self):
        self.setCursor(Qt.CursorShape.ArrowCursor if self.mode == "select" else Qt.CursorShape.CrossCursor)

    def set_shape(self, shape):
        if shape not in self.SHAPES:
            raise ValueError("Unknown shape")
        self.shape = shape

    def set_paper(self, paper):
        if paper not in ("plain", "grid"):
            raise ValueError("Unknown paper")
        self.paper = paper
        self.update()

    def set_pen_color(self, color):
        # Use Stroke's strict JSON-compatible color validation.
        Stroke(((0, 0),), color, 1)
        self.pen_color = color

    def set_pen_width(self, width):
        Stroke(((0, 0),), "#202020", width)
        if not 1 <= width <= 40:
            raise ValueError("Pen width must be between 1 and 40")
        self.pen_width = float(width)

    # View -------------------------------------------------------------------

    def offset(self):
        return (self._ox, self._oy)

    def scroll_to(self, x, y):
        x, y = max(0.0, float(x)), max(0.0, float(y))
        if (x, y) != (self._ox, self._oy):
            self._ox, self._oy = x, y
            self.update()
            self.view_changed.emit()

    def scroll_by(self, dx, dy):
        self.scroll_to(self._ox + dx, self._oy + dy)

    def set_zoom(self, zoom, anchor=None):
        """Zoom around a widget position, keeping the document point under it fixed."""
        zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, zoom))
        anchor = anchor if anchor is not None else QPointF(self.width() / 2, self.height() / 2)
        fixed = self.to_document(anchor)
        self.zoom = zoom
        self._ox = self._oy = None
        self.scroll_to(fixed[0] - anchor.x() / zoom, fixed[1] - anchor.y() / zoom)
        self.update()
        self.view_changed.emit()

    def reset_zoom(self):
        self.set_zoom(1.0)

    def to_document(self, position):
        return (position.x() / self.zoom + self._ox, position.y() / self.zoom + self._oy)

    def visible_rect(self):
        return QRectF(self._ox, self._oy, self.width() / self.zoom, self.height() / self.zoom)

    def content_rect(self):
        """Bounds of all ink in document units (empty at the origin when blank)."""
        rect = QRectF()
        for item in (*self.note.strokes, *self.note.images):
            rect = rect.united(self._item_rect(item))
        return rect

    def wheelEvent(self, event):
        delta = event.angleDelta()
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if delta.y():
                self.set_zoom(self.zoom * 1.1 ** (delta.y() / 120), event.position())
        else:
            dx, dy = delta.x(), delta.y()
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                dx, dy = dy, dx
            self.scroll_by(-dx / 120 * self.WHEEL_STEP / self.zoom,
                           -dy / 120 * self.WHEEL_STEP / self.zoom)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view_changed.emit()

    # History ----------------------------------------------------------------

    def undo(self):
        self.finalize_current_gesture()
        self.clear_selection()
        if self.note.undo():
            self.changed.emit()
            self.update()
            return True
        return False

    def redo(self):
        self.finalize_current_gesture()
        self.clear_selection()
        if self.note.redo():
            self.changed.emit()
            self.update()
            return True
        return False

    # Selection --------------------------------------------------------------

    def clear_selection(self):
        if self.selection:
            self.selection = []
            self.update()

    def delete_selection(self):
        chosen = {id(item) for item in self.selection}
        self.selection = []
        if chosen and self.note.replace([s for s in self.note.strokes if id(s) not in chosen],
                                        [i for i in self.note.images if id(i) not in chosen]):
            self.changed.emit()
        self.update()

    def copy_selection(self):
        """Put selected strokes and pictures on the system clipboard.

        Pictures are copied by key, so they paste within the same library.
        Returns False when nothing is selected.
        """
        self.finalize_current_gesture()
        if not self.selection:
            return False
        payload = {"strokes": [i.to_data() for i in self.selection if isinstance(i, Stroke)],
                   "images": [i.to_data() for i in self.selection if isinstance(i, PlacedImage)]}
        data = QMimeData()
        data.setData(CLIPBOARD_MIME, json.dumps(payload).encode("utf-8"))
        QApplication.clipboard().setMimeData(data)
        self._paste_count = 0
        return True

    def paste(self):
        """Paste copied ink/pictures, a clipboard picture (screenshots, browser
        images) or a copied image file, as one undo step, and select it."""
        self.finalize_current_gesture()
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return False
        if mime.hasFormat(CLIPBOARD_MIME):
            return self._paste_items(bytes(mime.data(CLIPBOARD_MIME)))
        if mime.hasImage():
            return self._paste_image(QImage(mime.imageData()))
        for url in mime.urls() if mime.hasUrls() else ():
            if url.isLocalFile():
                image = QImage(url.toLocalFile())
                if not image.isNull():
                    return self._paste_image(image)
        return False

    def _paste_items(self, raw):
        try:
            payload = json.loads(raw.decode("utf-8"))
            strokes = [Stroke(e["points"], e["color"], e["width"]) for e in payload["strokes"]]
            images = [PlacedImage(e["key"], e["x"], e["y"], e["width"], e["height"], e.get("angle", 0))
                      for e in payload["images"]]
        except (ValueError, TypeError, KeyError, NoteFormatError):
            return False
        if not strokes and not images:
            return False
        self._paste_count += 1
        dx = dy = PASTE_STEP * self._paste_count
        left = min([x for s in strokes for x, _ in s.points] + [i.x for i in images])
        top = min([y for s in strokes for _, y in s.points] + [i.y for i in images])
        visible = self.visible_rect()
        if not visible.contains(QPointF(left + dx, top + dy)):
            dx = visible.left() + 2 * PASTE_STEP * self._paste_count - left
            dy = visible.top() + 2 * PASTE_STEP * self._paste_count - top
        pasted = [self._shifted(item, dx, dy) for item in (*strokes, *images)]
        self.set_mode("select")
        self.note.replace([*self.note.strokes, *pasted[:len(strokes)]],
                          [*self.note.images, *pasted[len(strokes):]])
        self.selection = pasted
        self.changed.emit()
        self.update()
        return True

    def _paste_image(self, image):
        if self.image_store is None or image.isNull():
            return False
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        try:
            key = self.image_store.store_image(bytes(buffer.data()))
        except (OSError, ValueError):
            return False
        visible = self.visible_rect()
        ratio = image.devicePixelRatio() or 1.0
        width, height = image.width() / ratio, image.height() / ratio
        scale = min(1.0, (visible.width() - 2 * PASTE_MARGIN) / width,
                    (visible.height() - 2 * PASTE_MARGIN) / height)
        placed = PlacedImage(key, visible.left() + PASTE_MARGIN, visible.top() + PASTE_MARGIN,
                             width * scale, height * scale)
        self._pixmaps[key] = QPixmap.fromImage(image)
        self.set_mode("select")
        self.note.add_image(placed)
        self.selection = [placed]
        self.changed.emit()
        self.update()
        return True

    @staticmethod
    def _image_corners(image):
        """Corners of a picture after its rotation about the center."""
        cx, cy = image.x + image.width / 2, image.y + image.height / 2
        a = math.radians(image.angle)
        cos, sin = math.cos(a), math.sin(a)
        return [(cx + dx * cos - dy * sin, cy + dx * sin + dy * cos)
                for dx, dy in ((-image.width / 2, -image.height / 2), (image.width / 2, -image.height / 2),
                               (image.width / 2, image.height / 2), (-image.width / 2, image.height / 2))]

    def _item_rect(self, item):
        """Painted bounds: ink includes its pen width; pictures include rotation."""
        if isinstance(item, PlacedImage):
            return QPolygonF([QPointF(*c) for c in self._image_corners(item)]).boundingRect()
        return self._entry(item)[1]

    def _image_contains(self, image, x, y):
        cx, cy = image.x + image.width / 2, image.y + image.height / 2
        a = -math.radians(image.angle)
        dx, dy = x - cx, y - cy
        ux, uy = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
        return abs(ux) <= image.width / 2 and abs(uy) <= image.height / 2

    @staticmethod
    def _shifted(item, dx, dy):
        if isinstance(item, PlacedImage):
            return item.moved(dx, dy)
        return Stroke(tuple((x + dx, y + dy) for x, y in item.points), item.color, item.width)

    def _geometry(self, items):
        """Bounds of the stroke points and picture corners (no pen width)."""
        points = [p for item in items for p in (
            self._image_corners(item) if isinstance(item, PlacedImage) else item.points)]
        xs, ys = [x for x, _ in points], [y for _, y in points]
        return QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))

    def _shown_selection(self):
        return self._preview if self._preview is not None else self.selection

    def _frame(self):
        """Dashed selection frame around the (possibly previewed) selection."""
        items = self._shown_selection()
        pad = max([i.width / 2 for i in items if isinstance(i, Stroke)], default=0) + FRAME_PAD / self.zoom
        return self._geometry(items).adjusted(-pad, -pad, pad, pad)

    def _selection_rect(self):
        return self._frame()

    def selection_handles(self):
        """Document positions of the eight resize handles and the rotate handle."""
        if not self.selection:
            return {}
        frame = self._frame()
        center = frame.center()
        handles = {name: (center.x() + dx * frame.width() / 2, center.y() + dy * frame.height() / 2)
                   for name, (dx, dy) in HANDLES.items()}
        handles["rotate"] = (center.x(), frame.top() - ROTATE_OFFSET / self.zoom)
        return handles

    def _handle_at(self, point):
        """Handle under a document point. The core of the selection belongs to
        moving, so small shapes stay draggable while handles win near the edges."""
        if not self.selection:
            return None
        reach = HANDLE_REACH / self.zoom
        rect = self._geometry(self.selection)
        dx, dy = min(reach, rect.width() / 4), min(reach, rect.height() / 4)
        if rect.adjusted(dx, dy, -dx, -dy).contains(QPointF(*point)):
            return None
        handles = self.selection_handles()
        distance, name = min((math.dist(position, point), name) for name, position in handles.items())
        return name if distance <= reach else None

    def _transformed(self, item, fn, angle=0.0, scale=(1.0, 1.0)):
        """Map an item through a point transform; pictures keep their own axes."""
        if isinstance(item, PlacedImage):
            cx, cy = fn((item.x + item.width / 2, item.y + item.height / 2))
            a = math.radians(item.angle)
            # Scale along the picture's own axes (exact for multiples of 90 degrees).
            sw = math.hypot(scale[0] * math.cos(a), scale[1] * math.sin(a))
            sh = math.hypot(scale[0] * math.sin(a), scale[1] * math.cos(a))
            w, h = item.width * sw, item.height * sh
            return PlacedImage(item.key, cx - w / 2, cy - h / 2, w, h, item.angle + angle)
        return Stroke(tuple(fn(p) for p in item.points), item.color, item.width)

    def _transform_preview(self, point):
        """Selection as it would be after dragging the grabbed handle to point."""
        items = self.selection
        if self._handle is None:
            dx, dy = point[0] - self._move_from[0], point[1] - self._move_from[1]
            return [self._shifted(item, dx, dy) for item in items]
        rect = self._geometry(items)
        if self._handle == "rotate":
            cx, cy = rect.center().x(), rect.center().y()
            start = math.atan2(self._move_from[1] - cy, self._move_from[0] - cx)
            degrees = math.degrees(math.atan2(point[1] - cy, point[0] - cx) - start)
            if self._shift:
                degrees = round(degrees / SNAP_DEGREES) * SNAP_DEGREES
            a = math.radians(degrees)
            cos, sin = math.cos(a), math.sin(a)
            fn = lambda p: (cx + (p[0] - cx) * cos - (p[1] - cy) * sin,
                            cy + (p[0] - cx) * sin + (p[1] - cy) * cos)
            return [self._transformed(item, fn, angle=degrees) for item in items]
        hx, hy = HANDLES[self._handle]
        scales = []
        for direction, extent, moved, low, high in (
                (hx, rect.width(), point[0] - self._move_from[0], rect.left(), rect.right()),
                (hy, rect.height(), point[1] - self._move_from[1], rect.top(), rect.bottom())):
            if not direction or extent < 1e-6:
                scales.append(1.0)
            else:
                scales.append(max(extent + direction * moved, MIN_EXTENT) / extent)
        sx, sy = scales
        pictures_only = all(isinstance(item, PlacedImage) for item in items)
        if hx and hy and (self._shift != pictures_only):
            # Keep proportions: project the drag onto the frame's diagonal. A flat
            # line or a dot has no proportion to keep, so follow its own extent.
            w, h = rect.width(), rect.height()
            if w > 1e-6 and h > 1e-6:
                sx = sy = max((sx * w * w + sy * h * h) / (w * w + h * h), MIN_EXTENT / min(w, h))
            elif w > 1e-6:
                sy = sx
            elif h > 1e-6:
                sx = sy
        ax = rect.right() if hx < 0 else rect.left()
        ay = rect.bottom() if hy < 0 else rect.top()
        fn = lambda p: (ax + (p[0] - ax) * sx, ay + (p[1] - ay) * sy)
        return [self._transformed(item, fn, scale=(sx, sy)) for item in items]

    def keyPressEvent(self, event):
        if self.selection and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selection()
            event.accept()
        elif self.selection and event.key() == Qt.Key.Key_Escape:
            self.clear_selection()
            event.accept()
        else:
            super().keyPressEvent(event)

    # Gestures ---------------------------------------------------------------

    def finalize_current_gesture(self):
        """Commit pending ink, shape or move to its original note, or end an eraser group."""
        note = self.note
        stroke = None
        if self._points is not None:
            stroke = Stroke(self._snapped if self._snapped is not None else tuple(self._points),
                            self._ink_color, self._ink_width)
        moved = None
        if self._preview is not None:
            mapping = {id(old): new for old, new in zip(self.selection, self._preview)}
            moved = ([mapping.get(id(s), s) for s in note.strokes],
                     [mapping.get(id(i), i) for i in note.images])
            self.selection = list(self._preview)
        new_shape = self._gesture == "shape"
        self._stop_gesture()
        if stroke is not None and note.add_stroke(stroke):
            if new_shape and note is self.note:
                self.selection = [stroke]  # Show the frame and handles right away.
            self.changed.emit()
        if moved is not None and note.replace(*moved):
            self.changed.emit()
        self.update()

    def _stop_gesture(self):
        was_active = self._gesture is not None
        self._hold.stop()
        self.note.end_erase()
        self._gesture = None
        self._points = None
        self._snapped = None
        self._source = None
        self._last_erase = None
        self._lasso = None
        self._move_from = None
        self._handle = None
        self._preview = None
        self._shape_start = None
        self._shape_end = None
        if self._erase_changed:
            self._erase_changed = False
            self.changed.emit()
        if was_active:
            self.gesture_changed.emit(False)
        self.update()

    def _ink_stroke(self, points):
        return Stroke(tuple(points), self._ink_color, self._ink_width)

    def _press(self, position, source, eraser_tip=False):
        if not self.rect().contains(position.toPoint()):
            return
        self.finalize_current_gesture()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._source = source
        self._gesture = "eraser" if eraser_tip else self.mode
        self.gesture_changed.emit(True)
        point = self.to_document(position)
        if self._gesture == "shape" and self.selection and (
                self._handle_at(point) is not None or self._frame().contains(QPointF(*point))):
            self._gesture = "select"  # Like OneNote: a just-drawn shape is grabbed, not redrawn.
        if self._gesture == "eraser":
            self.clear_selection()  # Erased strokes must not linger in a lasso selection.
            self.note.begin_erase()
            self._erase(point)
        elif self._gesture == "select":
            handle = self._handle_at(point)
            if handle is not None:
                self._handle, self._move_from = handle, point
            elif self.selection and self._frame().contains(QPointF(*point)):
                self._move_from = point
            else:
                self.clear_selection()
                self._lasso = [point]
        elif self._gesture == "shape":
            self.clear_selection()
            self._shape_start = point
            self._ink_color, self._ink_width = self.pen_color, self.pen_width
        else:
            self._points = [point]
            self._ink_color, self._ink_width = self.pen_color, self.pen_width
            self._hold.start(self.HOLD_MS)
            self._update_doc(QRectF(*point, 0, 0))

    def _move(self, position, source):
        if source != self._source or self._gesture is None:
            return
        point = self.to_document(position)
        if self._gesture == "eraser":
            if self._last_erase is not None:
                self._erase(point)
        elif self._gesture == "select":
            if self._move_from is not None:
                self._preview = self._transform_preview(point)
                self.update()
            elif self._lasso is not None:
                self._lasso.append(point)
                self.update()
        elif self._gesture == "shape":
            self._shape_end = point
            self.update()
        elif self._points is not None and point != self._points[-1]:
            self._snapped = None
            previous = self._points[-1]
            self._points.append(point)
            self._hold.start(self.HOLD_MS)
            self._update_doc(QRectF(QPointF(*previous), QPointF(*point)).normalized())

    def _release(self, position, source):
        if source != self._source or self._gesture is None:
            return
        point = self.to_document(position)
        if self._gesture == "eraser":
            self._move(position, source)
        elif self._gesture == "select":
            if self._lasso is not None:
                self._lasso.append(point)
                self._select_in(self._lasso)
            elif self._move_from is not None:
                self._preview = self._transform_preview(point)
        elif self._gesture == "shape":
            start = self._shape_start
            if math.dist(start, point) > 2:
                self._points = list(shape_points(self.shape, start, point))
                self._snapped = None
        elif self._points is not None and point != self._points[-1]:
            self._points.append(point)
            self._snapped = None
        self.finalize_current_gesture()

    def _select_in(self, lasso):
        """Select strokes mostly inside the loop and pictures whose center is inside.

        A tap (a loop that never left its start) selects the topmost item under it.
        """
        if all(math.dist(lasso[0], p) <= 3 / self.zoom for p in lasso):
            x, y = lasso[0]
            for stroke in reversed(self.note.strokes):
                if self._hits_rendered(stroke, x, y, 3 / self.zoom):
                    self.selection = [stroke]
                    return
            for image in reversed(self.note.images):
                if self._image_contains(image, x, y):
                    self.selection = [image]
                    return
            self.selection = []
            return
        polygon = QPolygonF([QPointF(*p) for p in lasso])
        def inside(stroke):
            count = sum(polygon.containsPoint(QPointF(*p), Qt.FillRule.OddEvenFill) for p in stroke.points)
            return count * 2 > len(stroke.points)
        self.selection = [stroke for stroke in self.note.strokes if inside(stroke)] + [
            image for image in self.note.images
            if polygon.containsPoint(self._item_rect(image).center(), Qt.FillRule.OddEvenFill)]

    def _hold_end(self):
        if self._points is not None and self._gesture == "pen":
            result = normalize_shape(self._points)
            if result is not None:
                self._snapped = result[1]
                self.update()

    # Erasing ----------------------------------------------------------------

    @classmethod
    def _hits_rendered(cls, stroke, x, y, radius):
        # Cover the round pen (or dot) and the antialiased edge of its pixels.
        reach = radius + stroke.width / 2 + .5
        if len(stroke.points) == 1:
            px, py = stroke.points[0]
            return math.hypot(x - px, y - py) <= reach
        stroker = QPainterPathStroker()
        stroker.setWidth(2 * reach)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(cls._path(stroke)).contains(QPointF(x, y))

    def _erase(self, point):
        start = self._last_erase or point
        dx, dy = point[0] - start[0], point[1] - start[1]
        steps = max(1, math.ceil(max(abs(dx), abs(dy)) / 5))
        changed = False
        reach = self.ERASER_RADIUS / self.zoom
        for i in range(steps + 1):
            x, y = start[0] + dx * i / steps, start[1] + dy * i / steps
            changed = self.note.erase_where(
                lambda stroke: self._entry(stroke)[1].adjusted(-reach, -reach, reach, reach).contains(x, y)
                and self._hits_rendered(stroke, x, y, reach)) or changed
        self._last_erase = point
        if changed:
            self._erase_changed = True
            self.update()

    # Painting ---------------------------------------------------------------

    @staticmethod
    def _path(stroke):
        points = stroke.points
        path = QPainterPath(QPointF(*points[0]))
        if len(points) == 1:
            return path
        # Normalized polygons and arrows must keep their exact straight edges.
        exact = (len(points) in (4, 5) and points[0] == points[-1]
                 or len(points) == 5 and points[1] == points[3])
        if exact:
            for point in points[1:]:
                path.lineTo(QPointF(*point))
        else:
            for index in range(1, len(points) - 1):
                x, y = points[index]
                nx, ny = points[index + 1]
                path.quadTo(QPointF(x, y), QPointF((x + nx) / 2, (y + ny) / 2))
            path.quadTo(QPointF(*points[-1]), QPointF(*points[-1]))
        return path

    def _entry(self, stroke):
        """Cached (path, bounds) per stroke object; strokes are immutable."""
        entry = self._cache.get(id(stroke))
        if entry is None or entry[0] is not stroke:
            path = self._path(stroke)
            half = stroke.width / 2 + 1
            bounds = path.boundingRect().adjusted(-half, -half, half, half)
            entry = (stroke, path, bounds)
            self._cache[id(stroke)] = entry
        return entry[1:]

    def _paint_stroke(self, painter, stroke, path=None):
        color = qcolor(stroke.color)
        if len(stroke.points) == 1:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            radius = stroke.width / 2
            painter.drawEllipse(QPointF(*stroke.points[0]), radius, radius)
            return
        painter.setPen(QPen(color, stroke.width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path if path is not None else self._path(stroke))

    def _pixmap(self, key):
        """Load each picture once; None when its file is missing or unreadable."""
        if key not in self._pixmaps:
            pixmap = None
            if self.image_store is not None:
                try:
                    loaded = QPixmap(str(self.image_store.image_path(key)))
                except (OSError, ValueError):
                    loaded = QPixmap()
                pixmap = None if loaded.isNull() else loaded
            self._pixmaps[key] = pixmap
        return self._pixmaps[key]

    def _paint_images(self, painter, exposed, hidden, extra):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for image in [i for i in self.note.images if id(i) not in hidden] + extra:
            if not self._item_rect(image).intersects(exposed):
                continue
            painter.save()
            painter.translate(image.x + image.width / 2, image.y + image.height / 2)
            painter.rotate(image.angle)
            rect = QRectF(-image.width / 2, -image.height / 2, image.width, image.height)
            pixmap = self._pixmap(image.key)
            if pixmap is not None:
                painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
            else:
                pen = QPen(QColor("#9a9a9a"), 1, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(QColor(PLACEHOLDER_COLOR))
                painter.drawRect(rect)
                painter.drawLine(rect.topLeft(), rect.bottomRight())
                painter.drawLine(rect.topRight(), rect.bottomLeft())
            painter.restore()

    def _paint_halo(self, painter, stroke, path):
        """OneNote-style gray glow under selected ink."""
        if len(stroke.points) == 1:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HALO_COLOR)
            radius = stroke.width / 2 + 4
            painter.drawEllipse(QPointF(*stroke.points[0]), radius, radius)
            return
        painter.setPen(QPen(HALO_COLOR, stroke.width + 8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _paint_frame(self, painter):
        frame = self._frame()
        pen = QPen(QColor(FRAME_COLOR), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)
        if self._preview is not None and self._handle is not None:
            return  # Handles would jump around while transforming.
        handles = self.selection_handles()
        rotate = QPointF(*handles.pop("rotate"))
        painter.drawLine(QPointF(frame.center().x(), frame.top()), rotate)
        solid = QPen(QColor(FRAME_COLOR), 1)
        solid.setCosmetic(True)
        painter.setPen(solid)
        painter.setBrush(Qt.GlobalColor.white)
        size = HANDLE / self.zoom
        for x, y in handles.values():
            painter.drawRect(QRectF(x - size, y - size, 2 * size, 2 * size))
        # Rotate handle: a circular arrow, like OneNote's.
        radius = 1.6 * size
        painter.drawEllipse(rotate, radius + size * .6, radius + size * .6)
        arc = QRectF(rotate.x() - radius, rotate.y() - radius, 2 * radius, 2 * radius)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(arc, 90 * 16, 280 * 16)
        tip = QPointF(rotate.x(), rotate.y() - radius)
        painter.drawLine(tip, tip + QPointF(-size * .8, -size * .6))
        painter.drawLine(tip, tip + QPointF(-size * .8, size * .6))

    def _update_doc(self, rect):
        """Repaint only the widget area covering a document rectangle."""
        margin = (self._ink_width or self.pen_width) + 2
        rect = rect.adjusted(-margin, -margin, margin, margin)
        self.update(QRectF((rect.x() - self._ox) * self.zoom, (rect.y() - self._oy) * self.zoom,
                           rect.width() * self.zoom, rect.height() * self.zoom).toAlignedRect())

    def _paint_grid(self, painter, visible):
        pen = QPen(QColor(GRID_COLOR))
        pen.setCosmetic(True)
        painter.setPen(pen)
        step = self.GRID
        x = math.floor(visible.left() / step) * step
        while x <= visible.right():
            painter.drawLine(QPointF(x, visible.top()), QPointF(x, visible.bottom()))
            x += step
        y = math.floor(visible.top() / step) * step
        while y <= visible.bottom():
            painter.drawLine(QPointF(visible.left(), y), QPointF(visible.right(), y))
            y += step

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), Qt.GlobalColor.white)
        painter.scale(self.zoom, self.zoom)
        painter.translate(-self._ox, -self._oy)
        exposed = QRectF(event.rect().x() / self.zoom + self._ox, event.rect().y() / self.zoom + self._oy,
                         event.rect().width() / self.zoom, event.rect().height() / self.zoom)
        if self.paper == "grid":
            self._paint_grid(painter, exposed)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        hidden = {id(item) for item in self.selection} if self._preview is not None else set()
        shown = self._shown_selection()
        self._paint_images(painter, exposed, hidden,
                           [i for i in shown if isinstance(i, PlacedImage)] if hidden else [])
        selected = {id(item) for item in shown}
        live = {id(s) for s in self.note.strokes}
        if len(self._cache) > len(live) + 256:
            self._cache = {key: value for key, value in self._cache.items() if key in live}
        extra = [i for i in shown if isinstance(i, Stroke)] if hidden else []
        for stroke in [s for s in self.note.strokes if id(s) not in hidden] + extra:
            path, bounds = self._entry(stroke)
            if bounds.adjusted(-5, -5, 5, 5).intersects(exposed):
                if id(stroke) in selected:
                    self._paint_halo(painter, stroke, path)
                self._paint_stroke(painter, stroke, path)
        if self._points is not None:
            self._paint_stroke(painter, self._ink_stroke(self._snapped or self._points))
        elif self._shape_start is not None and self._shape_end is not None:
            self._paint_stroke(painter, self._ink_stroke(
                shape_points(self.shape, self._shape_start, self._shape_end)))
        if self.selection:
            self._paint_frame(painter)
        if self._lasso is not None and len(self._lasso) > 1:
            dash = QPen(QColor(SELECTION_COLOR), 1, Qt.PenStyle.DashLine)
            dash.setCosmetic(True)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(dash)
            painter.drawPolyline(QPolygonF([QPointF(*p) for p in self._lasso]))

    # Input events -----------------------------------------------------------

    def _mouse_ignored(self, event):
        return event.source() != Qt.MouseEventSource.MouseEventNotSynthesized or (
            time.monotonic() - self._tablet_time < self.MOUSE_SUPPRESSION_SECONDS)

    def _track_modifiers(self, event):
        modifiers = getattr(event, "modifiers", None)
        self._shift = bool(modifiers is not None and modifiers() & Qt.KeyboardModifier.ShiftModifier)

    def _hover(self, position):
        """Show resize/rotate/move cursors over a selection, like OneNote."""
        if self.mode not in ("select", "shape") or self._gesture is not None:
            return
        point = self.to_document(position)
        handle = self._handle_at(point)
        if handle is not None:
            self.setCursor(HANDLE_CURSORS[handle])
        elif self.selection and self._frame().contains(QPointF(*point)):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self._apply_cursor()

    def mousePressEvent(self, event):
        self._track_modifiers(event)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._mouse_ignored(event):
            pass
        elif event.button() == Qt.MouseButton.LeftButton:
            self._press(event.position(), "mouse")
        event.accept()

    def mouseMoveEvent(self, event):
        self._track_modifiers(event)
        if self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = event.position()
            self.scroll_by(-delta.x() / self.zoom, -delta.y() / self.zoom)
        elif not self._mouse_ignored(event) and event.buttons() & Qt.MouseButton.LeftButton:
            self._move(event.position(), "mouse")
        elif not event.buttons():
            self._hover(event.position())
        event.accept()

    def mouseReleaseEvent(self, event):
        self._track_modifiers(event)
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_from is not None:
            self._pan_from = None
            self._apply_cursor()
        elif not self._mouse_ignored(event) and event.button() == Qt.MouseButton.LeftButton:
            self._release(event.position(), "mouse")
        event.accept()

    def tabletEvent(self, event):
        if event.type() not in (QEvent.Type.TabletPress, QEvent.Type.TabletMove,
                                QEvent.Type.TabletRelease):
            return
        self._tablet_time = time.monotonic()
        self._track_modifiers(event)
        if event.type() == QEvent.Type.TabletPress:
            if self._source == "mouse":
                self._stop_gesture()
            pointer = getattr(event, "pointerType", None)
            eraser_tip = pointer is not None and pointer() == QPointingDevice.PointerType.Eraser
            self._press(event.position(), "tablet", eraser_tip)
        elif event.type() == QEvent.Type.TabletMove:
            self._move(event.position(), "tablet")
        else:
            self._release(event.position(), "tablet")
        event.accept()


class CanvasView(QWidget):
    """InkCanvas with scrollbars that always allow scrolling past the ink."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = InkCanvas()
        self.vertical = QScrollBar(Qt.Orientation.Vertical)
        self.horizontal = QScrollBar(Qt.Orientation.Horizontal)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.canvas, 0, 0)
        layout.addWidget(self.vertical, 0, 1)
        layout.addWidget(self.horizontal, 1, 0)
        self._syncing = False
        self.canvas.view_changed.connect(self._sync)
        self.vertical.valueChanged.connect(self._scrolled)
        self.horizontal.valueChanged.connect(self._scrolled)
        self._sync()

    def _sync(self):
        canvas = self.canvas
        zoom = canvas.zoom
        content = canvas.content_rect()
        ox, oy = canvas.offset()
        width, height = canvas.width(), canvas.height()
        self._syncing = True
        try:
            for bar, origin, extent, view in ((self.horizontal, ox, content.right(), width),
                                              (self.vertical, oy, content.bottom(), height)):
                # Keep half a screen of empty paper beyond the ink and the view.
                limit = max(extent * zoom, (origin * zoom) + view) + view / 2 - view
                bar.setRange(0, max(0, math.ceil(limit)))
                bar.setPageStep(view)
                bar.setSingleStep(InkCanvas.WHEEL_STEP)
                bar.setValue(round(origin * zoom))
        finally:
            self._syncing = False

    def _scrolled(self):
        if not self._syncing:
            zoom = self.canvas.zoom
            self.canvas.scroll_to(self.horizontal.value() / zoom, self.vertical.value() / zoom)
