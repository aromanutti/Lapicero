"""GUI-independent ink geometry and atomic local note storage."""

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import tempfile


class NoteFormatError(ValueError):
    """The file does not describe a supported note."""


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class Stroke:
    points: tuple[tuple[float, float], ...]
    color: str = "#202020"
    width: float = 3.0

    def __post_init__(self):
        if not self.points or any(
            not isinstance(point, (list, tuple))
            or len(point) != 2
            or not all(_number(n) for n in point)
            for point in self.points
        ):
            raise NoteFormatError("A stroke needs finite x/y points")
        if not isinstance(self.color, str) or len(self.color) not in (7, 9) or self.color[0] != "#" or any(
            c not in "0123456789abcdefABCDEF" for c in self.color[1:]
        ):
            raise NoteFormatError("Stroke color must be #RRGGBB or #RRGGBBAA")
        if not _number(self.width) or self.width <= 0:
            raise NoteFormatError("Stroke width must be positive and finite")
        object.__setattr__(self, "points", tuple((float(x), float(y)) for x, y in self.points))

    def to_data(self):
        return {"points": [list(p) for p in self.points], "color": self.color, "width": self.width}


IMAGE_KEY = re.compile(r"[0-9a-f]{64}\.png")


@dataclass(frozen=True)
class PlacedImage:
    """A pasted picture: a content-addressed PNG file name, its unrotated document
    rectangle, and a clockwise rotation in degrees about the rectangle's center."""

    key: str
    x: float
    y: float
    width: float
    height: float
    angle: float = 0.0

    def __post_init__(self):
        if not isinstance(self.key, str) or not IMAGE_KEY.fullmatch(self.key):
            raise NoteFormatError("Image key must be a SHA-256 PNG file name")
        if not all(_number(n) for n in (self.x, self.y, self.width, self.height, self.angle)):
            raise NoteFormatError("Image geometry must be finite numbers")
        if self.width <= 0 or self.height <= 0:
            raise NoteFormatError("Image size must be positive")
        for name in ("x", "y", "width", "height"):
            object.__setattr__(self, name, float(getattr(self, name)))
        angle = (float(self.angle) + 180.0) % 360.0 - 180.0
        object.__setattr__(self, "angle", 0.0 if abs(angle) < 1e-9 else angle)

    def to_data(self):
        data = {"key": self.key, "x": self.x, "y": self.y, "width": self.width, "height": self.height}
        if self.angle:  # Unrotated pictures keep the original, angle-free entry.
            data["angle"] = self.angle
        return data

    def moved(self, dx, dy):
        return PlacedImage(self.key, self.x + dx, self.y + dy, self.width, self.height, self.angle)


def _segment_distance_squared(x, y, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
    return (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2


def hits(stroke, x, y, radius):
    """True if a circular eraser overlaps any part of the stroke."""
    reach = radius + stroke.width / 2
    points = stroke.points
    return any(
        _segment_distance_squared(x, y, a, b) <= reach * reach
        for a, b in zip(points, points[1:] or points)
    )


@dataclass
class Note:
    strokes: list[Stroke] = field(default_factory=list)
    path: Path | None = None
    _saved: tuple[Stroke, ...] = field(default_factory=tuple, repr=False)
    # History entries are (strokes, images) snapshots, so moves of both are one step.
    _undo: list[tuple] = field(default_factory=list, repr=False)
    _redo: list[tuple] = field(default_factory=list, repr=False)
    _erase_active: bool = field(default=False, repr=False)
    _erase_recorded: bool = field(default=False, repr=False)
    # Pictures sit below all ink; the whole-stroke eraser never removes them.
    images: list[PlacedImage] = field(default_factory=list)
    _saved_images: tuple[PlacedImage, ...] = field(default_factory=tuple, repr=False)

    @property
    def dirty(self):
        return tuple(self.strokes) != self._saved or tuple(self.images) != self._saved_images

    def mark_saved(self):
        self._saved = tuple(self.strokes)
        self._saved_images = tuple(self.images)

    def _state(self):
        return tuple(self.strokes), tuple(self.images)

    def _restore(self, state):
        self.strokes, self.images = list(state[0]), list(state[1])

    def _replace(self, strokes, images=None):
        state = (tuple(strokes), tuple(self.images if images is None else images))
        if state == self._state():
            return False
        if not self._erase_active or not self._erase_recorded:
            self._undo.append(self._state())
            self._redo.clear()
            if self._erase_active:
                self._erase_recorded = True
        self._restore(state)
        return True

    def begin_erase(self):
        """Group live erasures until end_erase, recording only the first change."""
        self.end_erase()
        self._erase_active = True

    def end_erase(self):
        self._erase_active = False
        self._erase_recorded = False

    def add_stroke(self, stroke):
        if not isinstance(stroke, Stroke):
            raise TypeError("Expected a Stroke")
        self.end_erase()
        return self._replace([*self.strokes, stroke])

    def add_image(self, image):
        if not isinstance(image, PlacedImage):
            raise TypeError("Expected a PlacedImage")
        self.end_erase()
        return self._replace(self.strokes, [*self.images, image])

    def replace(self, strokes, images=None):
        """Swap the stroke list, and optionally the images, as one undo step."""
        if not all(isinstance(stroke, Stroke) for stroke in strokes):
            raise TypeError("Expected Strokes")
        if images is not None and not all(isinstance(image, PlacedImage) for image in images):
            raise TypeError("Expected PlacedImages")
        self.end_erase()
        return self._replace(strokes, images)

    def erase_where(self, predicate):
        """Remove matching whole strokes, honoring the active erase group."""
        return self._replace([s for s in self.strokes if not predicate(s)])

    def erase_at(self, x, y, radius=10):
        return self.erase_where(lambda stroke: hits(stroke, x, y, radius))

    def undo(self):
        self.end_erase()
        if not self._undo:
            return False
        self._redo.append(self._state())
        self._restore(self._undo.pop())
        return True

    def redo(self):
        self.end_erase()
        if not self._redo:
            return False
        self._undo.append(self._state())
        self._restore(self._redo.pop())
        return True

    @classmethod
    def load(cls, path):
        path = Path(path)
        try:
            with path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (ValueError, UnicodeError) as exc:
            raise NoteFormatError(f"Invalid note JSON: {exc}") from exc
        if not isinstance(data, dict) or set(data) != {"version", "strokes"} or type(data["version"]) is not int or data["version"] != 1 or not isinstance(data["strokes"], list):
            raise NoteFormatError("Unsupported note structure or version")
        strokes = []
        for entry in data["strokes"]:
            if not isinstance(entry, dict) or set(entry) != {"points", "color", "width"} or not isinstance(entry["points"], list):
                raise NoteFormatError("Invalid stroke structure")
            strokes.append(Stroke(entry["points"], entry["color"], entry["width"]))
        return cls(strokes=strokes, path=path, _saved=tuple(strokes))

    def save(self, path=None):
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("Choose a note path first")
        data = {"version": 1, "strokes": [stroke.to_data() for stroke in self.strokes]}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.path = target
        self._saved = tuple(self.strokes)
