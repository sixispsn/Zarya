"""Local acceptance: real PDF upload + public Studio API, never a study fixture.

PYTHONPATH=. venv/bin/python scripts/check_samara_ordinary_studio.py --source /path/to/3.2.pdf
Inputs are the already approved study assumptions, entered as a user would.
No frozen request, fire station, manufacturer review or private project is loaded.
"""
from argparse import ArgumentParser
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from scripts.build_samara_section_study import load_basis, make_draft

ROOT = Path(__file__).resolve().parents[1]


def check(source: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="zarya-ordinary-studio-") as temporary:
        env = {"ZARYA_STUDIO_ENABLED": "1", "ZARYA_PILOT_ENABLED": "0",
               "ZARYA_NORMATIVE_MONITOR_ENABLED": "0",
               "ZARYA_STUDIO_DIR": temporary + "/studio",
               "ZARYA_PROJECTS_DIR": temporary + "/projects"}
        with patch.dict(os.environ, env):
            from app.main import app
            with TestClient(app) as client:
                client.headers["X-Zarya-Studio"] = "1"

                def state(response):
                    assert response.status_code == 200, response.text
                    return response.json()

                current = state(client.post("/studio/api/draft"))
                current = state(client.post("/studio/api/files",
                    data={"revision": current["revision"]},
                    files=[("files", (source.name, source.read_bytes(), "application/pdf"))]))
                assert len(current["documents"]) == 1 and not current.get("study")
                document = current["documents"][0]
                inputs = {key: row["value"] for key, row in make_draft(load_basis())["answers"].items()}
                inputs["connection_note"] = (
                    "Учебный прогон по 3.2.pdf и разрешённым допущениям от 04.10.2026. "
                    "Hгар=30 м в точке подключения; Hгеом=48,195 м задан явно. "
                    "Трассы и геометрия для проверки, не подтверждённые данные реального проекта.")
                current = state(client.post("/studio/api/calculate",
                    json={"revision": current["revision"], "answers": inputs}))
                result = current["project_calculation"]
                assert result["state"] == "calculated" and result["can_preview"]
                assert not result["can_release"]
                assert result["flows"]["q_day_tot"] == 63
                assert result["flows"]["sewage_l_per_s"] == 4.785
                assert result["storm"]["q_total_l_per_s"] == 11.518
                assert result["head"]["required_m"] == 80.25
                assert result["head"]["pump_m"] == 50.25
                assert result["fire"]["network_topology"] == "separate"
                assert all(path["head"]["km"] == .3 for path in result["head"]["paths"])
                current = state(client.post("/studio/api/preview", json={"revision": current["revision"]}))
                preview = current["preview"]
                downloaded = []
                paths = {}
                for item in preview["documents"]:
                    url = f'/studio/api/preview/{preview["id"]}/files/{item["name"]}'
                    response = client.get(url)
                    assert response.status_code == 200 and response.headers["x-zarya-preview"] == "true"
                    reader = PdfReader(BytesIO(response.content))
                    path = output / item["name"]
                    path.write_bytes(response.content)
                    paths[item["kind"]] = path
                    downloaded.append({**item, "pages": len(reader.pages)})
                assert "hydraulic_pdf" not in paths and "resilience_pdf" not in paths
                # Compose only API-downloaded documents. Calculations/balance are
                # already inside each PZ/package; do not duplicate them.
                selected = [("ИОС2. Пояснительная записка", "pz_pdf"),
                            ("ИОС2. Принципиальная схема", "scheme_pdf"),
                            ("ИОС2. Вводы и узлы учёта", "metering_scheme_pdf"),
                            ("ИОС2. Насосы, зоны и ГВС", "pump_zone_scheme_pdf"),
                            ("ИОС2. Спецификация", "spec_pdf"),
                            ("ИОС3. Канализация", "wastewater_package_pdf")]
                final = output / "ВК_Самара_обычный_Studio.pdf"
                with PdfWriter() as writer:
                    for title, key in selected:
                        assert key in paths, key
                        writer.append(str(paths[key]), outline_item=title, import_outline=True)
                    with final.open("wb") as stream:
                        writer.write(stream)
                current = state(client.post("/studio/api/package", json={"revision": current["revision"]}))
                assert current["package"]["state"] == "blocked"
                stale_url = f'/studio/api/preview/{preview["id"]}/files/{downloaded[0]["name"]}'
                with TestClient(app) as other:
                    other.headers["X-Zarya-Studio"] = "1"
                    state(other.post("/studio/api/draft"))
                    assert other.get(stale_url).status_code == 404
                state(client.patch("/studio/api/answer", json={
                    "revision": current["revision"], "field": "fire_topology", "value": "combined"}))
                assert client.get(stale_url).status_code == 404
                audit = {"source": str(source), "upload": document,
                         "input_mode": "manual approved study inputs via ordinary API; no study fixture",
                         "manual_answers": inputs, "result": result, "documents": downloaded,
                         "pdf": str(final), "pages": len(PdfReader(final).pages),
                         "release_blocked": True, "private_and_edit_revocation_checked": True}
                (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2))
                return audit


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf/samara-section-3-2/ordinary-studio")
    args = parser.parse_args()
    audit = check(args.source, args.output)
    print(json.dumps({key: audit[key] for key in ("pdf", "pages", "release_blocked")}, ensure_ascii=False))
