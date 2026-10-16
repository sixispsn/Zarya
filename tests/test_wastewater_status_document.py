"""Incomplete sheets retain every reason and never become a design release."""
from copy import deepcopy
from dataclasses import replace
from importlib import import_module
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics

from app.pz.project import DocumentInfo
from app.pz.wastewater_status_document import (
    BOTTOM, FONT, KINDS, LEFT, RIGHT, SIZE, TOP, build_status_svgs, generate_status_pdf,
)
from tests.test_wastewater_building_drafting import _demo_project
from tests.test_wastewater_k3_scheme import _k3_project
from tests.test_wastewater_pressure_scheme import _pressure_project


def cases():
    for kind, suffix, factory in (
        ("k1-k2", "", _demo_project), ("k3", "_k3", _k3_project),
        ("pressure", "_pressure", _pressure_project),
    ):
        module = import_module(f"app.pz.wastewater{suffix}_scheme_service")
        yield kind, factory(), module, f"assess_wastewater{suffix}_scheme_readiness", f"generate_wastewater{suffix}_scheme"


def long_reasons(count=80):
    return tuple(f"Контроль-{n:03d}: " + "не подтверждена геометрия участка " * 12
                 + f"конец-{n:03d}" for n in range(1, count + 1))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("reasons", [(), ("Участок <К1> & отметка > 0 не подтверждены.",), long_reasons(), ("А" * 3000,)])
def test_complete_text_single_frame_bounds_numbering_and_unchanged_document(kind, reasons):
    document = DocumentInfo(cipher="QA-ИОС3.СК", object_name="Контрольный объект. Не для выпуска", sheet_no="77", sheet_total="99")
    before = deepcopy(document)
    pages = build_status_svgs(document, reasons, kind=kind)
    assert document == before
    if len(reasons) == 80:
        assert len(pages) > 1
    restored = {str(i): [] for i in range(1, len(reasons) + 1)}
    for index, svg in enumerate(pages, 1):
        root = ET.fromstring(svg)
        assert root.get("data-release-ready") == "false"
        assert root.get("viewBox") == "0 0 841 594"
        borders = [n for n in root.iter() if n.get("data-sheet-border")]
        assert len(borders) == 1 and borders[0].get("y") == "5"
        frames = [n for n in root.iter() if n.get("data-title-block")]
        assert len(frames) == 1
        assert frames[0].get("data-sheet-no") == str(index)
        assert frames[0].get("data-sheet-total") == str(len(pages))
        # The body is plain text. Only the common frame adds lines/geometry.
        assert all(n.tag.rsplit("}", 1)[-1] in {"text", "rect", "g"} for n in root)
        assert not any(n.tag.endswith(("path", "polyline", "circle")) for n in root.iter())
        for node in root:
            if node.tag.endswith("text"):
                x, y = float(node.get("x")), float(node.get("y"))
                width = pdfmetrics.stringWidth(node.text or "", FONT, float(node.get("font-size")))
                assert LEFT <= x and x + width <= RIGHT
                assert y < 529  # common stamp starts at 534
            key = node.get("data-status-row")
            if key:
                assert TOP <= float(node.get("y")) <= BOTTOM
                assert float(node.get("font-size")) == SIZE  # never shrink to fit
            if key in restored:
                restored[key].append(node.text or "")
    for n, reason in enumerate(reasons, 1):
        assert "".join("".join(restored[str(n)]).split()) == "".join(f"{n}. {reason}".split())


@pytest.mark.parametrize("kind", KINDS)
def test_public_service_preserves_failure_reasons_and_project(kind, tmp_path, monkeypatch):
    _, project, module, assess, generate = next(c for c in cases() if c[0] == kind)
    project.document.object_name = "Контроль статуса. Не для выпуска"
    before = deepcopy(project)
    reasons = long_reasons()
    readiness = replace(getattr(module, assess)(project), ready=False, reasons=reasons)
    monkeypatch.setattr(module, assess, lambda p: readiness)
    result = getattr(module, generate)(project, str(tmp_path / f"{kind}.pdf"))
    assert not result.ready and result.reasons == reasons and project == before
    assert "incomplete-status" in result.backend
    pdf = PdfReader(result.output_path)
    assert len(pdf.pages) > 1
    text = "".join("".join(p.extract_text().split()) for p in pdf.pages)
    for n in range(1, 81):
        assert f"Контроль-{n:03d}" in text and f"конец-{n:03d}" in text
    with fitz.open(result.output_path) as doc:
        for page in doc:
            assert tuple(v / mm for v in page.rect) == pytest.approx((0, 0, 841, 594), abs=.01)
            assert "Не проектная документация" in page.get_text()
            assert not page.get_text(clip=fitz.Rect(786*mm, 564*mm, 801*mm, 574*mm)).strip()  # no P/R stage


@pytest.mark.parametrize("field", ["cipher", "object_name"])
def test_unfittable_stamp_text_fails_before_replacing_output(field, tmp_path):
    document = DocumentInfo(**{field: "НеразрывныйИдентификатор" * 100})
    target = tmp_path / "previous.pdf"
    target.write_bytes(b"previous output")
    with pytest.raises(ValueError, match="основной надписи"):
        generate_status_pdf(document, ("Недостаточно данных",), target, kind="k3")
    assert target.read_bytes() == b"previous output"


def test_failed_second_page_render_preserves_previous_pdf(tmp_path, monkeypatch):
    target = tmp_path / "previous.pdf"
    target.write_bytes(b"previous output")
    original, calls = cairosvg.svg2pdf, []

    def fail_second(**kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError("conversion failed")
        return original(**kwargs)

    monkeypatch.setattr(cairosvg, "svg2pdf", fail_second)
    with pytest.raises(RuntimeError, match="conversion failed"):
        generate_status_pdf(DocumentInfo(), long_reasons(), target, kind="k1-k2")
    assert target.read_bytes() == b"previous output"
    assert list(tmp_path.iterdir()) == [target]


def test_short_reasons_stay_together_and_oversized_reason_has_continuation_label():
    pages = build_status_svgs(DocumentInfo(), long_reasons(), kind="k1-k2")
    for n in range(1, 81):
        assert sum(f'data-status-row="{n}"' in page for page in pages) == 1
    reason = "Очень длинное замечание " * 1500
    pages = build_status_svgs(DocumentInfo(), (reason,), kind="k3")
    assert len(pages) > 1
    assert all("Продолжение замечания 1" in page for page in pages[1:])
    text = "".join(n.text or "" for page in pages for n in ET.fromstring(page)
                   if n.get("data-status-row") == "1")
    assert "".join(text.split()) == "".join(("1. " + reason).split())
