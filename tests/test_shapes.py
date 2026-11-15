"""Geometry contracts independent of Tk and of note serialization."""

import math

import pytest

from lapicero.shapes import diagram_strokes, edit_shape, integral_points, normalize_shape


def trace(vertices, steps=7):
    """Sample an imperfect pointer path, including slightly perturbed edges."""
    result = []
    for index, (a, b) in enumerate(zip(vertices, vertices[1:])):
        for i in range(steps):
            t = i / steps
            jitter = 1.4 * math.sin(i * 2.7 + index * 1.3)
            result.append((a[0] + (b[0] - a[0]) * t + jitter,
                           a[1] + (b[1] - a[1]) * t - jitter * .6))
    result.append(vertices[-1])
    return result


@pytest.mark.parametrize("kind, vertices", [
    ("triangle", [(18, 24), (149, 38), (76, 139), (20, 27)]),
    ("square", [(22, 20), (124, 23), (120, 122), (19, 119), (23, 21)]),
    ("rectangle", [(12, 18), (194, 21), (191, 100), (16, 98), (13, 20)]),
    ("arrow", [(12, 83), (174, 79), (139, 51), (173, 80), (138, 111)]),
])
def test_irregular_polygons_and_single_stroke_arrow(kind, vertices):
    raw = trace(vertices)
    result = normalize_shape(raw)
    assert result is not None and result[0] == kind
    assert result[1] != tuple(raw)
    if kind != "arrow":
        assert result[1][0] == result[1][-1]
        assert len(result[1]) == (4 if kind == "triangle" else 5)
    else:
        assert len(result[1]) == 5 and result[1][1] == result[1][3]


@pytest.mark.parametrize("kind, corners", [
    ("square", [(22, 20), (124, 23), (120, 122), (19, 119)]),
    ("rectangle", [(12, 18), (194, 21), (191, 100), (16, 98)]),
])
def test_quadrilateral_snap_has_exact_geometry_and_preserves_placement(kind, corners):
    raw = trace(corners + [corners[0]])
    result = normalize_shape(raw)
    assert result is not None and result[0] == kind
    clean = result[1]
    assert len(clean) == 5 and clean[0] == clean[-1]
    edges = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(clean, clean[1:])]
    lengths = [math.hypot(*edge) for edge in edges]
    for before, after in zip(edges, edges[1:] + edges[:1]):
        assert before[0] * after[0] + before[1] * after[1] == pytest.approx(0, abs=1e-9)
    assert lengths[0] == pytest.approx(lengths[2], abs=1e-9)
    assert lengths[1] == pytest.approx(lengths[3], abs=1e-9)
    if kind == "square":
        assert lengths[0] == pytest.approx(lengths[1], abs=1e-9)
    else:
        assert max(lengths) / min(lengths) > 1.5
    for corner in corners:
        assert min(math.dist(corner, p) for p in clean[:4]) < 12
    for axis in (0, 1):
        assert sum(p[axis] for p in clean[:4]) / 4 == pytest.approx(
            sum(p[axis] for p in corners) / 4, abs=5)


def test_irregular_circle_normalizes_to_closed_round_outline():
    raw = [(90 + (57 + 2 * math.sin(7 * t)) * math.cos(t),
            95 + (57 + 2 * math.sin(7 * t)) * math.sin(t))
           for t in (2 * math.pi * i / 48 for i in range(49))]
    result = normalize_shape(raw)
    assert result is not None and result[0] == "circle"
    assert len(result[1]) == 49
    assert math.dist(result[1][0], result[1][-1]) < 1e-8


@pytest.mark.parametrize("points", [
    trace([(1, 1), (18, 3), (18, 18), (1, 18), (1, 1)]),  # tiny handwriting loop
    trace([(0, 0), (38, 0), (38, 38), (0, 38), (0, 0)]),  # small letter-shaped loop
    trace([(2, 10), (150, 10), (119, 13), (150, 10), (120, 15)]),  # same-side barbs
    trace([(10, 10), (200, 10), (200, 18), (10, 18), (10, 10)]),  # narrow writing loop
    trace([(10, 10), (150, 10), (190, 110), (10, 110), (10, 10)]),  # oblique quadrilateral
    trace([(20, 20), (140, 20), (40, 120), (140, 120), (20, 20)]),  # crossed scribble
    trace([(20, 20), (160, 20), (20, 20), (160, 20), (20, 20)]),  # retraced line
    trace([(20, 20), (150, 20), (150, 130), (20, 130), (20, 20),
           (150, 20), (150, 130), (20, 130), (20, 20)]),  # doubled outline
])
def test_conservative_rejection(points):
    assert normalize_shape(points) is None


def test_doubled_circle_is_not_single_outline():
    points = [(90 + 60 * math.cos(t), 90 + 60 * math.sin(t))
              for t in (4 * math.pi * i / 96 for i in range(97))]
    assert normalize_shape(points) is None


def test_mid_edge_start_still_recognizes_rectangle():
    points = trace([(100, 20), (180, 20), (180, 100), (20, 100), (20, 20), (100, 20)])
    assert normalize_shape(points)[0] == "rectangle"


