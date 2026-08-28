from copy import deepcopy
from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.generator import generate_wastewater_scheme_result
from app.pz.project import SewerElementSpec
from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_demo_resolves_flow_and_keeps_explicit_lower_turn_access():
    result = assess_wastewater_diagnostics(_project())
    assert not result.ready
    assert any("К1-М1" in row and "0–52 м" in row for row in result.errors)
    assert any("К2-М1" in row and "достижимость" in row for row in result.errors)
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
    assert {row.status for row in result.linear_service_checks} == {
        "verified", "fail",
    }
    assert {row.status for row in result.ventilation_checks} == {"verified"}
    risks = {row.zone_id: row for row in result.risk_zones}
    main_risk = risks["transient:К1-М1"]
    assert main_risk.serviced is False
    assert main_risk.access_element_ids == (
        "К1-Р1-1",
        "К1-Р2-1",
    )
    assert "одноячейковая модель не локализует" in main_risk.location_note
    assert "выбрать ревизию либо прочистку" in main_risk.placement_rule
    outlet_risk = risks["transient:К1-Вып1"]
    assert outlet_risk.access_element_ids == ("К1-Р2-1", "К1-ВыпЭ1")
    assert "дополнительная прочистка не требуется" in outlet_risk.placement_rule


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
        row for row in project.sewage.elements
        if row.element_id != "К2-ПрНП1"
    ]
    result = assess_wastewater_diagnostics(project)
    assert any("К1-М1" in row and "достижимость" in row for row in result.errors)

    project = deepcopy(_project())
    project.sewage.elements = [
        row for row in project.sewage.elements
        if row.element_id != "К2-ПрНП1"
    ]
    project.sewage.elements.append(SewerElementSpec(
        element_id="К2-Проверка-доступа",
        system="K2",
        kind="cleanout",
        name="Явно заданная проверочная прочистка",
        floor_from=0,
        dn_mm=100,
        section_id="К2-М1",
        connects_to="К2-Ст1",
        service_direction="upstream",
        service_fitting="wye_45",
        accessible=True,
    ))
    result = assess_wastewater_diagnostics(project)
    assert any("К2-Ст1" in row and "нет подтверждённого" in row for row in result.errors)


def test_vacuum_valves_do_not_replace_group_connection_to_atmosphere():
    project = deepcopy(_project())
    for riser in project.sewage.risers:
        riser.ventilation = "vacuum_valve"
    result = assess_wastewater_diagnostics(project)
    assert any("нет вентилируемого стояка" in row for row in result.errors)


def test_diagnostic_svg_contains_flow_sediment_and_real_cable_reach():
    result = generate_wastewater_scheme_result(_project(), diagnostics=True)
    assert any("К1-М1" in row and "0–52 м" in row for row in result.warnings)
    assert 'data-diagnostic-layer="true"' in result.svg
    assert result.svg.count('class="ww-flow"') > 10
    assert 'data-sediment-zone="turn:К1-Ст1"' in result.svg
    assert 'data-service-path="К1-ПрНП1"' in result.svg
    assert 'data-service-linear=' not in result.svg
    assert result.svg.count('data-draft-segment="cleanout_access"') == 4
    assert 'data-segment-dn="50"' in result.svg
    assert 'data-segment-dn="100"' in result.svg
    assert (
        'data-sediment-zones="service:К1-М1 transient:К1-М1"'
        in result.svg
    )
    assert "возможны отложения; требуется точка доступа" in result.svg
