"""Real accessories vs candidates; no alteration of canonical hydraulics."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.data.metering_extras import get_metering_extras_catalogue, catalogue_option_details
from app.intake.request_dto import IOS2Request, DocumentRequest
from app.intake.yaml_io import dump_request, load_request
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_extras import resolve_metering_extras, metering_option_rows
from app.pz.metering_rules import evaluate_metering_rules
from app.pz.metering_spec import build_metering_spec_section
from app.pz.generator import generate_pz_html, generate_spec_html
from scripts.preview_metering_detail import catalogue_review_project, review_project
from tests import test_studio as studio_tests

client = studio_tests.client


def test_catalogue_is_sourced_unique_and_not_mutable():
    cat = get_metering_extras_catalogue()
    assert len(cat["products"]) == 23 and len(cat["solutions"]) == 3
    assert cat["products"]["saures-r7-din"]["article"] == "CTR-R7.4"
    assert cat["products"]["pulsar-em-dn50"]["article"] == "Н10018617"
    assert cat["products"]["vega-si11"]["shared_inputs"] == 4
    for row in cat["products"].values():
        assert row["model"] and row["manufacturer"] and row["requirements"]
        assert all(cat["sources"][key]["url"].startswith("https://") for key in row["source_ids"])
    cat["products"].clear()
    assert len(get_metering_extras_catalogue()["products"]) == 23


@pytest.mark.parametrize("choice,ids", [
    ("saures_wifi_point", {"saures-r4-din", "gidrolock-wsp-plus"}),
    ("saures_nbiot_point", {"saures-r7-din", "gidrolock-wsp-plus"}),
    ("vega_lorawan_point", {"vega-si11", "vega-dp2"}),
])
@pytest.mark.parametrize("inputs", [1, 2])
def test_explicit_leak_kit_has_one_point_not_one_per_input(choice, ids, inputs):
    p = review_project(inputs)
    p.metering_detail.enhancements = {"leak_monitoring": choice}
    before = deepcopy(asdict(p))
    plan = resolve_metering_extras(p)
    assert {r["id"] for r in plan["items"]} == ids
    assert all(type(r["qty"]) is int and r["qty"] == 1 for r in plan["items"])
    rows = [r for r in build_metering_spec_section(p).rows if r.catalogue_id in ids]
    assert len(rows) == 2 and all(r.qty == 1 and r.unit == "шт." for r in rows)
    assert all(r.quantity_basis == "explicit_vu_accessory" for r in rows)
    assert "без перекрытия" in str(plan) or "Шлюз/сервер" in str(plan)
    assert asdict(p) == before


def test_shared_controller_is_counted_once():
    p = catalogue_review_project()
    p.metering_detail.enhancements = {"leak_monitoring": "saures_nbiot_point", "telemetry": "saures_r7"}
    rows = resolve_metering_extras(p)["items"]
    assert len(rows) == 2
    controller = next(r for r in rows if r["id"] == "saures-r7-din")
    assert controller["qty"] == 1 and set(controller["roles"]) == {"telemetry", "leak_monitoring"}


@pytest.mark.parametrize("values", [
    {"leak_monitoring": "saures_wifi_point", "telemetry": "vega_si11"},
    {"leak_monitoring": "saures_wifi_point", "telemetry": "nb_iot"},
    {"leak_monitoring": "vega_lorawan_point", "power": "mains"},
    {"leak_monitoring": "vega_lorawan_point", "telemetry": "rs485"},
    {"leak_monitoring": "saures_wifi_point", "telemetry": "mbus"},
])
def test_incompatible_selection_cannot_be_quantified(values):
    p = catalogue_review_project()
    p.metering_detail.enhancements = values
    plan = resolve_metering_extras(p)
    assert plan["issues"] and not plan["items"]
    rules = evaluate_metering_rules(p, None, inputs_count=1, bypass=False)
    assert any(r.code.startswith("VU-EXTRA-CONFLICT") and r.status == "error" for r in rules)
    assert not [r for r in build_metering_spec_section(p).rows if r.quantity_basis == "explicit_vu_accessory"]


def test_cold_room_and_shared_selection_do_not_keep_invalid_controller():
    p = catalogue_review_project()
    p.metering_detail.room_min_temperature_c = 0
    p.metering_detail.enhancements = {"telemetry": "saures_r4", "leak_monitoring": "saures_wifi_point"}
    assert resolve_metering_extras(p)["items"] == []


def test_candidates_do_not_replace_hardware_or_bypass_calculations():
    p = catalogue_review_project()
    before = build_metering_spec_section(p).rows
    p.metering_detail.enhancements = {"technology": "pulsar_em50", "magnetic_filter": "vodopribor_fmf",
        "assembly": "vodopribor_module", "valve_feedback": "bolid_sp4_24", "tamper_monitoring": "vodopribor_ipk"}
    original = deepcopy(asdict(p))
    plan = resolve_metering_extras(p)
    assert not plan["items"]
    assert any("DN32" in n for row in plan["selections"] for n in row["notes"])
    rows = build_metering_spec_section(p).rows
    assert [(r.component_ids,r.qty,r.unit) for r in rows[:len(before)]] == [
        (r.component_ids,r.qty,r.unit) for r in before]
    assert not rows[0].catalogue_id  # an EM candidate cannot validate a mechanical meter
    assert all(r.qty is None and r.pos is None for r in rows[len(before):])
    assert asdict(p) == original


def test_wishes_are_not_migrated_to_purchases():
    p = review_project()
    p.metering_detail.enhancements = {"leak_monitoring": "requested", "telemetry": "nb_iot"}
    assert not resolve_metering_extras(p)["items"]
    assert "WSP+" in str(metering_option_rows(p))
    assert "Рассмотреть" not in str(catalogue_option_details())


def test_pz_and_spec_reference_same_real_items():
    p = catalogue_review_project()
    p.metering_detail.enhancements = {"leak_monitoring": "saures_nbiot_point", "telemetry": "saures_r7"}
    pz, spec = generate_pz_html(p), generate_spec_html(p)
    for value in ("CTR-R7.4", "WSP+", "Одна водомерная"):
        assert value.lower() in pz.lower() and value.lower() in spec.lower()
    assert "SIM" in pz


def test_new_choices_yaml_roundtrip():
    values = {"leak_monitoring": "vega_lorawan_point", "magnetic_filter": "vodopribor_fmf"}
    req = IOS2Request(document=DocumentRequest("", "", ""), building_type="residential",
        floors=2, building_height_m=6.6, metering_detail=MeteringDetailData(enhancements=values))
    assert load_request(dump_request(req)).metering_detail.enhancements == values


def test_studio_new_equipment_choice_does_not_change_hydraulics(client):
    state = studio_tests.residential_project(client)
    state = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    baseline = deepcopy(state["project_calculation"])
    for key, value in {"leak_monitoring": "saures_nbiot_point", "telemetry": "saures_r7"}.items():
        state = studio_tests.answer(client, state, "vu_" + key, value)
    state = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    result = state["project_calculation"]
    assert len(result["metering_equipment"]["items"]) == 2
    assert "vu_leak_monitoring" in state["metering_catalogue"]["choices"]
    for key in ("flows", "meters", "head", "pumps", "fire", "storm"):
        assert result[key] == baseline[key]
    state = studio_tests.answer(client, state, "vu_leak_monitoring", None)
    state = studio_tests.answer(client, state, "vu_telemetry", None)
    state = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    assert state["project_calculation"]["metering_equipment"]["items"] == []
