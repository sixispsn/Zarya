"""HTTP/PDF smoke test for an isolated release container, never production data.

Run with docker exec -i <isolated-container> python - < this_file.py.
The container must have ZARYA_DEPLOY_SMOKE=1 and a temporary projects directory.
"""
from io import BytesIO
import os
from pathlib import Path

import httpx
from pypdf import PdfReader
from weasyprint import HTML


def main():
    if (os.environ.get("ZARYA_DEPLOY_SMOKE") != "1"
            or os.environ.get("ZARYA_PROJECTS_DIR") != "/tmp/zarya-smoke/projects"):
        raise SystemExit("Refusing mutation: not an isolated release smoke container")
    output = Path("/tmp/zarya-smoke/results")
    output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=240,
                      headers={"X-Zarya-Studio": "1"}) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            assert response.status_code == 200, (path, response.status_code, response.text[:500])
            return response

        assert call("GET", "/health").json() == {"status": "healthy"}
        assert client.get("/").headers["location"] == "/studio"
        studio = call("GET", "/studio").text
        assert 'id="clarification-dialog"' in studio
        assert 'data-view="home"' in studio
        assert 'data-view="project"' in call("GET", "/studio?view=project").text
        header = studio.split('<header class="site-header">')[1].split('</header>')[0]
        assert 'href="/studio/projects"' in header
        assert 'href="/wizard"' not in header and 'data-studio-handoff' not in header
        for asset in ("studio.js", "studio.css", "studio_questions.js", "studio_motion.js", "studio_transport.js"):
            assert len(call("GET", "/static/" + asset).content) > 100
        assert "#ff123b" in call("GET", "/static/studio.css").text.lower()
        for path in ("/wizard", "/wizard/projects", "/wizard/building-model"):
            call("GET", path)
        print("PASS: health, stable home, explicit resume, primary Studio navigation", flush=True)

        state = call("POST", "/studio/api/draft").json()
        before = state["revision"]
        assert 'href="/studio?view=project"' in call("GET", "/studio/projects").text
        assert call("GET", "/studio/api/draft").json()["revision"] == before
        pdf = HTML(string="<meta charset='utf-8'><p>Количество жителей: 20. Этажность: 2.</p>").write_pdf()
        state = call("POST", "/studio/api/files", data={"revision": state["revision"]},
                     files=[("files", ("smoke-input.pdf", pdf, "application/pdf"))]).json()
        assert state["documents"]
        answers = dict(residents=20, apartments=8, floors=2,
                       consumer_code="residential_full_bath", hws_type="central",
                       building_height_m=6.6, fire_height_m=4.8,
                       guaranteed_head_m=5, h_geom_m=6, hws_heater_in_scope="no",
                       pressure_loss_mode="sections", t3_loss_mode="sections",
                       roof_type="flat_non_accessible", storm_city="moscow",
                       storm_roof_area_m2=252, storm_walls_area_m2=0,
                       floor_height_m=3.3, basement_kind="basement", basement_floor_m=-3.1,
                       section_drainage="internal")
        state = call("POST", "/studio/api/calculate", json={
            "revision": state["revision"], "answers": answers}).json()
        result = state["project_calculation"]
        assert result["flows"]["q_day_tot"] == 3.6
        assert result["flows"]["sewage_l_per_s"] == 2.293
        assert result["storm"]["q_total_l_per_s"] == 5.395
        assert result["can_preview"] and not result["can_release"]
        assert result["head"]["required_m"] is None and result["pumps"] is None
        assert result["sewer_scheme"]["representative"]["ready"]
        assert not result["sewer_scheme"]["ready"]
        assert not any(step["id"] == "losses" for step in state["next_steps"])
        print("PASS: PDF input, current flows, no fabricated head or extra route question", flush=True)

        def preview(state, prefix, required):
            state = call("POST", "/studio/api/preview", json={"revision": state["revision"]}).json()
            data = state["preview"]
            texts = {}
            for kind in required:
                row = next(row for row in data["documents"] if row["kind"] == kind)
                path = f'/studio/api/preview/{data["id"]}/files/{row["name"]}'
                response = call("GET", path)
                assert response.headers["x-zarya-preview"] == "true"
                reader = PdfReader(BytesIO(response.content))
                assert reader.pages
                texts[kind] = " ".join(" ".join(p.extract_text().split()) for p in reader.pages)
                (output / f"{prefix}-{kind}.pdf").write_bytes(response.content)
                with httpx.Client(base_url=str(client.base_url)) as outsider:
                    assert outsider.get(path).status_code == 404
            return state, texts

        state, texts = preview(state, "project", ("pz_pdf", "v1_calculation_pdf", "pump_selection_pdf", "wastewater_scheme_pdf"))
        section = texts.pop("wastewater_scheme_pdf")
        assert "К1" in section and "К2" in section
        assert "Подвал" in section
        for value in texts.values():
            assert "Расчёт напора В1/Т3 не завершён" in value
            assert "повышение напора не требуется" not in value
        state = call("POST", "/studio/api/package", json={"revision": state["revision"]}).json()
        assert state["package"] == {"state": "blocked", "documents": []}
        print("PASS: private real PDF preview and blocked incomplete release", flush=True)

        for kind in ("two", "three"):
            state = call("POST", "/studio/api/study", json={"revision": state["revision"], "kind": kind}).json()
            assert state["project_calculation"]["can_preview"]
            state, _ = preview(state, kind, ("wastewater_scheme_pdf", "wastewater_pz_pdf"))
            state = call("POST", "/studio/api/study/exit", json={"revision": state["revision"]}).json()
            assert state["project_calculation"]["flows"]["q_day_tot"] == 3.6
            print(f"PASS: {kind}-storey study, runtime legacy parity, scheme and IOS3 PDF", flush=True)

        # Regression: a PDF with a 12–16-storey home used to produce HTTP 500
        # during the next calculation, mislabeled in the UI as an upload failure.
        state = call("POST", "/studio/api/calculate", json={
            "revision": state["revision"], "answers": {
                "floors": 15, "building_height_m": 48, "fire_height_m": 45,
            }}).json()
        assert state["project_calculation"]["state"] == "needs_inputs"
        assert state["project_calculation"]["missing"] == ["fire_corridor_length_m"]
        assert state["calculation"]["total"]["q_day"] == 3.6
        assert state["documents"]
        state = call("POST", "/studio/api/calculate", json={
            "revision": state["revision"], "answers": {"fire_corridor_length_m": 12}}).json()
        assert state["project_calculation"]["state"] == "calculated"
        assert state["project_calculation"]["fire"]["streams"] == 2
        assert state["documents"]
        print("PASS: missing fire input is a question, PDF/demand retained, answer unblocks calculation", flush=True)
    print("ALL RELEASE CONTAINER CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
