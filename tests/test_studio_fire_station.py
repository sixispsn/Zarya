"""Ordinary Studio must use the object's explicit model, never a Samara preset."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
from pathlib import Path

import pytest

from app.intake.studio_fire_station import parse_model
from app.intake.studio_intake import answer_field, build_handoff_request, public_draft, validate_value
from app.intake.studio_project import calculate_project
from app.intake.project_builder import build_project
from app.intake.preflight import preflight_request
from app.intake.yaml_io import dump_request, load_request
from tests.test_studio_apartment_meters import draft
from tests import test_studio as api_tests

client = api_tests.client


def control_model():
    # Only test data: copy explicit inputs, not the frozen L06 result/dia­phragms.
    from scripts.build_samara_section_study import load_basis, make_draft, make_request, make_fire_station
    basis = load_basis()
    request = make_request(make_draft(basis))
    net, station = request.network, make_fire_station(basis)
    def without_section(row):
        return {k: v for k, v in asdict(row).items() if k != "repair_section_id"}
    return dict(schema_version=1, basis="Явные исходные контрольного прогона, не данные реального проекта. A и Lэкв взяты из контрольной модели.",
        material="steel_vgp_ordinary", pump_axis_m=station.pump_axis_m,
        cabinet=dict(dn=request.cabinet_dn, nozzle_mm=request.nozzle_mm,
                     hose_length_m=request.hose_length_m, compact_jet_m=request.compact_jet_m),
        network=dict(source_node=net.source_node, second_source_node=net.second_source_node,
                     node_elevations=net.node_elevations,
                     runs=[without_section(r) for r in net.runs],
                     risers=[without_section(r) for r in net.risers]),
        supplies=[dict(name=f"Ввод-{i+1}", source_elevation_m=s.source_elevation_m,
            guaranteed_head_m=s.guaranteed_head_m, maximum_head_m=s.maximum_head_m,
            segments=[dict(length_m=p.length_m, A=p.A, equiv_length_m=p.equiv_length_m,
                           dn=p.diameter_mm) for p in s.segments])
            for i, s in enumerate(station.supplies)])


def station_draft(model=None):
    return draft(floors=17, building_height_m=54, fire_height_m=50, fire_topology="separate",
                 fire_station_model=control_model() if model is None else model)


def test_same_fixed_flow_engine_through_ordinary_studio_and_yaml():
    from app.calc.fire_pump_station import calculate_common_fire_station
    from app.pz.geometry_builder import build_network
    from scripts.build_samara_section_study import load_basis, make_draft, make_request, make_fire_station
    basis = load_basis()
    reference = calculate_common_fire_station(build_network(build_project(make_request(make_draft(basis)))), make_fire_station(basis), 2)
    d = station_draft()
    req = build_handoff_request(d)
    assert req.network is None  # exactly one authoritative graph
    restored = load_request(dump_request(req))
    assert restored == req
    assert not preflight_request(restored).can_release
    result = calculate_project(d)
    station = result["fire_station"]
    assert result["can_preview"] and not result["can_release"]
    assert station["state"] == "preliminary" and station["flow_lps"] == 5.2
    assert station["pump_head_m"] == pytest.approx(reference.hydraulic.pump_duty.required_head_m)
    assert station["minimum_suction_head_m"] == pytest.approx(reference.minimum_suction_head_m)
    assert len(station["supplies"]) == 2
    assert all(s["flow_lps"] == 5.2 for s in station["supplies"])
    assert all(s["loss_m"] == pytest.approx(.0023 * 22 * 5.2**2) for s in station["supplies"])
    assert station["pump"]["q_design_m3h"] == pytest.approx(5.2 * 3.6)
    assert station["pump"]["curve_kind"] == "duty_only"
    assert station["pump"]["model"]
    assert "диафрагмы" in station["note"]
    assert any(i["code"] == "studio.fire_station_preliminary" for i in result["issues"])


def test_inputs_are_not_mutated_and_data_changes_affect_current_duty():
    model = control_model()
    before = deepcopy(model)
    original = calculate_project(station_draft(model))["fire_station"]
    assert model == before
    model["supplies"][1]["guaranteed_head_m"] -= 5
    d = station_draft(model)
    changed = calculate_project(d)["fire_station"]
    assert changed["pump_head_m"] == pytest.approx(original["pump_head_m"] + 5)
    assert changed["supplies"][0]["suction_head_m"] == original["supplies"][0]["suction_head_m"]
    model["network"]["risers"][0]["height_m"] += 10
    model["network"]["risers"][0]["cabinet_elevation_m"] += 10
    higher = calculate_project(station_draft(model))["fire_station"]
    assert higher["pump_head_m"] > changed["pump_head_m"] + 10
    d["project_calculation"], d["preview"] = {"stale": True}, {"id": "old"}
    answer_field(d, "fire_station_model", model)
    assert d["project_calculation"] is None and d["preview"] is None
    answer_field(d, "fire_station_model", None)
    assert build_project(build_handoff_request(d)).fire_station_input is None
    assert calculate_project(d)["fire_station"] is None


def test_no_station_is_required_for_preliminary_water_and_sewer():
    d = draft(floors=17, building_height_m=54, fire_height_m=50, fire_topology="separate")
    state = public_draft(d)
    assert "fire_station_model" not in state["handoff_missing"]
    assert all("fire_station_model" not in s["fields"] for s in state["next_steps"])
    result = calculate_project(d)
    assert result["can_preview"] and result["fire_station"] is None


def test_sufficient_pressure_means_no_booster_and_unknown_maximum_stays_unknown():
    model = control_model()
    for inlet in model["supplies"]:
        inlet.update(guaranteed_head_m=100, maximum_head_m=None)
    out = calculate_project(station_draft(model))["fire_station"]
    assert out["pump_needed"] is False and out["pump"] is None and out["pump_head_m"] == 0
    assert out["maximum_static_suction_head_m"] is None


def test_bad_suction_does_not_destroy_water_sewer_preview_or_return_a_pump():
    model = control_model()
    model["supplies"][0]["guaranteed_head_m"] = 0
    out = calculate_project(station_draft(model))
    assert out["can_preview"] and out["head"]["ready"] and out["fire_station"]["state"] == "needs_data"
    assert "pump" not in out["fire_station"] and not out["can_release"]


@pytest.mark.parametrize("mutation", [
    lambda m: m.pop("basis"),
    lambda m: m.update(basis=" "),
    lambda m: m.update(schema_version=True),
    lambda m: m.update(material="plastic"),
    lambda m: m.update(pump_axis_m=float("nan")),
    lambda m: m.update(supplies=m["supplies"][:1]),
    lambda m: m["supplies"][0].update(maximum_head_m=1),
    lambda m: m["supplies"][0]["segments"][0].pop("A"),
    lambda m: m["supplies"][0]["segments"][0].update(equiv_length_m=-1),
    lambda m: m["supplies"][0]["segments"][0].update(dn=999),
    lambda m: m["network"]["runs"][0].update(length_m=True),
    lambda m: m["network"]["runs"][0].pop("equiv_length_m"),
    lambda m: m["network"].update(second_source_node=m["network"]["source_node"]),
    lambda m: m["network"]["node_elevations"].update(LOST=0),
    lambda m: m["network"]["node_elevations"].update({m["network"]["source_node"]: 0}),
    lambda m: m["network"]["node_elevations"].update({m["network"]["runs"][0]["to_node"]: 999}),
    lambda m: m["network"]["risers"][0].update(height_m=1),
    lambda m: m["cabinet"].update(nozzle_mm=14),
    lambda m: m.update(approved=True),
])
def test_incomplete_or_unsupported_inputs_are_not_defaulted(mutation):
    model = control_model()
    mutation(model)
    with pytest.raises(ValueError):
        validate_value("fire_station_model", model)


def test_no_unreviewed_topology_or_second_graph_and_no_frozen_preset():
    req = build_handoff_request(station_draft())
    req.fire_topology = "combined"
    assert any("раздельную" in s for s in req.validate())
    req.fire_topology = "separate"
    req.building_type = "public"
    assert any("к жилью" in s for s in req.validate())
    req.building_type = "residential"
    req.fire_mode = "force_on"
    assert any("автоматической" in s for s in req.validate())
    req.fire_mode = "auto"
    req.network = parse_model(req.fire_station_model).network
    assert any("два независимых" in s for s in req.validate())
    source = Path("app/intake/studio_fire_station.py").read_text()
    assert "scripts.build_samara" not in source and "demo/" not in source
    assert hashlib.sha256(Path("legacy/archive/sp30_calculator.pre-2026-09-21.html").read_bytes()).hexdigest() == "ace54b14e2f30fadaec768ec06aa5a326553709b9a869263208ef8ee58df3788"


def test_api_persists_model_and_rejects_invalid_replacement_without_mixing_results(client):
    state = api_tests.new(client)
    d = station_draft()
    values = {k: row["value"] for k, row in d["answers"].items()}
    response = client.post("/studio/api/calculate", json={"revision": state["revision"], "answers": values})
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["project_calculation"]["fire_station"]["state"] == "preliminary"
    invalid = control_model()
    invalid["network"]["runs"][0].pop("A")
    response = client.patch("/studio/api/answer", json=dict(revision=current["revision"], field="fire_station_model", value=invalid))
    assert response.status_code == 422
    unchanged = client.get("/studio/api/draft").json()
    assert unchanged["revision"] == current["revision"]
    assert unchanged["project_calculation"]["fire_station"] == current["project_calculation"]["fire_station"]
    removed = api_tests.answer(client, current, "fire_station_model", None)
    assert removed["project_calculation"] is None and removed["preview"] is None


def test_pdf_annex_is_delivered_inside_pz_and_revoked_with_inputs(client):
    from io import BytesIO
    from pypdf import PdfReader
    current = api_tests.new(client)
    d = station_draft()
    response = client.post("/studio/api/calculate", json={"revision": current["revision"],
        "answers": {k: row["value"] for k,row in d["answers"].items()}})
    assert response.status_code == 200, response.text
    current = response.json()
    response = client.post("/studio/api/preview", json={"revision": current["revision"]})
    assert response.status_code == 200, response.text
    current = response.json()
    docs = {r["kind"]:r for r in current["preview"]["documents"]}
    assert "fire_station_input_pdf" in docs and "hydraulic_pdf" in docs
    urls = {k:f'/studio/api/preview/{current["preview"]["id"]}/files/{r["name"]}' for k,r in docs.items()}
    annex = client.get(urls["fire_station_input_pdf"])
    assert annex.status_code == 200
    pdf = PdfReader(BytesIO(annex.content))
    assert pdf.outline and len(pdf.pages) >= 2
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "28,887" in text and "45,506" in text
    pz = PdfReader(BytesIO(client.get(urls["pz_pdf"]).content))
    assert "В2. Вводы и пожарная насосная" in "\n".join(page.extract_text() for page in pz.pages)
    api_tests.answer(client, current, "fire_station_model", None)
    assert client.get(urls["fire_station_input_pdf"]).status_code == 404
