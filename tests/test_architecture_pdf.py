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
from app.analysis.architecture_import_store import ArchitectureImportStore


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


def _geometry_form():
    return [
        ("page_number", "1"),
        ("plan_id", "АР-ПДФ-01"),
        ("cut_id", "1-1"),
        ("floor", "1"),
        ("elevation_m", "0"),
        ("clear_height_m", "3"),
        ("calibration_ax", "30"),
        ("calibration_ay", "270"),
        ("calibration_bx", "150"),
        ("calibration_by", "270"),
        ("calibration_distance_m", "4"),
        ("cut_ax", "30"),
        ("cut_ay", "180"),
        ("cut_bx", "420"),
        ("cut_by", "180"),
    ]


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


def test_architecture_upload_opens_persistent_confirmation_workspace(
    tmp_path,
    monkeypatch,
):
    from app.web import architecture_import as web

    store = ArchitectureImportStore(tmp_path)
    monkeypatch.setattr(web, "_STORE", store)
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
    assert response.status_code == 303
    import_id = response.headers["location"].rsplit("/", 1)[-1]
    assert store.metadata(import_id)["original_name"] == "Планы АР.pdf"

    result = web.architecture_workspace(
        _request(f"/wizard/architecture/{import_id}"),
        import_id,
    )
    body = result.body.decode("utf-8")
    assert result.status_code == 200
    assert "Планы АР.pdf" in body
    assert "Векторный план" in body
    assert "Калибровка" in body
    assert "Линия разреза" in body
    assert "data-plan-preview" in body


def test_workspace_finds_pdf_line_intersections_after_explicit_cut(
    tmp_path,
    monkeypatch,
):
    from app.web import architecture_import as web

    store = ArchitectureImportStore(tmp_path)
    monkeypatch.setattr(web, "_STORE", store)
    import_id = store.create("Планы АР.pdf", _vector_pdf())
    request = _request(f"/wizard/architecture/{import_id}/cut", "POST")
    request._form = FormData(_geometry_form())

    response = asyncio.run(web.architecture_cut_candidates(request, import_id))
    body = response.body.decode("utf-8")
    assert response.status_code == 200
    assert "Границы-кандидаты" in body
    assert "Шлюз 03" in body
    assert "data-preview-cut" in body
    assert "data-preview-candidate" in body


