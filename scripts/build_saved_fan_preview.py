"""Exercise the download handler with an isolated, explicitly synthetic project."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from app.intake.project_store import ProjectStore
from app.web import wizard
from tests.fan_binding_fixture import fan_binding_request_fixture


def main():
    output = (
        Path(__file__).resolve().parents[1]
        / "output/pdf/К1_К2_контроль_из_сохранённого_проекта.pdf"
    )
    old_store = wizard._STORE
    with TemporaryDirectory(prefix="zarya-fan-download-") as directory:
        store = ProjectStore(directory)
        wizard._STORE = store
        try:
            pid = store.save(fan_binding_request_fixture())
            revision = store.source_sha256(pid)
            request = Request(
                {"type": "http", "headers": [(b"if-match", revision.encode())]}
            )
            check = json.loads(wizard.check_saved_fan_project(request, pid).body)
            assert check["preview_ready"] and not check["production_ready"]
            response = wizard.download_saved_fan_preview(request, pid)
            assert response.status_code == 200
            assert response.headers["x-zarya-project-revision"] == revision
            assert response.headers["x-zarya-control-only"] == "true"
            assert response.headers["content-type"] == "application/pdf"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(response.body)
            print(output)
            print(f"Saved revision: {revision}; checks: {len(check['checks'])}")
        finally:
            wizard._STORE = old_store


if __name__ == "__main__":
    main()
