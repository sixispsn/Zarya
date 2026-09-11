from copy import deepcopy
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_layout import (
    PointMm,
    RectMm,
    WastewaterLayoutMode,
    WastewaterLayoutSource,
    WastewaterNodePlacement,
    WastewaterRoutePlacement,
    WastewaterSpace,
    audit_wastewater_layout,
)
from app.pz.wastewater_layout_builder import build_wastewater_floor_stack
from app.pz.wastewater_scheme_service import (
    assess_confirmed_architecture_basement_readiness,
    assess_wastewater_scheme_readiness,
    generate_wastewater_scheme,
)
from app.pz.wastewater_topology import build_wastewater_topology


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def _confirmed_axis_layout(project, *, omit: str = ""):
    layout = build_wastewater_floor_stack(project).layout
    layout.mode = WastewaterLayoutMode.CONFIRMED_ARCHITECTURE
    ordered_groups = sorted(layout.floor_groups, key=lambda row: row.y_mm)
    previous_y = ordered_groups[0].y_mm
    for group in ordered_groups[1:]:
        if group.kind != "floor":
            continue
        layout.spaces.append(WastewaterSpace(
            space_id=f"confirmed-{group.group_id}",
            group_id=group.group_id,
            label=f"№{group.floors[0]:02d} Подтверждённый этаж",
            frame=RectMm(170.0, previous_y, 501.0, group.y_mm - previous_y),
            source=WastewaterLayoutSource.ARCHITECTURE,
            source_ref="контрольный подтверждённый разрез АР",
        ))
        previous_y = group.y_mm
    topology = build_wastewater_topology(project)
    axes = {
        "К2-Ст1": 270.2,
        "К1-Ст1": 370.4,
        "К2-Ст2": 470.6,
        "К1-Ст2": 570.8,
    }
    for riser_id, x in axes.items():
        if riser_id == omit:
            continue
        pipe = topology.risers[riser_id]
        start_id = f"confirmed-{riser_id}-vent"
        end_id = f"confirmed-{riser_id}-base"
        start = PointMm(x, 60.0)
        end = PointMm(x, 360.0)
        layout.nodes.extend((
            WastewaterNodePlacement(
                start_id,
                pipe.from_node,
                pipe.system,
                start,
                kind="vent",
                source=WastewaterLayoutSource.MANUAL_CONFIRMED,
                source_ref="ось подтверждена по разрезу АР",
            ),
            WastewaterNodePlacement(
                end_id,
                pipe.to_node,
                pipe.system,
                end,
                kind="riser_base",
                source=WastewaterLayoutSource.MANUAL_CONFIRMED,
                source_ref="ось подтверждена по разрезу АР",
            ),
        ))
        layout.routes.append(WastewaterRoutePlacement(
            route_id=f"confirmed-{riser_id}-vertical",
            section_id=riser_id,
            system=pipe.system,
            from_placement_id=start_id,
            to_placement_id=end_id,
            points=(start, end),
            source=WastewaterLayoutSource.MANUAL_CONFIRMED,
            source_ref="ось подтверждена по разрезу АР",
        ))
    assert audit_wastewater_layout(project, layout).ready
    return layout


def test_canonical_release_uses_registry_building_pdf(tmp_path):
    output = tmp_path / "scheme.pdf"

    result = generate_wastewater_scheme(_project(), str(output))

    assert result.ready
    assert result.backend == "registry-building-v2-paginated"
    pages = PdfReader(str(output)).pages
    assert len(pages) == 2
    all_text = "\n".join(page.extract_text() or "" for page in pages)
    assert "ZARYA-DEMO-001-ИОС3.СК" in all_text
    assert "ZARYA-DEMO-001-ИОС2" not in all_text
    assert all(
        float(page.mediabox.width) * 25.4 / 72 == pytest.approx(841.0, abs=0.02)
        for page in pages
    )


