"""Toolbar icons and the app logo, painted with QPainter."""

import math
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from .shapes import diagram_strokes, shape_points

SIZE = 32
SCALE = 2  # Paint at 2x so icons stay crisp on high-DPI screens.
INK = QColor("#3b3b3b")


def _canvas(paint):
    pixmap = QPixmap(SIZE * SCALE, SIZE * SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(SCALE)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint(painter)
    painter.end()
    return QIcon(pixmap)


def _outline(painter, width=1.6, color=INK):
    painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))


def pen_icon(color, highlighter=False):
    """Slanted pen with an ink-colored nib, over a short stroke of its own ink."""
    tint = QColor(color[:7])

    def paint(p):
        # The stroke it draws, so the color reads even at small sizes.
        stroke = QColor(tint)
        stroke.setAlphaF(.55 if highlighter else 1)
        p.setPen(QPen(stroke, 5 if highlighter else 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        path = QPainterPath(QPointF(5, 27))
        path.cubicTo(QPointF(10, 24.5), QPointF(13, 29), QPointF(19, 26.5))
        p.drawPath(path)
        p.translate(19, 13)
        p.rotate(45)
        half = 4.5 if highlighter else 3.5
        _outline(p, 1.3)
        p.setBrush(QColor("#fbfbfa"))
        p.drawRoundedRect(QRectF(-half, -12, half * 2, 15), 2.2, 2.2)
        p.setBrush(tint)
        p.drawRoundedRect(QRectF(-half, -12, half * 2, 4), 2.2, 2.2)  # Cap in the ink color.
        nib = (QPolygonF([QPointF(-half, 3), QPointF(half, 3), QPointF(half, 7), QPointF(-half * .2, 9)])
               if highlighter else
               QPolygonF([QPointF(-half, 3), QPointF(half, 3), QPointF(0, 9.5)]))
        p.drawPolygon(nib)
    return _canvas(paint)


def eraser_icon():
    def paint(p):
        p.translate(16, 16)
        p.rotate(-35)
        _outline(p, 1.3)
        p.setBrush(QColor("#f28da5"))
        p.drawRoundedRect(QRectF(-11, -6, 11, 12), 2, 2)
        p.setBrush(QColor("#fafafa"))
        p.drawRoundedRect(QRectF(0, -6, 11, 12), 2, 2)
    return _canvas(paint)


def lasso_icon():
    def paint(p):
        pen = QPen(INK, 1.6, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap)
        pen.setDashPattern([2.5, 2])
        p.setPen(pen)
        p.drawEllipse(QRectF(5, 5, 22, 15))
        _outline(p, 1.6)
        path = QPainterPath(QPointF(11, 19))
        path.cubicTo(QPointF(8, 24), QPointF(14, 26), QPointF(11, 29))
        p.drawPath(path)
    return _canvas(paint)


def shape_icon(kind):
    def paint(p):
        _outline(p, 1.8)
        points = shape_points(kind, (6, 7), (26, 25))
        path = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(QPointF(*point))
        p.drawPath(path)
    return _canvas(paint)


def diagram_icon(kind):
    def paint(p):
        _outline(p, 1.8)
        for points in diagram_strokes(kind, (6, 6), (26, 26), labels=False):
            path = QPainterPath(QPointF(*points[0]))
            for point in points[1:]:
                path.lineTo(QPointF(*point))
            p.drawPath(path)
    return _canvas(paint)


def _arrow_icon(mirror):
    def paint(p):
        if mirror:
            p.translate(SIZE, 0)
            p.scale(-1, 1)
        _outline(p, 2)
        path = QPainterPath(QPointF(25, 23))
        path.cubicTo(QPointF(25, 12), QPointF(17, 10), QPointF(8, 13))
        p.drawPath(path)
        p.drawPolyline(QPolygonF([QPointF(12, 8), QPointF(8, 13), QPointF(13, 17)]))
    return _canvas(paint)


def undo_icon():
    return _arrow_icon(False)


def redo_icon():
    return _arrow_icon(True)


def paper_icon(grid):
    def paint(p):
        _outline(p, 1.3)
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(6, 4, 20, 24))
        if grid:
            p.setPen(QPen(QColor("#7fb1e0"), 1))
            for offset in (10, 14, 18, 22):
                p.drawLine(QPointF(offset, 4.5), QPointF(offset, 27.5))
            for offset in (8, 12, 16, 20, 24):
                p.drawLine(QPointF(6.5, offset), QPointF(25.5, offset))
    return _canvas(paint)


def fullscreen_icon():
    def paint(p):
        _outline(p, 2)
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx, cy = 16 - 10 * sx, 16 - 10 * sy
            p.drawPolyline(QPolygonF([QPointF(cx, cy + 6 * sy), QPointF(cx, cy),
                                      QPointF(cx + 6 * sx, cy)]))
    return _canvas(paint)


def sidebar_icon():
    def paint(p):
        _outline(p, 1.6)
        p.drawRoundedRect(QRectF(5, 7, 22, 18), 2, 2)
        p.drawLine(QPointF(12, 7), QPointF(12, 25))
        for y in (11, 15, 19):
            p.drawLine(QPointF(7.5, y), QPointF(9.5, y))
    return _canvas(paint)


def new_page_icon():
    def paint(p):
        _outline(p, 1.6)
        path = QPainterPath(QPointF(19, 4))
        for x, y in ((8, 4), (8, 28), (24, 28), (24, 9), (19, 4), (19, 9), (24, 9)):
            path.lineTo(QPointF(x, y))
        p.drawPath(path)
        p.drawLine(QPointF(16, 14), QPointF(16, 22))
        p.drawLine(QPointF(12, 18), QPointF(20, 18))
    return _canvas(paint)


def paste_icon():
    def paint(p):
        _outline(p, 1.6)
        p.drawRoundedRect(QRectF(7, 7, 18, 21), 2.5, 2.5)
        p.setBrush(QColor("#fbfbfa"))
        p.drawRoundedRect(QRectF(12, 4, 8, 5), 1.5, 1.5)
        for y in (15, 19, 23):
            p.drawLine(QPointF(11.5, y), QPointF(20.5 if y < 23 else 17, y))
    return _canvas(paint)


def settings_icon():
    """Three sliders: preferences."""
    def paint(p):
        _outline(p, 1.6)
        for y, knob in ((9, 20), (16, 11), (23, 17)):
            p.drawLine(QPointF(6, y), QPointF(26, y))
            p.setBrush(QColor("#fbfbfa"))
            p.drawEllipse(QPointF(knob, y), 2.6, 2.6)
    return _canvas(paint)


def swatch_icon(color):
    def paint(p):
        p.setPen(QPen(QColor("#9a9a9a"), 1))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(6, 6, 20, 20))
    return _canvas(paint)


