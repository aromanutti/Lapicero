"""Conservative, UI-independent recognition of single-stroke geometric outlines.

Returns ordinary point polylines so normalized ink needs no special storage format.
"""

import math


def _distance(a, b):
    return math.dist(a, b)


def _point_segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2)) if length2 else 0
    return _distance(p, (a[0] + t * dx, a[1] + t * dy))


def _simplify(points, tolerance):
    if len(points) <= 2:
        return list(points)
    distances = [_point_segment_distance(p, points[0], points[-1]) for p in points[1:-1]]
    largest = max(distances)
    if largest <= tolerance:
        return [points[0], points[-1]]
    pivot = distances.index(largest) + 1
    return _simplify(points[:pivot + 1], tolerance)[:-1] + _simplify(points[pivot:], tolerance)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def path_length_ratio(points, lengths):
    """Detect repeated outlines which happen to simplify to one polygon."""
    traveled = sum(_distance(a, b) for a, b in zip(points, points[1:]))
    return traveled / sum(lengths)


def _polygon(points, diagonal):
    # Choose a likely corner as the seam; otherwise a mid-edge stroke start
    # would appear as an extra vertex in the closed RDP simplification.
    n = len(points)
    perimeter = sum(_distance(points[i], points[(i + 1) % n]) for i in range(n))
    offset = perimeter * .12
    def neighbor(i, direction):
        traveled = 0
        j = i
        while traveled < offset:
            k = (j + direction) % n
            traveled += _distance(points[j], points[k])
            j = k
            if j == i:
                break
        return points[j]
    def bend(i):
        u = _sub(neighbor(i, -1), points[i])
        v = _sub(neighbor(i, 1), points[i])
        return _dot(u, v) / max(1e-9, math.hypot(*u) * math.hypot(*v))
    seam = max(range(n), key=bend)
    ring = list(points[seam:]) + list(points[:seam])
    vertices = _simplify(ring + [ring[0]], diagonal * .055)[:-1]
    if len(vertices) not in (3, 4):
        return None
    edges = [_sub(vertices[(i + 1) % len(vertices)], vertices[i]) for i in range(len(vertices))]
    lengths = [math.hypot(*edge) for edge in edges]
    if min(lengths) < diagonal * .22 or path_length_ratio(points, lengths) > 1.4:
        return None
    turns = [_cross(edges[i - 1], edges[i]) / (lengths[i - 1] * lengths[i])
             for i in range(len(vertices))]
    if min(abs(t) for t in turns) < .50 or not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
        return None
    # The simplified outline must actually follow the input, not merely pass
    # close to a few corners of a scribble or a retraced line.
    errors = [min(_point_segment_distance(p, vertices[i], vertices[(i + 1) % len(vertices)])
                  for i in range(len(vertices))) for p in points]
    if max(errors) > diagonal * .11 or sum(errors) / n > diagonal * .045:
        return None
    if len(vertices) == 3:
        area = abs(_cross(_sub(vertices[1], vertices[0]), _sub(vertices[2], vertices[0]))) / 2
        if area < diagonal * diagonal * .12:
            return None
        kind = "triangle"
    else:
        if any(abs(_dot(edges[i - 1], edges[i]) / (lengths[i - 1] * lengths[i])) > .32
               for i in range(4)):
            return None
        if any(abs(lengths[i] - lengths[i + 2]) > .30 * max(lengths[i], lengths[i + 2])
               for i in (0, 1)):
            return None
        sides = ((lengths[0] + lengths[2]) / 2, (lengths[1] + lengths[3]) / 2)
        kind = "square" if min(sides) / max(sides) >= .83 else "rectangle"
        if kind == "square":
            sides = (sum(lengths) / 4,) * 2
        # Average the opposite edges for a stable first axis, then construct
        # the second axis perpendicular to it instead of retaining noisy corners.
        axis = _sub(edges[0], edges[2])
        axis_length = math.hypot(*axis)
        ux, uy = axis[0] / axis_length, axis[1] / axis_length
        turn = 1 if _cross(edges[0], edges[1]) > 0 else -1
        vx, vy = -turn * uy, turn * ux
        cx = sum(p[0] for p in vertices) / 4
        cy = sum(p[1] for p in vertices) / 4
        first = (cx - sides[0] * ux / 2 - sides[1] * vx / 2,
                 cy - sides[0] * uy / 2 - sides[1] * vy / 2)
        vertices = [first,
                    (first[0] + sides[0] * ux, first[1] + sides[0] * uy),
                    (first[0] + sides[0] * ux + sides[1] * vx,
                     first[1] + sides[0] * uy + sides[1] * vy),
                    (first[0] + sides[1] * vx, first[1] + sides[1] * vy)]
    return kind, tuple(vertices + [vertices[0]])


