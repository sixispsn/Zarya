"""Local public-API acceptance for the optional explicit V2 model.

Uses control inputs only, never production storage or frozen L06 results.
PYTHONPATH=. venv/bin/python scripts/check_studio_fire_station.py
"""
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from scripts.build_samara_section_study import load_basis, make_draft
from tests.test_studio_fire_station import control_model


def check():
    output = Path("output/pdf/studio-fire-station").resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = {k: v["value"] for k,v in make_draft(load_basis())["answers"].items()}
    inputs.update(fire_topology="separate", fire_station_model=control_model())
    with TemporaryDirectory(prefix="zarya-station-qa-") as folder, patch.dict(os.environ, {
            "ZARYA_STUDIO_ENABLED":"1", "ZARYA_PILOT_ENABLED":"0", "ZARYA_NORMATIVE_MONITOR_ENABLED":"0",
            "ZARYA_STUDIO_DIR":folder+"/studio", "ZARYA_PROJECTS_DIR":folder+"/projects"}):
        from app.main import app
        with TestClient(app) as client:
            client.headers["X-Zarya-Studio"] = "1"
            def state(response):
                assert response.status_code == 200, response.text
                return response.json()
            current = state(client.post("/studio/api/draft"))
            current = state(client.post("/studio/api/calculate", json={"revision":current["revision"], "answers":inputs}))
            result = current["project_calculation"]
            assert result["state"] == "calculated" and result["can_preview"] and not result["can_release"]
            assert result["fire_station"]["state"] == "preliminary"
            current = state(client.post("/studio/api/preview", json={"revision":current["revision"]}))
            documents = {r["kind"]:r for r in current["preview"]["documents"]}
            proof = output / "В2_обычный_Studio.pdf"
            writer = PdfWriter()
            urls = []
            for kind,title in [("fire_station_input_pdf","В2. Вводы и насосная"),
                               ("hydraulic_pdf","В2. Гидравлический расчёт сети"),
                               ("pump_selection_pdf","Подбор насосов В1 и В2")]:
                row = documents[kind]
                url = f'/studio/api/preview/{current["preview"]["id"]}/files/{row["name"]}'
                response = client.get(url)
                assert response.status_code == 200 and response.headers["x-zarya-preview"] == "true"
                writer.append(PdfReader(BytesIO(response.content)), outline_item=title, import_outline=True)
                urls.append(url)
            with proof.open("wb") as stream:
                writer.write(stream)
            current = state(client.post("/studio/api/package", json={"revision":current["revision"]}))
            assert current["package"]["state"] == "blocked"
            with TestClient(app) as other:
                other.headers["X-Zarya-Studio"] = "1"
                state(other.post("/studio/api/draft"))
                assert all(other.get(url).status_code == 404 for url in urls)
            state(client.patch("/studio/api/answer", json={"revision":current["revision"], "field":"fire_station_model", "value":None}))
            assert all(client.get(url).status_code == 404 for url in urls)
            audit = dict(result=result, pdf=str(proof), pages=len(PdfReader(proof).pages),
                         private_and_revocation_checked=True, release_blocked=True)
            (output / "audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2))
            (output / "explicit-control-model.json").write_text(json.dumps(inputs["fire_station_model"],ensure_ascii=False,indent=2))
            (output / "control-answers.json").write_text(json.dumps(inputs,ensure_ascii=False,indent=2))
            print(json.dumps({k:audit[k] for k in ("pdf","pages","private_and_revocation_checked","release_blocked")},ensure_ascii=False))


if __name__ == "__main__":
    check()
