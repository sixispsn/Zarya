"""Approved extension: normative boundaries, no stale totals, one shared kernel."""
from dataclasses import asdict, replace
import math

import pytest

from app.calc.t3_hydraulics import (
    KCIR_TABLE, T3SectionInput, calculate_t3_hydraulics, circulation_factor,
)
from app.calc.v1_hydraulics import V1SectionInput, calculate_v1_hydraulics
from app.intake.studio_hydraulics import validate_t3_sections
from app.intake.studio_intake import answer_field, build_handoff_request, head_missing
from app.intake.studio_project import calculate_project
from app.intake.yaml_io import dump_request, load_request
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from app.pz.generator import generate_pz_html, generate_v1_calculation_html


SECTION = T3SectionInput("Т3-1", 12, 26, .01, .4, "terminal", velocity_limit_mps=1)


def draft():
    d = dict(revision=0, answers={}, documents=[])
    for k, v in dict(residents=20, consumer_code="residential_full_bath", floors=2,
                     apartments=8, building_height_m=6.6, fire_height_m=4.8,
                     hws_type="central", guaranteed_head_m=5, h_geom_m=6,
                     pressure_loss_mode="ready", h_il_m=2, h_vvod_m=1,
                     hws_heater_in_scope="yes", h_tepl_m=3,
                     h_apartment_c_meter_m=.5, h_apartment_h_meter_m=.7,
                     t3_loss_mode="sections", t3_sections=[asdict(SECTION)]).items():
        answer_field(d, k, v)
    return d


@pytest.mark.parametrize("ratio,factor", KCIR_TABLE)
def test_appendix_g_exact_values(ratio, factor):
    assert circulation_factor(ratio) == factor
    s = replace(SECTION, flow_lps=ratio*.2, circulation_flow_lps=.2, flow_mode="main")
    result = calculate_t3_hydraulics([s])
    assert not result.missing
    assert result.sections[0]["flow_lps"] == round(s.flow_lps*(1+factor), 3)
    assert result.sections[0]["circulation_factor"] == factor


@pytest.mark.parametrize("ratio", [.1, 1.19, 1.25, 2.05])
def test_no_unapproved_interpolation_or_extrapolation(ratio):
    with pytest.raises(ValueError):
        circulation_factor(ratio)
    result = calculate_t3_hydraulics([replace(SECTION, flow_mode="main", circulation_flow_lps=.4/ratio)])
    assert result.total_loss_m is None and result.missing


def test_above_upper_threshold_and_roundoff_at_table_point():
    assert circulation_factor(10) == 0
    assert circulation_factor(.3/.2) == .4


def test_formula15_is_shared_with_existing_kernel_not_hot_viscosity_guess():
    actual = calculate_t3_hydraulics([SECTION])
    expected = calculate_v1_hydraulics([V1SectionInput(
        section_id=SECTION.section_id, length_m=12, inner_diameter_mm=26,
        roughness_mm=.01, flow_lps=.4, velocity_limit_mps=1,
    )])
    for key, value in asdict(expected.sections[0]).items():
        assert actual.sections[0][key] == value
    assert actual.total_loss_m == expected.total_loss_m
    assert actual.reference_temperature_c == 10
    # Independent arithmetic check of the turbulent branch (no engine call).
    v = .0004/(math.pi*.026**2/4)
    re = v*.026/1.307e-6
    friction = .25/math.log10(.00001/(3.7*.026)+5.74/re**.9)**2
    assert actual.total_loss_m == round(friction*v*v/(2*9.80665*.026)*12*1.3, 3)


@pytest.mark.parametrize("changes", [
    {"length_m": float("nan")}, {"flow_lps": float("inf")}, {"flow_lps": True},
    {"inner_diameter_mm": 0}, {"roughness_mm": -1}, {"flow_mode": {}},
    {"flow_mode": "bad"}, {"velocity_limit_mps": 0}, {"section_id": " "},
    {"circulation_flow_lps": .2},
])
def test_invalid_values_rejected_everywhere(changes):
    with pytest.raises(ValueError):
        calculate_t3_hydraulics([replace(SECTION, **changes)])
    with pytest.raises(ValueError):
        validate_t3_sections([{**asdict(SECTION), **changes}])


def test_missing_circulation_limit_and_corrected_source_do_not_become_zero():
    for changes in ({"flow_mode": "unknown"}, {"flow_mode": "main"},
                    {"velocity_limit_mps": None}, {"flow_mode": "corrected"}):
        result = calculate_t3_hydraulics([replace(SECTION, **changes)])
        assert result.missing and result.total_loss_m is None
    ready = calculate_t3_hydraulics([replace(SECTION, flow_mode="corrected", basis="Расчёт ГВС, лист 3")])
    assert ready.total_loss_m == calculate_t3_hydraulics([SECTION]).total_loss_m


def test_partial_path_keeps_rows_but_not_a_fake_total():
    result = calculate_t3_hydraulics([SECTION, replace(SECTION, section_id="Т3-2", flow_mode="main")])
    assert result.sections[0]["total_loss_m"] > 0
    assert result.sections[1]["missing"]
    assert result.total_loss_m is None


