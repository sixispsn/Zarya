from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from app.intake.studio_fire_station import parse_model
from app.intake.studio_fire_review import calculate_review
from app.intake.studio_intake import build_handoff_request
from app.intake.project_builder import build_project
from app.pz.geometry_builder import build_network
from tests.test_studio_fire_station import control_model, station_draft
from tests import test_studio as api_tests

client = api_tests.client


def review_model():
    model = control_model()
    model["schema_version"] = 2
    model["basis"] = "Контроль интеграции: явные условные сопротивления; обвязка включена в пути. Не реальные исходные объекта."
    net = model["network"]
    net["risers"][0].update(height_m=41., cabinet_elevation_m=40.35)
    model["supplies"][1]["guaranteed_head_m"] = 25.
    names = [row["name"] for row in net["risers"]]
    model["pressure_review"] = dict(basis="Контроль адаптера с разными вводами и двумя заданными ПК.",
        pump_id="cnp-cdm32-3", characteristic="handbook_study", hose_material="rubber_lined",
        nozzle_kind="non_shutoff", loss_boundary="all_pipework_explicit_in_supplies_and_network",
        apertures_mm={names[0]: 21., names[1]: None}, groups=[names],
        repairs=[dict(id="port-1", basis="Явное отключение выхода 1", closed_runs=[], closed_ports=[net["source_node"]]),
                 dict(id="ring-1", basis="Явное отключение одного участка кольца", closed_ports=[],
                      closed_runs=[[net["runs"][2]["from_node"], net["runs"][2]["to_node"]]])],
        axis_offsets_px=[0., -2., 2.])
    return model


def evaluate(model):
    project = build_project(build_handoff_request(station_draft(model)))
    network = build_network(project)
    return project, network, calculate_review(project, network)


def test_v2_model_roundtrip_and_direct_existing_solver_parity():
    from app.calc.fire_repair_flow import check_repair_operating_point
    from app.calc.fire_pressure_flow import handbook_characteristic
    from app.intake.yaml_io import dump_request, load_request
    model = review_model(); before = deepcopy(model)
    req = build_handoff_request(station_draft(model))
    assert load_request(dump_request(req)) == req
    project, net, out = evaluate(model)
    assert model == before and out["scenario_count"] == 45
    assert out["reserve_in_flow_sum"] is False and out["release_ready"] is False
    boundary = out["boundaries"][0]
    chars = [handbook_characteristic(c, hose_material="rubber_lined", nozzle_kind="non_shutoff") for c in net.cabinets]
    explicit = check_repair_operating_point(net, chars, out["pump"]["curve"],
        closed_port_ids=[net.source.node_id], suction_static_head_m=boundary["static_head_m"],
        supply_resistance=boundary["resistance"], apertures_mm={net.cabinets[0].cabinet_id: 21.})
    row = next(row for row in out["rows"] if row["case"] == "port-1" and row["boundary"] == boundary["id"] and row["axis_offset_px"] == 0)
    assert row["result"] == asdict(explicit)
    assert not out["product_verified"]
    assert [b["static_head_m"] for b in out["boundaries"] if b["id"].endswith("Hгар")] == pytest.approx([30.255, 25.255])
    assert all(row["result"] is not None for row in out["rows"])


def test_editing_aperture_does_not_alter_static_pressure_or_auto_select():
    model = review_model()
    _, _, original = evaluate(model)
    model["pressure_review"]["apertures_mm"][model["network"]["risers"][0]["name"]] = 19.5
    _, _, changed = evaluate(model)
    assert changed["static_rows"] == original["static_rows"]
    assert changed["rows"] != original["rows"]
    assert changed["input_sha256"] != original["input_sha256"]
    assert changed["pump"] == original["pump"]


def test_unknown_maximum_is_not_replaced_and_high_maximum_fails_static():
    model = review_model()
    model["supplies"][0]["maximum_head_m"] = None
    _, _, out = evaluate(model)
    assert not out["maximum_source_known"] and not out["complete"]
    assert all(r["pressure_mpa"] is None for r in out["static_rows"])
    assert len(out["boundaries"]) == 3 and not out["all_model_static_limits_met"]
    model["supplies"][0]["maximum_head_m"] = 100.
    _, _, high = evaluate(model)
    assert not high["all_model_static_limits_met"]
    assert max(r["pressure_mpa"] for r in high["static_rows"]) > .9


