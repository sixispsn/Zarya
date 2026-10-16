"""Network checks on an isolated release container, never real project stores."""
import os
from io import BytesIO

import httpx
from pypdf import PdfReader

from app.intake.pilot_access import AccessStore
from app.pz.metering_options import METERING_OPTIONS


def main():
    assert os.environ.get("ZARYA_DEPLOY_SMOKE") == "1"
    assert os.environ.get("ZARYA_PROJECTS_DIR") == "/tmp/zarya-smoke/projects"
    assert os.environ.get("ZARYA_PILOT_DIR") == "/tmp/zarya-smoke/projects/_pilot"
    _, key = AccessStore().issue("Metering release smoke", days=1)
    base = "http://127.0.0.1:8000"
    headers = {"Origin": base, "X-Zarya-Studio": "1", "X-Zarya-Access": "1"}
    with httpx.Client(base_url=base, headers=headers, timeout=240) as client:
        def call(method, path, **kwargs):
            r = client.request(method, path, **kwargs)
            assert r.status_code == 200, (path, r.status_code)
            return r
        call("POST", "/access/login", json={"key": key})
        state = call("POST", "/studio/api/draft").json()
        client.headers["X-Zarya-Draft"] = state["project_id"]
        page = call("GET", "/studio").text
        assert "/static/studio.js?v=25" in page
        assert "Водомерный узел" in call("GET", "/static/studio_configurator.js?v=2").text
        answers = dict(residents=20, apartments=8, floors=2,
            consumer_code="residential_full_bath", hws_type="central",
            building_height_m=6.6, fire_height_m=4.8, guaranteed_head_m=5,
            h_geom_m=6, hws_heater_in_scope="no", roof_type="flat_non_accessible",
            storm_city="moscow", storm_roof_area_m2=252, storm_walls_area_m2=0,
            floor_height_m=3.3, basement_kind="basement", basement_floor_m=-3.1,
            section_drainage="internal")
        state = call("POST", "/studio/api/calculate", json={"revision": state["revision"], "answers": answers}).json()
        baseline = state["project_calculation"]
        assert baseline["metering_options"] == []
        wishes = dict(vu_technology="ultrasonic", vu_telemetry="nb_iot",
            vu_leak_monitoring="requested", vu_tamper_monitoring="requested",
            vu_valve_feedback="requested", vu_assembly="factory_module",
            vu_magnetic_filter="requested", vu_power="battery")
        state = call("POST", "/studio/api/calculate", json={"revision": state["revision"], "answers": wishes}).json()
        calculated = state["project_calculation"]
        assert len(calculated["metering_options"]) == len(METERING_OPTIONS)
        for name in ("flows", "meters", "head", "pumps", "fire", "storm"):
            assert calculated[name] == baseline[name], name
        restored = call("GET", "/studio/api/draft").json()
        values = {f["key"]: f["value"] for f in restored["fields"]}
        assert all(values[k] == v for k, v in wishes.items())
        state = call("POST", "/studio/api/preview", json={"revision": restored["revision"]}).json()
        preview = state["preview"]
        kinds = []
        for row in preview["documents"]:
            if row["kind"] not in ("pz_pdf", "spec_pdf", "metering_scheme_pdf"):
                continue
            pdf = call("GET", f'/studio/api/preview/{preview["id"]}/files/{row["name"]}').content
            pages = PdfReader(BytesIO(pdf)).pages
            text = "\n".join(p.extract_text() for p in pages)
            assert "NB-IoT" in text, row["kind"]
            kinds.append(row["kind"])
        assert "pz_pdf" in kinds and "metering_scheme_pdf" in kinds, kinds
        assert client.post("/access/logout").status_code == 303
        assert client.get("/studio/api/draft").status_code == 401
    print("PASS: live options persist; Q/H unchanged; PZ/detail PDF includes requests; logout secured.", flush=True)


if __name__ == "__main__":
    main()