def test_confirmed_architecture_release_adds_isolated_basement_sheets(tmp_path):
    project = _project()
    layout = _confirmed_axis_layout(project)
    readiness = assess_wastewater_scheme_readiness(project)

    basement = assess_confirmed_architecture_basement_readiness(
        layout,
        readiness.project_inputs,
    )
    result = generate_wastewater_scheme(
        project,
        str(tmp_path / "confirmed.pdf"),
        confirmed_layout=layout,
    )

    assert basement.ready
    assert result.backend == "confirmed-architecture-layout-v2-basement"
    pages = PdfReader(result.output_path).pages
    assert len(pages) == 3
    text = ["".join((page.extract_text() or "").split()) for page in pages]
    assert "Подтверждённыйэтаж" in text[0]
    assert "ВыпускК1-Вып1DN150заграньздания" in text[1]
    assert "ВыпускК2-Вып1DN150заграньздания" in text[2]
    assert all("К1·стояки" not in row for row in text[2:])


def test_confirmed_architecture_does_not_invent_basement_for_missing_axis(tmp_path):
    project = _project()
    layout = _confirmed_axis_layout(project, omit="К2-Ст2")
    readiness = assess_wastewater_scheme_readiness(project)

    basement = assess_confirmed_architecture_basement_readiness(
        layout,
        readiness.project_inputs,
    )
    result = generate_wastewater_scheme(
        project,
        str(tmp_path / "partial.pdf"),
        confirmed_layout=layout,
    )

    assert not basement.ready
    assert basement.missing_riser_ids == ("К2-Ст2",)
    assert result.backend == "confirmed-architecture-layout-v1"
    assert "К2-Ст2" in " ".join(result.reasons)
    assert len(PdfReader(result.output_path).pages) == 1


def test_missing_terminal_cleanout_produces_status_without_synthetic_fitting(
    tmp_path,
):
    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements
        if row.element_id != "К1-ПрНП1"
    ]

    readiness = assess_wastewater_scheme_readiness(project)
    result = generate_wastewater_scheme(project, str(tmp_path / "blocked.pdf"))

    assert not readiness.ready
    assert any("соосным заглушённым концом" in row for row in readiness.reasons)
    assert not result.ready
    assert result.backend == "incomplete-status"
    reader = PdfReader(result.output_path)
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text() or ""
    assert "ПРИНЦИПИАЛЬНАЯ СХЕМА НЕ СФОРМИРОВАНА" in text
    assert "Прочистка" not in text


def test_transition_not_linked_to_real_dn_change_blocks_release():
    project = deepcopy(_project())
    transition = next(
        row for row in project.sewage.elements
        if row.element_id == "К1-Пер1"
    )
    transition.connects_to = "КК-1"

    readiness = assess_wastewater_scheme_readiness(project)

    assert not readiness.ready
    assert any("перехода" in row for row in readiness.reasons)
    assert any("не привязан" in row for row in readiness.reasons)


def test_capped_cleanout_on_through_node_is_rejected():
    project = deepcopy(_project())
    cleanout = deepcopy(next(
        row for row in project.sewage.elements
        if row.element_id == "К1-ПрНП1"
    ))
    cleanout.element_id = "К1-ПрНП2-Запрещённая"
    cleanout.section_id = "К1-Вып1"
    cleanout.connects_to = "К1-Ст2"
    project.sewage.elements.append(cleanout)

    readiness = assess_wastewater_scheme_readiness(project)

    assert not readiness.ready
    assert any(
        "К1-Ст2" in row and "прочистка с заглушкой недопустима" in row
        for row in readiness.reasons
    )


def test_explicit_scheme_geometry_is_required_without_defaults():
    project = deepcopy(_project())
    project.sewage.floor_height_m = None
    project.sewage.roof_kind = "unknown"

    readiness = assess_wastewater_scheme_readiness(project)

    assert not readiness.ready
    assert any("высота типового этажа" in row for row in readiness.reasons)
    assert any("вид и доступность кровли" in row for row in readiness.reasons)
