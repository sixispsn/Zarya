"""Network/PDF smoke for a NEW isolated pilot container, never production data.

Run through docker exec -i <smoke-container> python - < this script.
No invitation/session secret is printed or written outside the disposable store.
"""
from io import BytesIO
import json
import os
import time

import httpx
from pypdf import PdfReader
from weasyprint import HTML

from app.intake.pilot_access import AccessStore


def main():
    if not (os.environ.get("ZARYA_DEPLOY_SMOKE") == "1"
            and os.environ.get("ZARYA_PROJECTS_DIR") == "/tmp/zarya-smoke/projects"
            and os.environ.get("ZARYA_PILOT_DIR") == "/tmp/zarya-smoke/projects/_pilot"
            and os.environ.get("ZARYA_PILOT_ENABLED") == "1"):
        raise SystemExit("Refusing mutations outside isolated pilot smoke container")
    access = AccessStore()
    deadline = time.monotonic() + 30
    while True:
        try:
            if httpx.get("http://127.0.0.1:8000/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise SystemExit("Isolated app did not become ready")
        time.sleep(0.2)
    alice_id, alice_key = access.issue("Smoke A", days=1)
    _, bob_key = access.issue("Smoke B", days=1)
    base = "http://127.0.0.1:8000"
    headers = {"Origin": base, "X-Zarya-Studio": "1", "X-Zarya-Access": "1"}
    with httpx.Client(base_url=base, headers=headers, timeout=240) as alice, httpx.Client(base_url=base, headers=headers, timeout=30) as bob:
        def call(client, method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            assert response.status_code == 200, (path, response.status_code)
            return response
        for client, key in ((alice, alice_key), (bob, bob_key)):
            assert client.get("/studio/api/draft").status_code == 401
            call(client, "POST", "/access/login", json={"key": key})
            assert "Выйти" in call(client, "GET", "/studio").text
            assert client.get("/wizard/projects").status_code == 403
        print("PASS: personal network login, legacy archive denied", flush=True)
        call(alice, "POST", "/access/participation", json={"accepted": True, "version": "pilot-auto-archive-v1"})
        state = call(alice, "POST", "/studio/api/draft").json()
        pdf = HTML(string="<meta charset='utf-8'><p>Количество жителей: 20. Этажность: 2.</p>").write_pdf()
        state = call(alice, "POST", "/studio/api/files", data={"revision": state["revision"]},
                     files=[("files", ("smoke-input.pdf", pdf, "application/pdf"))]).json()
        document = f'/studio/api/files/{state["documents"][0]["id"]}'
        assert call(alice, "GET", document).content.startswith(b"%PDF")
        assert bob.get(document).status_code == 404
        print("PASS: actual PDF upload isolated between participants", flush=True)
        answers = dict(residents=20, apartments=8, floors=2,
                       consumer_code="residential_full_bath", hws_type="central",
                       building_height_m=6.6, fire_height_m=4.8,
                       guaranteed_head_m=5, h_geom_m=6, hws_heater_in_scope="no",
                       pressure_loss_mode="sections", t3_loss_mode="sections",
                       roof_type="flat_non_accessible", storm_city="moscow",
                       storm_roof_area_m2=252, storm_walls_area_m2=0,
                       floor_height_m=3.3, basement_kind="basement", basement_floor_m=-3.1,
                       section_drainage="internal")
        state = call(alice, "POST", "/studio/api/calculate", json={"revision": state["revision"], "answers": answers}).json()
        calc = state["project_calculation"]
        assert calc["flows"]["q_day_tot"] == 3.6
        assert calc["flows"]["sewage_l_per_s"] == 2.293
        assert calc["storm"]["q_total_l_per_s"] == 5.395
        assert calc["can_preview"] and not calc["can_release"]
        state = call(alice, "POST", "/studio/api/preview", json={"revision": state["revision"]}).json()
        assert state["pilot_archive"]["state"] == "saved"
        from app.intake.pilot_capture import PilotCaptureStore
        from app.intake.pilot_access import Principal
        baseline = state["pilot_archive"]
        generated = PilotCaptureStore().generated(Principal(alice_id,"Smoke A","tester",None), baseline["object_id"], baseline["version"])
        assert generated and generated["kind"] == "preview"
        preview = state["preview"]
        for kind in ("pz_pdf", "wastewater_scheme_pdf"):
            row = next(row for row in preview["documents"] if row["kind"] == kind)
            url = f'/studio/api/preview/{preview["id"]}/files/{row["name"]}'
            response = call(alice, "GET", url)
            copied = next(f for f in generated["files"] if f["name"] == row["name"])
            baseline_url = f'/studio/pilot-generated/{generated["bundle_id"]}/files/{copied["id"]}'
            baseline_bytes = response.content
            assert call(alice,"GET",baseline_url).content == baseline_bytes
            assert bob.get(baseline_url).status_code == 404
            assert PdfReader(BytesIO(response.content)).pages
            assert bob.get(url).status_code == 404
        state = call(alice, "POST", "/studio/api/package", json={"revision": state["revision"]}).json()
        assert state["package"] == {"state": "blocked", "documents": []}
        print("PASS: unchanged demand/storm, real PZ and sewer PDF, incomplete release blocked", flush=True)
        snapshot = call(alice, "GET", "/studio/api/pilot-snapshot").json()
        assert snapshot["snapshot"]["results"]["state"] == "current"
        assert "smoke-input.pdf" not in str(snapshot)
        version_payload = {"revision": snapshot["revision"], "snapshot_sha256": snapshot["snapshot_sha256"],
                           "request_id": "a" * 32, "title": "Smoke object", "consent": True}
        saved = call(alice, "POST", "/studio/api/pilot-versions", json=version_payload).json()
        assert call(alice, "POST", "/studio/api/pilot-versions", json=version_payload).json() == saved
        assert saved["version"] == 1 and bob.get(saved["url"]).status_code == 404
        saved_html = call(alice, "GET", saved["url"]).text
        assert "3.6" in saved_html and "smoke-input.pdf" not in saved_html
        metadata = {"object_id": saved["object_id"], "version": 1, "request_id": "b" * 32,
                    "note": "Synthetic final bundle", "consent": True, "expertise_declared": True}
        bundle = call(alice, "POST", "/studio/api/pilot-attachments", data={"metadata":json.dumps(metadata)},
                      files=[("files", ("final.pdf", pdf, "application/pdf"))]).json()
        assert call(alice, "POST", "/studio/api/pilot-attachments", data={"metadata":json.dumps(metadata)},
                    files=[("files", ("final.pdf", pdf, "application/pdf"))]).json() == bundle
        from app.intake.pilot_access import Principal
        from app.intake.pilot_attachments import PilotAttachmentStore
        stored = PilotAttachmentStore().list(Principal(alice_id,"Smoke A","tester",None),saved["object_id"],1)[0]
        attachment_url = f'/studio/pilot-attachments/{bundle["bundle_id"]}/files/{stored["files"][0]["id"]}'
        attachment = call(alice, "GET", attachment_url)
        assert attachment.content == pdf and "attachment" in attachment.headers["content-disposition"]
        assert bob.get(attachment_url).status_code == 404
        saved_html = call(alice, "GET", saved["url"]).text
        assert "со слов инженера" in saved_html
        did = access.active_draft(alice_id)
        assert alice.post("/access/logout").status_code == 303
        assert alice.get(document).status_code == 401
        call(alice, "POST", "/access/login", json={"key": alice_key})
        assert access.active_draft(alice_id) == did
        assert call(alice, "GET", document).content.startswith(b"%PDF")
        feedback = {"request_id": "f" * 32, "category": "documents", "message": "Synthetic smoke: inspect document generation."}
        first = call(alice, "POST", "/access/feedback", json=feedback).json()
        assert call(alice, "POST", "/access/feedback", json=feedback).json() == first
        assert alice.get("/access/feedback").status_code == 403
        _, owner_key = access.issue("Smoke owner", role="admin", days=1)
        with httpx.Client(base_url=base, headers=headers, timeout=30) as owner:
            call(owner, "POST", "/access/login", json={"key": owner_key})
            assert first["ticket"] in call(owner, "GET", "/access/feedback").text
            assert saved["sha256"] in call(owner, "GET", saved["url"]).text
            assert call(owner, "GET", attachment_url).content == pdf
        state = call(alice, "POST", "/studio/api/files/delete", json={"revision": state["revision"], "document_id": document.rsplit("/", 1)[-1]}).json()
        assert state["documents"] == [] and state["preview"] is None and state["calculation"] is None
        assert alice.get(document).status_code == 404 and alice.get(url).status_code == 404
        assert call(alice, "GET", saved["url"]).text == saved_html
        assert call(alice, "GET", attachment_url).content == pdf
        assert call(alice, "GET", baseline_url).content == baseline_bytes
        print("PASS: exact generated PZ/scheme baseline, auto-consent capture, baseline survives source deletion", flush=True)
        print("PASS: final PDF bundle, idempotent retry, owner-only shared download, survives source deletion", flush=True)
        print("PASS: consent snapshot, retry receipt, private owner view and snapshot survives source deletion", flush=True)
        print("PASS: text-only feedback, duplicate prevention, owner inbox, source deletion and stale PDF revocation", flush=True)
        access.revoke(alice_id)
        assert alice.get(document).status_code == 401
        assert alice.get(attachment_url).status_code == 401
        print("PASS: resume and immediate revocation of stored-document access", flush=True)
    print("ALL ISOLATED PILOT CONTAINER CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
