"""Only the three meter corrections explicitly approved on 21.09.2026."""
from dataclasses import asdict, replace
import runpy

import pytest
from pydantic import ValidationError

from app.api.water_meters import calculate as api_calculate
from app.calc.meter_verification import MeterMinimumEvidence, validate_meter_minimum_checks
from app.calc.water_meters import MeterInput, _js_fixed3, calculate_meters
from app.intake.project_builder import build_project
from app.intake.studio_intake import build_handoff_request
from app.intake.yaml_io import dump_request, load_request
from app.pz.commission import build_commission_report
from app.pz.generator import generate_v1_calculation_html
from app.pz.ios2_orchestrator import design_ios2
from app.schemas.water_meters import MeterRequest


def inputs(**changes):
    return MeterInput(q_sec_c=10, q_sec_h=.3, q_day_c=15*24, q_day_h=1,
                      q_hr_c=99, q_hr_h=4, **changes)


def evidence(dn=65, q_min=.5, passport=.3):
    return MeterMinimumEvidence(dn, q_min, passport, "Паспорт модели/класса, лист 3", "Расчёт минимума, лист 2")


def test_dn65_sp_table_value_and_loss():
    cold = calculate_meters(inputs()).meters[0]
    assert cold.meter.d_mm == 65
    assert cold.meter.s == pytest.approx(.0081)
    assert cold.h_normal == .810  # SP 30 formula 18, not the legacy .081


def test_dn65_correction_propagates_to_selection():
    cold = calculate_meters(replace(inputs(), q_sec_c=20)).meters[0]
    assert cold.meter.d_mm == 80  # DN65: 3.24 > 2.5 m
    assert cold.h_normal == 1.056


def test_peak_flow_never_certifies_minimum_and_unknown_is_not_failure():
    result = calculate_meters(inputs())
    for row in result.meters:
        assert row.pass_sensitivity is None
        assert row.need_combo is False
        assert "Нужны данные" in row.minimum_flow_note


@pytest.mark.parametrize("q_min,passport,passed", [(.5,.3,True), (.3,.3,True), (.2,.3,False), (0,.3,False)])
def test_minimum_compares_real_passport_minimum_not_threshold(q_min, passport, passed):
    cold = calculate_meters(inputs(minimum_flow_checks={"cold": evidence(q_min=q_min, passport=passport)})).meters[0]
    assert cold.pass_sensitivity is passed
    assert cold.need_combo is (not passed)
    assert cold.minimum_flow_evidence.q_min_hourly_m3h == q_min


@pytest.mark.parametrize("changes", [
    {"dn_mm":15}, {"dn_mm":None}, {"q_min_hourly_m3h":None},
    {"q_min_passport_m3h":None}, {"passport_reference":" "}, {"flow_reference":""},
])
def test_incomplete_or_stale_passport_is_unknown(changes):
    cold = calculate_meters(inputs(minimum_flow_checks={"cold":replace(evidence(), **changes)})).meters[0]
    assert cold.pass_sensitivity is None and not cold.need_combo


def test_diameter_upgrade_does_not_reuse_passport_of_old_meter():
    cold = calculate_meters(replace(inputs(minimum_flow_checks={"cold":evidence()}),q_sec_c=20)).meters[0]
    assert cold.meter.d_mm == 80
    assert cold.pass_sensitivity is None
    assert "DN80" in cold.minimum_flow_note


@pytest.mark.parametrize("bad", [
    None, [], {"unknown":{}}, {"cold":{"wrong":1}}, {"cold":{"dn_mm":True}},
    {"cold":{"q_min_hourly_m3h":True}}, {"cold":{"q_min_hourly_m3h":float("nan")}},
    {"cold":{"q_min_hourly_m3h":float("inf")}}, {"cold":{"q_min_hourly_m3h":-1}},
    {"cold":{"q_min_passport_m3h":0}}, {"cold":{"passport_reference":123}},
])
def test_invalid_evidence_cannot_be_used_or_hidden(bad):
    with pytest.raises(ValueError):
        validate_meter_minimum_checks(bad)


