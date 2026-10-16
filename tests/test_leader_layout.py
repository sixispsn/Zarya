from xml.etree import ElementTree

import pytest

from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderRequest


def _request(identifier: str, target: tuple[float, float]) -> LeaderRequest:
    return LeaderRequest(
        leader_id=identifier,
        target_id=f"target-{identifier}",
        target=target,
        title="Прочистка",
        detail="DN100",
        preferred_side=1,
        preferred_vertical=-1,
    )


@pytest.mark.parametrize("offsets", [(), (0.,), (-1.,), (float("nan"),), (float("inf"),)])
def test_leader_rejects_invalid_distance_candidates(offsets):
    with pytest.raises(ValueError, match="offsets"):
        LeaderLayoutEngine(bounds=LeaderBounds(0, 0, 1000, 600), units_per_mm=1,
                           vertical_offsets_mm=offsets)


def test_explicit_long_leader_reaches_free_annotation_band():
    engine = LeaderLayoutEngine(bounds=LeaderBounds(450, 60, 900, 130), units_per_mm=10/3,
                                vertical_offsets_mm=(50., 60., 70., 80.))
    placement = engine.place(_request("long", (400, 350)))
    assert 60 <= placement.text_box[1] < placement.text_box[3] <= 130


def test_leader_has_arrow_horizontal_shelf_and_physical_text_height():
    engine = LeaderLayoutEngine(
        bounds=LeaderBounds(0, 0, 1000, 600),
        units_per_mm=10 / 3,
    )

    svg = engine.place_and_render(_request("L1", (400, 350)))
    root = ElementTree.fromstring(svg)

    assert root.get("data-arrow-kind") == "closed-filled"
    assert root.get("data-text-height-mm") == "3.5"
    assert root.get("data-shelf-horizontal") == "true"
    assert root.get("data-title-above-shelf") == "true"
    assert root.get("data-detail-below-shelf") == "true"
    assert len([row for row in root if row.get("data-leader-arrow")]) == 1
    assert len([row for row in root if row.get("data-leader-title")]) == 1
    assert len([row for row in root if row.get("data-leader-detail")]) == 1


def test_leader_engine_moves_second_callout_away_from_first():
    engine = LeaderLayoutEngine(
        bounds=LeaderBounds(0, 0, 1000, 600),
        units_per_mm=10 / 3,
    )

    first = engine.place(_request("L1", (400, 350)))
    second = engine.place(_request("L2", (410, 355)))

    assert first.text_box != second.text_box
    assert (
        first.text_box[2] <= second.text_box[0]
        or second.text_box[2] <= first.text_box[0]
        or first.text_box[3] <= second.text_box[1]
        or second.text_box[3] <= first.text_box[1]
    )


def test_leader_rejects_non_standard_text_height():
    engine = LeaderLayoutEngine(
        bounds=LeaderBounds(0, 0, 1000, 600),
        units_per_mm=10 / 3,
    )
    request = LeaderRequest(
        leader_id="L1",
        target_id="target",
        target=(400, 350),
        title="Прочистка",
        detail="DN100",
        text_height_mm=4.0,
    )

    with pytest.raises(ValueError, match="3.5 or 5 mm"):
        engine.place(request)