def ask_icon():
    """Dashed selection box with a speech bubble: ask Claude about an area."""

    def paint(p):
        pen = QPen(INK, 1.4, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(3, 3, 17, 15))
        _outline(p, 1.5)
        p.setBrush(QColor("#d9e8fb"))
        bubble = QPainterPath()
        bubble.addRoundedRect(QRectF(13, 13, 16, 12), 4, 4)
        bubble.moveTo(17, 25)
        bubble.lineTo(15, 29.5)
        bubble.lineTo(21, 25)
        p.drawPath(bubble.simplified())
        p.setPen(QPen(QColor("#2f7de1"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x in (17.5, 21, 24.5):
            p.drawPoint(QPointF(x, 19))

    return _canvas(paint)


def history_icon():
    """Clock with a counter-clockwise arrow: earlier chats."""

    def paint(p):
        _outline(p, 1.8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        center = QPointF(16.5, 16)
        p.drawArc(QRectF(6.5, 6, 20, 20), 200 * 16, -310 * 16)  # Open at the lower left for the arrow.
        p.drawPolyline(QPolygonF([QPointF(4.5, 12.5), QPointF(7.4, 19), QPointF(12.2, 14.6)]))
        p.drawPolyline(QPolygonF([QPointF(center.x(), 10.5), center, QPointF(20.5, 18.5)]))

    return _canvas(paint)


APP_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
APP_ICON_PATH = Path(__file__).parent / "assets" / "lapicero.ico"


def _paint_logo(p, size):
    """Lapicero logo: a white ballpoint pen writing a swoosh on a blue tile."""
    s = size / 64
    p.scale(s, s)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.fillPath(tile, QColor("#2F4FD8"))

    swoosh = QPainterPath(QPointF(11, 49))
    swoosh.cubicTo(17, 41, 21, 54, 27, 47)
    swoosh.cubicTo(30, 44, 31, 47, 34, 46)
    p.setPen(QPen(QColor("#AFC0FF"), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(swoosh)

    # Pen drawn upright, then rotated so its tip lands at the end of the swoosh.
    p.translate(34, 46)
    p.rotate(40)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(-4.5, -9), QPointF(4.5, -9)]))
    p.drawRoundedRect(QRectF(-4.5, -35, 9, 24), 2.5, 2.5)
    p.setBrush(QColor("#2F4FD8"))
    p.drawEllipse(QPointF(0, -1.6), 1.4, 1.4)  # Ballpoint tip.
    p.drawRect(QRectF(-4.5, -16, 9, 2.2))  # Grip band.


def app_logo_pixmap(size):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _paint_logo(painter, size)
    painter.end()
    return pixmap


def app_icon():
    """Window and taskbar icon, painted at every size so small ones stay sharp."""
    icon = QIcon()
    for size in APP_ICON_SIZES:
        icon.addPixmap(app_logo_pixmap(size))
    return icon


def write_app_ico(path=APP_ICON_PATH):
    """Write a multi-size .ico (PNG entries) for the Windows shortcut."""
    images = []
    for size in APP_ICON_SIZES:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        app_logo_pixmap(size).save(buffer, "PNG")
        buffer.close()
        images.append((size, bytes(data)))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        side = 0 if size >= 256 else size  # 0 means 256 in the ICO directory.
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        blobs += png
    Path(path).write_bytes(header + entries + blobs)
    return Path(path)


if __name__ == "__main__":
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication([])
    print(f"Wrote {write_app_ico()}")
