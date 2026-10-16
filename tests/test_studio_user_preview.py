"""Ordinary explicit input -> real PDF -> download -> reopen -> revoke.

No replacement of handoff, Project, calculation, readiness or renderer.
All inputs are explicit synthetic test data; this is not a release approval.
"""
from hashlib import sha256
from io import BytesIO
import json

import fitz
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.lib.units import mm

from app.intake.studio_store import StudioStore
from app.pz.artifact_readiness import WASTEWATER_GRAPHIC_ARTIFACTS
from tests import test_studio as studio_tests
from tests.test_studio_risers import building_answers, rows as risers
from tests.test_studio_sewer_pipes import rows as pipes
from tests.test_studio_sewer_elements import rows as elements
from tests.test_studio_fans import evidence
from tests.test_studio_preview_readiness import findings

client = studio_tests.client


def full_answers():
    return {**building_answers(), "object_name":"Контроль обычного ввода Studio · TEST-ONLY",
            "sewer_pipes":pipes(), "sewer_elements":elements(),
            "wastewater_fan_ventilation":evidence(), "sewage_risers":risers()}


def assert_frame(content, width, height):
    """Check physical frame and stamp boundaries in the downloaded PDF."""
    # Browser SVG-to-PDF coordinates are quantized; 0.05 mm bounds that
    # conversion error (observed outer-edge deviation is about 0.022 mm).
    tolerance = .05
    with fitz.open(stream=content, filetype="pdf") as document:
        page = document[0]
        assert page.rect.width / mm == pytest.approx(width, abs=.02)
        assert page.rect.height / mm == pytest.approx(height, abs=.02)
        edges = []
        for drawing in page.get_drawings():
            for item in drawing["items"]:
                if item[0] == "l":
                    edges.append((*item[1], *item[2]))
                elif item[0] == "re":
                    r = item[1]
                    edges.extend(((r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1),
                                  (r.x1, r.y1, r.x0, r.y1), (r.x0, r.y1, r.x0, r.y0)))
        for x, y, right, bottom in ((20, 5, width - 5, height - 5),
                                    (width - 190, height - 60, width - 5, height - 5)):
            for expected in ((x, y, right, y), (right, y, right, bottom),
                             (right, bottom, x, bottom), (x, bottom, x, y)):
                # The stamp shares its right/bottom edges with the outer frame;
                # these can be drawn once as longer continuous segments.
                vertical = expected[0] == expected[2]
                fixed, moving = (0, 1) if vertical else (1, 0)
                assert any(
                    abs(edge[fixed] / mm - expected[fixed]) < tolerance
                    and abs(edge[fixed + 2] / mm - expected[fixed]) < tolerance
                    and min(edge[moving], edge[moving + 2]) / mm
                    <= min(expected[moving], expected[moving + 2]) + tolerance
                    and max(edge[moving], edge[moving + 2]) / mm
                    >= max(expected[moving], expected[moving + 2]) - tolerance
                    for edge in edges
                ), expected


