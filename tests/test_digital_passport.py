import base64
import re
from pathlib import Path

import pytest
from weasyprint import HTML

from app.intake.passport_store import PassportIntegrityError, PassportStore
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.commission import build_commission_report
from app.pz.digital_passport import build_passport_info, new_passport_id
from app.pz.generator import generate_pz_html
from app.pz.proof import build_proof_graph


def _project():
    return build_project(load_request_file("demo/demo_project.yaml"))


def _document(tmp_path: Path) -> dict:
    path = tmp_path / "ПЗ.pdf"
    HTML(string="<h1>Пояснительная записка</h1>").write_pdf(path)
    return {
        "group": "common",
        "label": "Пояснительная записка",
        "name": path.name,
    }


def _defense_payload(project, commission) -> dict:
    graph = build_proof_graph(project, commission)
    return {
        "version": graph.version,
        "project_fingerprint": graph.project_fingerprint,
        "legacy_fingerprint": graph.legacy_fingerprint,
        "build_commit": graph.build_commit,
        "generated_at": graph.generated_at,
        "summary": {
            "total": len(graph.decisions),
            "proven": graph.proven_count,
            "missing": graph.missing_count,
            "stage_r": graph.stage_r_count,
        },
        "decisions": [{
            "id": "v1-head",
            "system": "В1",
            "title": "Требуемый напор",
            "value": "45,00",
            "unit": "м",
            "status": "verified",
            "status_label": "подтверждено",
            "summary": "Расчёт подтверждён.",
            "steps": [],
            "documents": [{
                "label": "Пояснительная записка",
                "name": "ПЗ.pdf",
                "page": 1,
                "view_url": "/wizard/view/run/ПЗ.pdf",
                "download_url": "/wizard/file/run/ПЗ.pdf",
            }],
        }],
    }


def test_passport_id_and_qr_are_url_safe_and_vector():
    passport_id = new_passport_id()
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", passport_id)
    info = build_passport_info(passport_id, "https://zaryaproekt.ru/")
    assert info.url == f"https://zaryaproekt.ru/p/{passport_id}"
    prefix = "data:image/svg+xml;base64,"
    assert info.qr_data_uri.startswith(prefix)
    svg = base64.b64decode(info.qr_data_uri.removeprefix(prefix))
    assert b"<svg" in svg
    assert len(svg) > 1000


def test_published_passport_survives_new_store_and_detects_tampering(tmp_path):
    project = _project()
    commission = build_commission_report(project)
    passport_id = new_passport_id()
    url = f"https://zaryaproekt.ru/p/{passport_id}"
    store = PassportStore(str(tmp_path / "passports"))
    manifest = store.publish(
        passport_id=passport_id,
        canonical_url=url,
        project_id="0123456789",
        project=project,
        commission=commission,
        defense_payload=_defense_payload(project, commission),
        documents=[_document(tmp_path)],
        outdir=str(tmp_path),
    )
    assert len(manifest["seal_sha256"]) == 64
    assert len(manifest["documents"][0]["sha256"]) == 64
    assert manifest["proof"]["decisions"][0]["documents"][0][
        "view_url"
    ].startswith(url + "/file/")

    reopened = PassportStore(str(tmp_path / "passports"))
    assert reopened.load(passport_id)["passport_id"] == passport_id
    verification = reopened.verify(passport_id)
    assert verification["valid"] is True
    from app.web.passport import _TPL
    page = _TPL.env.get_template("passport_public.html").render(
        passport=manifest,
        verification=verification,
    )
    assert "Целостность выпуска" in page
    assert "Подтверждена" in page
    assert manifest["seal_sha256"] in page
    path, record = reopened.document(passport_id, "ПЗ.pdf")
    assert path.is_file()
    assert record["label"] == "Пояснительная записка"

    path.write_bytes(path.read_bytes() + b"tampered")
    verification = reopened.verify(passport_id)
    assert verification["manifest_valid"] is True
    assert verification["documents_valid"] is False
    assert verification["valid"] is False
    with pytest.raises(PassportIntegrityError):
        reopened.document(passport_id, "ПЗ.pdf")


def test_pz_contains_persistent_passport_url_and_qr():
    project = _project()
    passport_id = new_passport_id()
    project.digital_passport = build_passport_info(
        passport_id,
        "https://zaryaproekt.ru",
    )
    html = generate_pz_html(project)
    assert "ЦИФРОВОЙ ПАСПОРТ ВЫПУСКА" in html
    assert f"https://zaryaproekt.ru/p/{passport_id}" in html
    assert "data:image/svg+xml;base64," in html
    assert "read-only release" in html


def test_public_passport_routes_and_read_only_template_are_exposed():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/p/{passport_id}" in paths
    assert "/p/{passport_id}/manifest.json" in paths
    assert "/p/{passport_id}/file/{name}" in paths
    template = Path(
        "app/web/templates/passport_public.html",
    ).read_text(encoding="utf-8")
    assert "READ ONLY" in template
    assert "Целостность выпуска" in template
    assert "Неизменяемые документы" in template
    assert "Seal манифеста" in template