def _arrow(points, diagonal):
    vertices = _simplify(points, diagonal * .045)
    if len(vertices) != 5:
        return None
    tail, tip, wing1, again, wing2 = vertices
    shaft = _sub(tip, tail)
    length = math.hypot(*shaft)
    if length < 45 or _distance(tip, again) > length * .13:
        return None
    wings = (_sub(wing1, tip), _sub(wing2, tip))
    for wing in wings:
        size = math.hypot(*wing)
        back = -_dot(wing, shaft) / length**2
        if not (.16 <= size / length <= .55 and .12 <= back <= .52):
            return None
    if _cross(shaft, wings[0]) * _cross(shaft, wings[1]) >= 0:
        return None
    if min(abs(_cross(shaft, wing)) / (length * math.hypot(*wing)) for wing in wings) < .22:
        return None
    # Reject complex trails whose simplification hides loops or extra strokes.
    errors = [min(_point_segment_distance(p, a, b) for a, b in zip(vertices, vertices[1:])) for p in points]
    if max(errors) > diagonal * .09 or sum(errors) / len(points) > diagonal * .035:
        return None
    return "arrow", (tail, tip, wing1, tip, wing2)


def normalize_shape(points):
    """Return (kind, clean points), or None when ink should remain untouched."""
    points = tuple(tuple(p) for p in points)
    if len(points) < 8:
        return None
    left, right = min(p[0] for p in points), max(p[0] for p in points)
    top, bottom = min(p[1] for p in points), max(p[1] for p in points)
    width, height = right - left, bottom - top
    diagonal = math.hypot(width, height)
    if diagonal < 45:
        return None
    path_length = sum(_distance(a, b) for a, b in zip(points, points[1:]))
    if path_length > diagonal * 6:
        return None
    if _distance(points[0], points[-1]) > diagonal * .18:
        return _arrow(points, diagonal)
    if min(width, height) < 45 or path_length < diagonal * 2.0:
        return None
    cx, cy = (left + right) / 2, (top + bottom) / 2
    radius = (width + height) / 4
    radii = [_distance(p, (cx, cy)) for p in points]
    winding = sum(_cross(_sub(a, (cx, cy)), _sub(b, (cx, cy))) for a, b in zip(points, points[1:]))
    if (min(width, height) / max(width, height) > .80
            and 4.5 < abs(winding) / radius**2 < 8.1
            and max(abs(r - radius) for r in radii) < radius * .23
            and sum(abs(r - radius) for r in radii) / len(radii) < radius * .095):
        phase = math.atan2(points[0][1] - cy, points[0][0] - cx)
        direction = 1 if winding >= 0 else -1
        clean = tuple((cx + radius * math.cos(phase + direction * 2 * math.pi * i / 48),
                       cy + radius * math.sin(phase + direction * 2 * math.pi * i / 48)) for i in range(49))
        return "circle", clean
    return _polygon(points, diagonal)


SHAPE_KINDS = ("line", "arrow", "rectangle", "ellipse", "triangle")
ELLIPSE_SEGMENTS = 48


def shape_points(kind, start, end):
    """Clean stroke geometry for a shape dragged from start to end.

    Closed polygons repeat their first vertex and arrows use the
    (tail, tip, wing, tip, wing) layout, so renderers keep straight edges.
    """
    (x0, y0), (x1, y1) = start, end
    left, right, top, bottom = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    if kind == "line":
        return (start, end)
    if kind == "rectangle":
        return ((left, top), (right, top), (right, bottom), (left, bottom), (left, top))
    if kind == "triangle":
        return ((left, bottom), ((left + right) / 2, top), (right, bottom), (left, bottom))
    if kind == "ellipse":
        cx, cy, rx, ry = (left + right) / 2, (top + bottom) / 2, (right - left) / 2, (bottom - top) / 2
        ring = tuple((cx + rx * math.cos(2 * math.pi * i / ELLIPSE_SEGMENTS),
                      cy + ry * math.sin(2 * math.pi * i / ELLIPSE_SEGMENTS))
                     for i in range(ELLIPSE_SEGMENTS))
        return ring + (ring[0],)
    if kind == "arrow":
        length = math.dist(start, end)
        if not length:
            return (start, end)
        head = min(18.0, length * .35)
        angle = math.atan2(y1 - y0, x1 - x0)
        wings = tuple((x1 - head * math.cos(angle + side), y1 - head * math.sin(angle + side))
                      for side in (math.radians(28), -math.radians(28)))
        return (start, end, wings[0], end, wings[1])
    raise ValueError(f"Unknown shape: {kind}")