def test_rounding_has_js_half_up_semantics_and_dn200_regression():
    assert _js_fixed3(.0625) == .063
    cold = calculate_meters(replace(inputs(),q_day_c=150*24)).meters[0]
    assert cold.meter.d_mm == 200
    assert cold.h_normal == .004


def test_api_exposes_unknown_and_accepts_independent_evidence():
    body = asdict(inputs())
    unknown = api_calculate(MeterRequest(**body))
    assert unknown.meters[0].pass_sensitivity is None
    body["minimum_flow_checks"] = {"cold":asdict(evidence())}
    verified = api_calculate(MeterRequest(**body))
    assert verified.meters[0].pass_sensitivity is True
    assert verified.meters[0].minimum_flow_evidence.passport_reference
    body["minimum_flow_checks"]["cold"]["q_min_hourly_m3h"] = True
    with pytest.raises(ValidationError):
        MeterRequest(**body)


def test_yaml_pipeline_pz_and_release_do_not_claim_missing_check_passed(tmp_path):
    draft = runpy.run_path("tests/test_t3_hydraulics.py")["draft"]()
    req = build_handoff_request(draft)
    # This test exercises explicit, synthetic passport evidence rather than
    # Studio's manufacturer-bound proposal (covered by test_meter_products).
    req.metering_detail.meter_selection_mode = "manual"
    bundle = design_ios2(build_project(req), output_dir=str(tmp_path), render_documents=False)
    row = next(x for x in bundle.commission_report.checks if x.code == "CALC-03")
    assert row.blocking and row.status == "missing"
    html = generate_v1_calculation_html(bundle.project)
    assert "Нужны данные" in html and "предварительно" in html
    before = build_commission_report(bundle.project).project_fingerprint

    # Explicit data per selected meter. Fixtures only: not project defaults.
    req.source_data.meter_minimum_checks = {
        key: asdict(evidence(dn=m.dn))
        for key, m in zip(("total", "cold", "hot"), bundle.project.meters.rows, strict=True)
    }
    restored = load_request(dump_request(req))
    assert restored.source_data.meter_minimum_checks == req.source_data.meter_minimum_checks
    checked = design_ios2(build_project(restored), output_dir=str(tmp_path), render_documents=False)
    assert not next(x for x in checked.commission_report.checks if x.code == "CALC-03").blocking
    assert all(r.ok_v is True for r in checked.project.meters.rows)
    assert build_commission_report(checked.project).project_fingerprint != before
    html = generate_v1_calculation_html(checked.project)
    assert "Паспорт модели/класса" in html and "Расчёт минимума, лист 2" in html


def test_wizard_preserves_meter_evidence_without_hydraulic_sections(tmp_path, monkeypatch):
    import asyncio
    from starlette.datastructures import FormData
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from app.intake.project_store import ProjectStore
    from app.web import wizard

    draft = runpy.run_path("tests/test_t3_hydraulics.py")["draft"]()
    req = build_handoff_request(draft)
    req.t3_sections = []
    req.source_data.meter_minimum_checks = {"cold":asdict(evidence(dn=15))}
    store = ProjectStore(str(tmp_path / "projects"))
    pid = store.save(req)
    monkeypatch.setattr(wizard, "_STORE", store)
    captured = []

    def capture(request, received, project_id):
        captured.append(received)
        return JSONResponse({"ok":True})

    monkeypatch.setattr(wizard, "design_request_response", capture)
    request = Request({"type":"http", "http_version":"1.1", "method":"POST",
                       "scheme":"http", "path":"/wizard/design", "root_path":"",
                       "query_string":b"", "headers":[], "server":("testserver",80)})
    request._form = FormData({
        "project_id":pid, "consumer1_name":"Жилая часть",
        "consumer1_code":"residential_full_bath", "consumer1_count":"20",
        "hws_type":"central", "hws_heater_in_scope":"on", "building_type":"residential",
        "floors":"2", "height":"6.6",
    })
    asyncio.run(wizard.wizard_design(request))
    assert captured[0].source_data.meter_minimum_checks == req.source_data.meter_minimum_checks
