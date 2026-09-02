from copy import deepcopy
from pathlib import Path

from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.project import SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_pressure_drafting import (
    audit_wastewater_pressure_svgs,
    build_wastewater_pressure_svgs,
)
from app.pz.wastewater_pressure_project_inputs import (
    pressure_sewer_is_applicable,
    resolve_wastewater_pressure_project_inputs,
)
from app.pz.wastewater_pressure_scheme_service import (
    assess_wastewater_pressure_scheme_readiness,
    generate_wastewater_pressure_scheme,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _pressure_project():
    project = deepcopy(build_project(load_request_file(str(DEMO))))
    sewage = project.sewage
    sewage.pump_required = True
    sewage.pump_system = "K1"
    sewage.pump_mode = "local_fixture_unit"
    sewage.pump_fixture_count = 3
    sewage.pump_location = "техническое помещение УН-01"
    sewage.pump_model = "Насосная установка НК-4 (по паспорту проекта)"
    sewage.pump_q_m3h = 4.0
    sewage.pump_head_m = 6.0
    sewage.pump_power_kw = 1.1
    sewage.pump_static_head_m = 4.0
    sewage.pump_dynamic_loss_m = 2.0
    sewage.pump_curve = [(0.0, 8.0), (2.0, 7.0), (4.0, 6.0), (6.0, 4.0)]
    sewage.pump_curve_source = "Паспорт НК-4, лист 3"
    sewage.pump_hydraulic_source = "Расчётная схема НК-01, участки Н1"
    sewage.pump_working_units = 1
    sewage.pump_reserve_units = 1
    sewage.pump_discharge_node = "К1-М1"
    sewage.pump_reserve_note = "1 рабочий + 1 резервный"
    sewage.pump_power_category = "II категория"
    sewage.pump_automation_note = "Автоматический пуск по уровню; сигнал в диспетчерскую"
    sewage.pump_emergency_note = "Аварийный верхний уровень; запрет притока; сигнал диспетчеру"
    sewage.pipes.append(SewerPipeSpec(
        system="K1",
        section_id="К1-Н1",
        purpose="напорная линия от локальной установки",
        material="ПЭ 100 SDR17",
        standard="ГОСТ 18599-2001",
        outer_diameter_mm=50.0,
        wall_thickness_mm=3.0,
        length_m=18.0,
        calculation_length_m=24.0,
        nominal_diameter_mm=40,
        design_flow_lps=4.0 / 3.6,
        hydraulic_source="Расчётная схема НК-01, участок Н1",
        from_node="К1-НУ1",
        to_node="К1-М1",
        room="техническое помещение и коридор",
        elevation_start_m=-2.80,
        elevation_end_m=-0.20,
        pressure_rated=True,
        pressure_class_bar=10.0,
    ))
    sewage.elements.extend((
        SewerElementSpec(
            element_id="К1-Н1-Н",
            system="K1",
            kind="pump",
            name="Канализационный насос НК-4",
            quantity=2,
            dn_mm=40,
            section_id="К1-Н1",
            type_mark="НК-4",
        ),
        SewerElementSpec(
            element_id="К1-Н1-КО",
            system="K1",
            kind="check_valve",
            name="Клапан обратный",
            quantity=2,
            dn_mm=40,
            section_id="К1-Н1",
            type_mark="DN40 PN10",
        ),
        SewerElementSpec(
            element_id="К1-Н1-КШ",
            system="K1",
            kind="ball_valve",
            name="Кран шаровой",
            quantity=2,
            dn_mm=40,
            section_id="К1-Н1",
            type_mark="DN40 PN10",
        ),
        SewerElementSpec(
            element_id="К1-Н1-ПГ",
            system="K1",
            kind="pressure_break_loop",
            name="Петля гашения напора",
            quantity=1,
            dn_mm=40,
            section_id="К1-Н1",
            connects_to="К1-М1",
            type_mark="DN40",
        ),
    ))
    return project


def test_k2_pressure_pipes_do_not_activate_sewage_pump_contour():
    project = build_project(load_request_file(str(DEMO)))
    assert not pressure_sewer_is_applicable(project)


def test_resolver_accepts_confirmed_local_pressure_unit():
    inputs = resolve_wastewater_pressure_project_inputs(_pressure_project())
    assert inputs.complete, inputs.diagnostics
    assert inputs.system == "K1"
    assert [row.section_id for row in inputs.pressure_pipes] == ["К1-Н1"]
    assert inputs.working_point is not None
    assert round(inputs.working_point.q_m3h, 6) == 4.0
    assert round(inputs.working_point.pump_head_m, 6) == 6.0


def test_local_unit_requires_two_to_four_fixtures_and_pressure_break_loop():
    project = _pressure_project()
    project.sewage.pump_fixture_count = 5
    project.sewage.elements = [
        row for row in project.sewage.elements if row.kind != "pressure_break_loop"
    ]
    readiness = assess_wastewater_pressure_scheme_readiness(project)
    assert not readiness.ready
    assert any("от 2 до 4" in row for row in readiness.reasons)
    assert any("Петля гашения" in row for row in readiness.reasons)


def test_working_point_mismatch_is_blocking():
    project = _pressure_project()
    project.sewage.pump_head_m = 7.0
    inputs = resolve_wastewater_pressure_project_inputs(project)
    assert not inputs.complete
    assert any("не равен сумме" in row for row in inputs.diagnostics)


def test_internal_station_requires_registered_sump_and_emergency_volume():
    project = _pressure_project()
    sewage = project.sewage
    sewage.pump_mode = "internal_station"
    sewage.pump_fixture_count = None
    sewage.pump_receiver_useful_volume_m3 = 0.8
    sewage.pump_emergency_volume_m3 = 1.2
    sewage.pump_emergency_runtime_min = 30.0
    sewage.elements = [
        row for row in sewage.elements if row.kind != "pressure_break_loop"
    ]
    sewage.elements.append(SewerElementSpec(
        element_id="К1-НУ1-Р",
        system="K1",
        kind="sump",
        name="Приёмный резервуар",
        quantity=1,
        section_id="К1-Н1",
        type_mark="Vпол=0,8 м³",
    ))
    inputs = resolve_wastewater_pressure_project_inputs(project)
    assert inputs.complete, inputs.diagnostics
    assert inputs.sump_element is not None
    assert inputs.pressure_break_loop_element is None


def test_invalid_curve_is_a_diagnostic_not_a_crash():
    project = _pressure_project()
    project.sewage.pump_curve = [(0.0, 8.0), (0.0, 7.0), (4.0, 6.0)]
    inputs = resolve_wastewater_pressure_project_inputs(project)
    assert not inputs.complete
    assert any("возрастающий Q" in row for row in inputs.diagnostics)


def test_pressure_scheme_contains_registered_chain_and_working_point(tmp_path):
    project = _pressure_project()
    inputs = resolve_wastewater_pressure_project_inputs(project)
    svgs = build_wastewater_pressure_svgs(project, inputs)
    assert not audit_wastewater_pressure_svgs(inputs, svgs)
    assert 'data-pressure-section="К1-Н1"' in svgs[0]
    assert 'data-pressure-element="К1-Н1-ПГ"' in svgs[0]
    assert 'data-working-point="Q=4.000000;H=6.000000"' in svgs[1]

    output = tmp_path / "Схема_напорной_канализации.pdf"
    result = generate_wastewater_pressure_scheme(project, str(output))
    assert result.ready
    assert result.backend == "pressure-sewer-confirmed-curve-v1"
    assert len(PdfReader(output).pages) == 2


def test_incomplete_pressure_input_gets_honest_status_sheet(tmp_path):
    project = _pressure_project()
    project.sewage.pump_curve = []
    output = tmp_path / "status.pdf"
    result = generate_wastewater_pressure_scheme(project, str(output))
    assert not result.ready
    assert result.backend == "pressure-sewer-incomplete-status"
    assert any("минимум три точки" in row for row in result.reasons)
    assert len(PdfReader(output).pages) == 1
