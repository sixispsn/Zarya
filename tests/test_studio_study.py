"""Opt-in templates must never overwrite or silently become a real project."""
import pytest

from app.intake.studio_study import (initialize_study, build_study, calculate_study,
                                      study_ios3_project)
from app.intake.studio_intake import answer_field
from tests import test_studio as studio_tests

client = studio_tests.client
new, answer, values = studio_tests.new, studio_tests.answer, studio_tests.values


def start(client, state, kind="two"):
    r = client.post("/studio/api/study", json={"revision": state["revision"], "kind": kind})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("kind,floors,count,area", [("two",2,20,252), ("three",3,36,300)])
def test_snapshot_drives_demand_geometry_text_and_revision(kind, floors, count, area):
    d = {"revision":0, "answers":{}, "documents":[]}
    initialize_study(d, kind, None)
    old_hash = calculate_study(d)["model_hash"]
    req, model, calc, water, storm, h = build_study(d)
    assert req.floors == floors and req.apartments == floors*4 and req.residents == count
    assert storm.f_calculated_m2 == area
    p = study_ios3_project(req, water, storm)
    assert p.flows.sewage_l_per_s == water.sewage_flow == d["calculation"]["sewage_flow"]
    assert p.balance.rows[0].total_m3_day == water.total.q_day
    assert p.sewage.roof_relative_elevation_m == req.wastewater_roof_relative_elevation_m
    assert p.building.height_m == req.wastewater_roof_relative_elevation_m
    assert "К1 и К2 раздельно" in p.sewage.laying_method
    from app.pz.generator import generate_wastewater_pz_html
    assert "Сложение выполняется до округления" in generate_wastewater_pz_html(p)
    d["preview"] = {"id":"obsolete"}
    answer_field(d, "residents", 50)
    answer_field(d, "storm_roof_area_m2", 200)
    req, model, calc, water, storm, h = build_study(d)
    assert water.total.q_day == 9 and storm.f_calculated_m2 == 200
    assert h != old_hash and d["preview"] is None
    assert d["project_calculation"] is None
    p = study_ios3_project(req, water, storm)
    assert p.flows.q_day_tot == 9 and p.storm.result == storm
    if calc:
        assert calc.residents == 50 and calc.catchments_m2 == (50,)*4
    else:
        assert model.residents == 50 and sum(model.catchments) == 200


def test_real_draft_preserved_switch_and_exit(client):
    state = answer(client, new(client), "residents", 77)
    original = client.cookies.get("zarya_studio_draft")
    state = start(client, state)
    assert client.cookies.get("zarya_studio_draft") != original
    assert state["study"]["kind"] == "two" and "snapshot" not in state["study"]
    assert not state["next_steps"] and state["project_calculation"]["can_preview"]
    state = start(client, state, "three")
    assert values(state)["floors"]["value"] == 3
    response = client.post("/studio/api/study/exit", json={"revision": state["revision"]})
    assert response.status_code == 200
    assert response.json()["study"] is None and values(response.json())["residents"]["value"] == 77
    assert client.cookies.get("zarya_studio_draft") == original


def test_no_release_handoff_or_silent_geometry_override(client):
    state = start(client, new(client))
    response = client.patch("/studio/api/answer", json={"revision":state["revision"], "field":"floors", "value":16})
    assert response.status_code == 422
    assert client.post("/studio/api/handoff", json={"revision":state["revision"]}).status_code == 422
    response = client.post("/studio/api/package", json={"revision":state["revision"]})
    assert response.json()["package"]["state"] == "blocked"
    assert not response.json()["project_calculation"]["can_release"]


