"""QA of plain building notes; only the explicit fan-binding control is delivered."""
# ruff: noqa: E402 -- repository script bootstrap
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cairosvg
import fitz
from pypdf import PdfReader, PdfWriter

from app.pz.generator import merge_pdfs
from app.pz.wastewater_scheme_service import generate_wastewater_fan_binding_preview
from tests.fan_binding_fixture import fan_binding_fixture
from tests.test_building_note_layout import note_layout_samples
from tests.test_fan_control_layout import check_control_page


def main():
    temporary = ROOT / "tmp/pdfs/building-note-layout"
    destination = ROOT / "output/pdf/building-note-layout"
    temporary.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    samples = note_layout_samples()
    writer = PdfWriter()
    for key in (0, 1, "reference"):
        writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=samples[key].encode()))))
    ordinary = temporary / "ordinary-and-legacy.pdf"
    with ordinary.open("wb") as stream:
        writer.write(stream)

    project, data = fan_binding_fixture()
    before = deepcopy((project, data))
    bound = temporary / "building-control.pdf"
    result = generate_wastewater_fan_binding_preview(project, data, str(bound))
    assert not result.ready and (project, data) == before
    with fitz.open(bound) as pdf:
        assert len(pdf) == 7
        check_control_page(pdf[-1])
        assert "7 / 7" in pdf[-1].get_text()
        for page in list(pdf)[:-1]:
            assert "Не проектная документация" in page.get_text()
            assert abs(page.rect.width * 25.4 / 72 - 841) < .01
            assert abs(page.rect.height * 25.4 / 72 - 594) < .01
    output = destination / "Проверка_пояснений_листов_здания.pdf"
    merge_pdfs([str(bound)], str(output), section_titles=[
        "Контроль привязки к синтетическому зданию. Не проектная документация",
    ])
    with fitz.open(output) as final, fitz.open(bound) as source:
        assert len(final) == 7
        for page, original in zip(final, source, strict=True):
            assert page.get_pixmap().samples == original.get_pixmap().samples
        print(len(final), "pages;", len(final.get_toc()), "bookmarks; merge pixels unchanged")
    print("Internal ordinary/legacy QA:", ordinary)
    print("Control-only deliverable:", output)


if __name__ == "__main__":
    main()
