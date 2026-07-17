from app.calc.fire_hydraulics import PumpDutyPoint, SourceKind
from app.pz.pump_bridge import compute_fire_pump_from_duty


def test_fire_pump_selected_by_main_duty_point():
    duty = PumpDutyPoint(
        required_head_m=70.0,
        flow_lps=2.6,
        source_kind=SourceKind.CITY_MAIN,
    )
    result = compute_fire_pump_from_duty(
        duty, npsh_a_m=8.0, maximum_source_head_m=30.0)
    assert result.required is True
    assert result.model == "Grundfos Hydro MX-A CR15-9"
    assert result.wp_q > 0 and result.wp_h > 0
    assert result.q_design_m3h == 9.36
    assert result.h_design_m == 70.0
    assert result.top3[0].type_label == "пожарный"
    assert "1 рабочий + 1 резервный" in result.count_note
    assert result.selection_note.startswith("Предварительный подбор")
    assert any("кавитации нет" in reason for reason in result.top3[0].reasons)
    assert result.pump_head_at_design_m >= result.h_design_m
    assert result.maximum_system_pressure_bar < result.top3[0].p_max_bar
    checks = {check.clause: check for check in result.sp10_checks}
    assert checks["12.1"].status == "verified"
    assert checks["12.3"].status == "specified"
    assert checks["12.27"].status == "specified"
    assert result.working_units == 1 and result.reserve_units == 1
    assert result.sp10_compliant is None  # размещение насосной подтверждает АР


def test_fire_pump_keeps_required_duty_when_catalog_has_no_candidate():
    duty = PumpDutyPoint(
        required_head_m=150.0,
        flow_lps=10.0,
        source_kind=SourceKind.RESERVOIR,
    )
    result = compute_fire_pump_from_duty(duty)
    assert result.required is True
    assert result.model == ""
    assert result.q_design_m3h == 36.0
    assert result.h_design_m == 150.0
    assert "Q=36.00" in result.selection_note
    assert "H=150.0" in result.selection_note


def test_fire_pump_not_selected_without_duty():
    assert compute_fire_pump_from_duty(None).required is False


def test_sp10_rejects_legacy_candidate_that_misses_full_duty_head():
    """Legacy допускает близкую точку, но В2 обязан дать Hрасч при полном Qрасч."""
    duty = PumpDutyPoint(
        required_head_m=100.0,
        flow_lps=2.0 / 3.6,
        source_kind=SourceKind.CITY_MAIN,
    )
    result = compute_fire_pump_from_duty(duty)
    assert result.model == ""
    assert result.sp10_compliant is False
    assert next(c for c in result.sp10_checks if c.clause == "12.1").status == "fail"


def test_pz_and_spec_show_separate_fire_pump_selection():
    from app.pz.generator import generate_pz_html
    from app.pz.project import FireSystem, Project
    from app.pz.spec import build_specification

    duty = PumpDutyPoint(
        required_head_m=70.0,
        flow_lps=2.6,
        source_kind=SourceKind.CITY_MAIN,
    )
    project = Project()
    project.fire = FireSystem(
        required=True, streams=1, q_per_stream=2.6, q_total=2.6,
        needs_pump=True, required_head_m=100.0, available_head_m=30.0,
    )
    project.fire_pumps = compute_fire_pump_from_duty(
        duty, npsh_a_m=8.0, maximum_source_head_m=30.0)

    html = generate_pz_html(project)
    assert "Grundfos Hydro MX-A CR15-9" in html
    assert "Расчётная точка системы" in html
    assert "1 рабочий + 1 резервный" in html
    assert "Проверка пожарной насосной установки по СП 10.13130.2020" in html
    assert "12.27" in html
    assert "<svg" in html

    fire_section = next(
        section for section in build_specification(project).sections
        if section.title.startswith("В2")
    )
    assert any("Установка пожарная насосная" in row.name for row in fire_section.rows)
