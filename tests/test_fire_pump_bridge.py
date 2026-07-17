from app.calc.fire_hydraulics import PumpDutyPoint, SourceKind
from app.pz.pump_bridge import compute_fire_pump_from_duty


def test_fire_pump_selected_by_main_duty_point():
    duty = PumpDutyPoint(
        required_head_m=70.0,
        flow_lps=2.6,
        source_kind=SourceKind.CITY_MAIN,
    )
    result = compute_fire_pump_from_duty(duty, npsh_a_m=8.0)
    assert result.required is True
    assert result.model == "Grundfos Hydro MX-A CR15-9"
    assert result.wp_q > 0 and result.wp_h > 0
    assert result.q_design_m3h == 9.36
    assert result.h_design_m == 70.0
    assert result.top3[0].type_label == "пожарный"
    assert "1 рабочий + 1 резервный" in result.count_note
    assert result.selection_note.startswith("Предварительный подбор")
    assert any("кавитации нет" in reason for reason in result.top3[0].reasons)


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
    project.fire_pumps = compute_fire_pump_from_duty(duty, npsh_a_m=8.0)

    html = generate_pz_html(project)
    assert "Grundfos Hydro MX-A CR15-9" in html
    assert "Расчётная точка системы" in html
    assert "1 рабочий + 1 резервный" in html
    assert "<svg" in html

    fire_section = next(
        section for section in build_specification(project).sections
        if section.title.startswith("В2")
    )
    assert any("Установка пожарная насосная" in row.name for row in fire_section.rows)