def test_live_total_does_not_add_local_losses_or_equipment_twice():
    d = draft()
    answer_field(d, "h_il_hot_m", 999)
    req = build_handoff_request(d)
    assert req.source_data.h_il_hot_m is None
    assert req.source_data.internal_losses_scope == "cold_only"
    result = calculate_project(d)
    cold, hot = result["head"]["paths"]
    assert result["head"]["ready"]
    total = result["hot_hydraulics"]["total_loss_m"]
    assert hot["head"]["h_losses_dynamic_m"] == round(total+1+3+hot["meter_loss_m"], 2)
    assert cold["head"]["h_losses_dynamic_m"] == round(2+1+cold["meter_loss_m"], 2)
    d["project_calculation"], d["preview"] = result, {"old": True}
    answer_field(d, "t3_sections", [asdict(replace(SECTION, flow_mode="main"))])
    assert d["project_calculation"] is None and d["preview"] is None
    assert "t3_sections" in head_missing(d)
    result = calculate_project(d)
    assert not result["head"]["ready"] and result["pumps"] is None
    assert result["head"]["paths"][1]["head"]["h_required_m"] is None
    answer_field(d, "t3_loss_mode", "ready")
    assert not build_handoff_request(d).t3_sections
    assert calculate_project(d)["head"]["ready"]


def test_yaml_and_reports_use_current_t3_and_velocity_gate(tmp_path):
    req = build_handoff_request(draft())
    restored = load_request(dump_request(req))
    assert restored.t3_sections == req.t3_sections
    bundle = design_ios2(build_project(restored), output_dir=str(tmp_path), render_documents=False)
    value = bundle.project.t3_hydraulic_result.total_loss_m
    for html in (generate_pz_html(bundle.project), generate_v1_calculation_html(bundle.project)):
        assert "Т3-1" in html and "10.11" in html
        assert f"{value:.3f}".replace(".", ",") in html
        assert "демонстрац" not in html.lower()
    assert not next(c for c in bundle.commission_report.checks if c.code == "CALC-T3").blocking
    restored.t3_sections = [replace(SECTION, velocity_limit_mps=.01)]
    bundle = design_ios2(build_project(restored), output_dir=str(tmp_path), render_documents=False)
    assert next(c for c in bundle.commission_report.checks if c.code == "CALC-T3").blocking


def test_no_hot_water_ignores_retained_hot_route_and_rejects_direct_dto():
    d = draft()
    answer_field(d, "hws_type", "none")
    assert not build_handoff_request(d).t3_sections
    assert "t3_sections" not in head_missing(d)
    req = build_handoff_request(draft())
    req.hws_type = "none"
    assert any("t3_sections" in error for error in req.validate())


def test_comma_numbers_and_duplicate_names():
    rows = validate_t3_sections([{**asdict(SECTION), "flow_lps": "0,4"}])
    assert rows[0]["flow_lps"] == .4
    with pytest.raises(ValueError):
        validate_t3_sections(rows * 2)


def test_explicit_ready_hot_mode_cannot_borrow_cold_total():
    d = draft()
    answer_field(d, "t3_loss_mode", "ready")
    assert "h_il_hot_m" in head_missing(d)
    result = calculate_project(d)
    assert not result["head"]["ready"]
    assert result["head"]["paths"][1]["head"]["h_required_m"] is None


def test_t3_input_changes_commission_fingerprint():
    from app.pz.commission import _project_fingerprint
    project = build_project(build_handoff_request(draft()))
    before = _project_fingerprint(project)
    project.t3_sections = [replace(SECTION, length_m=20)]
    assert before != _project_fingerprint(project)


@pytest.mark.parametrize("changed", [False, True])
def test_full_editor_preserves_t3_without_v1_sections(tmp_path, monkeypatch, changed):
    import asyncio
    from starlette.datastructures import FormData
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from app.intake.project_store import ProjectStore
    from app.web import wizard

    req = build_handoff_request(draft())
    assert not req.v1_sections
    store = ProjectStore(str(tmp_path / "projects"))
    pid = store.save(req)
    monkeypatch.setattr(wizard, "_STORE", store)
    captured = []

    def capture(request, received, project_id):
        captured.append(received)
        return JSONResponse({"ok": True})

    monkeypatch.setattr(wizard, "design_request_response", capture)
    request = Request({"type": "http", "http_version": "1.1", "method": "POST",
                       "scheme": "http", "path": "/wizard/design", "root_path": "",
                       "query_string": b"", "headers": [], "server": ("testserver", 80)})
    request._form = FormData({
        "project_id": pid, "consumer1_name": "Жилая часть",
        "consumer1_code": "residential_full_bath", "consumer1_count": "100" if changed else "20",
        "hws_type": "central", "hws_heater_in_scope": "on", "building_type": "residential",
        "floors": "2", "height": "6.6",
    })
    response = asyncio.run(wizard.wizard_design(request))
    if changed:
        assert not captured and "Пересчитайте участки В1 и Т3" in response.body.decode()
    else:
        assert captured[0].t3_sections == req.t3_sections