def test_user_input_real_pdf_roundtrip_and_revocation(client, tmp_path):
    state = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={
        "revision":state["revision"], "answers":full_answers()})
    assert response.status_code == 200, response.text
    state = response.json()
    before = state["project_calculation"]
    assert before["sewer_scheme"]["ready"] and before["can_preview"]
    assert not before["can_release"]
    assert findings(before)["K-GOST-A03"]["state"] == "conditional"
    response = client.post("/studio/api/preview", json={"revision":state["revision"]})
    assert response.status_code == 200, response.text
    state = response.json()
    after = state["project_calculation"]
    assert findings(after)["K-GOST-A03"]["state"] == "ready"
    assert not after["can_release"]
    assert state["package"] is None
    for key in ("flows", "meters", "head", "pumps", "storm", "sewer_scheme"):
        assert after[key] == before[key], key
    for code, row in findings(before).items():
        if row["state"] == "blocked":
            assert findings(after)[code]["state"] == "blocked", code
    label, kind = WASTEWATER_GRAPHIC_ARTIFACTS["k1-k2"]
    preview = state["preview"]
    assert preview["artifact_readiness"][label]
    assert preview["graphic_artifact_requirements"] == [label]
    store = StudioStore(tmp_path / "studio")
    saved = store.load(state["project_id"])
    assert saved["preview"] == preview
    folder = store.folder(state["project_id"]) / "previews" / preview["id"]
    report = {"folder":str(folder), "documents":[], "blocked":[
        code for code, row in findings(after).items() if row["state"] == "blocked"]}
    downloads = {}
    for document in preview["documents"]:
        path = folder / document["name"]
        content = path.read_bytes()
        url = f'/studio/api/preview/{preview["id"]}/files/{document["name"]}'
        download = client.get(url)
        assert download.status_code == 200, download.text[:200]
        assert download.headers["x-zarya-preview"] == "true"
        assert download.headers["cache-control"] == "private, no-store"
        assert sha256(download.content).digest() == sha256(content).digest()
        pdf = PdfReader(BytesIO(content))
        assert pdf.pages
        texts = [p.extract_text() or "" for p in pdf.pages]
        report["documents"].append({**document, "path":str(path), "pages":len(pdf.pages),
                                   "sha256":sha256(content).hexdigest()})
        downloads[document["kind"]] = (url, content, texts)
        if document["kind"] == kind:
            assert document["state"] == "ready"
            assert len(pdf.pages) == 1
            assert_frame(content, 420, 594)
            assert "ПРИНЦИПИАЛЬНАЯ СХЕМА НЕ СФОРМИРОВАНА" not in texts[0]
            # K2 columns in this canonical sheet are labelled by roof funnel,
            # not by hidden pipe registry IDs. Verify the actual drawing labels.
            for rid in ("К1-Ст1", "К1-Ст2", "К2-Вр1", "К2-Вр2", "К1-Вып1", "К2-Вып1"):
                assert rid in texts[0]
        if document["kind"] == "wastewater_package_pdf":
            assert document["state"] == "preliminary"
        if document["kind"] in {"balance_pdf", "wastewater_balance_pdf"}:
            assert len(pdf.pages) == 1
            assert_frame(content, 420, 297)
            assert float(pdf.pages[0].mediabox.width) > float(pdf.pages[0].mediabox.height)
    for required in ("wastewater_scheme_pdf", "wastewater_package_pdf", "wastewater_pz_pdf",
                     "wastewater_calculation_pdf", "wastewater_balance_pdf", "wastewater_spec_pdf", "balance_pdf"):
        assert required in downloads
    # Canonical composition: calculations and balance are already appended to PZ.
    pz = downloads["wastewater_pz_pdf"][2]
    calculation = downloads["wastewater_calculation_pdf"][2]
    balance = downloads["wastewater_balance_pdf"][2]
    assert pz[-len(calculation) - len(balance):] == calculation + balance
    assert downloads["wastewater_package_pdf"][2] == (
        pz + downloads[kind][2] + downloads["wastewater_ugo_pdf"][2]
        + downloads["wastewater_spec_pdf"][2])
    report_path = tmp_path / "preview-evidence.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nPreview evidence: {report_path}")
    # Restart HTTP client and disk store, no in-memory substitution.
    with TestClient(studio_tests.app) as reopened:
        reopened.cookies.update(client.cookies)
        reopened.headers["X-Zarya-Studio"] = "1"
        restored = reopened.get("/studio/api/draft").json()
        assert restored["preview"] == preview
        assert restored["project_calculation"] == after
        url, content, _ = downloads[kind]
        assert reopened.get(url).content == content
        # The normal release endpoint must remain blocked, not bypassed.
        response = reopened.post("/studio/api/package", json={"revision":state["revision"]})
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["package"] == {"state":"blocked", "documents":[]}
        assert state["preview"] == preview
        assert not state["project_calculation"]["can_release"]
        # Editing a real riser invalidates current links but keeps archived bytes.
        state = studio_tests.answer(reopened, state, "sewage_risers", risers()[:1])
        assert state["preview"] is None and state["project_calculation"] is None
        assert reopened.get(url).status_code == 404
        assert (folder / next(d["name"] for d in preview["documents"] if d["kind"] == kind)).read_bytes() == content
        response = reopened.post("/studio/api/calculate", json={"revision":state["revision"]})
        assert response.status_code == 200, response.text
        calculation = response.json()["project_calculation"]
        assert not calculation["sewer_scheme"]["ready"] and not calculation["can_release"]
        assert any("Режим стояка" in r for r in calculation["sewer_scheme"]["reasons"])
