"""Real positive graphic -> preview -> disk -> HTTP roundtrip.

Only the handoff input is substituted: Studio's questionnaire does not accept
this complete registry/fan model. This is NOT a user-input end-to-end test or
approval of the demo project. Rendering, calculations and readiness are real.
"""
from copy import deepcopy
from hashlib import sha256
import io

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.intake import studio_project
from app.intake.studio_store import StudioStore
from app.intake.yaml_io import load_request_file
from app.pz import ios2_orchestrator
from app.pz.artifact_readiness import WASTEWATER_GRAPHIC_ARTIFACTS, WASTEWATER_PACKAGE
from app.web import studio
from tests import test_studio as studio_tests
from tests.test_studio_apartment_meters import draft
from tests.test_studio_preview_readiness import findings
from tests.test_wastewater_scheme_service import _project

client = studio_tests.client


def test_ready_graphic_survives_disk_and_new_session_without_releasing_project(
    client, tmp_path, monkeypatch,
):
    request_model = load_request_file("demo/demo_project.yaml")
    request_model.wastewater_fan_ventilation = _project().sewage.fan_ventilation
    # Existing explicit test-only ventilation confirmations; never saved to demo.
    def handoff(_draft):
        return deepcopy(request_model)
    monkeypatch.setattr(studio, "build_handoff_request", handoff)
    monkeypatch.setattr(studio_project, "build_handoff_request", handoff)
    rendered = []
    real_design = ios2_orchestrator.design_ios2

    def observe_design(*args, **kwargs):
        bundle = real_design(*args, **kwargs)
        if kwargs.get("render_documents", True):
            rendered.append(bundle)
        return bundle
    monkeypatch.setattr(ios2_orchestrator, "design_ios2", observe_design)

    state = studio_tests.new(client)
    data = draft(floor_height_m=3.3, basement_kind="basement", basement_floor_m=-3.1,
                 roof_type="flat_non_accessible", storm_city="moscow",
                 storm_roof_area_m2=252, section_drainage="internal")
    response = client.post("/studio/api/calculate", json={
        "revision": state["revision"],
        "answers": {key: row["value"] for key, row in data["answers"].items()},
    })
    assert response.status_code == 200, response.text
    state = response.json()
    before = state["project_calculation"]
    assert before["sewer_scheme"]["ready"] is True
    assert findings(before)["K-GOST-A03"]["state"] == "conditional"
    assert before["can_release"] is False

    response = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert response.status_code == 200, response.text
    state = response.json()
    assert len(rendered) == 1
    bundle = rendered[0]
    result = bundle.wastewater_graphic_results["k1-k2"]
    assert result.ready is True
    label, attribute = WASTEWATER_GRAPHIC_ARTIFACTS["k1-k2"]
    artifacts = ios2_orchestrator.bundle_artifacts(bundle)
    assert artifacts[label] and artifacts[WASTEWATER_PACKAGE]
    scheme = next(d for d in state["preview"]["documents"] if d["kind"] == attribute)
    package = next(d for d in state["preview"]["documents"]
                   if d["kind"] == "wastewater_package_pdf")
    assert scheme["state"] == "ready"
    assert package["state"] == "preliminary"  # preview never becomes a release
    after = state["project_calculation"]
    assert findings(after)["K-GOST-A03"]["state"] == "ready"
    assert findings(after)["V-GOST-A07"]["state"] == "blocked"
    assert after["can_release"] is False
    for code, row in findings(before).items():
        if row["state"] == "blocked":
            assert findings(after)[code]["state"] == "blocked", code
    for key in ("flows", "meters", "head", "pumps", "storm", "sewer_scheme"):
        assert after[key] == before[key], key

    # A new store instance reads JSON, not an in-memory object from the handler.
    disk_store = StudioStore(tmp_path / "studio")
    saved = disk_store.load(state["project_id"])
    assert saved["preview"] == state["preview"]
    assert saved["preview"]["artifact_readiness"][label] is True
    assert saved["preview"]["graphic_artifact_requirements"] == [label]
    path = disk_store.folder(state["project_id"]) / "previews" / state["preview"]["id"] / scheme["name"]
    content = path.read_bytes()
    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) == 1
    assert "ПРИНЦИПИАЛЬНАЯ СХЕМА НЕ СФОРМИРОВАНА" not in reader.pages[0].extract_text()
    url = f"/studio/api/preview/{state['preview']['id']}/files/{scheme['name']}"
    with TestClient(studio_tests.app) as reopened:
        reopened.cookies.update(client.cookies)
        reopened.headers["X-Zarya-Studio"] = "1"
        response = reopened.get("/studio/api/draft")
        assert response.status_code == 200
        assert response.json()["preview"] == saved["preview"]
        assert response.json()["project_calculation"] == after
        download = reopened.get(url)
        assert download.status_code == 200
        assert sha256(download.content).digest() == sha256(content).digest()
        for endpoint in ("calculate", "package"):
            response = reopened.post("/studio/api/" + endpoint,
                                     json={"revision": state["revision"]})
            assert response.status_code == 200, response.text
            state = response.json()
            calculation = state["project_calculation"]
            assert findings(calculation)["K-GOST-A03"]["state"] == "ready"
            assert findings(calculation)["V-GOST-A07"]["state"] == "blocked"
            assert calculation["can_release"] is False
        assert state["package"]["state"] == "blocked"
        assert len(rendered) == 1  # blocked package did not regenerate/release

        # Removing only this test's PDF must revoke presence on revalidation.
        path.rename(tmp_path / "ready-k1-k2-review.pdf")
        response = reopened.post("/studio/api/calculate", json={"revision": state["revision"]})
        assert response.status_code == 200, response.text
        state = response.json()
        assert findings(state["project_calculation"])["K-GOST-A03"]["state"] == "blocked"
        assert findings(state["project_calculation"])["DOC-03"]["state"] == "blocked"
        assert state["project_calculation"]["can_release"] is False
        assert reopened.get(url).status_code == 404
        state = studio_tests.answer(reopened, state, "residents", 21)
        assert state["preview"] is None and state["project_calculation"] is None
        assert reopened.get(url).status_code == 404
