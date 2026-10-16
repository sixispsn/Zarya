"""Two synthetic K3 pages through the public exporter; not a project release."""
# ruff: noqa: E402 -- repository script bootstrap
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from app.pz.generator import merge_pdfs
from app.pz.wastewater_k3_scheme_service import generate_wastewater_k3_scheme
from tests.test_wastewater_k3_scheme import _k3_project


def main():
    temporary = ROOT / "tmp/pdfs/k3-note-layout"
    destination = ROOT / "output/pdf/k3-note-layout"
    temporary.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    project = _k3_project()
    project.document.cipher = "QA-K3-NOTES-ИОС3"
    project.document.object_name = "Контроль оформления К3. Не проектная документация"
    project.document.object_part = "Синтетические исходные данные"
    before = deepcopy(project)
    source = temporary / "k3-public-export.pdf"
    result = generate_wastewater_k3_scheme(project, str(source))
    # ready refers only to completeness of this synthetic fixture, not approval.
    assert result.ready and project == before
    output = destination / "Проверка_пояснений_К3.pdf"
    merge_pdfs([str(source)], str(output), section_titles=[
        "Контроль оформления К3. Синтетический пример, не проектная документация",
    ])
    with fitz.open(source) as original, fitz.open(output) as final:
        assert len(original) == len(final) == 2
        for page, old in zip(final, original, strict=True):
            assert abs(page.rect.width * 25.4 / 72 - 841) < .01
            assert abs(page.rect.height * 25.4 / 72 - 594) < .01
            assert "Не проектная документация" in " ".join(page.get_text().split())
            assert page.get_pixmap().samples == old.get_pixmap().samples
        assert "К3 показана самостоятельной" in final[0].get_text()
        assert "Данные К3" in final[1].get_text()
        print("2 A1 pages;", len(final.get_toc()), "bookmark; merge pixels unchanged")
    print(output)


if __name__ == "__main__":
    main()