def test_held_straight_stroke_becomes_a_line_but_a_curve_does_not():
    slash = trace([(4, 10), (163, 116)])
    assert normalize_shape(slash) == ("line", (slash[0], slash[-1]))
    arc = [(20 + 150 * i / 30, 100 - 60 * math.sin(math.pi * i / 30)) for i in range(31)]
    assert normalize_shape(arc) is None


def test_rotated_ellipse_is_recognized_and_stays_oval():
    tilt = math.radians(30)
    raw = []
    for i in range(61):
        t = 2 * math.pi * i / 60
        x, y = (95 + 3 * math.sin(5 * t)) * math.cos(t), (45 + 2 * math.sin(3 * t)) * math.sin(t)
        raw.append((200 + x * math.cos(tilt) - y * math.sin(tilt), 150 + x * math.sin(tilt) + y * math.cos(tilt)))
    kind, clean = normalize_shape(raw)
    assert kind == "ellipse" and clean[0] == clean[-1]
    radii = [math.dist(p, (200, 150)) for p in clean]
    assert max(radii) == pytest.approx(95, abs=6) and min(radii) == pytest.approx(45, abs=6)


def flat(points):
    return [c for p in points for c in p]


def test_edit_shape_pivots_lines_on_the_tail_and_keeps_arrow_heads_sized():
    line = edit_shape("line", ((0, 0), (10, 0)), (10, 0), (0, 20))
    assert flat(line) == pytest.approx([0, 0, 0, 20])
    arrow = ((0, 0), (100, 0), (85, -8), (100, 0), (85, 8))
    tail, tip, wing, again, _ = edit_shape("arrow", arrow, (100, 0), (0, 200))
    assert tail == (0, 0) and tip == again == pytest.approx((0, 200))
    assert math.dist(wing, tip) == pytest.approx(math.dist((85, -8), (100, 0)))


def test_edit_shape_scales_closed_outlines_around_their_center():
    square = ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0))
    assert flat(edit_shape("square", square, (0, 0), (-5, -5))) == pytest.approx(
        [-5, -5, 15, -5, 15, 15, -5, 15, -5, -5])


def test_xyz_axes_share_an_origin_and_point_up_right_and_toward_the_viewer():
    strokes = diagram_strokes("axes_xyz", (0, 0), (100, 100))
    arrows, labels = strokes[:3], strokes[3:]
    origin = arrows[0][0]
    assert all(arrow[0] == origin and len(arrow) == 5 for arrow in arrows)
    x, y, z = (arrow[1] for arrow in arrows)
    assert x[0] < origin[0] and x[1] > origin[1]  # Lower left, toward the viewer.
    assert y[0] > origin[0] and y[1] == origin[1]
    assert z[0] == origin[0] and z[1] < origin[1]
    assert len(labels) == 5  # x and y have two strokes, z one.
    assert diagram_strokes("axes_xyz", (0, 0), (100, 100), labels=False) == arrows


def hand_integral(left=40, top=20, width=40, height=160):
    clean = integral_points(left, top, left + width, top + height)
    return [(x + 1.5 * math.sin(i * 1.7), y + 1.2 * math.cos(i * 2.3)) for i, (x, y) in enumerate(clean)]


@pytest.mark.parametrize("points", [hand_integral(), hand_integral(width=60, height=140),
                                    hand_integral()[::-1]])
def test_held_hand_drawn_integral_snaps_to_a_clean_sign(points):
    kind, clean = normalize_shape(points)
    assert kind == "integral" and clean[0][1] < clean[-1][1]
    assert clean[0][0] > clean[-1][0]  # Top hook on the right, bottom hook on the left.
    assert max(p[1] for p in clean) - min(p[1] for p in clean) == pytest.approx(
        max(p[1] for p in points) - min(p[1] for p in points), rel=.08)


def s_letter():
    return [(100 + 30 * math.cos(t), 60 - 25 * math.sin(t)) for t in (math.pi * i / 12 for i in range(4, 19))] + [
        (100 - 30 * math.cos(t), 110 - 25 * math.sin(t)) for t in (math.pi * i / 12 for i in range(-6, 9))]


@pytest.mark.parametrize("points", [
    s_letter(),
    [(80, 20 + 4 * i) for i in range(35)] + [(80 - 6 * i, 160 + 3 * math.sin(i)) for i in range(1, 6)],  # J
    [(60 + 30 * math.cos(math.pi * i / 10), 40 - 20 * math.sin(math.pi * i / 10)) for i in range(11)][::-1][:1]
    + [(30, 20 + 4 * i) for i in range(35)],  # l-like stroke without hooks
])
def test_letters_are_not_integrals(points):
    result = normalize_shape(points)
    assert result is None or result[0] != "integral"


def test_integral_from_the_engineering_menu_fills_the_box_height():
    (sign,) = diagram_strokes("integral", (10, 10), (40, 130))
    assert sign == integral_points(10, 10, 40, 130)
    ys = [p[1] for p in sign]
    assert min(ys) == pytest.approx(10, abs=4) and max(ys) == pytest.approx(130, abs=4)
