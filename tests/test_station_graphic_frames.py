"""Physical frames, numbering and unchanged bodies; not hydraulic approval."""

from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.fire_station_input_report import frame_station_calculation
from app.pz.project import DocumentInfo
from app.pz.wastewater_building_drafting import _title_block_svg, drawing_frame_svg
from tests.test_pump_document_frame import segments


def qa_document():
    return DocumentInfo(
        cipher="QA-ИОС2",
        stage="Р",
        sheet_total="99",
        object_name="Контроль оформления. Не для проектной выдачи",
        object_part="Проверка рамок",
        organization="ЗАРЯ",
        developer_name="Иванов",
    )


def check_text_frames(data, count):
    pdf = fitz.open(stream=data, filetype="pdf")
    assert len(pdf) == count
    for i, page in enumerate(pdf, 1):
        top = 237 if i == 1 else 277
        assert (20, top, 205, top) in segments(page)
        assert page.get_text().count("Изм.") == 1
        region = (185, 267, 205, 277) if i == 1 else (195, 284, 205, 292)
        assert page.get_text(clip=fitz.Rect(*(v * mm for v in region))).strip() == str(
            count if i == 1 else i
        )
        if i == 1:
            assert (
                page.get_text(
                    clip=fitz.Rect(155 * mm, 267 * mm, 170 * mm, 277 * mm)
                ).strip()
                == "Р"
            )
        words = [
            w for w in page.get_text("words") if w[0] > 21 * mm and w[1] < top * mm
        ]
        assert all(w[3] < (top - 4.9) * mm and w[2] < 205 * mm for w in words)
    return pdf


def test_station_frame_preserves_body_bookmarks_metadata_and_document():
    content = BytesIO()
    c = canvas.Canvas(content, pagesize=(210 * mm, 297 * mm))
    for i in range(3):
        c.drawString(30 * mm, 260 * mm, f"Original body {i}")
        c.showPage()
    c.save()
    w = PdfWriter()
    w.clone_document_from_reader(PdfReader(content))
    w.add_outline_item("One", 0)
    w.add_outline_item("Three", 2)
    w.add_metadata({"/Subject": "preserve me"})
    content = BytesIO()
    w.write(content)
    doc = qa_document()
    before = asdict(doc)
    result = frame_station_calculation(content.getvalue(), doc, "Проверка рамок")
    pdf = check_text_frames(result, 3)
    for i, page in enumerate(pdf):
        assert f"Original body {i}" in page.get_text()
    reader = PdfReader(BytesIO(result))
    assert reader.metadata.subject == "preserve me"
    assert [reader.get_destination_page_number(d) for d in reader.outline] == [0, 2]
    assert asdict(doc) == before


@pytest.mark.parametrize(
    "width,height,scale",
    [(210, 297, 1), (297, 420, 1), (420, 297, 1), (594, 420, 1), (841, 594, 10 / 3)],
)
@pytest.mark.parametrize("number,total", [(1, 1), (2, 3)])
def test_graphic_frame_physical_grid_and_unclipped_cells(
    width, height, scale, number, total
):
    ensure_drafting_font_registered()
    doc = qa_document()
    before = asdict(doc)
    title = "Насосная В2. Принципиальная схема с длинным наименованием"
    if scale == 1:
        body = drawing_frame_svg(
            doc,
            width_mm=width,
            height_mm=height,
            title=title,
            system_label="В2",
            sheet_no=number,
            sheet_total=total,
        )
    else:
        body = _title_block_svg(
            doc,
            sheet_no=number,
            sheet_total=total,
            title=title,
            system_label="В2",
            sheet_width_mm=width,
            sheet_height_mm=height,
            units_per_mm=scale,
        )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width * scale} {height * scale}">{body}</svg>'
    pdf = fitz.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()), filetype="pdf")
    page, x, y = pdf[0], width - 190, height - 60
    lines = segments(page)
    for dx in (10, 20, 30, 40, 55, 65):
        assert any(
            all(
                abs(a - b) < 0.02
                for a, b in zip(
                    line, (x + dx, y, x + dx, y + (25 if dx in (10, 30) else 55))
                )
            )
            for line in lines
        )
    region = fitz.Rect((x + 150) * mm, (y + 30) * mm, (x + 165) * mm, (y + 40) * mm)
    assert page.get_text(clip=region).strip() == (str(number) if total > 1 else "")
    region = fitz.Rect((x + 165) * mm, (y + 30) * mm, (x + 185) * mm, (y + 40) * mm)
    assert page.get_text(clip=region).strip() == (str(total) if number == 1 else "")
    assert "…" not in page.get_text()
    assert title in " ".join(page.get_text().split())
    assert asdict(doc) == before
    stamp = ET.fromstring(body)
    assert any(e.get("data-inventory-columns") == "20-22" for e in stamp.iter())
    # The exact grid applies to every graphic sheet, including continuations.
    assert any(e.get("data-title-block") == "form-3" for e in stamp.iter())


