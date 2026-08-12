from pathlib import Path

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_layout import audit_wastewater_layout
from app.pz.wastewater_layout_builder import build_wastewater_floor_stack
from app.pz.wastewater_structure_renderer import (
    WastewaterStructureScope,
    build_wastewater_structure_svg,
    generate_wastewater_structure_pdf,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_floor_stack_contains_every_floor_once_and_a_hatched_basement_slab():
    project = _project()
    result = build_wastewater_floor_stack(project)
    floors = [
        group.floors[0]
        for group in result.layout.floor_groups
        if group.kind == "floor"
    ]
    assert floors == list(range(16, 0, -1))
    assert len(floors) == project.building.floors_above
    assert not any(len(group.floors) > 1 for group in result.layout.floor_groups)
    assert any(group.kind == "technical" for group in result.layout.floor_groups)
    lower = next(group for group in result.layout.floor_groups if group.kind == "technical")
    assert lower.elevation_m is None
    foundation = [
        slab for slab in result.layout.slabs
        if slab.kind == "basement_foundation_slab"
    ]
    assert len(foundation) == 1
    assert foundation[0].hatch == "diagonal"
    assert foundation[0].frame.width / result.layout.sheet_width_mm == pytest.approx(
        0.596, abs=0.002,
    )
    assert audit_wastewater_layout(project, result.layout).ready


def test_floor_stack_svg_contains_all_floor_labels_and_hatch():
    project = _project()
    layout = build_wastewater_floor_stack(project).layout
    svg = build_wastewater_structure_svg(
        project, layout, scope=WastewaterStructureScope.FULL_FLOOR_STACK,
    )
    for floor in range(1, 17):
        assert f">{floor} этаж</text>" in svg
    assert "этажи 4–15 повторяются" not in svg
    assert 'id="diagonal-hatch"' in svg
    assert 'fill="url(#diagonal-hatch)"' in svg
    assert "Фундаментная плита подвала" in svg
    assert "отм. по АР" in svg
    assert "-0,720" not in svg


def test_stepwise_default_renders_only_the_foundation_stage():
    project = _project()
    layout = build_wastewater_floor_stack(project).layout
    svg = build_wastewater_structure_svg(project, layout)
    assert "Фундаментная плита подвала" in svg
    assert "Техническое подполье" in svg
    assert ">16 этаж</text>" not in svg
    assert "Контроль этажности" not in svg


def test_floor_stack_pdf_is_a1(tmp_path):
    project = _project()
    layout = build_wastewater_floor_stack(project).layout
    output = tmp_path / "floor-stack.pdf"
    generate_wastewater_structure_pdf(project, layout, str(output))
    page = PdfReader(str(output)).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    assert width_mm == pytest.approx(841.0, abs=0.02)
    assert height_mm == pytest.approx(594.0, abs=0.02)
