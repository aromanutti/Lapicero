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


# Unit-box cubic Beziers (x right, y down) of a typeset-looking integral sign,
# drawn top hook first: curl over to the stem, a slight slant, then curl under.
_INTEGRAL_CURVES = (((.95, .10), (.90, -.02), (.62, -.04), (.56, .18)),
                    ((.56, .18), (.52, .40), (.48, .60), (.44, .82)),
                    ((.44, .82), (.38, 1.04), (.10, 1.02), (.05, .90)))


def integral_points(left, top, right, bottom):
    """A clean integral sign filling the box height, kept to a slender width."""
    height = bottom - top
    width = min(max(right - left, height * .22), height * .45)
    x0 = (left + right) / 2 - width / 2
    result = []
    for index, (a, b, c, d) in enumerate(_INTEGRAL_CURVES):
        for i in range(0 if index == 0 else 1, 13):
            t = i / 12
            u = 1 - t
            x = u**3 * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t**3 * d[0]
            y = u**3 * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t**3 * d[1]
            result.append((x0 + x * width, top + y * height))
    return tuple(result)


def _integral(points):
    """A tall stroke with a hook over the right at the top and under the left at the bottom."""
    if points[0][1] > points[-1][1]:
        points = points[::-1]  # Accept it drawn bottom to top.
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    width, height = right - left, bottom - top
    if height < 45 or not height * .12 <= width <= height * .7:
        return None
    apex = points[ys.index(top)]
    base = points[ys.index(bottom)]
    first, last = points[0], points[-1]
    if not (first[0] - apex[0] > width * .08 and first[1] - top > height * .03
            and base[0] - last[0] > width * .08 and bottom - last[1] > height * .03):
        return None
    # The stem between the hooks must run steadily down, not zigzag like a letter.
    stem = [p for p in points if top + height * .25 <= p[1] <= bottom - height * .25]
    if len(stem) < 2 or any(b[1] < a[1] - height * .02 for a, b in zip(stem, stem[1:])):
        return None
    if max(p[0] for p in stem) - min(p[0] for p in stem) > width * .6:
        return None
    return "integral", integral_points(left, top, right, bottom)


def _line(points, path_length):
    start, end = points[0], points[-1]
    chord = _distance(start, end)
    if chord < 45 or path_length > chord * 1.2:
        return None
    if max(_point_segment_distance(p, start, end) for p in points) > max(4.0, chord * .06):
        return None
    return "line", (start, end)


