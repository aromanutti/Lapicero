"""Infinite ink surface; stored coordinates are logical document units.

The view shows the document from ``offset`` (top-left, never negative) at
``zoom``. The document grows right and down without limit.
"""

import json
import math
import struct
import sys
import time
from array import array
from itertools import chain

from PySide6.QtCore import (QBuffer, QByteArray, QDataStream, QIODevice, QMimeData, QPointF, QRectF, Qt,
                            QEvent, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform,
                           QPixmap, QPointingDevice, QPolygonF)
from PySide6.QtWidgets import QApplication, QGridLayout, QScrollBar, QWidget

from .model import Note, NoteFormatError, PlacedImage, Stroke, pressure_width
from .shapes import DIAGRAM_KINDS, SHAPE_KINDS, diagram_strokes, edit_shape, normalize_shape, shape_points


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
CURSOR_ALPHA = 110  # Pen-tip cursor: a translucent dot in the ink color, like OneNote.
MIN_CURSOR_DOT = 4.0  # Pixels, so thin pens and far zoom still show a tip.
MAX_CURSOR = 128


def tip_cursor(color, diameter, ring=False):
    """A dot (pens, shapes) or ring (eraser) of ``diameter`` screen pixels, hotspot in the center."""
    diameter = max(MIN_CURSOR_DOT, min(float(diameter), MAX_CURSOR - 4))
    side = math.ceil(diameter) + 4
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    center = QPointF(side / 2, side / 2)
    if ring:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 200), 3))
        painter.drawEllipse(center, diameter / 2, diameter / 2)
        painter.setPen(QPen(QColor(60, 60, 60, 220), 1.2))
        painter.drawEllipse(center, diameter / 2, diameter / 2)
    else:
        tint = qcolor(color[:7])
        tint.setAlpha(CURSOR_ALPHA)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawEllipse(center, diameter / 2, diameter / 2)
    painter.end()
    return QCursor(pixmap, side // 2, side // 2)
SELECTION_COLOR = "#2f7de1"
ASK_COLOR = "#2f4fd8"  # The theme accent: the region a question is about.


def pressure_samples(points, pressures, width, first, last):
    """Discs (center, radius) along the smoothed curve of InkCanvas._path.

    Segment i (1-based) runs from the midpoint before points[i] to the one after
    it, with points[i] as control. Returns the start of segment `first` plus two
    samples per segment up to `last`, so consecutive ranges join seamlessly.
    """
    radius = lambda p: pressure_width(width, p) / 2
    n = len(points)

    def boundary(i):  # Start of segment i (= end of segment i - 1).
        if i <= 1:
            return points[0], pressures[0]
        if i >= n:
            return points[-1], pressures[-1]
        return (((points[i - 1][0] + points[i][0]) / 2, (points[i - 1][1] + points[i][1]) / 2),
                (pressures[i - 1] + pressures[i]) / 2)

    start, start_p = boundary(first)
    samples = [(start, radius(start_p))]
    for i in range(first, last + 1):
        control, control_p = points[i], pressures[i]
        end, end_p = boundary(i + 1)
        for t in (.5, 1.0):
            a, b, c = (1 - t) ** 2, 2 * t * (1 - t), t * t
            samples.append(((a * start[0] + b * control[0] + c * end[0],
                             a * start[1] + b * control[1] + c * end[1]),
                            radius(a * start_p + b * control_p + c * end_p)))
        start, start_p = end, end_p
    return samples


def new_outline_path():
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    return path


OUTLINE_TOLERANCE = .03  # Largest gap, in document units, between a round cap and its polygon.


INNER_PIVOT = .35  # Radians: sharper inner bends pivot on the disc center.


def _arc(points, center, r, start, sweep):
    """Append the arc after its start point: from angle start, turning by sweep."""
    step = 2 * math.acos(max(-1.0, 1 - OUTLINE_TOLERANCE / r)) if r > OUTLINE_TOLERANCE else math.pi / 2
    n = max(1, math.ceil(abs(sweep) / step))
    cx, cy, cos, sin = center[0], center[1], math.cos, math.sin
    for k in range(1, n + 1):
        angle = start + sweep * k / n
        points.append((cx + r * cos(angle), cy + r * sin(angle)))


def _polygon(points):
    """QPolygonF from (x, y) tuples, read in bulk: one QPointF per vertex from
    Python cost more than all the outline math."""
    coordinates = array("d", chain.from_iterable(points))
    if sys.byteorder == "big":
        coordinates.byteswap()
    data = QByteArray(struct.pack("<I", len(points)) + coordinates.tobytes())  # Must outlive the stream.
    stream = QDataStream(data, QIODevice.OpenModeFlag.ReadOnly)
    stream.setByteOrder(QDataStream.ByteOrder.LittleEndian)
    stream.setFloatingPointPrecision(QDataStream.FloatingPointPrecision.DoublePrecision)
    polygon = QPolygonF()
    stream >> polygon
    return polygon


def _turn(angle):
    """An angle difference folded into (-pi, pi]."""
    return angle - 2 * math.pi * math.ceil((angle - math.pi) / (2 * math.pi))


def outline_polygon(samples):
    """One closed polygon covering discs at samples joined by tangent hulls.

    It follows the left tangents forward, around the last disc, back along the
    right tangents and around the first disc, always turning the same way, with
    round arcs on the outside of bends. Inside a bend the tangents cross and
    loop with the same orientation, so the nonzero fill keeps them solid. One
    polygon per stroke fills much faster than a union of hundreds of discs.
    """
    kept = []
    for center, r in samples:  # Drop discs inside a neighbor; their hulls are covered too.
        if kept and math.dist(kept[-1][0], center) <= r - kept[-1][1]:
            kept.pop()
            while kept and math.dist(kept[-1][0], center) <= r - kept[-1][1]:
                kept.pop()
        if kept and math.dist(kept[-1][0], center) <= kept[-1][1] - r:
            continue
        kept.append((center, r))
    if len(kept) == 1:
        (center, r), = kept
        points = [(center[0] + r, center[1])]
        _arc(points, center, r, 0.0, -2 * math.pi)
        return _polygon(points)
    atan2, acos, dist, cos, sin = math.atan2, math.acos, math.dist, math.cos, math.sin
    edges = [(atan2(b[1] - a[1], b[0] - a[0]), acos((ra - rb) / dist(a, b)))
             for (a, ra), (b, rb) in zip(kept, kept[1:])]  # Tangent (theta, phi) per hull.
    theta, phi = edges[0]
    (cx, cy), r = kept[0]
    left = [(cx + r * cos(theta + phi), cy + r * sin(theta + phi))]
    right = [(cx + r * cos(theta - phi), cy + r * sin(theta - phi))]
    last = len(kept) - 1
    for i in range(1, last + 1):
        (cx, cy), r = kept[i]
        theta, phi = edges[i - 1]
        left_in, right_in = theta + phi, theta - phi
        left.append((cx + r * cos(left_in), cy + r * sin(left_in)))
        right.append((cx + r * cos(right_in), cy + r * sin(right_in)))
        if i == last:
            break
        theta, phi = edges[i]
        # Outside a bend the tangents part: round it. Inside they cross and loop
        # with the outline's own orientation, which stays filled; sharp inner
        # bends pivot on the center, like a stroker's inner join.
        for side, start, end, outward in ((left, left_in, theta + phi, -1), (right, right_in, theta - phi, 1)):
            sweep = _turn(end - start)
            if abs(sweep) * r <= OUTLINE_TOLERANCE:
                continue  # Both tangents meet at one point, within tolerance.
            if sweep * outward > 0:
                _arc(side, (cx, cy), r, start, sweep)
            else:
                if -sweep * outward > INNER_PIVOT:
                    side.append((cx, cy))
                side.append((cx + r * cos(end), cy + r * sin(end)))
    theta, phi = edges[-1]
    _arc(left, kept[-1][0], kept[-1][1], theta + phi, -2 * phi)  # Around the end, to the right tangent.
    left.extend(reversed(right[:-1]))
    theta, phi = edges[0]
    _arc(left, kept[0][0], kept[0][1], theta - phi, -(2 * math.pi - 2 * phi))  # Around the start, back.
    return _polygon(left)


def add_outline(path, samples):
    """Add the closed outline of consecutive pressure samples to a path."""
    path.addPolygon(outline_polygon(samples))
    path.closeSubpath()
    return path


def pressure_outline(stroke):
    """Filled outline of a pressure stroke along the smoothed curve of InkCanvas._path."""
    points = stroke.points
    return add_outline(new_outline_path(),
                       pressure_samples(points, stroke.pressures, stroke.width, 1, len(points) - 1))


def clamp_pressure(pressure):
    """0..1 tablet pressure, or None for missing or non-finite readings."""
    if pressure is None or not math.isfinite(pressure):
        return None
    return max(0.0, min(1.0, pressure))


def ink_width(stroke):
    """Widest painted width of a stroke, including pressure."""
    if stroke.pressures is None:
        return stroke.width
    return pressure_width(stroke.width, max(stroke.pressures))


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
    region_requested = Signal(QRectF)  # Ask tool: a document rectangle the user dragged.
    HOLD_MS = 500
    MOUSE_SUPPRESSION_SECONDS = .15
    ERASER_RADIUS = 10
    GRID = 24
    MIN_ZOOM, MAX_ZOOM = .25, 4.0
    WHEEL_STEP = 60
    MODES = ("pen", "eraser", "select", "shape", "ask")
    MIN_ASK_SIDE = 8.0  # Smallest ask rectangle side, in screen pixels.
    SHAPES = SHAPE_KINDS
    DIAGRAMS = DIAGRAM_KINDS  # Engineering elements: drawn like shapes, as several strokes.
    TILE = 256  # Side of a cached page tile, in widget pixels.
    MAX_TILES = 128  # Cached tiles kept; the farthest from the view are dropped first.
    EDGE_MARGIN = 48  # Widget pixels from an edge where dragging scrolls the view.
    EDGE_SPEED = 900  # Widget pixels per second at the very edge (or beyond it).

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
        self._pressures = None  # Pen pressure per point, for tablet pen strokes.
        self._live = None  # Outline cache of the stroke being drawn (see _live_outline).
        self.pressure_enabled = True  # Pens use pressure; highlighters turn it off.
        self._ink_color = None
        self._ink_width = None
        self._snapped = None
        self._snap = None  # (kind, clean points, pen point) while a snapped shape is held.
        self._source = None
        self._last_erase = None
        self._erase_changed = False
        self._lasso = None
        self._move_from = None
        self._shape_start = None
        self._shape_end = None
        self._shape_extra = []  # Strokes after the first of a multi-stroke diagram.
        self.pending_region = None  # Ask tool: region kept marked while its question is typed.
        self._pan_from = None
        self._cache = {}
        self._centerlines = {}  # Halo paths of pressure strokes (see _centerline).
        self._boxes = {}  # Culling bounds per stroke (see _box), without building outlines.
        self._paste_count = 0
        self._handle = None  # Grabbed selection handle (see HANDLES, or "rotate").
        # While dragging a selection, its cached ink is drawn through _drag_transform;
        # transformed strokes are only built once, on release.
        self._drag_point = None
        self._drag_transform = None
        self._drag_geometry = None
        self._drag_frame = None
        self._shift = False
        # Items whose preview must match the result exactly: pictures always, and
        # pressure ink while scaling (a mapped outline would scale its thickness).
        self._drag_rebuilt = {}
        self._drag_scaling = False
        # Optional Library-like object: store_image(bytes) -> key, image_path(key) -> Path.
        self.image_store = None
        self._pixmaps = {}
        # Paper, pictures and settled ink, pre-rendered in TILE-sized squares of the
        # zoomed document (see _sync_tiles). Repainting a page of pressure ink took
        # ~200 ms, so scrolling, erasing and the toolbar fade lagged.
        self._tiles = {}
        self._tile_key = None
        self._tile_strokes = ()
        self._tile_images = ()
        self._tile_excluded = frozenset()
        self._tablet_time = float("-inf")
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._hold_end)
        # Dragging a selection or a lasso near an edge scrolls the view that way (see _edge_tick).
        self._edge_pos = None
        self._edge_time = 0.0
        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(16)
        self._edge_timer.timeout.connect(self._edge_tick)
        self._apply_cursor()

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
        if self.mode in ("select", "ask"):
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.mode == "eraser":
            self.setCursor(tip_cursor(None, self.ERASER_RADIUS * 2 * self.zoom, ring=True))
        else:  # Pen and shapes: the tip, in the ink color and roughly the ink width.
            self.setCursor(tip_cursor(self.pen_color, self.pen_width * self.zoom))

    def set_shape(self, shape):
        if shape not in self.SHAPES + self.DIAGRAMS:
            raise ValueError("Unknown shape")
        self.shape = shape

    def _shape_polylines(self, start, end):
        if self.shape in self.DIAGRAMS:
            return diagram_strokes(self.shape, start, end)
        return (shape_points(self.shape, start, end),)

    def set_paper(self, paper):
        if paper not in ("plain", "grid"):
            raise ValueError("Unknown paper")
        self.paper = paper
        self.update()

    def set_pen_color(self, color):
        # Use Stroke's strict JSON-compatible color validation.
        Stroke(((0, 0),), color, 1)
        self.pen_color = color
        self._apply_cursor()

    def set_pen_width(self, width):
        Stroke(((0, 0),), "#202020", width)
        if not 1 <= width <= 40:
            raise ValueError("Pen width must be between 1 and 40")
        self.pen_width = float(width)
        self._apply_cursor()

    @property
    def gesture_active(self):
        return self._gesture is not None

    # View -------------------------------------------------------------------

    def offset(self):
        return (self._ox, self._oy)

    def to_widget(self, rect):
        """Widget rectangle of a document rectangle at the current scroll and zoom."""
        return QRectF((rect.x() - self._ox) * self.zoom, (rect.y() - self._oy) * self.zoom,
                      rect.width() * self.zoom, rect.height() * self.zoom)

    def set_pending_region(self, region):
        self.pending_region = QRectF(region) if region is not None else None
        self.update()

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
        self._apply_cursor()  # The tip follows the zoomed ink width.
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
            strokes = [Stroke(e["points"], e["color"], e["width"], e.get("pressures"))
                       for e in payload["strokes"]]
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
        return item.with_points((x + dx, y + dy) for x, y in item.points)

    def _geometry(self, items):
        """Bounds of the stroke points and picture corners (no pen width)."""
        points = [p for item in items for p in (
            self._image_corners(item) if isinstance(item, PlacedImage) else item.points)]
        xs, ys = [x for x, _ in points], [y for _, y in points]
        return QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))

    def _frame(self):
        """Dashed selection frame, following the selection while it is dragged."""
        items = self.selection
        pad = max([i.width / 2 for i in items if isinstance(i, Stroke)], default=0) + FRAME_PAD / self.zoom
        geometry = self._drag_geometry if self._drag_geometry is not None else self._geometry(items)
        if self._drag_transform is not None:
            geometry = self._drag_transform.mapRect(geometry)
        return geometry.adjusted(-pad, -pad, pad, pad)

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
        return item.with_points(fn(p) for p in item.points)

    def _drag_params(self, point):
        """(QTransform, point function, angle, scale) for dragging the grabbed
        handle (or the selection itself) from where it was pressed to point."""
        rect = self._drag_geometry
        transform = QTransform()
        if self._handle is None:
            dx, dy = point[0] - self._move_from[0], point[1] - self._move_from[1]
            transform.translate(dx, dy)
            return transform, lambda p: (p[0] + dx, p[1] + dy), 0.0, (1.0, 1.0)
        if self._handle == "rotate":
            cx, cy = rect.center().x(), rect.center().y()
            start = math.atan2(self._move_from[1] - cy, self._move_from[0] - cx)
            degrees = math.degrees(math.atan2(point[1] - cy, point[0] - cx) - start)
            if self._shift:
                degrees = round(degrees / SNAP_DEGREES) * SNAP_DEGREES
            a = math.radians(degrees)
            cos, sin = math.cos(a), math.sin(a)
            transform.translate(cx, cy)
            transform.rotate(degrees)
            transform.translate(-cx, -cy)
            return transform, (lambda p: (cx + (p[0] - cx) * cos - (p[1] - cy) * sin,
                                          cy + (p[0] - cx) * sin + (p[1] - cy) * cos)), degrees, (1.0, 1.0)
        hx, hy = HANDLES[self._handle]
        scales = []
        for direction, extent, moved in ((hx, rect.width(), point[0] - self._move_from[0]),
                                         (hy, rect.height(), point[1] - self._move_from[1])):
            if not direction or extent < 1e-6:
                scales.append(1.0)
            else:
                scales.append(max(extent + direction * moved, MIN_EXTENT) / extent)
        sx, sy = scales
        pictures_only = all(isinstance(item, PlacedImage) for item in self.selection)
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
        transform.translate(ax, ay)
        transform.scale(sx, sy)
        transform.translate(-ax, -ay)
        return transform, lambda p: (ax + (p[0] - ax) * sx, ay + (p[1] - ay) * sy), 0.0, (sx, sy)

    def _begin_drag(self, point, handle):
        self._handle, self._move_from = handle, point
        self._drag_geometry = self._geometry(self.selection)
        self._drag_frame = self._frame()

    def _drag_area(self, transform=None, items=()):
        """Document area covered by the dragged selection, its frame, handles,
        halo, and any exactly rebuilt items."""
        transform = transform if transform is not None else self._drag_transform
        rect = self._drag_frame if transform is None else transform.mapRect(self._drag_frame)
        for item in items:
            rect = rect.united(self._item_rect(item))
        ink = max([ink_width(i) for i in self.selection if isinstance(i, Stroke)], default=0)
        margin = (ROTATE_OFFSET + 2 * HANDLE_REACH) / self.zoom + ink + 8
        return rect.adjusted(-margin, -margin, margin, margin)

    def _rebuild_for_preview(self, params):
        transform, fn, angle, scale = params
        self._drag_scaling = scale != (1.0, 1.0)
        return {id(item): self._transformed(item, fn, angle, scale) for item in self.selection
                if isinstance(item, PlacedImage)}

    def _paint_pressure_preview(self, painter, stroke, transform):
        """Scaled pressure ink while dragging: each segment at its own pressure
        width. Mapping the outline would scale its thickness too, and rebuilding
        outlines on every pointer move made scaling a sentence lag."""
        points = [transform.map(QPointF(*p)) for p in stroke.points]
        color = qcolor(stroke.color)
        for a, b, pa, pb in zip(points, points[1:], stroke.pressures, stroke.pressures[1:]):
            painter.setPen(QPen(color, pressure_width(stroke.width, (pa + pb) / 2), Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(a, b)

    def _update_area(self, area):
        self.update(QRectF((area.x() - self._ox) * self.zoom, (area.y() - self._oy) * self.zoom,
                           area.width() * self.zoom, area.height() * self.zoom).toAlignedRect())

    def _drag_to(self, point):
        before = self._drag_area(items=self._drag_rebuilt.values())
        params = self._drag_params(point)
        self._drag_point = point
        self._drag_transform = params[0]
        self._drag_rebuilt = self._rebuild_for_preview(params)
        self._update_area(before.united(self._drag_area(items=self._drag_rebuilt.values())))

    def _commit_drag(self):
        """Transformed copies of the selection; reuse cached ink for exact maps."""
        transform, fn, angle, scale = self._drag_params(self._drag_point)
        items = []
        for item in self.selection:
            new = self._transformed(item, fn, angle, scale)
            if isinstance(item, Stroke) and (item.pressures is None or scale == (1.0, 1.0)):
                # Affine maps keep centre-line curves exact; pressure outlines stay
                # exact only for moves and rotations (scaling would stretch thickness).
                path, bounds = self._entry(item)
                self._cache[id(new)] = (new, transform.map(path), transform.mapRect(bounds))
            items.append(new)
        return items

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
            stroke = (Stroke(self._snapped, self._ink_color, self._ink_width) if self._snapped is not None
                      else self._ink_stroke(self._points))
        moved = None
        dragged_area = None
        if self._drag_point is not None:
            # Where the selection was, was last shown, and lands: nothing else changes.
            dragged_area = self._drag_area(QTransform()).united(
                self._drag_area(items=self._drag_rebuilt.values()))
            dragged = self._commit_drag()
            # Cover where everything lands, not only the mapped frame.
            dragged_area = dragged_area.united(self._drag_area(QTransform(), dragged))
            mapping = {id(old): new for old, new in zip(self.selection, dragged)}
            moved = ([mapping.get(id(s), s) for s in note.strokes],
                     [mapping.get(id(i), i) for i in note.images])
            self.selection = dragged
        new_shape = self._gesture == "shape"
        extra = [self._ink_stroke(points) for points in self._shape_extra] if stroke is not None else []
        ink_only = self._gesture == "pen" and moved is None
        # The live preview may differ from the committed ink (a snapped shape).
        drawn = (QPolygonF([QPointF(*q) for q in self._points]).boundingRect()
                 if ink_only and self._points else QRectF())
        self._stop_gesture(repaint=not ink_only and dragged_area is None)
        if dragged_area is not None:
            self._update_area(dragged_area)
        if stroke is not None and (note.replace([*note.strokes, stroke, *extra]) if extra
                                   else note.add_stroke(stroke)):
            if new_shape and note is self.note:
                self.selection = [stroke, *extra]  # Show the frame and handles right away.
            self.changed.emit()
        if ink_only:
            # Only the new ink changed; repainting a full page per stroke lagged.
            if stroke is not None:
                drawn = drawn.united(self._entry(stroke)[1])
            self._update_doc(drawn)
            return
        if moved is not None and note.replace(*moved):
            self.changed.emit()
        if dragged_area is None:
            self.update()

    def _edge_velocity(self, position):
        """(-1..1, -1..1): how hard a drag at position pushes past each edge of the view."""

        def axis(value, size):
            margin = min(self.EDGE_MARGIN, size / 4)
            if margin <= 0:
                return 0.0
            if value < margin:
                return -min(1.0, (margin - value) / margin)
            if value > size - margin:
                return min(1.0, (value - (size - margin)) / margin)
            return 0.0

        return axis(position.x(), self.width()), axis(position.y(), self.height())

    def _edge_follow(self, position):
        """Remember the drag position; scroll while it stays near an edge."""
        self._edge_pos = QPointF(position)
        if self._edge_velocity(position) == (0.0, 0.0):
            self._edge_timer.stop()
        elif not self._edge_timer.isActive():
            self._edge_time = time.monotonic()
            self._edge_timer.start()

    def _edge_tick(self):
        if self._gesture != "select" or self._edge_pos is None:
            self._edge_timer.stop()
            return
        vx, vy = self._edge_velocity(self._edge_pos)
        now = time.monotonic()
        step = self.EDGE_SPEED * min(now - self._edge_time, .05) / self.zoom
        self._edge_time = now
        before = self.offset()
        self.scroll_by(vx * step, vy * step)
        if self.offset() != before:
            # The pointer stayed put but the page moved under it: the drag follows.
            self._move(self._edge_pos, self._source, edge=True)

    def _stop_gesture(self, repaint=True):
        was_active = self._gesture is not None
        self._hold.stop()
        self._edge_timer.stop()
        self._edge_pos = None
        self.note.end_erase()
        self._gesture = None
        self._points = None
        self._pressures = None
        self._live = None
        self._snapped = None
        self._snap = None
        self._source = None
        self._last_erase = None
        self._lasso = None
        self._move_from = None
        self._handle = None
        self._drag_point = None
        self._drag_transform = None
        self._drag_geometry = None
        self._drag_frame = None
        self._drag_rebuilt = {}
        self._drag_scaling = False
        self._shape_start = None
        self._shape_end = None
        self._shape_extra = []
        if self._erase_changed:
            self._erase_changed = False
            self.changed.emit()
        if was_active:
            self.gesture_changed.emit(False)
        if repaint:
            self.update()

    def _ink_stroke(self, points):
        pressures = self._pressures if self._pressures is not None and len(self._pressures) == len(points) else None
        return Stroke(tuple(points), self._ink_color, self._ink_width, pressures)

    def _live_outline(self):
        """Outline of the stroke being drawn, built incrementally.

        Every curve segment except the last is final once the next point exists,
        so it is added to a cached path once; only the last segment is rebuilt
        per repaint. Rebuilding the whole outline on each pen sample made long
        strokes lag.
        """
        points, pressures, width = self._points, self._pressures, self._ink_width
        final = len(points) - 2
        if self._live is None:
            first = (points[0], pressure_width(width, pressures[0]) / 2)
            self._live = [0, add_outline(new_outline_path(), [first])]
        if self._live[0] < final:
            add_outline(self._live[1], pressure_samples(points, pressures, width, self._live[0] + 1, final))
            self._live[0] = final
        tail = pressure_samples(points, pressures, width, final + 1, len(points) - 1)
        return self._live[1], add_outline(new_outline_path(), tail)

    def _add_point(self, point, pressure):
        self._points.append(point)
        if self._pressures is not None:
            pressure = clamp_pressure(pressure)
            self._pressures.append(self._pressures[-1] if pressure is None else pressure)

    def _press(self, position, source, eraser_tip=False, pressure=None):
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
                self._begin_drag(point, handle)
            elif self.selection and self._frame().contains(QPointF(*point)):
                self._begin_drag(point, None)
            else:
                self.clear_selection()
                self._lasso = [point]
        elif self._gesture in ("shape", "ask"):
            self.clear_selection()
            self._shape_start = point
            self._ink_color, self._ink_width = self.pen_color, self.pen_width
        else:
            self._points = [point]
            pressure = clamp_pressure(pressure)
            self._pressures = [pressure] if pressure is not None and self.pressure_enabled else None
            self._live = None
            self._ink_color, self._ink_width = self.pen_color, self.pen_width
            self._hold.start(self.HOLD_MS)
            self._update_doc(QRectF(*point, 0, 0))

    def _move(self, position, source, pressure=None, edge=False):
        if source != self._source or self._gesture is None:
            return
        point = self.to_document(position)
        if self._gesture == "eraser":
            if self._last_erase is not None:
                self._erase(point)
        elif self._gesture == "select":
            if self._move_from is not None:
                self._drag_to(point)
            elif self._lasso is not None:
                self._lasso.append(point)
                self.update()
            if not edge:
                self._edge_follow(position)
        elif self._gesture in ("shape", "ask"):
            self._shape_end = point
            self.update()
        elif self._snap is not None:
            self._edit_snap(point)
        elif self._points is not None and point != self._points[-1]:
            previous = self._points[-1]
            self._add_point(point, pressure)
            self._hold.start(self.HOLD_MS)
            self._update_doc(QRectF(QPointF(*previous), QPointF(*point)).normalized())

    def _release(self, position, source, pressure=None):
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
                self._drag_point = point
        elif self._gesture == "ask":
            start = self._shape_start
            region = QRectF(QPointF(*start), QPointF(*point)).normalized()
            self._stop_gesture()
            side = self.MIN_ASK_SIDE / self.zoom
            if region.width() >= side and region.height() >= side:
                self.region_requested.emit(region)
            return
        elif self._gesture == "shape":
            start = self._shape_start
            if math.dist(start, point) > 2:
                first, *rest = self._shape_polylines(start, point)
                self._points = list(first)
                self._shape_extra = rest
                self._snapped = None
        elif self._snap is not None:
            self._edit_snap(point)
        elif self._points is not None and point != self._points[-1]:
            self._add_point(point, pressure)
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
                # Keep holding to edit: the shape now follows the pen instead of new ink.
                self._snap = (result[0], result[1], self._points[-1])
                self.update()

    def _edit_snap(self, point):
        kind, clean, anchor = self._snap
        self._snapped = edit_shape(kind, clean, anchor, point)
        self.update()

    # Erasing ----------------------------------------------------------------

    @classmethod
    def _hits_rendered(cls, stroke, x, y, radius):
        # Cover the round pen (or dot) and the antialiased edge of its pixels.
        reach = radius + ink_width(stroke) / 2 + .5
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
                lambda stroke: self._box(stroke).adjusted(-reach, -reach, reach, reach).contains(x, y)
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
            pressured = stroke.pressures is not None and len(stroke.points) > 1
            path = pressure_outline(stroke) if pressured else self._path(stroke)
            half = 1 if pressured else stroke.width / 2 + 1
            bounds = path.boundingRect().adjusted(-half, -half, half, half)
            entry = (stroke, path, bounds)
            self._cache[id(stroke)] = entry
        return entry[1:]

    def _box(self, stroke):
        """Generous bounds for culling, from the points alone: the smoothed curve
        stays inside their box. Opening a page no longer builds every outline."""
        entry = self._boxes.get(id(stroke))
        if entry is None or entry[0] is not stroke:
            xs, ys = [p[0] for p in stroke.points], [p[1] for p in stroke.points]
            reach = ink_width(stroke) / 2 + 6  # Antialiased edge plus the usual 5 unit margin.
            entry = (stroke, QRectF(min(xs) - reach, min(ys) - reach,
                                    max(xs) - min(xs) + 2 * reach, max(ys) - min(ys) + 2 * reach))
            self._boxes[id(stroke)] = entry
        return entry[1]

    def _centerline(self, stroke):
        """Simple centre-line path for the halo. Stroking a pressure outline
        (hundreds of discs) with a wide pen cost milliseconds per stroke and
        made dragging a selected sentence lag."""
        if stroke.pressures is None or len(stroke.points) == 1:
            return self._entry(stroke)[0]
        entry = self._centerlines.get(id(stroke))
        if entry is None or entry[0] is not stroke:
            entry = (stroke, self._path(stroke))
            self._centerlines[id(stroke)] = entry
        return entry[1]

    def _paint_stroke(self, painter, stroke, path=None):
        color = qcolor(stroke.color)
        if len(stroke.points) == 1:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            radius = ink_width(stroke) / 2
            painter.drawEllipse(QPointF(*stroke.points[0]), radius, radius)
            return
        if stroke.pressures is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(path if path is not None else pressure_outline(stroke))
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

    def _paint_images(self, painter, exposed, images):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for image in images:
            if exposed is not None and not self._item_rect(image).intersects(exposed):
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
            radius = ink_width(stroke) / 2 + 4
            painter.drawEllipse(QPointF(*stroke.points[0]), radius, radius)
            return
        painter.setPen(QPen(HALO_COLOR, ink_width(stroke) + 8, Qt.PenStyle.SolidLine,
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
        if self._drag_transform is not None and self._handle is not None:
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

    # Page tiles ---------------------------------------------------------------

    def _origin(self):
        """Whole-pixel view offset in the zoomed document, so tiles blit exactly."""
        return round(self._ox * self.zoom), round(self._oy * self.zoom)

    def _tile_rect(self, tx, ty):
        size = self.TILE / self.zoom
        return QRectF(tx * size, ty * size, size, size)

    def _tile_painter(self, device, tx, ty):
        painter = QPainter(device)
        painter.translate(-tx * self.TILE, -ty * self.TILE)
        painter.scale(self.zoom, self.zoom)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        return painter

    def _cached_items(self):
        """Ink and pictures drawn live instead: selected ink (its halo lies under
        it) and, while dragging, the whole selection."""
        dragging = self._drag_transform is not None
        return frozenset(id(item) for item in self.selection if dragging or isinstance(item, Stroke))

    def _render_tile(self, tx, ty, dpr):
        pixmap = QPixmap(round(self.TILE * dpr), round(self.TILE * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.white)
        painter = self._tile_painter(pixmap, tx, ty)
        rect = self._tile_rect(tx, ty)
        if self.paper == "grid":
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            self._paint_grid(painter, rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        excluded = self._tile_excluded
        self._paint_images(painter, rect, [i for i in self._tile_images if id(i) not in excluded])
        for stroke in self._tile_strokes:
            if id(stroke) not in excluded and self._box(stroke).intersects(rect):
                self._paint_stroke(painter, stroke, self._entry(stroke)[0])
        painter.end()
        return pixmap

    def _tiles_over(self, rect):
        """Keys of cached tiles intersecting a document rectangle."""
        size = self.TILE / self.zoom
        pad = 2 / self.zoom  # Antialiased edges.
        xs = range(math.floor((rect.left() - pad) / size), math.floor((rect.right() + pad) / size) + 1)
        ys = range(math.floor((rect.top() - pad) / size), math.floor((rect.bottom() + pad) / size) + 1)
        return [key for key in self._tiles if key[0] in xs and key[1] in ys]

    def _item_bounds(self, item):
        return self._box(item) if isinstance(item, Stroke) else self._item_rect(item)

    def _sync_tiles(self, dpr):
        """Bring cached tiles up to date with the note, by identity of its items.

        Appended ink is drawn onto existing tiles; any other change drops only
        the tiles under the items that came, went or changed live/cached side.
        """
        key = (self.zoom, self.paper, dpr, id(self.note), id(self.image_store))
        strokes, images = tuple(self.note.strokes), tuple(self.note.images)
        excluded = self._cached_items()
        old_strokes, old_images = self._tile_strokes, self._tile_images
        same = lambda a, b: len(a) == len(b) and all(x is y for x, y in zip(a, b))
        if key != self._tile_key:
            self._tiles.clear()
        elif same(strokes, old_strokes) and same(images, old_images) and excluded == self._tile_excluded:
            return
        elif (excluded == self._tile_excluded and same(images, old_images)
              and same(strokes[:len(old_strokes)], old_strokes)):
            added = [s for s in strokes[len(old_strokes):] if id(s) not in excluded]
            for stroke in added:
                path, bounds = self._entry(stroke)
                for tx, ty in self._tiles_over(bounds.adjusted(-5, -5, 5, 5)):
                    painter = self._tile_painter(self._tiles[tx, ty], tx, ty)
                    self._paint_stroke(painter, stroke, path)
                    painter.end()
        else:
            old = {id(item): item for item in (*old_strokes, *old_images)}
            new = {id(item): item for item in (*strokes, *images)}
            changed = (old.keys() ^ new.keys()) | (excluded ^ self._tile_excluded)
            if not changed:
                self._tiles.clear()  # Same items, new order.
            for identity in changed:
                item = new.get(identity, old.get(identity))
                if item is not None:
                    for tile in self._tiles_over(self._item_bounds(item)):
                        del self._tiles[tile]
        self._tile_key, self._tile_strokes, self._tile_images = key, strokes, images
        self._tile_excluded = excluded

    def _paint_tiles(self, painter, area):
        """Blit (rendering when missing) the tiles under a widget rectangle."""
        dpr = self.devicePixelRatioF()
        self._sync_tiles(dpr)
        bx, by = self._origin()
        size = self.TILE
        xs = range((area.left() + bx) // size, (area.right() + bx) // size + 1)
        ys = range((area.top() + by) // size, (area.bottom() + by) // size + 1)
        for ty in ys:
            for tx in xs:
                tile = self._tiles.get((tx, ty))
                if tile is None:
                    tile = self._tiles[tx, ty] = self._render_tile(tx, ty, dpr)
                painter.drawPixmap(tx * size - bx, ty * size - by, tile)
        if len(self._tiles) > self.MAX_TILES:
            cx, cy = (bx + self.width() / 2) / size, (by + self.height() / 2) / size
            far = sorted(self._tiles, key=lambda k: (k[0] + .5 - cx) ** 2 + (k[1] + .5 - cy) ** 2)
            for tile in far[self.MAX_TILES:]:
                del self._tiles[tile]

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
        area = event.rect()
        live = {id(s) for s in self.note.strokes}
        if len(self._cache) > len(live) + 256:
            self._cache = {key: value for key, value in self._cache.items() if key in live}
            self._centerlines = {key: value for key, value in self._centerlines.items() if key in live}
            self._boxes = {key: value for key, value in self._boxes.items() if key in live}
        self._paint_tiles(painter, area)
        bx, by = self._origin()
        painter.translate(-bx, -by)
        painter.scale(self.zoom, self.zoom)
        exposed = QRectF((area.x() + bx) / self.zoom, (area.y() + by) / self.zoom,
                         area.width() / self.zoom, area.height() / self.zoom)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        drag = self._drag_transform
        selected = {id(item) for item in self.selection}
        if drag is not None:
            # Pictures preview exactly as they will be committed (a skewing
            # transform would slant a rotated picture).
            self._paint_images(painter, exposed, [self._drag_rebuilt[id(i)] for i in self.selection
                                                  if isinstance(i, PlacedImage) and id(i) in self._drag_rebuilt])
        elif selected:
            for stroke in self.note.strokes:  # Selected ink is live: its halo lies under it.
                if id(stroke) in selected and self._box(stroke).intersects(exposed):
                    self._paint_halo(painter, stroke, self._centerline(stroke))
                    self._paint_stroke(painter, stroke, self._entry(stroke)[0])
        if drag is not None:
            # Cached ink mapped through the drag: no stroke is rebuilt per pointer move.
            for stroke in self.selection:
                if isinstance(stroke, Stroke) and len(stroke.points) == 1:
                    dot = drag.map(QPointF(*stroke.points[0]))
                    moved = stroke.with_points([(dot.x(), dot.y())])  # A dot has no path to map.
                    self._paint_halo(painter, moved, None)
                    self._paint_stroke(painter, moved)
                elif isinstance(stroke, Stroke) and self._drag_scaling and stroke.pressures is not None:
                    self._paint_halo(painter, stroke, drag.map(self._centerline(stroke)))
                    self._paint_pressure_preview(painter, stroke, drag)
                elif isinstance(stroke, Stroke):
                    path, bounds = self._entry(stroke)
                    if drag.mapRect(bounds).adjusted(-5, -5, 5, 5).intersects(exposed):
                        self._paint_halo(painter, stroke, drag.map(self._centerline(stroke)))
                        self._paint_stroke(painter, stroke, drag.map(path))
        if self._points is not None:
            if self._snapped is None and self._pressures is not None and len(self._points) > 1:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(qcolor(self._ink_color))
                for path in self._live_outline():
                    painter.drawPath(path)
            else:
                self._paint_stroke(painter, self._ink_stroke(self._snapped or self._points))
        elif self._gesture == "ask" and self._shape_start is not None and self._shape_end is not None:
            dash = QPen(QColor(SELECTION_COLOR), 1.5, Qt.PenStyle.DashLine)
            dash.setCosmetic(True)
            painter.setPen(dash)
            painter.setBrush(QColor(47, 125, 225, 30))
            painter.drawRect(QRectF(QPointF(*self._shape_start), QPointF(*self._shape_end)).normalized())
        elif self._shape_start is not None and self._shape_end is not None:
            for points in self._shape_polylines(self._shape_start, self._shape_end):
                self._paint_stroke(painter, self._ink_stroke(points))
        if self.pending_region is not None:
            dash = QPen(QColor(ASK_COLOR), 2, Qt.PenStyle.DashLine)
            dash.setCosmetic(True)
            painter.setPen(dash)
            painter.setBrush(QColor(47, 79, 216, 18))
            painter.drawRoundedRect(self.pending_region, 6 / self.zoom, 6 / self.zoom)
        if self.selection:
            self._paint_frame(painter)
        if self._lasso is not None and len(self._lasso) > 1:
            dash = QPen(QColor(SELECTION_COLOR), 1, Qt.PenStyle.DashLine)
            dash.setCosmetic(True)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(dash)
            painter.drawPolyline(QPolygonF([QPointF(*p) for p in self._lasso]))

    def render_region(self, rect, scale=1.0):
        """Paint paper, pictures and ink inside a document rectangle into a new image.

        Selection frames, halos and live gestures are left out: the image shows
        the page as stored. ``scale`` is image pixels per document unit.
        """
        rect = QRectF(rect)
        if rect.width() <= 0 or rect.height() <= 0 or not scale > 0:
            raise ValueError("Render needs a non-empty rectangle and a positive scale")
        width = max(1, math.ceil(rect.width() * scale))
        height = max(1, math.ceil(rect.height() * scale))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        try:
            painter.scale(scale, scale)
            painter.translate(-rect.x(), -rect.y())
            if self.paper == "grid" and self.GRID * scale >= 3:  # Denser lines would be a gray wash.
                self._paint_grid(painter, rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._paint_images(painter, rect, self.note.images)
            for stroke in self.note.strokes:
                path, bounds = self._entry(stroke)
                if bounds.adjusted(-5, -5, 5, 5).intersects(rect):
                    self._paint_stroke(painter, stroke, path)
        finally:
            painter.end()
        return image

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
        reader = getattr(event, "pressure", None)
        pressure = reader() if reader is not None else None
        if event.type() == QEvent.Type.TabletPress:
            if self._source == "mouse":
                self._stop_gesture()
            pointer = getattr(event, "pointerType", None)
            eraser_tip = pointer is not None and pointer() == QPointingDevice.PointerType.Eraser
            self._press(event.position(), "tablet", eraser_tip, pressure)
        elif event.type() == QEvent.Type.TabletMove:
            self._move(event.position(), "tablet", pressure)
        else:
            self._release(event.position(), "tablet", pressure)
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
