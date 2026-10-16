"""Isolated smoke writes; production verification is strictly read-only after login."""
import os
from pathlib import Path
import re

import httpx


def main():
    live = os.environ.get("ZARYA_RAINWATER_TREATMENT_LIVE") == "1"
    if live:
        keys = set(re.findall(r"zarya_[A-Za-z0-9_-]{43}", Path(os.environ["ZARYA_OWNER_KEY_FILE"]).read_text()))
        assert len(keys) == 1
        key = keys.pop()
        base = "https://zaryaproekt.ru"
    else:
        assert os.environ.get("ZARYA_DEPLOY_SMOKE") == "1"
        assert os.environ.get("ZARYA_PROJECTS_DIR") == "/tmp/zarya-smoke/projects"
        from app.intake.pilot_access import AccessStore
        _, key = AccessStore().issue("Rainwater isolated smoke", days=1)
        base = "http://127.0.0.1:8000"
    with httpx.Client(base_url=base, timeout=90, headers={"Origin":base, "X-Zarya-Access":"1", "X-Zarya-Studio":"1"}) as c:
        assert c.get("/studio/api/draft").status_code == 401
        login = c.post("/access/login", json={"key":key,"remember_device":True})
        assert login.status_code == 200
        if live:
            assert all(s in login.headers["set-cookie"] for s in ("Secure", "HttpOnly", "SameSite=strict", "Max-Age="))
        try:
            if not live:
                assert c.post("/studio/api/draft").status_code == 200
            before = c.get("/studio/api/draft").json()
            page = c.get("/studio?view=project")
            assert page.status_code == 200 and "/static/studio.js?v=30" in page.text
            assert "/static/studio.css?v=20" in page.text
            assert "rainTreatmentResult" in c.get("/static/studio.js?v=30").text
            assert "rainwater_treatment_" in c.get("/static/studio_configurator.js?v=5").text
            assert "rainwater_treatment_setup" in before["options"]
            assert before["options"]["rainwater_enabled"] == [{"value":"no","label":"Нет"},{"value":"yes","label":"Да"}]
            assert "rainwater_reuse" in before
            assert "saures_nbiot_point" in before["metering_catalogue"]["choices"]["vu_leak_monitoring"]
            if live:
                assert c.get("/access/admin").status_code == 200
                assert c.get("/studio/api/location/config").status_code == 200
                assert c.get("/studio/api/draft").json() == before
                assert c.post("/studio/api/draft", headers={"Origin":"https://invalid.example"}).status_code == 403
            else:
                c.headers["X-Zarya-Draft"] = before["project_id"]
                answers = dict(residents=20, apartments=8, floors=2, consumer_code="residential_full_bath",
                    hws_type="central", building_height_m=6.6, fire_height_m=4.8, roof_type="flat_accessible",
                    rainwater_enabled="yes", rainwater_purpose="irrigation", rainwater_location="site",
                    rainwater_demand_m3_day=1, rainwater_useful_volume_m3=2,
                    rainwater_collection_area_m2=100, rainwater_collection_factor=0.8,
                    rainwater_profile="2026-06-01;50\n2026-06-02;0\n2026-06-03;0",
                    rainwater_source="Synthetic isolated verification; factor is a test input")
                answers.update({"rainwater_"+k:v for k,v in dict(
                    treatment_setup="residential_terrace_irrigation", treatment_surface="hard_terrace",
                    treatment_selection_flow_lps=.4, treatment_filter_loss_m=1.8, treatment_uv_loss_m=.2,
                    treatment_selection_source="Synthetic smoke fixture, not supplier approval",
                    treatment_quality_basis="Synthetic check only, not a water analysis",
                    pump_setup="submersible_irrigation", pump_flow_lps=.4,
                    pump_geometric_head_m=3, pump_terminal_head_m=20,
                    pump_network_loss_m=2, pump_treatment_loss_m=99,
                    pump_loss_source="Synthetic isolated test only",
                    pump_min_submergence_m=.5, pump_max_submergence_m=2,
                    pump_temperature_c=15, pump_clean_water="yes", pump_pipe_inner_mm=26,
                    pump_pipe_length_m=12, outlets_count=2, hose_choice="custom",
                    hose_model="Synthetic hose, not a purchased model", hose_length_m=25,
                    hose_inner_mm=25, hose_pn_bar=10, hose_loss_m=3, hose_sets=2).items()})
                r = c.post("/studio/api/calculate", json={"revision":before["revision"],"answers":answers})
                assert r.status_code == 200, r.status_code
                state = r.json()
                assert state["rainwater_reuse"]["totals"]["supplied_m3"] == 2
                assert state["calculation"]["total"]["q_day"] == 3.6
                assert state["rainwater_reuse"]["pump"]["selected"]["id"] == "vodomet-55-50-a"
                assert state["rainwater_reuse"]["pump"]["duty"]["h_m"] == 30
                assert not state["project_calculation"]["can_release"]
                r = c.post("/studio/api/preview", json={"revision":state["revision"]})
                assert r.status_code == 200, r.status_code
                state = r.json()
                doc = next(d for d in state["preview"]["documents"] if d["kind"] == "rainwater_reuse_pdf")
                assert doc["state"] == "incomplete"
                file = c.get(f'/studio/api/preview/{state["preview"]["id"]}/files/{doc["name"]}')
                assert file.status_code == 200 and file.content.startswith(b"%PDF-")
                from io import BytesIO
                from pypdf import PdfReader
                pdf = PdfReader(BytesIO(file.content))
                assert len(pdf.pages) == 7
                assert "DUV-1-48-N MST" in pdf.pages[2].extract_text()
                assert not state["rainwater_reuse"]["treatment"]["quality_verified"]
                assert "55/50" in pdf.pages[4].extract_text()
                assert state["package"] is None
                r = c.post("/studio/api/calculate", json={"revision":state["revision"], "answers":{"rainwater_hose_pn_bar":3}})
                assert r.status_code == 200
                assert r.json()["rainwater_reuse"]["pump"]["selected"] is None
                assert r.json()["rainwater_reuse"]["pump"]["status"] == "no_match"
                r = c.post("/studio/api/calculate", json={"revision":r.json()["revision"], "answers":{"rainwater_hose_pn_bar":10,"rainwater_pump_flow_lps":.3}})
                assert r.status_code == 200
                assert r.json()["rainwater_reuse"]["treatment"]["head_loss_m"] is None
                assert r.json()["rainwater_reuse"]["pump"]["selected"] is None
                r = c.post("/studio/api/calculate", json={"revision":r.json()["revision"], "answers":{"rainwater_pump_flow_lps":.4,"roof_type":"gable"}})
                assert r.status_code == 200
                assert r.json()["rainwater_reuse"]["treatment"]["status"] == "out_of_scope"
                assert r.json()["rainwater_reuse"]["pump"]["selected"] is None
        finally:
            assert c.post("/access/logout").status_code == 303
        assert c.get("/studio/api/draft").status_code == 401
    print("Production read-only smoke passed" if live else "Isolated treatment/PDF/stale selection smoke passed")


if __name__ == "__main__":
    main()