def _ellipse(points):
    """Fit one closed loop to a (possibly rotated) ellipse, or a circle when round."""
    n = len(points)
    mx, my = sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points) / n
    syy = sum((p[1] - my) ** 2 for p in points) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points) / n
    spread = math.hypot(sxx - syy, 2 * sxy)
    # Near-isotropic loops have no stable principal axis; stay axis-aligned.
    small, large = (sxx + syy - spread) / 2, (sxx + syy + spread) / 2
    angle = .5 * math.atan2(2 * sxy, sxx - syy) if large and small / large < .72 else 0.0
    ux, uy = math.cos(angle), math.sin(angle)
    local = [((p[0] - mx) * ux + (p[1] - my) * uy, -(p[0] - mx) * uy + (p[1] - my) * ux) for p in points]
    us, vs = [q[0] for q in local], [q[1] for q in local]
    a, b = (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2
    if min(a, b) < 20:
        return None
    cu, cv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
    cx, cy = mx + cu * ux - cv * uy, my + cu * uy + cv * ux
    area = abs(sum(_cross(_sub(p, (cx, cy)), _sub(q, (cx, cy))) for p, q in zip(points, points[1:]))) / 2
    if not .72 < area / (math.pi * a * b) < 1.29:
        return None
    radii = [math.hypot((u - cu) / a, (v - cv) / b) for u, v in local]
    if max(abs(r - 1) for r in radii) >= .23 or sum(abs(r - 1) for r in radii) / n >= .095:
        return None
    if min(a, b) / max(a, b) >= .85:
        a = b = (a + b) / 2
        kind = "circle"
    else:
        kind = "ellipse"
    phase = math.atan2(points[0][1] - cy, points[0][0] - cx) - angle
    winding = sum(_cross(_sub(p, (cx, cy)), _sub(q, (cx, cy))) for p, q in zip(points, points[1:]))
    direction = 1 if winding >= 0 else -1
    clean = []
    for i in range(ELLIPSE_SEGMENTS + 1):
        t = phase + direction * 2 * math.pi * i / ELLIPSE_SEGMENTS
        x, y = a * math.cos(t), b * math.sin(t)
        clean.append((cx + x * ux - y * uy, cy + x * uy + y * ux))
    clean[-1] = clean[0]
    return kind, tuple(clean)


def normalize_shape(points, zoom=1.0):
    """Return (kind, clean points), or None when ink should remain untouched.

    Size limits are screen pixels: ``zoom`` (screen pixels per page unit) maps
    the ink to the screen for recognition, and the clean shape back to the page,
    so a box that looks big enough snaps the same at any zoom.
    """
    if zoom != 1.0:
        result = normalize_shape([(x * zoom, y * zoom) for x, y in points])
        if result is None:
            return None
        return result[0], tuple((x / zoom, y / zoom) for x, y in result[1])
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
        return _integral(points) or _line(points, path_length) or _arrow(points, diagonal)
    if min(width, height) < 45 or path_length < diagonal * 2.0:
        return None
    ellipse = _ellipse(points)
    if ellipse is not None:
        return ellipse
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


CLOSED_KINDS = ("circle", "ellipse", "triangle", "square", "rectangle")


def edit_shape(kind, points, anchor, target):
    """Rotate and scale a recognized shape so the pen's hold point follows the pen.

    Lines and arrows pivot on their tail, so dragging changes length and
    direction; closed outlines pivot on their center and grow, shrink or turn.
    Arrow heads keep their size instead of scaling with the shaft.
    """
    points = tuple(tuple(p) for p in points)
    if kind in ("line", "arrow"):
        pivot = complex(*points[0])
    else:
        ring = points[:-1] if points[0] == points[-1] else points
        pivot = complex(sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    origin = complex(*anchor) - pivot
    if abs(origin) < 1e-6:
        return points
    factor = (complex(*target) - pivot) / origin
    if abs(factor) < 1e-3:
        factor = factor / abs(factor) * 1e-3 if factor else 1e-3
    def move(p):
        z = pivot + (complex(*p) - pivot) * factor
        return (z.real, z.imag)
    if kind != "arrow":
        return tuple(move(p) for p in points)
    tail, tip = points[0], points[1]
    turn = factor / abs(factor) * min(1.0, abs(factor))
    new_tip = complex(*move(tip))
    wings = [new_tip + (complex(*w) - complex(*tip)) * turn for w in (points[2], points[4])]
    new_tip = (new_tip.real, new_tip.imag)
    return (tail, new_tip, (wings[0].real, wings[0].imag), new_tip, (wings[1].real, wings[1].imag))


DIAGRAM_KINDS = ("axes_xy", "axes_xyz", "integral")


def _letter(char, center, size):
    """Hand-lettered axis label as straight strokes, ``size`` being its half height."""
    cx, cy = center
    s = size
    if char == "x":
        return (((cx - s, cy - s), (cx + s, cy + s)), ((cx + s, cy - s), (cx - s, cy + s)))
    if char == "y":
        return (((cx - s, cy - s), (cx, cy)), ((cx + s, cy - s), (cx - s * .5, cy + s)))
    if char == "z":
        return (((cx - s, cy - s), (cx + s, cy - s), (cx - s, cy + s), (cx + s, cy + s)),)
    raise ValueError(f"No strokes for label: {char}")


def diagram_strokes(kind, start, end, labels=True):
    """Engineering diagrams dragged over the box from start to end, as several strokes.

    ``axes_xy`` puts the origin at the box's lower left with X to the right and
    Y up. ``axes_xyz`` is an oblique right-handed frame: Z up, Y right and X
    toward the viewer (lower left). Each axis is an arrow labeled at its tip.
    """
    (x0, y0), (x1, y1) = start, end
    left, right, top, bottom = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    width, height = right - left, bottom - top
    if kind == "integral":
        return (integral_points(left, top, right, bottom),)
    if kind == "axes_xy":
        origin = (left, bottom)
        tips = (("x", (right, bottom)), ("y", (left, top)))
    elif kind == "axes_xyz":
        origin = (left + width * .4, top + height * .6)
        tips = (("x", (left, bottom)), ("y", (right, origin[1])), ("z", (origin[0], top)))
    else:
        raise ValueError(f"Unknown diagram: {kind}")
    strokes = [shape_points("arrow", origin, tip) for _, tip in tips]
    if labels:
        size = max(4.0, min(10.0, min(width, height) * .06 or max(width, height) * .06))
        for char, tip in tips:
            dx, dy = tip[0] - origin[0], tip[1] - origin[1]
            length = math.hypot(dx, dy) or 1
            # Just past the tip, along the axis, clear of the arrow head.
            center = (tip[0] + dx / length * size * 2.2, tip[1] + dy / length * size * 2.2)
            strokes.extend(_letter(char, center, size))
    return tuple(strokes)
