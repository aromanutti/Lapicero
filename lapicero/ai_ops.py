"""Operations AI tools may run on the open library (always on the Qt main thread)."""

import base64
import inspect
import math
from uuid import uuid4

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF

from .bridge import BridgeError
from .ink_text import text_strokes
from .model import NoteFormatError, Stroke
from .qt_canvas import InkCanvas
from .shapes import SHAPE_KINDS, shape_points


MAX_SIDE = 1600  # Longest side of a rendered page image, in pixels.
MAX_SCALE = 2.0
MAX_REGION = 20000.0  # Longest side of a rendered rectangle, in document units.
MAX_STROKES = 2000
MAX_POINTS = 5000
CONTENT_PAD = 24.0
BLANK_PAGE = QRectF(0, 0, 800, 600)
DEFAULT_COLOR = "#205bb5"


def png_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def _number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise BridgeError(f"{name} must be a finite number")
    return float(value)



def _section_listing(section):
    return {"id": section.id, "name": section.name,
            "pages": [{"id": page.id, "name": page.name, "strokes": len(page.note.strokes),
                       "pictures": len(page.note.images)} for page in section.pages],
            "sections": [_section_listing(child) for child in section.sections]}

class AiOperations:
    """Read and write pages of a LapiceroWindow on behalf of AI tools.

    Writes become ordinary ink: one undo step per call, and autosaved like the
    user's own strokes.
    """

    def __init__(self, window):
        self.window = window
        self.asks = {}  # ask id -> {"question", "page_id", "region", "png"}

    # Dispatch ---------------------------------------------------------------

    def handle(self, method, params):
        operation = {"list_pages": self.list_pages, "read_page": self.read_page,
                     "write_text": self.write_text, "draw_strokes": self.draw_strokes,
                     "draw_shape": self.draw_shape, "get_ask": self.get_ask}.get(method)
        if operation is None:
            raise BridgeError(f"Unknown method {method!r}")
        try:
            inspect.signature(operation).bind(**params)
        except TypeError as exc:
            raise BridgeError(f"Invalid parameters for {method}: {exc}") from exc
        try:
            return operation(**params)
        except NoteFormatError as exc:
            raise BridgeError(str(exc)) from exc

    # Helpers ----------------------------------------------------------------

    @property
    def library(self):
        return self.window.library

    def _page(self, page_id):
        if page_id is None:
            page_id = self.window.current_page_id
            if page_id is None:
                raise BridgeError("No page is open in Lapicero; pass page_id (see list_pages)")
        if not isinstance(page_id, str):
            raise BridgeError("page_id must be a string")
        try:
            return self.library.page(page_id)
        except KeyError:
            raise BridgeError(f"No page with id {page_id!r}") from None

    def _canvas_for(self, page):
        """The live canvas when it shows this page, else an off-screen one."""
        canvas = self.window.canvas
        if page.note is canvas.note:
            return canvas
        canvas = InkCanvas(page.note)
        canvas.image_store = self.library
        canvas.paper = page.paper
        return canvas

    def render(self, page, rect, max_side=MAX_SIDE):
        scale = min(MAX_SCALE, max_side / max(rect.width(), rect.height()))
        return png_bytes(self._canvas_for(page).render_region(rect, scale)), scale

    def _add(self, page, strokes):
        if not strokes:
            raise BridgeError("Nothing to draw")
        note = page.note
        note.replace([*note.strokes, *strokes])  # One undo step for the whole call.
        if note is self.window.canvas.note:
            self.window.canvas.update()
        self.window.note_changed_externally()
        bounds = QRectF()
        for stroke in strokes:
            xs = [x for x, _ in stroke.points]
            ys = [y for _, y in stroke.points]
            bounds = bounds.united(QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
        return {"page_id": page.id, "strokes_added": len(strokes),
                "bounds": {"x": bounds.x(), "y": bounds.y(), "width": bounds.width(), "height": bounds.height()}}

    # Operations -------------------------------------------------------------

    def list_pages(self):
        return {"current_page_id": self.window.current_page_id,
                "subjects": [{"id": subject.id, "name": subject.name,
                              "sections": [_section_listing(section) for section in subject.sections]}
                             for subject in self.library.subjects]}

    def read_page(self, page_id=None, area="content", x=None, y=None, width=None, height=None):
        page = self._page(page_id)
        if any(v is not None for v in (x, y, width, height)):
            if any(v is None for v in (x, y, width, height)):
                raise BridgeError("Pass all of x, y, width and height, or none")
            rect = QRectF(_number(x, "x"), _number(y, "y"), _number(width, "width"), _number(height, "height"))
            if rect.width() <= 0 or rect.height() <= 0:
                raise BridgeError("width and height must be positive")
            if max(rect.width(), rect.height()) > MAX_REGION:
                raise BridgeError(f"width and height are limited to {MAX_REGION:g} document units")
        elif area == "view":
            if page.note is not self.window.canvas.note:
                raise BridgeError("area='view' needs the page to be open in Lapicero")
            rect = self.window.canvas.visible_rect()
        elif area == "content":
            canvas = self._canvas_for(page)
            content = canvas.content_rect()
            rect = (content.adjusted(-CONTENT_PAD, -CONTENT_PAD, CONTENT_PAD, CONTENT_PAD)
                    if not content.isEmpty() else QRectF(BLANK_PAGE))
            rect.setLeft(max(0.0, rect.left()))
            rect.setTop(max(0.0, rect.top()))
            # Huge pages are shown whole, just smaller (the image size is capped anyway).
            rect.setWidth(min(rect.width(), MAX_REGION))
            rect.setHeight(min(rect.height(), MAX_REGION))
        else:
            raise BridgeError("area must be 'content' or 'view'")
        png, scale = self.render(page, rect)
        return {"page_id": page.id, "page_name": page.name, "empty": not page.note.strokes and not page.note.images,
                "region": {"x": rect.x(), "y": rect.y(), "width": rect.width(), "height": rect.height()},
                "scale": scale, "png_base64": base64.b64encode(png).decode("ascii")}

    def write_text(self, text, x, y, size=24.0, color=DEFAULT_COLOR, max_width=None, page_id=None):
        page = self._page(page_id)
        if not isinstance(text, str):
            raise BridgeError("text must be a string")
        try:
            strokes = text_strokes(text, _number(x, "x"), _number(y, "y"), _number(size, "size"), color,
                                   None if max_width is None else _number(max_width, "max_width"))
        except ValueError as exc:
            raise BridgeError(str(exc)) from exc
        return self._add(page, strokes)

    def draw_strokes(self, strokes, page_id=None):
        page = self._page(page_id)
        if not isinstance(strokes, list) or not 0 < len(strokes) <= MAX_STROKES:
            raise BridgeError(f"strokes must be a list of 1 to {MAX_STROKES} strokes")
        built = []
        for entry in strokes:
            if not isinstance(entry, dict) or not isinstance(entry.get("points"), list):
                raise BridgeError("Each stroke needs a 'points' list of [x, y] pairs")
            if len(entry["points"]) > MAX_POINTS:
                raise BridgeError(f"A stroke is limited to {MAX_POINTS} points")
            built.append(Stroke(tuple(tuple(p) if isinstance(p, list) else p for p in entry["points"]),
                                entry.get("color", DEFAULT_COLOR), entry.get("width", 3.0)))
        return self._add(page, built)

    def draw_shape(self, kind, x1, y1, x2, y2, color=DEFAULT_COLOR, width=3.0, page_id=None):
        page = self._page(page_id)
        if kind not in SHAPE_KINDS:
            raise BridgeError(f"kind must be one of {', '.join(SHAPE_KINDS)}")
        points = shape_points(kind, (_number(x1, "x1"), _number(y1, "y1")), (_number(x2, "x2"), _number(y2, "y2")))
        return self._add(page, [Stroke(tuple(points), color, width)])

    # Ask Claude -------------------------------------------------------------

    def create_ask(self, page, region, question):
        ask_id = uuid4().hex[:12]
        png, scale = self.render(page, region)
        self.asks[ask_id] = {"question": question, "page_id": page.id, "page_name": page.name,
                             "region": {"x": region.x(), "y": region.y(),
                                        "width": region.width(), "height": region.height()},
                             "scale": scale, "png": png}
        return ask_id

    def get_ask(self, ask_id):
        ask = self.asks.get(ask_id) if isinstance(ask_id, str) else None
        if ask is None:
            raise BridgeError(f"No question with id {ask_id!r}")
        return {key: value for key, value in ask.items() if key != "png"} | {
            "png_base64": base64.b64encode(ask["png"]).decode("ascii")}
