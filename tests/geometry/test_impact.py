from __future__ import annotations

import math
import random

import pytest

from spacedrums.geometry import Arc, Segment, crossing_time, segment_arc, segment_segment


def test_segment_segment_analytic_parameter_and_time():
    hit = segment_segment((0.5, 0.0), (0.5, 1.0), Segment((0.0, 0.25), (1.0, 0.25)))
    assert hit is not None
    assert hit.s == pytest.approx(0.25, abs=1e-12)
    assert hit.point == pytest.approx((0.5, 0.25), abs=1e-12)
    assert crossing_time(10.0, 10.04, hit.s) == pytest.approx(10.01, abs=1e-12)


def test_segment_arc_analytic_crossing_error():
    arc = Arc((0.5, 0.5), 0.2, 0.2, 0.0, math.pi, 2 * math.pi)
    hit = segment_arc((0.5, 0.0), (0.5, 0.4), arc)
    assert hit is not None
    assert hit.s == pytest.approx(0.75, abs=1e-12)
    assert hit.point == pytest.approx((0.5, 0.3), abs=1e-12)


def test_degenerate_parallel_collinear_grazing_and_starting_surface():
    line = Segment((0.0, 0.3), (1.0, 0.3))
    assert segment_segment((0.0, 0.2), (1.0, 0.2), line) is None
    assert segment_segment((0.2, 0.3), (0.8, 0.3), line) is None
    hit = segment_segment((0.5, 0.3), (0.5, 0.6), line)
    assert hit is not None and hit.s == 0.0


def test_property_crossing_parameter_and_time_are_monotone():
    rng = random.Random(404)
    previous_s = -1.0
    previous_t = -1.0
    for s in sorted(rng.uniform(0.01, 0.99) for _ in range(500)):
        surface = Segment((0.0, s), (1.0, s))
        hit = segment_segment((0.5, 0.0), (0.5, 1.0), surface)
        assert hit is not None and hit.s >= previous_s
        t = crossing_time(4.0, 5.0, hit.s)
        assert t >= previous_t
        previous_s, previous_t = hit.s, t
