from copy import deepcopy
from dataclasses import replace
from io import BytesIO

import fitz
from pypdf import PdfReader
import pytest
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from app.intake.studio_study import build_study, initialize_study
from app.pz.network_takeoff_pdf import generate_network_takeoff_pdf
from app.pz.small_residential_calculation_pdf import generate_residential_calculation_pdf
from app.pz.small_residential_takeoff import educational_residential_takeoff
from app.pz.study_document_frame import build_study_text_pdf
from tests.test_annex_spec_frame import lines, region


@pytest.fixture
def study():
    draft = {"revision": 0, "answers": {}, "documents": []}
    initialize_study(draft, "two", None)
    _, model, calc, *_ = build_study(draft)
    return model, calc, educational_residential_takeoff(model, calc)


def check_frames(pdf, width, cipher):
    dx = width - 210
    for i, page in enumerate(pdf, 1):
        top = 237 if i == 1 else 277
        assert page.rect.width / mm == pytest.approx(width, abs=.01)
        assert page.rect.height / mm == pytest.approx(297, abs=.01)
        assert (20 + dx, top, 205 + dx, top) in lines(page)
        text = page.get_text()
        assert text.count("Изм.") == 1
        assert text.count(cipher) == 1
        assert "Не для выпуска и заказа материалов" in text
        assert "Формат А" in text
        if i == 1:
            assert region(page, 155 + dx, 267, 170 + dx, 277) == ""  # no assigned P/R
            assert region(page, 185 + dx, 267, 205 + dx, 277) == str(len(pdf))
            assert region(page, 170 + dx, 267, 185 + dx, 277) == ("1" if len(pdf) > 1 else "")
        else:
            assert region(page, 195 + dx, 284, 205 + dx, 292) == str(i)
            assert "Листов" not in text
        # All body text stays above the reserved stamp band and inside the frame.
        for word in page.get_text("words"):
            if word[0] / mm >= 24 and 21 <= word[1] / mm < top:
                assert word[2] / mm <= width - 10 + .1
                assert word[3] / mm <= top - 5 + .1


@pytest.mark.parametrize("kind,width,cipher", [
    ("calculation", 210, "УЧЕБНЫЙ-К1К2.Р"),
    ("takeoff", 420, "УЧЕБНЫЙ-К1К2.ВО"),
])
def test_real_study_attachments_keep_frames_limitations_and_inputs(study, tmp_path, kind, width, cipher):
    model, calc, network = study
    before = deepcopy(study)
    path = tmp_path / (kind + ".pdf")
    if kind == "calculation":
        generate_residential_calculation_pdf(str(path), model, calc, rain_source_sha256="a" * 64)
    else:
        generate_network_takeoff_pdf(str(path), network)
    with fitz.open(path) as pdf:
        check_frames(pdf, width, cipher)
        text = " ".join(" ".join(p.get_text().split()) for p in pdf)
        assert len(pdf) == 3
        assert pdf.get_toc() and pdf.get_toc()[0][2] == 1
        if kind == "calculation":
            for value in ("5,395", "2,293", "104,6", "самоочищение не проверено"):
                assert value in text
            assert "19.09.2026" not in text
        else:
            assert network.fingerprint[:20] in text
            assert "нормативную СО не заменяет" in text
            assert not network.purchase_ready
    assert study == before


def test_long_takeoff_keeps_all_limitations_and_continuation_pages(study, tmp_path):
    network = replace(study[2], limitations=study[2].limitations + tuple(
        f"QA-LIMIT-{i:03d}: " + "Неизвестные данные требуют подтверждения. " * 14
        for i in range(40)))
    original = deepcopy(network)
    path = tmp_path / "long-takeoff.pdf"
    generate_network_takeoff_pdf(str(path), network)
    with fitz.open(path) as pdf:
        assert len(pdf) > 3
        check_frames(pdf, 420, "УЧЕБНЫЙ-К1К2.ВО")
        text = " ".join(page.get_text() for page in pdf)
        for i in range(40):
            assert text.count(f"QA-LIMIT-{i:03d}") == 1
    assert network == original


@pytest.mark.parametrize("layout,width", [("a4_text", 210), ("a3_text", 420)])
def test_long_grid_repeats_headers_without_losing_rows(layout, width):
    # Same GRID/repeatRows policy as both attachments, across automatic breaks.
    table = Table([["HEADER", "VALUE"]] + [[f"ROW-{i:03d}", str(i)] for i in range(100)],
                  colWidths=[80 * mm, 70 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .3, (0, 0, 0)),
                               ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    content = build_study_text_pdf([table], title="QA", sheet_title="Проверка таблицы",
                                   cipher="QA", layout=layout)
    with fitz.open(stream=content, filetype="pdf") as pdf:
        assert len(pdf) > 1
        check_frames(pdf, width, "QA")
        text = " ".join(page.get_text() for page in pdf)
        for i in range(100):
            assert text.count(f"ROW-{i:03d}") == 1
        assert all("HEADER" in page.get_text() for page in pdf)


def test_single_page_has_blank_sheet_and_keeps_metadata_and_link():
    paragraph = Paragraph('<link href="https://example.org">CONTROL LINK</link>',
                          ParagraphStyle("body", fontSize=12))
    content = build_study_text_pdf([paragraph], title="QA single", sheet_title="Контроль",
                                   cipher="QA")
    with fitz.open(stream=content, filetype="pdf") as pdf:
        assert len(pdf) == 1
        check_frames(pdf, 210, "QA")
        assert pdf.metadata["title"] == "QA single"
        assert pdf[0].get_links()[0]["uri"] == "https://example.org"
    assert len(PdfReader(BytesIO(content)).outline) == 1


@pytest.mark.parametrize("layout,detail", [("a3_graphic", ""), ("a4_text", "X" * 500)])
def test_bad_layout_or_overflowing_notice_is_rejected(layout, detail):
    with pytest.raises(ValueError):
        build_study_text_pdf([], title="QA", sheet_title="QA", cipher="QA", layout=layout, detail=detail)
