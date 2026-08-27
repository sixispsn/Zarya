import asyncio
import base64
import io

import cairosvg
import pytest
from starlette.datastructures import FormData, UploadFile
from starlette.requests import Request

from app.analysis.architecture_pdf import (
    ArchitecturePdfError,
    survey_architecture_pdf,
)


def _vector_pdf() -> bytes:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400">
    <g fill="none" stroke="black" stroke-width="2">
      <rect x="40" y="40" width="520" height="300"/>
      <line x1="200" y1="40" x2="200" y2="340"/>
      <line x1="400" y1="40" x2="400" y2="340"/>
      <line x1="40" y1="140" x2="560" y2="140"/>
      <line x1="40" y1="240" x2="560" y2="240"/>
      <rect x="210" y="150" width="80" height="80"/>
      <rect x="410" y="150" width="80" height="80"/>
    </g>
    <g font-family="Arial" font-size="14">
      <text x="70" y="90">101 Кухня</text>
      <text x="230" y="90">102 Коридор</text>
      <text x="430" y="90">103 Санузел</text>
    </g></svg>"""
    return cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))


def _raster_pdf() -> bytes:
    source = b"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400">
    <rect width="600" height="400" fill="white"/>
    <path d="M40 40H560V340H40Z M200 40V340 M400 40V340"
      fill="none" stroke="black" stroke-width="3"/></svg>"""
    png = cairosvg.svg2png(bytestring=source)
    encoded = base64.b64encode(png).decode("ascii")
    wrapper = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400">'
        f'<image href="data:image/png;base64,{encoded}" x="0" y="0" '
        'width="600" height="400"/></svg>'
    )
    return cairosvg.svg2pdf(bytestring=wrapper.encode("utf-8"))


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


def test_vector_plan_yields_observed_candidates_but_requires_confirmation():
    survey = survey_architecture_pdf(
        _vector_pdf(), original_name="Планы АР.pdf"
    )

    assert survey.original_name == "Планы АР.pdf"
    assert survey.page_count == 1
    assert survey.vector_page_count == 1
    assert survey.requires_confirmation
    page = survey.pages[0]
    assert page.kind == "vector"
    assert page.selectable_for_vector_confirmation
    assert len(page.vector_lines) >= 12
    assert any("Кухня" in row.text for row in page.texts)
    assert survey.issues[0].code == "confirmation.required"


def test_raster_plan_never_becomes_vector_architecture():
    survey = survey_architecture_pdf(
        _raster_pdf(), original_name="Скан планов.pdf"
    )

    page = survey.pages[0]
    assert page.kind == "raster"
    assert page.image_count == 1
    assert not page.vector_lines
    assert not page.selectable_for_vector_confirmation
    assert survey.issues[0].code == "raster.ocr_required"


def test_public_mapping_hides_raw_candidates_by_default():
    survey = survey_architecture_pdf(_vector_pdf())

    compact = survey.to_mapping()
    detailed = survey.to_mapping(include_candidates=True)
    assert "vector_lines" not in compact["pages"][0]
    assert compact["pages"][0]["vector_line_count"] >= 12
    assert compact["pages"][0]["text_preview"]
    assert detailed["pages"][0]["vector_lines"]
    assert detailed["pages"][0]["texts"]


@pytest.mark.parametrize("content", [b"", b"not-a-pdf", b"PK\x03\x04fake"])
def test_invalid_file_is_rejected(content):
    with pytest.raises(ArchitecturePdfError, match="не является PDF"):
        survey_architecture_pdf(content)


def test_architecture_upload_page_surveys_vector_pdf():
    from app.web import architecture_import as web

    upload = UploadFile(
        filename="Планы АР.pdf",
        file=io.BytesIO(_vector_pdf()),
    )
    request = _request("/wizard/architecture/survey", "POST")
    request._form = FormData([
        ("confirm_rights", "yes"),
        ("plan_pdf", upload),
    ])

    response = asyncio.run(web.architecture_survey(request))
    body = response.body.decode("utf-8")
    assert response.status_code == 200
    assert "Планы АР.pdf" in body
    assert "Векторный план" in body
    assert "Можно передать в рабочее место подтверждения" in body
    assert "Масштаб, этажи, линия разреза" in body


def test_architecture_routes_template_and_navigation_are_wired():
    from app.main import app
    from app.web.architecture_import import _TPL

    paths = {route.path for route in app.routes}
    assert "/wizard/architecture" in paths
    assert "/wizard/architecture/survey" in paths
    _TPL.env.get_template("wizard_architecture.html")
    for name in (
        "wizard_form.html",
        "wizard_result.html",
        "wizard_projects.html",
        "wizard_analysis.html",
        "wizard_analysis_result.html",
    ):
        html = open(f"app/web/templates/{name}", encoding="utf-8").read()
        assert 'href="/wizard/architecture"' in html
