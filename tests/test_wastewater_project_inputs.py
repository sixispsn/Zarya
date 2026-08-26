from pathlib import Path

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.generator import generate_wastewater_stack_node_pdf_from_project
from app.pz.project import Project, SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_project_inputs import (
    resolve_wastewater_basement_project_inputs,
    resolve_wastewater_stack_project_inputs,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _demo_project() -> Project:
    return build_project(load_request_file(str(DEMO)))


def _project_with_outlet() -> Project:
    project = Project()
    project.building.floors_above = 2
    project.sewage.basement_floor_elevation_m = -3.2
    project.sewage.pipes = [
        SewerPipeSpec(
            system="K1",
            section_id="К1-7",
            purpose="выпуск",
            nominal_diameter_mm=100,
            slope_per_mille=20.0,
            elevation_end_m=-1.75,
        )
    ]
    project.sewage.elements = [
        SewerElementSpec(
            element_id="К1-Вып1",
            system="K1",
            kind="outlet",
            section_id="К1-7",
        )
    ]
    return project


def test_resolver_uses_exact_outlet_element_link():
    result = resolve_wastewater_basement_project_inputs(_project_with_outlet())

    assert result.complete
    assert result.selection_status == "resolved"
    assert result.selected_section_id == "К1-7"
    assert result.outlet_id == "К1-7"
    assert result.basement_floor_elevation_m == -3.2
    assert result.outlet_invert_elevation_m == -1.75
    assert result.collector_slope_per_mille == 20.0
    assert result.outlet_dn_mm == 100


def test_resolver_never_picks_one_of_multiple_linked_outlets():
    project = _project_with_outlet()
    project.sewage.pipes.append(
        SewerPipeSpec(
            system="K1",
            section_id="К1-8",
            purpose="выпуск",
            nominal_diameter_mm=100,
            slope_per_mille=20.0,
            elevation_end_m=-1.9,
        )
    )
    project.sewage.elements.append(
        SewerElementSpec(
            element_id="К1-Вып2",
            system="K1",
            kind="outlet",
            section_id="К1-8",
        )
    )

    result = resolve_wastewater_basement_project_inputs(project)

    assert result.selection_status == "ambiguous"
    assert result.outlet_id == ""
    assert result.outlet_invert_elevation_m is None
    assert result.collector_slope_per_mille is None
    assert "outlet_id" in result.missing_project_inputs


def test_resolver_does_not_substitute_absolute_elevation_for_relative_invert():
    project = _project_with_outlet()
    project.sewage.pipes[0].elevation_end_m = None
    project.sewage.pipes[0].absolute_elevation_end_m = 146.25

    result = resolve_wastewater_basement_project_inputs(project)

    assert result.selection_status == "partial"
    assert result.outlet_invert_elevation_m is None
    assert "outlet_invert_elevation_m" in result.missing_project_inputs


def test_resolver_requires_explicit_nominal_outlet_dn():
    project = _project_with_outlet()
    project.sewage.pipes[0].nominal_diameter_mm = None

    result = resolve_wastewater_basement_project_inputs(project)

    assert result.selection_status == "partial"
    assert result.outlet_dn_mm is None
    assert "outlet_dn_mm" in result.missing_project_inputs


def test_stack_resolver_expands_every_floor_without_inventing_fixture_types():
    result = resolve_wastewater_stack_project_inputs(
        _demo_project(),
        riser_id="К1-Ст1",
    )

    assert result.complete
    assert result.selection_status == "resolved"
    assert result.riser_dn_mm == 100
    assert result.slope_dn50 == 0.03
    assert result.slope_dn100 == 0.02
    assert sorted(result.fixtures_by_floor) == list(range(1, 17))
    assert [
        (row.fixture_id, row.kind, row.dn_mm, row.quantity)
        for row in result.fixtures_by_floor[1]
    ] == [
        ("К1-Мой1", "sink", 50, 1),
        ("К1-Ун1", "toilet", 100, 2),
        ("К1-Ум1", "washbasin", 50, 2),
        ("К1-Ван1", "bath", 50, 1),
    ]


def test_stack_resolver_rejects_project_with_outlet_but_no_floor_branches():
    result = resolve_wastewater_stack_project_inputs(
        _project_with_outlet(),
        riser_id="К1-Ст1",
    )

    assert not result.complete
    assert result.fixtures_by_floor == {}
    assert any("не привязано ни одного" in row for row in result.diagnostics)


def test_stack_resolver_rejects_quantity_not_matching_floor_range():
    project = _demo_project()
    toilet = next(row for row in project.sewage.elements if row.element_id == "К1-Ун1")
    toilet.quantity = 31

    result = resolve_wastewater_stack_project_inputs(project, riser_id="К1-Ст1")

    assert not result.complete
    assert any("2 шт. x 16 этажей = 32 шт." in row for row in result.diagnostics)


def test_stack_resolver_rejects_conflicting_slopes_for_same_dn():
    project = _demo_project()
    sink = next(row for row in project.sewage.elements if row.element_id == "К1-Мой1")
    sink.slope_per_mille = 25.0

    result = resolve_wastewater_stack_project_inputs(project, riser_id="К1-Ст1")

    assert not result.complete
    assert any("DN50" in row and "разные уклоны" in row for row in result.diagnostics)


def test_project_bound_export_requires_explicit_floor_height_and_roof_case(tmp_path):
    with pytest.raises(TypeError, match="floor_height_m"):
        generate_wastewater_stack_node_pdf_from_project(
            str(tmp_path / "invalid.pdf"),
            _demo_project(),
        )


def test_stack_pdf_from_project_uses_registry_floors_fixtures_and_basement(tmp_path):
    output = tmp_path / "stack-from-project.pdf"

    generate_wastewater_stack_node_pdf_from_project(
        str(output),
        _demo_project(),
        riser_id="К1-Ст1",
        floor_height_m=3.0,
        roof_kind="flat_non_accessible",
        max_floors_per_sheet=5,
    )

    pages = PdfReader(str(output)).pages
    assert len(pages) == 5
    floor_text = "".join(page.extract_text() for page in pages[:-1])
    compact_floor_text = "".join(floor_text.split())
    assert compact_floor_text.count("К1-Мой1") == 16
    assert compact_floor_text.count("К1-Ун1") == 16
    assert "Унитаз;DN100;2шт." in compact_floor_text
    basement_text = pages[-1].extract_text()
    compact_text = "".join(basement_text.split())
    assert "ВыпускК1-Вып1DN150" in compact_text
    assert "отм.пола-3,200" in compact_text
    assert "отм.лотка-0,820" in compact_text
    assert "0,008" in basement_text
    assert "i=" not in basement_text
