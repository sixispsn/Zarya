"""Optional requirements survive exports but never masquerade as hardware."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.intake.project_builder import build_project
from app.intake.request_dto import IOS2Request, DocumentRequest
from app.intake.yaml_io import dump_request, load_request, YamlFormatError
from app.pz.generator import generate_pz_html, generate_spec_html, generate_v1_calculation_html
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_options import METERING_OPTIONS, OPTIONS_NOTICE, option_requests
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_rules import evaluate_metering_rules, remote_readout_required
from scripts.preview_metering_detail import catalogue_review_project
from tests import test_studio as studio_tests

client = studio_tests.client


def wishes():
    return {"technology": "ultrasonic", "telemetry": "nb_iot",
            "leak_monitoring": "requested", "tamper_monitoring": "requested",
            "valve_feedback": "requested", "assembly": "factory_module",
            "magnetic_filter": "requested", "power": "battery"}


def test_optional_choices_are_decisions_not_consideration(client):
    state = studio_tests.new(client)
    for key in ("leak_monitoring", "tamper_monitoring", "valve_feedback", "magnetic_filter"):
        options = state["options"]["vu_" + key]
        assert next(row["label"] for row in options if row["value"] == "requested") == "Да — подобрать оборудование"
        assert all("рассмотр" not in row["label"].lower() for row in options)
    project = catalogue_review_project()
    project.metering_detail.enhancements = wishes()
    assert all("рассмотр" not in row.note.lower() for row in build_metering_spec_section(project).rows)


def test_optional_settings_have_no_defaults_or_required_questions(client):
    state = studio_tests.residential_project(client)
    fields = studio_tests.values(state)
    for key in METERING_OPTIONS:
        assert fields["vu_" + key]["value"] is None
        assert fields["vu_" + key]["status"] == "missing"
    calculated = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    assert calculated["project_calculation"]["metering_options"] == []
    assert calculated["can_calculate"]
    assert "vu_" not in str(calculated["next_steps"])


def test_studio_roundtrip_removal_and_calculation_invariance(client):
    state = studio_tests.residential_project(client)
    baseline = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    state = baseline
    for key, value in wishes().items():
        state = studio_tests.answer(client, state, "vu_" + key, value)
    restored = client.get("/studio/api/draft").json()
    fields = studio_tests.values(restored)
    assert {k: fields["vu_" + k]["value"] for k in wishes()} == wishes()
    result = client.post("/studio/api/calculate", json={"revision": restored["revision"]}).json()
    assert result["calculation"] == baseline["calculation"]
    for key in ("flows", "head", "pumps", "fire", "storm"):
        assert result["project_calculation"][key] == baseline["project_calculation"][key]
    # A non-mechanical wish withdraws the mechanical PRODUCT approval, not its
    # legacy reference calculation. Do not demand stale passport metadata.
    for actual, old in zip(result["project_calculation"]["meters"], baseline["project_calculation"]["meters"]):
        for key in ("dn", "s_resist", "h_a", "h_b", "qexpl", "qmax", "need_bypass"):
            assert actual[key] == old[key]
        assert actual["product"]["errors"] and not actual["product"]["id"]
    assert len(result["project_calculation"]["metering_options"]) == 8
    for key in wishes():
        result = studio_tests.answer(client, result, "vu_" + key, None)
    result = client.post("/studio/api/calculate", json={"revision": result["revision"]}).json()
    assert result["project_calculation"]["metering_options"] == []


def test_yaml_and_builder_keep_wishes_separate_from_components():
    req = IOS2Request(document=DocumentRequest("", "", ""),
        building_type="residential", floors=2, building_height_m=6.6, fire_height_m=3.3,
        metering_detail=MeteringDetailData(enhancements=wishes()))
    restored = load_request(dump_request(req))
    assert restored.metering_detail == req.metering_detail
    project = build_project(restored)
    assert project.metering_detail.enhancements == wishes()
    project.metering_detail.enhancements.clear()
    assert restored.metering_detail.enhancements == wishes()


@pytest.mark.parametrize("bad", [{"telemetry": "magic"}, {"technology": True},
                                  {"unknown": "requested"}, [], None])
def test_unrecognised_or_malformed_saved_options_rejected(bad):
    detail = MeteringDetailData(enhancements=bad)
    assert detail.validate()
    with pytest.raises(ValueError):
        option_requests(detail)
    with pytest.raises(YamlFormatError):
        load_request(dump_request(IOS2Request(document=DocumentRequest("", "", ""),
            building_type="residential", floors=2, building_height_m=6.6,
            metering_detail=detail)))


@pytest.mark.parametrize("key", list(METERING_OPTIONS))
def test_api_rejects_unknown_option_values(client, key):
    state = studio_tests.new(client)
    result = client.patch("/studio/api/answer", json={"revision": state["revision"],
        "field": "vu_" + key, "value": "anything"})
    assert result.status_code == 422


def test_outputs_show_pending_requirements_without_duplicate_hardware():
    project = catalogue_review_project()
    baseline_rows = build_metering_spec_section(project).rows
    baseline_state = drawing_state(project)
    project.metering_detail.enhancements = wishes()
    original = deepcopy(asdict(project))
    rows = build_metering_spec_section(project).rows
    assert [(r.component_ids,r.qty,r.unit) for r in rows[:len(baseline_rows)]] == [
        (r.component_ids,r.qty,r.unit) for r in baseline_rows]
    assert not rows[0].catalogue_id  # ultrasound is not the approved mechanical model
    extras = rows[len(baseline_rows):]
    assert len(extras) == 8
    assert all(r.qty is None and not r.component_ids and not r.catalogue_id for r in extras)
    assert all(r.pos is None for r in extras)
    assert all("Не скомплектовано" == r.type_mark for r in extras)
    state_now = drawing_state(project)
    for key in ('meter','bypass','electric_bypass','inputs_count','fire_branch'):
        assert getattr(state_now,key) == getattr(baseline_state,key)
    assert any('Модель' in message for message in state_now.missing)
    assert remote_readout_required(project)
    state = drawing_state(project)
    rules = evaluate_metering_rules(project, state.meter, inputs_count=1, bypass=state.bypass)
    assert all(r.status == "review" for r in rules if r.code.startswith("VU-OPTION"))
    assert OPTIONS_NOTICE in generate_pz_html(project)
    assert OPTIONS_NOTICE in generate_v1_calculation_html(project)
    spec = generate_spec_html(project)
    drawings = "".join(build_metering_detail_pages(project))
    for request in option_requests(project.metering_detail):
        assert request["label"] in spec and request["label"] in drawings
    assert asdict(project) == original
