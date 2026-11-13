"""Turn typed text into ink strokes, so AI answers can be written on a page.

Glyph outlines are traced with a pen about as wide as the font's stems, which
closes each letter into solid, marker-like ink.
"""

from PySide6.QtCore import QPointF
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QPainterPath

from .model import Stroke


HANDWRITING_FAMILIES = ("Ink Free", "Segoe Print", "Comic Sans MS")
STEM_RATIO = .085  # Outline pen width as a fraction of the font size.
MAX_TEXT = 5000


def _font(size):
    families = set(QFontDatabase.families())
    font = QFont()
    for family in HANDWRITING_FAMILIES:
        if family in families:
            font = QFont(family)
            break
    font.setPixelSize(max(1, round(size)))
    return font


def _wrap(text, metrics, max_width):
    lines = []
    for paragraph in text.split("\n"):
        if max_width is None:
            lines.append(paragraph)
            continue
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else f"{line} {word}"
            if line and metrics.horizontalAdvance(candidate) > max_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def text_strokes(text, x, y, size=24.0, color="#205bb5", max_width=None):
    """Strokes spelling ``text`` with its first line's top-left at document (x, y)."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Text must not be empty")
    if len(text) > MAX_TEXT:
        raise ValueError(f"Text is limited to {MAX_TEXT} characters")
    if not 4 <= size <= 400:
        raise ValueError("Text size must be between 4 and 400")
    if max_width is not None and max_width < size:
        raise ValueError("max_width must be at least the text size")
    font = _font(size)
    metrics = QFontMetricsF(font)
    width = max(1.0, size * STEM_RATIO)
    strokes = []
    baseline = y + metrics.ascent()
    for line in _wrap(text.replace("\r\n", "\n"), metrics, max_width):
        if line.strip():
            path = QPainterPath()
            path.addText(QPointF(x, baseline), font, line)
            for polygon in path.toSubpathPolygons():
                points = [(p.x(), p.y()) for p in polygon]
                if len(points) > 1 and points[0] != points[-1]:
                    points.append(points[0])
                if points:
                    strokes.append(Stroke(tuple(points), color, width))
        baseline += metrics.lineSpacing()
    return strokes
