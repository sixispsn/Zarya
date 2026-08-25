from xml.etree import ElementTree

import pytest
from pypdf import PdfReader

from app.pz.generator import generate_wastewater_stack_node_pdf
from app.pz.wastewater_floor_drafting import FloorFixtureInput
from app.pz.wastewater_stack_drafting import (
    build_wastewater_stack_assembly,
    build_wastewater_stack_control_svgs,
)


def test_stack_builds_every_floor_without_collapsing_repeated_storeys():
    stack = build_wastewater_stack_assembly(floors_above=9)

    assert stack.validate() == []
    assert [row.floor_no for row in stack.floors] == list(range(1, 10))
    assert [floor for page in stack.pages for floor in page.floor_numbers] == list(
        range(9, 0, -1)
    )
    assert [page.floor_numbers for page in stack.pages] == [
        (9, 8, 7, 6, 5),
        (4, 3, 2, 1),
    ]
    assert stack.flow_regime == "gravity"


@pytest.mark.parametrize(
    ("floors", "expected"),
    [
        (1, (1,)),
        (4, (1, 4)),
        (5, (1, 4, 5)),
        (9, (1, 4, 7, 9)),
        (16, (1, 4, 7, 10, 13, 16)),
    ],
)
def test_revision_floors_follow_lower_upper_and_three_storey_spacing(
    floors, expected
):
    stack = build_wastewater_stack_assembly(floors_above=floors)
    assert stack.revision_floors == expected
    assert max((b - a for a, b in zip(expected, expected[1:])), default=0) <= 3


@pytest.mark.parametrize(
    ("roof_kind", "height"),
    [
        ("flat_non_accessible", 0.2),
        ("pitched", 0.2),
        ("collecting_vent_shaft", 0.1),
        ("flat_accessible", 3.0),
    ],
)
def test_vent_extension_uses_explicit_sp30_roof_case(roof_kind, height):
    stack = build_wastewater_stack_assembly(
        floors_above=3,
        roof_kind=roof_kind,
    )
    assert stack.vent_height_above_roof_m == height


def test_custom_floor_inputs_remain_local_to_the_selected_floor():
    custom = (
        FloorFixtureInput("К1-Мой-3", "sink", "Кухня"),
        FloorFixtureInput("К1-Ван-3", "bath", "Санузел"),
        FloorFixtureInput("К1-Ун-3", "toilet", "Санузел"),
    )
    stack = build_wastewater_stack_assembly(
        floors_above=4,
        fixtures_by_floor={3: custom},
    )
    assert [row.fixture_id for row in stack.floor(3).fixtures] == [
        "К1-Мой-3",
        "К1-Ван-3",
        "К1-Ун-3",
    ]
    assert len(stack.floor(2).fixtures) == 4


def test_stack_svgs_mark_every_floor_revisions_roof_and_page_continuations():
    stack = build_wastewater_stack_assembly(floors_above=9)
    pages = build_wastewater_stack_control_svgs(stack)

    assert len(pages) == 2
    combined = "".join(pages)
    assert combined.count('data-floor-assembly="') == 9
    for floor in range(1, 10):
        assert combined.count(f'data-stack-floor-label="{floor}"') == 1
    for floor in stack.revision_floors:
        assert combined.count(f'data-stack-revision-floor="{floor}"') == 1
    assert pages[0].count('data-roof="flat_non_accessible"') == 1
    assert 'продолжение на листе 2' in pages[0]
    assert 'продолжение с листа 1' in pages[1]
    assert "Напорная линия после КНС сюда не входит" in combined


def test_svg_decimal_comma_formatting_never_corrupts_numeric_coordinates():
    stack = build_wastewater_stack_assembly(floors_above=3)
    svg = build_wastewater_stack_control_svgs(stack)[0]
    root = ElementTree.fromstring(svg)
    for element in root.iter():
        for attribute in ("x", "y", "x1", "y1", "x2", "y2"):
            value = element.attrib.get(attribute)
            if value is not None:
                assert "," not in value


def test_stack_rejects_force_main_assumptions_and_invalid_inputs():
    with pytest.raises(ValueError, match="floors_above must be positive"):
        build_wastewater_stack_assembly(floors_above=0)
    with pytest.raises(ValueError, match="at least DN100"):
        build_wastewater_stack_assembly(floors_above=3, riser_dn_mm=50)
    with pytest.raises(ValueError, match="unsupported roof_kind"):
        build_wastewater_stack_assembly(floors_above=3, roof_kind="unknown")
    with pytest.raises(ValueError, match="unknown floors"):
        build_wastewater_stack_assembly(
            floors_above=3,
            fixtures_by_floor={4: ()},
        )


def test_stack_pdf_is_multipage_a1_landscape(tmp_path):
    output = tmp_path / "stack.pdf"
    generate_wastewater_stack_node_pdf(
        str(output),
        floors_above=9,
        max_floors_per_sheet=5,
    )
    pages = PdfReader(str(output)).pages
    assert len(pages) == 2
    for page in pages:
        width_mm = float(page.mediabox.width) * 25.4 / 72
        height_mm = float(page.mediabox.height) * 25.4 / 72
        assert width_mm == pytest.approx(841.0, abs=0.1)
        assert height_mm == pytest.approx(594.0, abs=0.1)