def test_graphic_long_text_fails_instead_of_silent_truncation():
    with pytest.raises(ValueError, match="не помещается"):
        drawing_frame_svg(
            DocumentInfo(object_name="Длинное имя " * 100),
            width_mm=420,
            height_mm=297,
            title="Схема",
            system_label="В2",
        )


def test_portrait_composition_uses_actual_paper_not_translated_a1_stamp():
    from dataclasses import replace
    from tests.test_wastewater_building_drafting import _demo_assembly
    from app.pz.wastewater_building_drafting import (
        build_residential_wastewater_reference_svg,
    )

    svg = build_residential_wastewater_reference_svg(
        replace(_demo_assembly(), document=qa_document())
    )
    pdf = fitz.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()), filetype="pdf")
    p = pdf[0]
    assert p.rect.width / mm == pytest.approx(420, abs=0.01)
    assert p.rect.height / mm == pytest.approx(594, abs=0.01)
    assert "Формат А2" in p.get_text() and "Формат А1" not in p.get_text()
    assert "Взам." in p.get_text(clip=fitz.Rect(8 * mm, 509 * mm, 13 * mm, 534 * mm))


def test_station_design_combined_and_standalone_correction(tmp_path):
    from app.intake.samara_study import load_case
    from app.pz.fire_station_design_report import render_station_design
    from app.pz.fire_diaphragm_correction_report import correction_review_pdf

    r = load_case()["payload"]["result"]
    before = deepcopy(r)
    doc = qa_document()
    doc_before = asdict(doc)
    for combined in (False, True):
        report = deepcopy(r)
        if not combined:
            report.pop("repair_review")
        path = tmp_path / f"design-{combined}.pdf"
        render_station_design(path, report, document=doc)
        check_text_frames(path.read_bytes(), 8 if combined else 5)
        reader = PdfReader(path)
        assert [reader.get_destination_page_number(d) for d in reader.outline] == list(
            range(8 if combined else 5)
        )
    check_text_frames(correction_review_pdf(r["repair_review"], document=doc), 3)
    assert r == before and asdict(doc) == doc_before


def test_generic_station_and_pressure_report(tmp_path):
    from tests.test_fire_review_binding import bundle, passing_model
    from app.pz.fire_station_input_report import render_station_input_report
    from app.pz.fire_pressure_review_report import render_pressure_review

    b = bundle(passing_model(), tmp_path)
    b.project.document = qa_document()
    before = deepcopy(asdict(b.project))
    for name, render, result in (
        ("input", render_station_input_report, b.fire_station_result),
        ("pressure", render_pressure_review, b.fire_pressure_review),
    ):
        path = tmp_path / f"{name}.pdf"
        render(path, b.project, result)
        check_text_frames(path.read_bytes(), len(PdfReader(path).pages))
    assert asdict(b.project) == before


def test_pressure_drawing_table_has_closed_rows_and_both_columns():
    from tests.test_wastewater_pressure_scheme import _pressure_project
    from app.pz.wastewater_pressure_drafting import build_wastewater_pressure_curve_svg
    from app.pz.wastewater_pressure_project_inputs import (
        resolve_wastewater_pressure_project_inputs,
    )

    p = _pressure_project()
    svg = build_wastewater_pressure_curve_svg(
        p, resolve_wastewater_pressure_project_inputs(p)
    )
    table = next(
        e for e in ET.fromstring(svg).iter() if e.get("data-pressure-calculation-table")
    )
    ls = [e for e in table if e.tag.endswith("line")]
    assert any(
        e.get("x1") == e.get("x2") == "2190"
        and e.get("y1") == "480"
        and e.get("y2") == "1073"
        for e in ls
    )
    assert {float(e.get("y1")) for e in ls if e.get("y1") == e.get("y2")} == {
        540,
        *(585 + i * 61 for i in range(9)),
    }
