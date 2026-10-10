"""Geometry contracts independent of Tk and of note serialization."""

import math

import pytest

from lapicero.shapes import normalize_shape


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
    trace([(4, 10), (163, 116)]),  # slash is not an arrow
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
