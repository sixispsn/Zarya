from copy import deepcopy
from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.generator import generate_wastewater_scheme_result
from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_demo_resolves_flow_and_passes_hydraulics_service_and_ventilation():
    result = assess_wastewater_diagnostics(_project())
    assert result.ready
    assert result.errors == []
    assert result.resolved_flows_lps == {"К1-М1": 2.758, "К1-Вып1": 5.516}
    assert {row.status for row in result.hydraulics} == {"verified"}
    assert {row.status for row in result.diameter_checks} == {"verified"}
    sanitary_segments = [
        row.generated_segment_dn_mm for row in result.diameter_checks
        if row.section_id == "К1-Ветв-СУ1"
    ]
    assert sanitary_segments == [50, 50, 100]
    assert {row.status for row in result.network_diameter_checks} == {"verified"}
    assert {row.status for row in result.turn_checks} == {"verified"}
    assert {row.status for row in result.linear_service_checks} == {"verified"}
    assert {row.status for row in result.ventilation_checks} == {"verified"}


def test_toilet_and_its_branch_cannot_be_less_than_dn100():
    project = deepcopy(_project())
    toilet = next(row for row in project.sewage.elements if row.element_id == "К1-Ун1")
    toilet.dn_mm = 50
    branch = next(row for row in project.sewage.pipes if row.section_id == "К1-Ветв-СУ1")
    branch.nominal_diameter_mm = 50
    result = assess_wastewater_diagnostics(project)
    assert not result.ready
    assert any("К1-Ун1" in row and "минимума 100" in row for row in result.errors)


def test_dn_increase_requires_explicit_transition_and_never_reduces_downstream():
    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements if row.element_id != "К1-Пер1"
    ]
    result = assess_wastewater_diagnostics(project)
    assert any("К1-Вып1" in row and "не подтверждено переходом" in row for row in result.errors)

    project = deepcopy(_project())
    outlet = next(row for row in project.sewage.pipes if row.section_id == "К1-Вып1")
    outlet.nominal_diameter_mm = 50
    result = assess_wastewater_diagnostics(project)
    assert any("К1-Вып1" in row and "уменьшается по потоку" in row for row in result.errors)


def test_linear_service_gap_and_wrong_cleanout_direction_are_blocking():
    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements if row.element_id != "К1-ПрМ1-50"
    ]
    result = assess_wastewater_diagnostics(project)
    assert any("К1-М1" in row and "достижимость" in row for row in result.errors)

    project = deepcopy(_project())
    cleanout = next(row for row in project.sewage.elements if row.element_id == "К2-Пр1")
    cleanout.service_direction = "upstream"
    result = assess_wastewater_diagnostics(project)
    assert any("К2-Ст1" in row and "троса" in row for row in result.errors)


def test_vacuum_valves_do_not_replace_group_connection_to_atmosphere():
    project = deepcopy(_project())
    for riser in project.sewage.risers:
        riser.ventilation = "vacuum_valve"
    result = assess_wastewater_diagnostics(project)
    assert any("нет вентилируемого стояка" in row for row in result.errors)


def test_diagnostic_svg_contains_flow_sediment_and_real_cable_reach():
    result = generate_wastewater_scheme_result(_project(), diagnostics=True)
    assert result.warnings == []
    assert 'data-diagnostic-layer="true"' in result.svg
    assert result.svg.count('class="ww-flow"') > 10
    assert 'data-sediment-zone="turn:К1-Ст1"' in result.svg
    assert 'data-service-path="К1-Р1-1"' in result.svg
    assert 'data-service-linear="К1-ПрМ1-10"' in result.svg
    assert 'data-service-range-m="10:20"' in result.svg
    assert 'data-segment-dn="50"' in result.svg
    assert 'data-segment-dn="100"' in result.svg
