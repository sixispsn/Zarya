from pypdf import PdfReader

from app.pz.generator import generate_wastewater_stack_node_pdf_from_project
from app.pz.project import Project, SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_project_inputs import (
    resolve_wastewater_basement_project_inputs,
)


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


def test_stack_pdf_from_project_places_registry_values_on_basement_sheet(tmp_path):
    output = tmp_path / "stack-from-project.pdf"

    generate_wastewater_stack_node_pdf_from_project(
        str(output),
        _project_with_outlet(),
    )

    pages = PdfReader(str(output)).pages
    assert len(pages) == 2
    basement_text = pages[-1].extract_text()
    compact_text = "".join(basement_text.split())
    assert "ВыпускК1-7DN100" in compact_text
    assert "отм.пола-3,200" in compact_text
    assert "отм.лотка-1,750" in compact_text
    assert "0,020" in basement_text
    assert "i=" not in basement_text