def test_pdf_revoked_and_private_after_edit(client, monkeypatch):
    from app.intake import studio_study
    def fake_render(draft, folder):
        folder.mkdir(parents=True)
        (folder / "scheme.pdf").write_bytes(b"%PDF-test")
        h = calculate_study(draft)["model_hash"]
        return [{"name":"scheme.pdf", "kind":"wastewater_scheme_pdf", "label":"Scheme", "model_hash":h}], h
    monkeypatch.setattr(studio_study, "render_study", fake_render)
    state = start(client, new(client))
    r = client.post("/studio/api/preview", json={"revision":state["revision"]})
    assert r.status_code == 200, r.text
    state = r.json()
    path = f'/studio/api/preview/{state["preview"]["id"]}/files/scheme.pdf'
    assert client.get(path).status_code == 200
    assert state["preview"]["model_hash"] == state["project_calculation"]["model_hash"]
    state = answer(client, state, "storm_roof_area_m2", 280)
    assert state["preview"] is None and client.get(path).status_code == 404


def test_legacy_mismatch_stops_before_pdf(client, tmp_path, monkeypatch):
    from app.intake import studio_study
    from app.intake.studio_intake import IntakeError
    d = {"revision":0,"answers":{},"documents":[]}
    initialize_study(d,"two",None)
    def mismatch(*args):
        raise IntakeError("legacy mismatch")
    monkeypatch.setattr(studio_study,"verify_legacy",mismatch)
    with pytest.raises(IntakeError, match="legacy"):
        studio_study.render_study(d,tmp_path / "pdf")
    assert not (tmp_path / "pdf").exists()


def test_stale_switch_cannot_replace_current_draft(client):
    state = new(client)
    answer(client,state,"residents",20)
    r = client.post("/studio/api/study",json={"revision":state["revision"],"kind":"two"})
    assert r.status_code == 409


def test_other_browser_cannot_read_study_pdf(client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.intake import studio_study
    def fake_render(draft, folder):
        folder.mkdir(parents=True)
        (folder / "scheme.pdf").write_bytes(b"%PDF-test")
        h = calculate_study(draft)["model_hash"]
        return [{"name":"scheme.pdf", "label":"Scheme"}], h
    monkeypatch.setattr(studio_study,"render_study",fake_render)
    state = start(client,new(client))
    state = client.post("/studio/api/preview",json={"revision":state["revision"]}).json()
    with TestClient(app) as stranger:
        path = f'/studio/api/preview/{state["preview"]["id"]}/files/scheme.pdf'
        assert stranger.get(path).status_code == 404


@pytest.mark.parametrize("kind", ["two", "three"])
def test_real_pdf_contains_changed_values_not_template_constants(kind, tmp_path):
    import os
    import shutil
    from pypdf import PdfReader
    from app.intake.studio_study import render_study
    if not (os.environ.get("NODE_BINARY") or shutil.which("node")):
        pytest.skip("Executable legacy verification requires Node")
    d = {"revision":0,"answers":{},"documents":[]}
    initialize_study(d,kind,None)
    answer_field(d,"residents",50)
    answer_field(d,"storm_roof_area_m2",200)
    docs, h = render_study(d,tmp_path / "pdf")
    text = " ".join(p.extract_text() for p in PdfReader(tmp_path / "pdf/ПЗ_ИОС3.pdf").pages)
    assert "200,0" in text and "9,000" in text
    assert "2,653" in text and "4,281" in text
    assert all(doc["model_hash"] == h for doc in docs)
    assert all(doc["state"] == "incomplete" for doc in docs)
    assert all(doc["state_note"] == "Учебные исходные. Не для выпуска." for doc in docs)
    assert (tmp_path / "pdf/Схема_К1_К2.pdf").is_file()
    if kind == "two":
        import json
        takeoff = json.loads((tmp_path / "pdf/Объёмы_сети_К1_К2.json").read_text())
        assert takeoff["model_hash"] == h and not takeoff["purchase_ready"]
        assert len(takeoff["network"]["routes"]) == 102
        assert any(d["kind"] == "study_takeoff_pdf" for d in docs)
        pages = PdfReader(tmp_path / "pdf/Объёмы_сети_К1_К2.pdf").pages
        assert len(pages) == 3
        assert "8 квартир" in pages[0].extract_text()
    else:
        assert not any(d["kind"] == "study_takeoff_pdf" for d in docs)
