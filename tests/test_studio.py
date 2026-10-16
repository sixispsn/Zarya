"""Studio adds an input channel, not a second calculation engine."""

import io
import zipfile
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from weasyprint import HTML

from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.intake.project_store import ProjectStore
from app.intake.studio_intake import (
    extract_candidates,
)
from app.main import app


def pdf(text):
    return HTML(
        string=f'<html><meta charset="utf-8"><body><p>{text}</p></body></html>'
    ).write_pdf()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ZARYA_STUDIO_ENABLED", "1")
    monkeypatch.setenv("ZARYA_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.setenv("ZARYA_PROJECTS_DIR", str(tmp_path / "projects"))
    with TestClient(app) as client:
        client.headers["X-Zarya-Studio"] = "1"
        yield client


def new(client):
    response = client.post("/studio/api/draft")
    assert response.status_code == 200
    return response.json()


def answer(client, state, key, value):
    response = client.patch(
        "/studio/api/answer",
        json={"revision": state["revision"], "field": key, "value": value},
    )
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, state, text, name="ТЗ.pdf"):
    response = client.post(
        "/studio/api/files",
        data={"revision": state["revision"]},
        files=[("files", (name, pdf(text), "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    return response.json()


def values(state):
    return {row["key"]: row for row in state["fields"]}


def residential_project(client):
    state = new(client)
    for key, value in {
        "residents": 20,
        "consumer_code": "residential_full_bath",
        "floors": 2,
        "apartments": 8,
        "building_height_m": 6.6,
        "fire_height_m": 4.8,
        "hws_type": "central",
    }.items():
        state = answer(client, state, key, value)
    return state


def test_default_fixture_needs_no_answer_but_document_conflict_does(client):
    state = new(client)
    state = answer(client, state, "residents", 20)
    state = answer(client, state, "consumer_code", "residential_full_bath")
    assert state["can_calculate"] and state["next_question"] is None
    state = client.post(
        "/studio/api/calculate", json={"revision": state["revision"]}
    ).json()
    assert state["calculation"]["sewage_fixture_discharge"] == 1.6
    assert state["calculation"]["sewage_flow"] == 2.293
    state = upload(client, state, "q0s = 2,0 л/с.")
    assert not state["can_calculate"]
    assert state["next_question"] == "sewage_max_fixture_lps"
    state = answer(client, state, "sewage_max_fixture_lps", 2)
    state = client.post(
        "/studio/api/calculate", json={"revision": state["revision"]}
    ).json()
    assert state["calculation"]["sewage_fixture_discharge"] == 2
    state = answer(client, state, "sewage_max_fixture_lps", 1.6)
    assert state["calculation"] is None
    assert values(state)["sewage_max_fixture_lps"]["source"]["kind"] == "user"


def test_full_pipeline_preserves_demand_and_does_not_invent_missing_head(client):
    state = residential_project(client)
    state = client.post(
        "/studio/api/calculate", json={"revision": state["revision"]}
    ).json()
    project = state["project_calculation"]
    assert project["state"] == "calculated"
    assert (
        project["flows"]["sewage_l_per_s"]
        == state["calculation"]["sewage_flow"]
        == 2.293
    )
    assert project["flows"]["q_day_tot"] == 3.6
    assert project["meters"]
    assert project["fire"]["required"] is False
    assert project["head"]["required_m"] is None
    assert project["pumps"] is None and project["storm"] is None
    assert not project["can_release"]
    assert not project["sewer_scheme"]["ready"]
    assert project["sewer_scheme"]["reasons"]
    state = client.post(
        "/studio/api/package", json={"revision": state["revision"]}
    ).json()
    assert state["package"]["state"] == "blocked"


def test_head_storm_use_existing_pipeline_and_edit_revokes_results(client):
    state = residential_project(client)
    for key, value in {
        "guaranteed_head_m": 5,
        "h_geom_m": 6,
        "h_il_m": 3,
        "h_vvod_m": 1,
        "h_apartment_c_meter_m": 0.5,
        "h_apartment_h_meter_m": 0.5,
        "hws_heater_in_scope": "no",
        "roof_type": "flat",
        "storm_city": "moscow",
        "storm_roof_area_m2": 252,
        "storm_walls_area_m2": 0,
    }.items():
        state = answer(client, state, key, value)
    response = client.post(
        "/studio/api/calculate", json={"revision": state["revision"]}
    )
    assert response.status_code == 200, response.text
    state = response.json()
    result = state["project_calculation"]
    from app.calc.storm import StormInput, calculate_storm

    assert result["storm"] == asdict(calculate_storm(StormInput("moscow", 252, 0, 1)))
    assert result["head"]["ready"]
    assert result["head"]["required_m"] == max(
        p["head"]["h_required_m"] for p in result["head"]["paths"]
    )
    assert all(p["head"]["h_pr_m"] == 20 for p in result["head"]["paths"])
    assert result["pumps"] is not None
    state = answer(client, state, "h_geom_m", 7)
    assert state["project_calculation"] is None and state["package"] is None
    assert state["calculation"] is not None  # only demand remains current
    state = client.post(
        "/studio/api/calculate", json={"revision": state["revision"]}
    ).json()
    assert state["project_calculation"]["head"]["required_m"] == pytest.approx(
        result["head"]["required_m"] + 1
    )


def test_package_uses_shared_release_path_and_private_file_access(
    client, monkeypatch, tmp_path
):
    from app.web import studio, wizard
    from fastapi.responses import RedirectResponse

    # Isolate the expensive renderer here; real pipeline is covered separately.
    monkeypatch.setattr(
        studio, "calculate_project", lambda draft: {"can_release": True}
    )
    calls = []

    def release(request, req, **kw):
        calls.append((req, kw))
        return RedirectResponse("/wizard/result/abc", status_code=303)

    monkeypatch.setattr(wizard, "design_request_response", release)
    monkeypatch.setattr(
        wizard, "_get_run", lambda _: {"quality": {"state": "conditional"}, "outdir": str(tmp_path)}
    )
    monkeypatch.setattr(
        wizard,
        "_run_documents",
        lambda _: (
            [{"name": "calculation.pdf", "label": "Расчёт", "state": "ready"}],
            [],
        ),
    )
    state = residential_project(client)
    response = client.post("/studio/api/package", json={"revision": state["revision"]})
    assert response.status_code == 200
    state = response.json()
    assert state["package"]["state"] == "ready"
    assert calls[0][1] == {"force_quality_gates": True}
    assert calls[0][0].sewage_max_fixture_lps == 1.6
    archive_url = "/studio/api/package/abc/download"
    assert client.get(archive_url).status_code == 404  # missing file, not an empty ZIP
    calculation = tmp_path / "calculation.pdf"
    calculation.write_bytes(b"%PDF-test")
    monkeypatch.setattr(wizard, "_run_file", lambda run, name: calculation)
    archive = client.get(archive_url)
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        assert zipped.namelist() == ["calculation.pdf"]
        assert zipped.read("calculation.pdf") == calculation.read_bytes()
    assert client.get("/studio/api/package/wrong/download").status_code == 404
    assert client.get("/studio/api/package/abc/files/not-listed.pdf").status_code == 404
    with TestClient(app) as other:
        assert other.get(archive_url).status_code == 404
        assert (
            other.get("/studio/api/package/abc/files/calculation.pdf").status_code
            == 404
        )
    state = answer(client, state, "residents", 25)
    assert state["package"] is None
    assert client.get(archive_url).status_code == 404
    assert (
        client.get("/studio/api/package/abc/files/calculation.pdf").status_code == 404
    )


def test_flag_off_preserves_existing_home(monkeypatch):
    monkeypatch.setenv("ZARYA_STUDIO_ENABLED", "0")
    with TestClient(app) as client:
        assert client.get("/studio").status_code == 404
        assert client.get("/studio/api/draft").status_code == 404
        assert client.get("/", follow_redirects=False).headers["location"] == "/wizard"


def test_start_page_has_local_assets_and_no_demo_numbers(client):
    response = client.get("/studio")
    assert response.status_code == 200
    assert "/static/studio.js" in response.text
    assert "Начать без документов" in response.text
    state = new(client)
    assert not state["can_calculate"]
    defaults = {
        row["key"]: row["value"]
        for row in state["fields"]
        if row["status"] == "default"
    }
    assert defaults == {
        "vu_per_inlet": "no",
        "t3_loss_mode": "sections",
        "pressure_loss_mode": "sections",
        "sewage_max_fixture_lps": 1.6,
        "h_pr_m": 20.0,
        "inputs_count": 1,
    }
    assert all(
        row["status"] == "missing"
        for row in state["fields"]
        if row["key"] not in defaults
    )
    assert len([row for row in state["fields"] if row["required"]]) == 2
    assert state["calculation"] is None
    assert client.cookies.get("zarya_studio_draft")


def test_quick_start_is_a_visible_suggestion_not_a_hidden_default(client):
    state = new(client)
    assert state["quick_start_presets"] == {
        "building_purpose": "residential",
        "consumer_code": "residential_full_bath", "hws_type": "central",
        "roof_type": "flat_non_accessible",
    }
    assert values(state)["consumer_code"]["status"] == "missing"
    response = client.post("/studio/api/calculate", json={
        "revision": state["revision"], "answers": {"residents": 20},
    })
    assert response.status_code == 422
    # No partial save when the atomic calculation fails.
    assert values(client.get("/studio/api/draft").json())["residents"]["status"] == "missing"


def test_one_click_quick_start_reuses_the_existing_calculation(client):
    state = new(client)
    presets = state["quick_start_presets"]
    response = client.post("/studio/api/calculate", json={
        "revision": state["revision"],
        "answers": {"residents": 20, **presets}, "preset_keys": list(presets),
    })
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["calculation"]["total"]["q_day"] == 3.6
    assert state["calculation"]["sewage_flow"] == 2.293
    for key, value in presets.items():
        assert values(state)[key]["value"] == value
        assert values(state)[key]["source"]["kind"] == "residential_preset"
    for key in ("floors", "apartments", "guaranteed_head_m", "storm_roof_area_m2"):
        assert values(state)[key]["status"] == "missing"
    assert state["project_calculation"]["state"] == "needs_inputs"


def test_preset_cannot_overwrite_manual_choice_or_change_core_defaults(client):
    state = new(client)
    state = answer(client, state, "roof_type", "sloped")
    response = client.patch("/studio/api/answers", json={
        "revision": state["revision"], "answers": {"roof_type": "flat"},
        "preset_keys": ["roof_type"],
    })
    assert response.status_code == 422
    assert values(client.get("/studio/api/draft").json())["roof_type"]["value"] == "sloped"
    response = client.patch("/studio/api/answers", json={
        "revision": state["revision"], "answers": {"guaranteed_head_m": 5},
        "preset_keys": ["guaranteed_head_m"],
    })
    assert response.status_code == 422


def test_manual_form_is_atomic_validated_and_revision_protected(client):
    state = new(client)
    for answers in ({"residents": 20, "floors": -1}, {"unexpected": 1}):
        response = client.patch("/studio/api/answers", json={
            "revision": state["revision"], "answers": answers,
        })
        assert response.status_code == 422
        assert client.get("/studio/api/draft").json()["revision"] == state["revision"]
    response = client.patch("/studio/api/answers", json={
        "revision": state["revision"], "answers": {"residents": 20, "roof_type": "sloped"},
    })
    assert response.status_code == 200
    assert values(response.json())["roof_type"]["source"]["kind"] == "user"
    assert client.patch("/studio/api/answers", json={
        "revision": state["revision"], "answers": {"residents": 30},
    }).status_code == 409


def test_cleared_preset_stays_unknown_after_reload(client):
    state = new(client)
    state = answer(client, state, "roof_type", None)
    assert "roof_type" not in state["quick_start_presets"]
    assert "roof_type" not in client.get("/studio/api/draft").json()["quick_start_presets"]
    assert client.patch("/studio/api/answers", json={
        "revision": state["revision"], "answers": {"roof_type": "flat"},
        "preset_keys": ["roof_type"],
    }).status_code == 422
    state = answer(client, state, "roof_type", "sloped")
    assert values(state)["roof_type"]["value"] == "sloped"


def test_explicit_scalar_only_no_inferred_values():
    text = "Этажность: 2. Количество квартир: 8. Число жителей: 20. Гарантированный напор: 5 м. Общая высота здания: 6,6 м. Пожарно-техническая высота: 4,8 м."
    found = extract_candidates(text, "d", 2)
    assert {row["field"]: row["value"] for row in found} == {
        "floors": 2,
        "apartments": 8,
        "residents": 20,
        "guaranteed_head_m": 5,
        "building_height_m": 6.6,
        "fire_height_m": 4.8,
    }
    assert all(row["page"] == 2 and row["quote"] for row in found)
    assert not extract_candidates(
        "Требуемый напор 75 м. План 2 этажа. Квартиры 45,0 м².", "d", 1
    )
    for line in [
        "Гарантированный напор: 5–10 м",
        "Гарантированный напор: не менее 5 м",
        "Гарантированный напор: 5 МПа",
        "Этажность: 2+1",
        "Число жителей: 20-30",
        "Гарантированный напор: -5 м",
        "Число жителей: 1 000",
        "Количество квартир: 20%",
    ]:
        assert not extract_candidates(line, "d", 1), line


def test_pdf_evidence_needs_confirmation_and_survives_reload(client):
    state = upload(
        client,
        new(client),
        "Число жителей: 20. Этажность: 2. Гарантированный напор: 5 м.",
    )
    residents = values(state)["residents"]
    assert residents["status"] == "review"
    assert residents["value"] is None
    assert residents["candidates"][0]["value"] == 20
    assert residents["candidates"][0]["page"] == 1
    assert not state["can_calculate"]
    state = answer(client, state, "residents", "20")
    assert values(state)["residents"]["source"]["kind"] == "document_confirmed"
    assert values(client.get("/studio/api/draft").json())["residents"]["value"] == 20
    document_id = state["documents"][0]["id"]
    viewed = client.get("/studio/api/files/" + document_id)
    assert viewed.content.startswith(b"%PDF-")
    assert viewed.headers["cache-control"] == "private, no-store"
    with TestClient(app) as other:
        assert other.get("/studio/api/files/" + document_id).status_code == 404


def test_new_conflict_reopens_answer_and_never_uses_last_document(client):
    state = upload(client, new(client), "Число жителей: 20.")
    state = answer(client, state, "residents", 20)
    state = answer(client, state, "consumer_code", "residential_full_bath")
    state = answer(client, state, "sewage_max_fixture_lps", "1,6")
    state = client.post(
        "/studio/api/calculate", json={"revision": state["revision"]}
    ).json()
    assert state["calculation"]
    state = upload(client, state, "Число жителей: 24.", "Уточнение.pdf")
    row = values(state)["residents"]
    assert row["status"] == "conflict"
    assert row["previous_value"] == 20 and row["value"] is None
    assert state["calculation"] is None
    assert (
        client.post(
            "/studio/api/calculate", json={"revision": state["revision"]}
        ).status_code
        == 422
    )
    state = answer(client, state, "residents", 24)
    assert values(state)["residents"]["status"] == "confirmed"
    assert state["can_calculate"]


@pytest.mark.parametrize("residents", [20, 500])
def test_demand_exactly_reuses_core_and_preserves_daily_total(client, residents):
    state = new(client)
    for key, value in [
        ("residents", residents),
        ("consumer_code", "residential_full_bath"),
        ("sewage_max_fixture_lps", "1,6"),
    ]:
        state = answer(client, state, key, value)
    response = client.post(
        "/studio/api/calculate", json={"revision": state["revision"]}
    )
    assert response.status_code == 200
    state = response.json()
    expected = asdict(
        calculate_water_demand(
            [ConsumerGroup("residential_full_bath", residents)],
            apply_k06=False,
            sewage_max_fixture_lps=1.6,
        )
    )
    assert state["calculation"] == expected
    assert state["calculation"]["total"]["q_day"] == pytest.approx(residents * 0.18)
    assert values(state)["guaranteed_head_m"]["value"] is None
    # Head is optional for demand; answering it must not discard an unrelated result.
    state = answer(client, state, "guaranteed_head_m", 0)
    assert state["calculation"] == expected
    state = answer(client, state, "residents", residents + 1)
    assert state["calculation"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("residents", True),
        ("residents", "2.5"),
        ("residents", 0),
        ("consumer_code", "office"),
        ("guaranteed_head_m", "NaN"),
        ("sewage_max_fixture_lps", "-1"),
        ("guaranteed_head_m", "1e309"),
        ("not_a_field", 5),
    ],
)
def test_invalid_answers_do_not_change_draft(client, key, value):
    state = new(client)
    response = client.patch(
        "/studio/api/answer", json={"revision": 0, "field": key, "value": value}
    )
    assert response.status_code == 422
    assert client.get("/studio/api/draft").json()["revision"] == state["revision"]


def test_stale_tab_and_cross_site_requests_are_rejected(client):
    state = new(client)
    state = answer(client, state, "residents", 20)
    assert (
        client.patch(
            "/studio/api/answer",
            json={"revision": 0, "field": "residents", "value": 24},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/studio/api/draft", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post("/studio/api/draft", headers={"X-Zarya-Studio": ""}).status_code
        == 403
    )
    assert values(client.get("/studio/api/draft").json())["residents"]["value"] == 20


def test_bad_pdf_batch_is_atomic_and_scan_is_not_fictionally_parsed(client):
    state = new(client)
    response = client.post(
        "/studio/api/files",
        data={"revision": 0},
        files=[
            ("files", ("real.pdf", pdf("Число жителей: 20."), "application/pdf")),
            ("files", ("fake.pdf", b"not a PDF", "application/pdf")),
        ],
    )
    assert response.status_code == 422
    assert client.get("/studio/api/draft").json()["documents"] == []
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    response = client.post(
        "/studio/api/files",
        data={"revision": 0},
        files=[("files", ("../../plan.pdf", stream.getvalue(), "application/pdf"))],
    )
    state = response.json()
    assert state["documents"][0]["name"] == "plan.pdf"
    assert state["documents"][0]["status"] == "scan"
    assert all(not row["candidates"] for row in state["fields"])


def test_duplicate_upload_is_deduplicated(client):
    state = new(client)
    content = pdf("Число жителей: 20.")
    state = client.post(
        "/studio/api/files",
        data={"revision": 0},
        files=[
            ("files", ("a.pdf", content, "application/pdf")),
            ("files", ("b.pdf", content, "application/pdf")),
        ],
    ).json()
    assert len(state["documents"]) == 1


def test_password_pdf_and_oversized_stream_do_not_change_draft(client, monkeypatch):
    new(client)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    stream = io.BytesIO()
    writer.write(stream)
    response = client.post(
        "/studio/api/files",
        data={"revision": 0},
        files=[("files", ("protected.pdf", stream.getvalue(), "application/pdf"))],
    )
    assert response.status_code == 422 and "паролем" in response.text
    import app.web.studio as routes

    monkeypatch.setattr(routes, "MAX_TOTAL_BYTES", 0)
    response = client.post(
        "/studio/api/files",
        content=b"x" * (1024 * 1024 + 1),
        headers={"Content-Type": "multipart/form-data; boundary=test"},
    )
    assert response.status_code == 413
    assert client.get("/studio/api/draft").json()["documents"] == []


def test_no_confirmation_no_handoff(client):
    state = new(client)
    response = client.post("/studio/api/handoff", json={"revision": state["revision"]})
    assert response.status_code == 422
    assert client.get("/studio/api/draft").json()["revision"] == 0


def test_unreviewed_tu_value_is_not_silently_dropped_at_handoff(client):
    state = upload(client, new(client), "Гарантированный напор: 5 м.", "ТУ.pdf")
    for key, value in [
        ("residents", 20),
        ("consumer_code", "residential_full_bath"),
        ("sewage_max_fixture_lps", 1.6),
        ("floors", 2),
        ("apartments", 8),
        ("building_height_m", 6.6),
        ("fire_height_m", 4.8),
        ("hws_type", "central"),
    ]:
        state = answer(client, state, key, value)
    assert state["can_calculate"]
    assert state["handoff_missing"] == ["guaranteed_head_m"]
    response = client.post("/studio/api/handoff", json={"revision": state["revision"]})
    assert response.status_code == 422
    assert "Гарантированный напор" in response.text


def test_handoff_preserves_values_uses_full_wizard_and_does_not_guess_missing_inputs(
    client, tmp_path
):
    state = new(client)
    for key, value in [
        ("residents", 20),
        ("consumer_code", "residential_full_bath"),
        ("sewage_max_fixture_lps", 1.6),
    ]:
        state = answer(client, state, key, value)
    assert (
        client.post(
            "/studio/api/handoff", json={"revision": state["revision"]}
        ).status_code
        == 422
    )
    for key, value in [
        ("floors", 2),
        ("building_height_m", 6.6),
        ("fire_height_m", 4.8),
        ("hws_type", "central"),
        ("guaranteed_head_m", 5),
        ("apartments", 8),
    ]:
        state = answer(client, state, key, value)
    result = client.post(
        "/studio/api/handoff", json={"revision": state["revision"]}
    ).json()
    assert result["next_url"].startswith("/wizard/open/")
    project_id = result["next_url"].rsplit("/", 1)[-1]
    req = ProjectStore(tmp_path / "projects").load(project_id)
    assert req.floors == 2 and req.apartments == 8 and req.residents == 20
    assert req.source_data.guaranteed_head_m == 5
    assert req.document.cipher == ""
    assert req.fire_mode == "auto"
    assert req.storm_city == "" and req.storm_roof_area_m2 == 0
    assert req.source_data.elev_header_m is None
    assert not req.sewer_pipes
    # Retry returns the same destination, never overwrites a project edited in the wizard.
    repeated = client.post(
        "/studio/api/handoff", json={"revision": result["draft"]["revision"]}
    ).json()
    assert repeated["next_url"] == result["next_url"]


def test_preview_is_private_not_a_release_and_edits_revoke_old_urls(
    client, monkeypatch
):
    from pathlib import Path
    from app.web import studio, wizard
    from app.pz import ios2_orchestrator

    monkeypatch.setattr(
        studio,
        "calculate_project",
        lambda draft: {"can_preview": True, "can_release": False,
                       "handoff_version": studio.STUDIO_HANDOFF_VERSION},
    )
    monkeypatch.setattr(
        wizard,
        "design_request_response",
        lambda *a, **k: pytest.fail("Preview must not publish a release"),
    )

    def render(project, *, output_dir):
        from app.pz.commission import build_commission_report
        Path(output_dir).mkdir(parents=True)
        (Path(output_dir) / "test.pdf").write_bytes(b"%PDF-1.4\nroute test")
        return ios2_orchestrator.IOS2DesignBundle(
            project=project, commission_report=build_commission_report(project, artifacts={}),
        )

    monkeypatch.setattr(ios2_orchestrator, "design_ios2", render)
    monkeypatch.setattr(
        wizard,
        "_bundle_documents",
        lambda _: ([{"name": "test.pdf", "label": "Test", "state": "ready"}], []),
    )
    state = residential_project(client)
    response = client.post(
        "/studio/api/preview", json={"revision": state["revision"]}
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["package"] is None
    assert state["calculation"] and state["preview"]["state"] == "preview"
    url = "/studio/api/preview/" + state["preview"]["id"] + "/files/test.pdf"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["x-zarya-preview"] == "true"
    assert client.get(url.replace("test.pdf", "other.pdf")).status_code == 404
    with TestClient(app) as other:
        assert other.get(url).status_code == 404
    state = answer(client, state, "residents", 21)
    assert state["preview"] is None and client.get(url).status_code == 404


def test_unknown_apartment_count_does_not_silently_remove_apartment_meter_losses(
    client,
):
    state = residential_project(client)
    state = answer(client, state, "apartments", None)
    state = client.post(
        "/studio/api/calculate", json={"revision": state["revision"]}
    ).json()
    assert state["project_calculation"]["state"] == "needs_inputs"
    assert "apartments" in state["handoff_missing"]


def test_contextual_steps_do_not_invent_values_or_repeat_completed_answers(client):
    state = new(client)
    assert state["next_steps"] == []
    state = client.post("/studio/api/calculate", json={
        "revision": state["revision"],
        "answers": {"residents": 20, "consumer_code": "residential_full_bath",
                    "hws_type": "central", "roof_type": "flat_non_accessible"},
        "preset_keys": ["consumer_code", "hws_type", "roof_type"],
    }).json()
    assert state["next_steps"][0]["id"] == "building"
    assert state["next_steps"][0]["fields"] == [
        "floors", "building_height_m", "fire_height_m", "apartments",
    ]
    assert all("sewage_max_fixture_lps" not in step["fields"] for step in state["next_steps"])
    assert values(state)["guaranteed_head_m"]["value"] is None
    state = client.post("/studio/api/calculate", json={
        "revision": state["revision"], "answers": {
            "floors": 2, "apartments": 8, "building_height_m": 6.6, "fire_height_m": 4.8,
        },
    }).json()
    assert state["next_steps"][0]["id"] == "section"
    assert state["next_steps"][1]["id"] == "supply"
    assert values(state)["floor_height_m"]["value"] is None
    # A user may work on rain first; missing head is not fabricated or marked ready.
    state = client.post("/studio/api/calculate", json={
        "revision": state["revision"], "answers": {
            "storm_city": "moscow", "storm_roof_area_m2": 252, "storm_walls_area_m2": 0,
        },
    }).json()
    assert all(step["id"] != "storm" for step in state["next_steps"])
    assert state["project_calculation"]["storm"]["q_total_l_per_s"] == 5.395
    assert state["project_calculation"]["head"]["ready"] is False
    assert state["calculation"]["total"]["q_day"] == 3.6
    reloaded = client.get("/studio/api/draft").json()
    assert reloaded["next_steps"] == state["next_steps"]


def test_contextual_steps_follow_hws_applicability(client):
    state = residential_project(client)
    state = answer(client, state, "hws_type", "none")
    state = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    keys = [key for step in state["next_steps"] for key in step["fields"]]
    assert "h_apartment_h_meter_m" not in keys
    assert "hws_heater_in_scope" not in keys and "h_tepl_m" not in keys
    state = answer(client, state, "hws_type", "central")
    state = answer(client, state, "hws_heater_in_scope", "yes")
    state = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    assert not any(step["id"] == "losses" for step in state["next_steps"])
    assert values(state)["h_apartment_h_meter_m"]["source"]["kind"] == "apartment_estimate"


def test_unconfirmed_pdf_candidates_are_first_contextual_step(client):
    state = upload(client, residential_project(client), "Гарантированный напор: 5 м.")
    state = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    assert state["next_steps"][0]["id"] == "sources"
    assert state["next_steps"][0]["fields"] == ["guaranteed_head_m"]
    assert values(state)["guaranteed_head_m"]["status"] == "review"
    assert state["project_calculation"]["state"] == "needs_inputs"
