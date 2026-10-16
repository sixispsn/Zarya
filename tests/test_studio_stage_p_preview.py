"""A missing detailed route blocks confirmed head, not stage-P work in Studio."""
from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.studio_intake import answer_field, build_handoff_request, public_draft
from app.intake.studio_project import calculate_project
from app.pz.generator import generate_pump_selection_html, generate_pz_html
from app.pz.ios2_orchestrator import design_ios2
from app.pz.rules import project_governing_head
from tests import test_studio as studio_tests
from tests.test_studio_apartment_meters import draft
from tests.test_studio_hydraulics import draft as route_draft

client = studio_tests.client


def no_route():
    return draft(pressure_loss_mode="sections", t3_loss_mode="sections",
                 h_il_m=None, h_vvod_m=None, h_il_hot_m=None)


def test_absent_route_allows_preview_without_fabricating_losses_or_pump():
    d = no_route()
    state = public_draft(d)
    result = calculate_project(d)
    assert not any(step["id"] == "losses" for step in state["next_steps"])
    assert {"v1_sections", "t3_sections"} <= set(state["head_missing"])
    assert result["can_preview"] and not result["can_release"]
    assert result["flows"]["q_day_tot"] == 3.6
    assert result["preview_notes"] and not result["head"]["ready"]
    assert result["head"]["required_m"] is None
    assert result["head"]["pump_m"] is None
    assert result["head"]["pump_needed"] is None
    assert result["pumps"] is None
    req = build_handoff_request(d)
    assert req.source_data.h_il_m is None and req.source_data.h_vvod_m is None


def test_partial_cold_path_cannot_certify_shared_pump_in_review_pdf(tmp_path):
    d = route_draft(hot=True)
    calculation = calculate_project(d)
    project = build_project(build_handoff_request(d))
    project.document.review_head_pending = True
    project.document.review_notes = tuple(calculation["preview_notes"])
    project = design_ios2(project, output_dir=str(tmp_path), render_documents=False).project
    assert project.head_paths.cold.complete and not project.head_paths.hot.complete
    assert project.head_paths.cold.head.h_required_m is not None
    head = project_governing_head(project)
    assert head.h_required_m is None and head.h_pump_m is None and head.pump_needed is None
    assert not project.pumps.model and not project.pumps.required
    for html in (generate_pz_html(project), generate_pump_selection_html(project)):
        assert calculation["preview_notes"][0] in html
        assert "повышение напора не требуется" not in html
    assert "Недостаточно исходных данных для определения необходимости насоса" in generate_pump_selection_html(project)


def test_complete_head_and_regular_document_are_not_relabelled(tmp_path):
    result = calculate_project(draft())
    assert result["head"]["ready"] and not result["preview_notes"]
    project = build_project(build_handoff_request(draft()))
    project = design_ios2(project, output_dir=str(tmp_path), render_documents=False).project
    assert not project.document.review_head_pending and not project.document.review_notes
    assert project_governing_head(project).h_required_m == result["head"]["required_m"]
    assert "Предварительный просмотр. Документы требуют" not in generate_pz_html(project)


def test_missing_building_inputs_still_prevent_project_preview():
    d = no_route()
    answer_field(d, "floors", None)
    result = calculate_project(d)
    assert result["state"] == "needs_inputs" and not result.get("can_preview", False)


def test_reopening_old_draft_refreshes_readiness_without_editing_inputs(client, monkeypatch):
    from app.web import studio
    d = no_route()
    d["project_calculation"] = calculate_project(d)
    d["project_calculation"].pop("preview_notes")
    d["project_calculation"]["can_preview"] = False
    revision, answers = d["revision"], dict(d["answers"])
    monkeypatch.setattr(studio, "store", lambda request=None: SimpleNamespace(load=lambda _: d))
    result = client.get("/studio/api/draft").json()
    assert result["project_calculation"]["can_preview"]
    assert result["revision"] == d["revision"] == revision and d["answers"] == answers
    assert not d["project_calculation"]["can_preview"]  # read-only refresh


def test_real_pdf_preview_without_routes_is_private_and_cannot_release(client):
    state = studio_tests.new(client)
    data = no_route()
    response = client.post("/studio/api/calculate", json={
        "revision": state["revision"],
        "answers": {key: row["value"] for key, row in data["answers"].items()},
    })
    assert response.status_code == 200, response.text
    state = response.json()
    response = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["package"] is None and state["preview"]["notes"]
    assert state["project_calculation"]["review_sections"]
    for kind in ("pz_pdf", "water_package_pdf", "v1_calculation_pdf", "pump_selection_pdf"):
        document = next(row for row in state["preview"]["documents"] if row["kind"] == kind)
        assert document["state"] == "incomplete"
        url = f'/studio/api/preview/{state["preview"]["id"]}/files/{document["name"]}'
        response = client.get(url)
        assert response.status_code == 200 and response.headers["x-zarya-preview"] == "true"
        reader = PdfReader(BytesIO(response.content))
        text = " ".join(" ".join(page.extract_text().split()) for page in reader.pages)
        assert "Расчёт напора В1/Т3 не завершён" in text
        assert "повышение напора не требуется" not in text
    response = client.post("/studio/api/package", json={"revision": state["revision"]})
    assert response.status_code == 200
    assert response.json()["package"] == {"state": "blocked", "documents": []}
