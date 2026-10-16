from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from pypdf import PdfReader

from app.pz.architecture_section_engine import (
    ArchitectureBarrierPlan,
    PlanPoint,
    PlanRect,
    architecture_section_to_wastewater_layout,
    audit_architecture_plan_registry,
    build_architecture_section,
    build_architecture_section_control_svg,
    generate_architecture_section_control_pdf,
    load_architecture_plan_registry,
)
from app.pz.project import Project
from app.pz.wastewater_structure_renderer import (
    WastewaterStructureScope,
    build_wastewater_structure_svg,
)


DEMO = Path(__file__).parents[1] / "demo" / "architecture_section_registry.json"


def _registry():
    return load_architecture_plan_registry(DEMO)


def test_plan_cut_preserves_confirmed_room_order_numbers_and_sources():
    model = build_architecture_section(_registry())
    floor = model.floor(6)

    assert [row.room_id for row in floor.cells] == [
        "F6-601",
        "F6-602",
        "F6-603",
        "F6-604",
        "F6-605",
        "F6-606",
        "F6-607",
        "F6-608",
    ]
    assert [(row.start_m, row.end_m) for row in floor.cells] == [
        (0.0, 4.0),
        (4.0, 8.0),
        (8.0, 10.0),
        (10.0, 14.0),
        (14.0, 16.0),
        (16.0, 18.0),
        (18.0, 21.0),
        (21.0, 24.0),
    ]
    assert floor.cells[0].number == "601"
    assert floor.cells[0].name == "Кухня"
    assert "экспликация 6 этажа" in floor.cells[0].source_ref


def test_only_equal_typical_architecture_is_collapsed():
    model = build_architecture_section(_registry())

    assert model.displayed_floor_numbers == (6, 2, 1, 0)
    assert model.collapsed_floor_ranges == ((3, 5),)

    registry = _registry()
    changed_room = replace(registry.floors[3].rooms[0], name="Кухня-ниша")
    changed_floor = replace(
        registry.floors[3],
        rooms=(changed_room,) + registry.floors[3].rooms[1:],
    )
    registry = replace(
        registry,
        floors=registry.floors[:3] + (changed_floor,) + registry.floors[4:],
    )

    assert build_architecture_section(registry).displayed_floor_numbers == (
        6,
        5,
        4,
        3,
        2,
        1,
        0,
    )


def test_audit_rejects_missing_labels_and_unproved_cut_geometry():
    registry = _registry()
    unlabeled = replace(registry.floors[1].rooms[0], name="")
    floor = replace(
        registry.floors[1],
        rooms=(unlabeled,) + registry.floors[1].rooms[1:],
    )
    registry = replace(
        registry,
        floors=(registry.floors[0], floor) + registry.floors[2:],
    )
    assert "room.label" in {
        row.code for row in audit_architecture_plan_registry(registry)
    }

    registry = _registry()
    shortened = replace(
        registry.floors[1].rooms[0],
        bounds=PlanRect(0.0, 0.0, 3.0, 10.0),
    )
    floor = replace(
        registry.floors[1],
        rooms=(shortened,) + registry.floors[1].rooms[1:],
    )
    registry = replace(
        registry,
        floors=(registry.floors[0], floor) + registry.floors[2:],
    )
    assert "floor.coverage" in {
        row.code for row in audit_architecture_plan_registry(registry)
    }


def test_audit_rejects_room_overlap_and_nonintersecting_barrier():
    registry = _registry()
    overlapping = replace(
        registry.floors[1].rooms[1],
        bounds=PlanRect(3.5, 0.0, 4.5, 10.0),
    )
    barrier = ArchitectureBarrierPlan(
        barrier_id="F1-FW-OFF-CUT",
        kind="противопожарная стена",
        start=PlanPoint(12.0, 7.0),
        end=PlanPoint(12.0, 9.0),
        source_ref="АР-КОНТРОЛЬ-01, вне разреза",
    )
    floor = replace(
        registry.floors[1],
        rooms=(registry.floors[1].rooms[0], overlapping)
        + registry.floors[1].rooms[2:],
        barriers=registry.floors[1].barriers + (barrier,),
    )
    registry = replace(
        registry,
        floors=(registry.floors[0], floor) + registry.floors[2:],
    )

    codes = {row.code for row in audit_architecture_plan_registry(registry)}
    assert "floor.overlap" in codes
    assert "barrier.cut" in codes


