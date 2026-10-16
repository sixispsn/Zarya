"""HTTP + common-generator smoke. Only writes inside an isolated disposable app."""
import os
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader


def main():
    assert os.environ.get("ZARYA_DEPLOY_SMOKE") == "1"
    assert os.environ.get("ZARYA_PROJECTS_DIR") == "/tmp/zarya-smoke/projects"
    from app.intake.pilot_access import AccessStore
    from app.intake.studio_intake import answer_field, build_handoff_request, calculate_draft
    from app.intake.project_builder import build_project
    from app.intake.yaml_io import load_request, dump_request
    from app.pz.wastewater_graphic_exports import generate_wastewater_graphic_export, wastewater_graphic_export
    _, key = AccessStore().issue("Unified section isolated verification", days=1)
    qa = Path("/tmp/zarya-smoke/qa")
    qa.mkdir(parents=True, exist_ok=True)
    values = dict(residents=20, apartments=8, floors=2, building_height_m=6.6, fire_height_m=4.8,
                  consumer_code="residential_full_bath", hws_type="central", guaranteed_head_m=5,
                  h_geom_m=6, pressure_loss_mode="ready", h_il_m=3, h_vvod_m=1,
                  t3_loss_mode="ready", h_il_hot_m=4, hws_heater_in_scope="no",
                  floor_height_m=3.3, basement_kind="basement", basement_floor_m=-3.1,
                  roof_type="flat_non_accessible", section_drainage="internal")
    for system, dn, grade, mark, target in (("k1",150,.02,-1.8,"КК-1"), ("k2",200,.008,-1.65,"ДК-2")):
        values.update({f"section_{system}_{key}":value for key,value in dict(
            dn_mm=dn, slope=grade, outlet_invert_m=mark, discharge_point=target,
            source_ref="Isolated smoke fixture; not a design approval").items()})
    base = "http://127.0.0.1:8000"
    with httpx.Client(base_url=base, timeout=90, headers={"Origin":base, "X-Zarya-Access":"1", "X-Zarya-Studio":"1"}) as c:
        assert c.post("/access/login", json={"key":key,"remember_device":True}).status_code == 200
        try:
            state = c.post("/studio/api/draft").json()
            c.headers["X-Zarya-Draft"] = state["project_id"]
            r = c.post("/studio/api/calculate", json={"revision":state["revision"], "answers":values})
            assert r.status_code == 200
            state = r.json()
            scheme = state["project_calculation"]["sewer_scheme"]
            assert scheme["presentation"] == "representative" and scheme["available"] and not scheme["ready"]
            assert not state["project_calculation"]["can_release"]
            r = c.post("/studio/api/preview", json={"revision":state["revision"]})
            assert r.status_code == 200
            state = r.json()
            docs = {row["kind"]:row for row in state["preview"]["documents"]}
            assert docs["wastewater_scheme_pdf"]["state"] == docs["wastewater_package_pdf"]["state"] == "preliminary"
            loaded = {}
            for kind, name in (("wastewater_scheme_pdf", "section.pdf"),
                               ("wastewater_package_pdf", "section-package.pdf"),
                               ("wastewater_pz_pdf", "section-pz.pdf")):
                url = f'/studio/api/preview/{state["preview"]["id"]}/files/{docs[kind]["name"]}'
                f = c.get(url)
                assert f.status_code == 200 and f.headers["x-zarya-preview"] == "true"
                (qa / name).write_bytes(f.content)
                loaded[kind] = PdfReader(BytesIO(f.content))
            standalone = loaded["wastewater_scheme_pdf"]
            merged = loaded["wastewater_package_pdf"]
            offset = len(loaded["wastewater_pz_pdf"].pages)
            assert len(standalone.pages) == 1
            assert standalone.pages[0].extract_text() == merged.pages[offset].extract_text()
            # PDF serialization rounds floating coordinates; this tolerance is
            # sub-micrometre precision, not a drawing/layout tolerance.
            assert all(abs(float(a)-float(b)) < 1e-5 for a,b in
                       zip(standalone.pages[0].mediabox, merged.pages[offset].mediabox))
            assert "не документ к выпуску" in standalone.pages[0].extract_text()
            for text in ("0,020", "0,008", "-1,80", "-1,65", "КК-1", "ДК-2"):
                assert text in standalone.pages[0].extract_text(), text
            assert merged.outline
            d = dict(revision=0, answers={}, documents=[])
            for k,v in values.items():
                answer_field(d, k, v)
            d["calculation"] = calculate_draft(d)
            p = build_project(load_request(dump_request(build_handoff_request(d))))
            assert wastewater_graphic_export(p, "k1-k2").presentation == "representative"
            direct = qa / "section-restored.pdf"
            result = generate_wastewater_graphic_export(p, "k1-k2", str(direct))
            assert not result.ready and result.backend == "representative-section"
            assert standalone.pages[0].extract_text() == PdfReader(direct).pages[0].extract_text()
            assert not p.sewage.pipes and not p.sewage.elements
            old_url = f'/studio/api/preview/{state["preview"]["id"]}/files/{docs["wastewater_scheme_pdf"]["name"]}'
            r = c.post("/studio/api/calculate", json={"revision":state["revision"], "answers":{"section_k1_slope":.015}})
            assert r.status_code == 200 and c.get(old_url).status_code == 404
        finally:
            assert c.post("/access/logout").status_code == 303
    print("PASS: HTTP preview, merged PDF, YAML restoration, missing-data status and stale-link revocation")


if __name__ == "__main__":
    main()