def test_selected_boundaries_and_labeled_intervals_create_confirmed_floor(
    tmp_path,
    monkeypatch,
):
    from app.analysis.architecture_confirmation import (
        confirmed_architecture_section_from_mapping,
    )
    from app.web import architecture_import as web

    store = ArchitectureImportStore(tmp_path)
    monkeypatch.setattr(web, "_STORE", store)
    import_id = store.create("Планы АР.pdf", _vector_pdf())

    boundaries_request = _request(
        f"/wizard/architecture/{import_id}/boundaries",
        "POST",
    )
    boundaries_request._form = FormData(
        _geometry_form()
        + [("boundary_station_pt", "120"), ("boundary_station_pt", "270")]
    )
    intervals_response = asyncio.run(
        web.architecture_confirm_boundaries(boundaries_request, import_id)
    )
    intervals_body = intervals_response.body.decode("utf-8")
    assert intervals_response.status_code == 200
    assert "Экспликация вдоль разреза" in intervals_body
    assert intervals_body.count('name="cell_start_pt"') == 3

    confirmation_request = _request(
        f"/wizard/architecture/{import_id}/confirm-floor",
        "POST",
    )
    confirmation_request._form = FormData(
        _geometry_form()
        + [
            ("cell_start_pt", "0"), ("cell_end_pt", "120"),
            ("cell_id", "F1-101"), ("cell_number", "101"),
            ("cell_name", "Кухня"), ("cell_kind", "room"),
            ("cell_start_pt", "120"), ("cell_end_pt", "270"),
            ("cell_id", "F1-102"), ("cell_number", "102"),
            ("cell_name", "Коридор"), ("cell_kind", "corridor"),
            ("cell_start_pt", "270"), ("cell_end_pt", "390"),
            ("cell_id", "F1-103"), ("cell_number", "103"),
            ("cell_name", "Сантехническая шахта"), ("cell_kind", "shaft"),
        ]
    )
    confirmed_response = asyncio.run(
        web.architecture_confirm_floor(confirmation_request, import_id)
    )
    confirmed_body = confirmed_response.body.decode("utf-8")
    assert confirmed_response.status_code == 200
    assert "Архитектурный разрез подтверждён" in confirmed_body
    model = confirmed_architecture_section_from_mapping(
        store.load_confirmations(import_id)
    )
    assert [row.number for row in model.floors[0].cells] == ["101", "102", "103"]

    refreshed = web.architecture_workspace(
        _request(f"/wizard/architecture/{import_id}"),
        import_id,
    )
    refreshed_body = refreshed.body.decode("utf-8")
    assert refreshed.status_code == 200
    assert "Архитектурный разрез подтверждён" in refreshed_body
    assert 'value="АР-ПДФ-01"' in refreshed_body
    assert 'value="Кухня"' in refreshed_body
    assert "Привязка К1/К2 к помещениям" in refreshed_body

    riser_request = _request(
        f"/wizard/architecture/{import_id}/wastewater/riser",
        "POST",
    )
    riser_request._form = FormData([
        ("placement_id", "R-K1-1-F1"),
        ("riser_id", "К1-Ст1"),
        ("system", "K1"),
        ("shaft_ref", "1::F1-103"),
        ("station_m", "11"),
        ("dn_mm", "100"),
        ("source_ref", "АР, лист 1; подтверждено проектировщиком"),
    ])
    riser_response = asyncio.run(
        web.architecture_add_wastewater_riser(riser_request, import_id)
    )
    assert riser_response.status_code == 200
    assert "К1-Ст1 · 1 этаж" in riser_response.body.decode("utf-8")

    receiver_request = _request(
        f"/wizard/architecture/{import_id}/wastewater/receiver",
        "POST",
    )
    receiver_request._form = FormData([
        ("placement_id", "P-SINK-F1"),
        ("element_id", "К1-Мой1"),
        ("kind", "sink"),
        ("system", "K1"),
        ("room_ref", "1::F1-101"),
        ("station_m", "2"),
        ("connection_height_m", "0.5"),
        ("quantity", "1"),
        ("dn_mm", "50"),
        ("riser_id", "К1-Ст1"),
        ("source_ref", "АР, лист 1, помещение 101"),
    ])
    receiver_response = asyncio.run(
        web.architecture_add_wastewater_receiver(receiver_request, import_id)
    )
    assert receiver_response.status_code == 200
    assert "К1-Мой1 · 1 этаж" in receiver_response.body.decode("utf-8")
    binding = store.load_wastewater_binding(import_id)
    assert binding["risers"][0]["shaft_cell_id"] == "F1-103"
    assert binding["receivers"][0]["room_cell_id"] == "F1-101"


def test_import_store_detects_source_substitution(tmp_path):
    store = ArchitectureImportStore(tmp_path)
    import_id = store.create("Планы АР.pdf", _vector_pdf())
    source = tmp_path / import_id / "source.pdf"
    source.write_bytes(_raster_pdf())

    with pytest.raises(ValueError, match="checksum mismatch"):
        store.survey(import_id)


def test_import_store_persists_versioned_project_link(tmp_path):
    store = ArchitectureImportStore(tmp_path)
    import_id = store.create("Планы АР.pdf", _vector_pdf())

    store.save_project_link(
        import_id,
        project_id="ab12cd34ef",
        project_source_sha256="a" * 64,
    )

    assert store.load_project_link(import_id) == {
        "project_id": "ab12cd34ef",
        "project_source_sha256": "a" * 64,
    }
    store.delete_project_link(import_id)
    assert store.load_project_link(import_id) == {}

    with pytest.raises(ValueError, match="linked project id"):
        store.save_project_link(
            import_id,
            project_id="../../etc/passwd",
            project_source_sha256="a" * 64,
        )


def test_architecture_routes_template_and_navigation_are_wired():
    from app.main import app
    from app.web.architecture_import import _TPL

    paths = {route.path for route in app.routes}
    assert "/wizard/architecture" in paths
    assert "/wizard/architecture/survey" in paths
    assert "/wizard/architecture/{import_id}" in paths
    assert "/wizard/architecture/{import_id}/cut" in paths
    assert "/wizard/architecture/{import_id}/boundaries" in paths
    assert "/wizard/architecture/{import_id}/confirm-floor" in paths
    assert "/wizard/architecture/{import_id}/wastewater/riser" in paths
    assert "/wizard/architecture/{import_id}/wastewater/receiver" in paths
    assert "/wizard/architecture/{import_id}/wastewater/project" in paths
    assert "/wizard/architecture/{import_id}/wastewater/project/delete" in paths
    assert "/wizard/architecture/{import_id}/wastewater/control.svg" in paths
    assert "/wizard/architecture/{import_id}/wastewater/delete" in paths
    assert "/wizard/architecture/{import_id}/delete" in paths
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