def test_disconnected_cabinets_are_counted_not_dropped_or_accepted():
    model = review_model()
    net = model["network"]
    model["pressure_review"]["repairs"] = [dict(id="cut", basis="Контроль разрыва",
        closed_ports=[], closed_runs=[[r["from_node"],r["to_node"]] for r in net["runs"][:2]])]
    _, _, out = evaluate(model)
    failures = [r for r in out["rows"] if r["case"] == "cut"]
    assert len(failures) == 15 and all(r["error"] for r in failures)
    assert not out["complete"] and not out["all_model_minima_met"]


@pytest.mark.parametrize("mutation", [
    lambda m: m["pressure_review"].update(pump_id="invented"),
    lambda m: m["pressure_review"].update(pump_id=[]),
    lambda m: m["pressure_review"].update(loss_boundary="guess_zero"),
    lambda m: m["pressure_review"].pop("apertures_mm"),
    lambda m: m["pressure_review"].update(apertures_mm={}),
    lambda m: m["pressure_review"]["apertures_mm"].update({m["network"]["risers"][0]["name"]: 13.7}),
    lambda m: m["pressure_review"].update(nozzle_kind="shutoff"),
    lambda m: m["pressure_review"].update(characteristic="technical_documentation"),
    lambda m: m["pressure_review"].update(axis_offsets_px=[2]),
    lambda m: m["pressure_review"].update(axis_offsets_px=[True]),
    lambda m: m["pressure_review"].update(axis_offsets_px=[0,0]),
    lambda m: m["pressure_review"].update(groups=[["unknown"]]),
    lambda m: m["pressure_review"].update(groups=m["pressure_review"]["groups"]*2),
    lambda m: m["pressure_review"]["repairs"][0].update(closed_ports=["unknown"]),
    lambda m: m["pressure_review"]["repairs"][0].update(closed_ports=[]),
    lambda m: m["pressure_review"]["repairs"][1].update(closed_runs=[["unknown", "unknown2"]]),
    lambda m: m["pressure_review"].update(approved=True),
])
def test_bad_review_input_fails_atomically(mutation):
    model = review_model(); mutation(model)
    with pytest.raises(ValueError):
        parse_model(model)


def test_review_requires_normative_number_of_jets_and_no_new_engine():
    model = review_model()
    model["pressure_review"]["groups"] = [[r["name"]] for r in model["network"]["risers"]]
    with pytest.raises(ValueError, match="нормативное количество"):
        evaluate(model)
    source = Path("app/intake/studio_fire_review.py").read_text()
    assert "scripts.build_samara" not in source and "demo/" not in source


def test_large_matrix_is_rejected_without_silent_sampling():
    from itertools import combinations
    model = review_model()
    prototype = model["network"]["risers"][0]
    model["network"]["risers"] = [dict(prototype, name=f"R{i}") for i in range(8)]
    review = model["pressure_review"]
    review["apertures_mm"] = {f"R{i}": None for i in range(8)}
    review["groups"] = [list(g) for g in list(combinations(review["apertures_mm"], 2))[:16]]
    with pytest.raises(ValueError, match="матрица превышает"):
        parse_model(model)


def test_ordinary_api_review_preview_private_and_revoked(client):
    from pypdf import PdfReader
    from io import BytesIO
    draft = api_tests.new(client)
    values = {k:v["value"] for k,v in station_draft(review_model())["answers"].items()}
    response = client.post("/studio/api/calculate", json={"revision":draft["revision"], "answers":values})
    assert response.status_code == 200, response.text
    state = response.json()
    review = state["project_calculation"]["fire_station"]["pressure_review"]
    assert review["scenario_count"] == 45 and not state["project_calculation"]["can_release"]
    response = client.post("/studio/api/preview", json={"revision":state["revision"]})
    assert response.status_code == 200, response.text
    state = response.json()
    doc = next(d for d in state["preview"]["documents"] if d["kind"] == "fire_pressure_review_pdf")
    url = f'/studio/api/preview/{state["preview"]["id"]}/files/{doc["name"]}'
    response = client.get(url)
    assert response.status_code == 200
    text = " ".join(p.extract_text() for p in PdfReader(BytesIO(response.content)).pages)
    assert "Диафрагмы и отключения" in text and "CNP CDM32-3" in text and "Самара" not in text
    api_tests.answer(client, state, "fire_station_model", None)
    assert client.get(url).status_code == 404
