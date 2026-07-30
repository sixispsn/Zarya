# -*- coding: utf-8 -*-
import asyncio
import io
import zipfile

import pytest
from starlette.datastructures import FormData, UploadFile
from starlette.requests import Request
from weasyprint import HTML

from app.analysis.reference_project import (
    ReferenceAnalysisError,
    ReferenceAnalysisStore,
    UploadedPackage,
    expand_packages,
)


def _pdf(body: str) -> bytes:
    return HTML(string=(
        "<html><meta charset='utf-8'><body>"
        f"{body}"
        "</body></html>"
    )).write_pdf()


def _request(path: str, method: str = "GET") -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    })


def test_reference_analysis_extracts_page_evidence_and_norm_editions(tmp_path):
    store = ReferenceAnalysisStore(tmp_path)
    pz = _pdf(
        "<h1>Пояснительная записка</h1>"
        "<p>Система В1. Суточный расход Qсут = 90 м³/сут.</p>"
        "<p>Требуемый напор Hтр = 54,5 м вод.</p>"
        "<p>Рабочая точка насоса Q = 18 м³/ч H = 42 м.</p>"
        "<p>Расчёт выполнен по СП 30.13330.2016.</p>"
    )
    conclusion = _pdf(
        "<h1>Заключение экспертизы</h1>"
        "<p>По результатам рассмотрения выдано положительное заключение.</p>"
    )

    analysis_id = store.create("МКД — проект-аналог", [
        UploadedPackage("ПЗ.pdf", pz),
        UploadedPackage("Заключение экспертизы.pdf", conclusion),
    ])
    report = store.load(analysis_id)

    assert report["title"] == "МКД — проект-аналог"
    assert report["summary"]["documents"] == 2
    assert report["summary"]["positive_conclusion"] is True
    assert report["documents"][0]["category"] == "pz"
    assert report["documents"][1]["category"] == "conclusion"
    metrics = {item["metric"]: item for item in report["evidence"]}
    assert metrics["daily_flow"]["value"] == 90
    assert metrics["daily_flow"]["page"] == 1
    assert metrics["required_head"]["value"] == 54.5
    assert metrics["pump_point"]["display_value"] == "Q 18 · H 42"
    assert metrics["daily_flow"]["quote"]
    assert report["norms"][0]["reference"] == "СП 30.13330.2016"
    assert report["norms"][0]["replacement"] == "СП 30.13330.2020"
    titles = {item["title"] for item in report["findings"]}
    assert "Положительное заключение найдено" in titles
    assert "Найдены прежние редакции нормативов" in titles


def test_reference_analysis_flags_conflicting_values_without_calling_them_errors(
    tmp_path,
):
    store = ReferenceAnalysisStore(tmp_path)
    analysis_id = store.create("Сверка", [
        UploadedPackage(
            "ПЗ.pdf",
            _pdf(
                "<h1>Пояснительная записка</h1>"
                "<p>В1. Суточный расход Qсут = 90 м³/сут.</p>"
            ),
        ),
        UploadedPackage(
            "Баланс.pdf",
            _pdf(
                "<h1>Расчётные обоснования</h1>"
                "<p>В1. Суточный расход Qсут = 65 м³/сут.</p>"
            ),
        ),
    ])
    report = store.load(analysis_id)

    conflicts = [
        item for item in report["findings"]
        if item["status"] == "conflict"
    ]
    assert report["summary"]["conflicts"] == 1
    assert len(conflicts) == 1
    assert "65, 90 м³/сут" in conflicts[0]["message"]
    assert "не объявляется ошибкой автоматически" in conflicts[0]["message"]
    assert len(conflicts[0]["sources"]) == 2


def test_zip_is_read_in_memory_and_rejects_traversal():
    pdf = _pdf("<h1>Пояснительная записка</h1>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("01/ПЗ.pdf", pdf)
        archive.writestr("readme.txt", "служебный файл")

    files, ignored = expand_packages([
        UploadedPackage("Комплект.zip", buffer.getvalue())
    ])
    assert len(files) == 1
    assert files[0].original_name.endswith("01/ПЗ.pdf")
    assert ignored == ["Комплект.zip / readme.txt"]

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../ПЗ.pdf", pdf)
    with pytest.raises(ReferenceAnalysisError, match="небезопасный путь"):
        expand_packages([UploadedPackage("unsafe.zip", unsafe.getvalue())])


def test_fake_pdf_and_unsafe_file_lookup_are_rejected(tmp_path):
    with pytest.raises(ReferenceAnalysisError, match="не является PDF"):
        expand_packages([UploadedPackage("fake.pdf", b"not a pdf")])

    store = ReferenceAnalysisStore(tmp_path)
    analysis_id = store.create("Безопасность", [
        UploadedPackage("ПЗ.pdf", _pdf("<h1>Пояснительная записка</h1>"))
    ])
    with pytest.raises(ValueError):
        store.file_path(analysis_id, "../manifest.json")
    store.delete(analysis_id)
    with pytest.raises(FileNotFoundError):
        store.load(analysis_id)


def test_web_upload_redirects_to_persistent_analysis(tmp_path, monkeypatch):
    from app.web import reference_analysis as web

    store = ReferenceAnalysisStore(tmp_path)
    monkeypatch.setattr(web, "_STORE", store)
    upload = UploadFile(
        filename="ПЗ.pdf",
        file=io.BytesIO(_pdf(
            "<h1>Пояснительная записка</h1>"
            "<p>В1. Суточный расход Qсут = 90 м³/сут.</p>"
        )),
    )
    request = _request("/wizard/analyze", "POST")
    request._form = FormData([
        ("title", "Проверочный проект"),
        ("confirm_rights", "yes"),
        ("files", upload),
    ])

    response = asyncio.run(web.analysis_upload(request))

    assert response.status_code == 303
    analysis_id = response.headers["location"].rsplit("/", 1)[-1]
    assert store.load(analysis_id)["title"] == "Проверочный проект"
    result = web.analysis_result(
        _request(f"/wizard/analyze/{analysis_id}"),
        analysis_id,
    )
    body = result.body.decode("utf-8")
    assert "Проверочный проект" in body
    assert "Извлечённые показатели" in body
    assert "90" in body
    assert "ПЗ.pdf · стр. 1" in body


def test_reference_analysis_routes_and_navigation_are_wired():
    from app.main import app
    from app.web.reference_analysis import _TPL

    paths = {route.path for route in app.routes}
    for path in (
        "/wizard/analyze",
        "/wizard/analyze/{analysis_id}",
        "/wizard/analyze/{analysis_id}/report.json",
        "/wizard/analyze/{analysis_id}/file/{stored_name}",
        "/wizard/analyze/{analysis_id}/delete",
    ):
        assert path in paths
    _TPL.env.get_template("wizard_analysis.html")
    _TPL.env.get_template("wizard_analysis_result.html")
    for name in (
        "wizard_form.html",
        "wizard_result.html",
        "wizard_projects.html",
    ):
        html = open(f"app/web/templates/{name}", encoding="utf-8").read()
        assert 'href="/wizard/analyze"' in html