def test_wastewater_adapter_contains_only_architecture_registry_spaces():
    model = build_architecture_section(_registry())
    layout = architecture_section_to_wastewater_layout(model)

    assert layout.mode.value == "confirmed_architecture"
    assert [row.floors for row in layout.floor_groups] == [(6,), (2,), (1,), (0,)]
    expected = {
        f"section-{floor.floor}-{cell.room_id}"
        for floor in model.floors
        if floor.floor in model.displayed_floor_numbers
        for cell in floor.cells
    }
    assert {row.space_id for row in layout.spaces} == expected
    assert not any("Пом." in row.label for row in layout.spaces)
    assert layout.slabs[0].kind == "basement_foundation_slab"
    assert layout.slabs[0].hatch == "diagonal"


def test_control_svg_has_rooms_barriers_and_typical_floor_break():
    svg = build_architecture_section_control_svg(build_architecture_section(_registry()))

    assert 'data-section-room="F6-601"' in svg
    assert 'data-room-number="601"' in svg
    assert 'data-room-name="Кухня"' in svg
    assert 'data-section-barrier="F6-FW-1"' in svg
    assert 'data-collapsed-architecture-floors="3-5"' in svg
    assert "этажи 3-5 не показаны" in svg


def test_control_sheet_keeps_visible_nonproject_status_and_input_registry():
    registry = _registry()
    original_registry = deepcopy(registry)
    model = build_architecture_section(registry)
    original_model = deepcopy(model)
    root = ET.fromstring(build_architecture_section_control_svg(model))
    labels = ["".join(element.itertext()) for element in root.iter()
              if element.tag == "{http://www.w3.org/2000/svg}text"]

    # The disclaimer must remain printable text, not only metadata / a comment.
    assert any("Контрольный модуль" in label for label in labels)
    assert any("Контрольный лист компонента, не лист проектной документации." in label
               for label in labels)
    assert any(model.source_ref in label for label in labels)
    assert registry == original_registry
    assert model == original_model


def test_generator_wrapper_uses_control_export_without_project_conversion(tmp_path, monkeypatch):
    import app.pz.architecture_section_engine as engine
    from app.pz.generator import generate_architecture_section_node_pdf

    calls = []
    output = str(tmp_path / "component-control.pdf")

    def record_control_export(output_path, registry):
        calls.append((output_path, registry))
        return output_path

    monkeypatch.setattr(engine, "generate_architecture_section_control_pdf", record_control_export)
    assert generate_architecture_section_node_pdf(str(DEMO), output) == output
    assert calls == [(output, _registry())]


def test_confirmed_layout_renderer_keeps_storeys_rooms_and_typical_break():
    model = build_architecture_section(_registry())
    layout = architecture_section_to_wastewater_layout(model)

    svg = build_wastewater_structure_svg(
        Project(),
        layout,
        scope=WastewaterStructureScope.FULL_FLOOR_STACK,
    )

    assert 'data-layout-mode="confirmed_architecture"' in svg
    assert 'data-building-roof-boundary="true"' in svg
    assert svg.count('data-building-storey-boundary="') == 3
    assert 'data-collapsed-architecture-floors="3-5"' in svg
    assert "этажи 3-5 не показаны" in svg
    assert "№601 Кухня" in svg
    assert "№001 Техническое помещение" in svg


def test_control_pdf_is_vector_a1_landscape(tmp_path):
    output = tmp_path / "architecture-section.pdf"
    generate_architecture_section_control_pdf(str(output), _registry())

    page = PdfReader(str(output)).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    text = page.extract_text() or ""
    assert width_mm == pytest.approx(841.0, abs=0.02)
    assert height_mm == pytest.approx(594.0, abs=0.02)
    assert "План" in text
    assert "принципиальный" in text
    assert "разрез" in text
    assert "№601" in text
    assert "Кухня" in text
