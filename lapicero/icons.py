"""Toolbar icons painted with QPainter, so the app ships no image assets."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from .shapes import shape_points

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
    """Upright pen like OneNote's: grey barrel, colored band and tip."""
    tint = QColor(color[:7])

    def paint(p):
        body_width = 12 if highlighter else 9
        left = 16 - body_width / 2
        _outline(p, 1.2)
        p.setBrush(QColor("#f4f4f4"))
        p.drawRoundedRect(QRectF(left, 3, body_width, 15), 2, 2)
        p.setBrush(tint)
        p.drawRect(QRectF(left, 13, body_width, 5))
        tip = QPolygonF([QPointF(left, 18), QPointF(left + body_width, 18),
                         QPointF(16 + (3 if highlighter else 1.5), 27),
                         QPointF(16 - (3 if highlighter else 1.5), 27)])
        p.setBrush(QColor("#d9d9d9"))
        p.drawPolygon(tip)
        p.setBrush(tint)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(16 - (3 if highlighter else 1.5), 24, 6 if highlighter else 3, 4))
        if highlighter:
            p.setOpacity(.55)
            p.drawRoundedRect(QRectF(5, 28, 22, 3), 1.5, 1.5)
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


def swatch_icon(color):
    def paint(p):
        p.setPen(QPen(QColor("#9a9a9a"), 1))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(6, 6, 20, 20))
    return _canvas(paint)
