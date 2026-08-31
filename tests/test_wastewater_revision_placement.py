import pytest

from app.pz.wastewater_revision_placement import (
    REVISION_PLACEMENT_RULE_ID,
    resolve_riser_revision_placement,
    revision_y_from_clean_floor,
)


def test_general_revision_defaults_to_one_metre_above_clean_floor():
    placement = resolve_riser_revision_placement(floor_height_m=3.0)

    assert placement.height_above_clean_floor_m == 1.0
    assert placement.source == "project-default"
    assert not placement.kitchen_riser_exception
    assert REVISION_PLACEMENT_RULE_ID == "zarya-project-accessibility"
    assert revision_y_from_clean_floor(
        clean_floor_y=300.0,
        graphic_floor_height=240.0,
        real_floor_height_m=3.0,
        placement=placement,
    ) == 220.0


@pytest.mark.parametrize("height", [0.8, 1.0, 1.2])
def test_explicit_accessible_project_height_is_preserved(height):
    placement = resolve_riser_revision_placement(
        floor_height_m=3.0,
        requested_height_m=height,
    )

    assert placement.height_above_clean_floor_m == pytest.approx(height)
    assert placement.source == "project-input"


@pytest.mark.parametrize("height", [0.5, 1.5, 2.7])
def test_general_revision_outside_accessible_band_is_rejected(height):
    with pytest.raises(ValueError, match="0.8-1.2 m"):
        resolve_riser_revision_placement(
            floor_height_m=3.0,
            requested_height_m=height,
        )


def test_kitchen_riser_is_limited_by_explicit_sink_rim_height():
    placement = resolve_riser_revision_placement(
        floor_height_m=3.0,
        kitchen_sink_rim_height_m=0.85,
    )

    assert placement.height_above_clean_floor_m == 0.85
    assert placement.kitchen_riser_exception
    assert placement.source == "sp30-kitchen-riser-limit"
