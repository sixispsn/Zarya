"""Grade and envelope checks never obtain dimensions from schematic pixels."""
from dataclasses import replace

import pytest

from app.pz.wastewater_suspended_profile import SuspendedCollectorProfile


def profile(**changes):
    # Explicit synthetic test dimensions, not proposed site design inputs.
    return replace(SuspendedCollectorProfile(
        "K1", start_invert_m=-.6, length_m=12, slope=.02,
        outer_diameter_mm=110, wall_thickness_mm=2.7,
        extra_top_envelope_mm=20, extra_bottom_envelope_mm=30,
    ), **changes)


def test_grade_and_clearances_include_the_pipe_wall_and_socket_hanger_envelope():
    p = profile()
    assert p.end_invert_m == pytest.approx(-.84)
    assert p.ceiling_clearance_m(-.3) == pytest.approx(.1727)
    assert p.passage_height_m(-3.1) == pytest.approx(2.2273)
    assert p.drop_height_m(-2.2) == pytest.approx(1.36)
    p.validate_envelope(ceiling_m=-.3, floor_m=-3.1, required_ceiling_gap_m=.05, required_passage_m=2)


def test_unknown_inputs_stay_unknown_and_do_not_pass_validation():
    p = SuspendedCollectorProfile("K2")
    assert p.end_invert_m is None
    assert p.ceiling_clearance_m(-.3) is None
    assert p.passage_height_m(-3.1) is None
    assert p.drop_height_m(-2.2) is None
    with pytest.raises(ValueError, match="missing"):
        p.validate_envelope(ceiling_m=-.3, floor_m=-3.1, required_ceiling_gap_m=.05, required_passage_m=2)


@pytest.mark.parametrize("key", ["start_invert_m", "length_m", "slope"])
def test_incomplete_grade_does_not_supply_an_end_invert(key):
    p = profile(**{key: None})
    assert p.end_invert_m is None
    assert p.passage_height_m(-3.1) is None
    assert p.drop_height_m(-2.2) is None


def test_unspecified_mounting_envelope_is_not_silently_zero():
    assert profile(extra_top_envelope_mm=None).ceiling_clearance_m(-.3) is None
    assert profile(extra_bottom_envelope_mm=None).passage_height_m(-3.1) is None


def test_increasing_length_reduces_passage_and_can_block_the_route():
    p = profile(length_m=30)
    assert p.passage_height_m(-3.1) < 2
    with pytest.raises(ValueError, match="passage"):
        p.validate_envelope(ceiling_m=-.3, floor_m=-3.1, required_ceiling_gap_m=.05, required_passage_m=2)


def test_ceiling_collision_and_reverse_drop_are_blocked():
    with pytest.raises(ValueError, match="ceiling"):
        profile(start_invert_m=-.4).validate_envelope(
            ceiling_m=-.3, floor_m=-3.1, required_ceiling_gap_m=.05, required_passage_m=2)
    with pytest.raises(ValueError, match="downward"):
        profile().drop_height_m(-.5)


@pytest.mark.parametrize("changes", [
    {"system": "K1+K2"}, {"length_m": -1}, {"length_m": 0}, {"slope": 0},
    {"slope": -.02}, {"start_invert_m": float("nan")}, {"length_m": float("inf")},
    {"slope": True}, {"outer_diameter_mm": 0}, {"wall_thickness_mm": 55},
    {"extra_top_envelope_mm": -1}, {"extra_bottom_envelope_mm": -1},
])
def test_invalid_profile_input_is_rejected(changes):
    with pytest.raises(ValueError):
        profile(**changes)
