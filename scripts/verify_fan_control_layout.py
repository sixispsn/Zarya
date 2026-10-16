"""Isolated fan controls plus the existing full-building control, never release."""
# ruff: noqa: E402 -- repository script bootstrap
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from app.pz.generator import merge_pdfs
from app.pz.wastewater_fan_drafting import generate_fan_details_pdf
from app.pz.wastewater_scheme_service import generate_wastewater_fan_binding_preview
from scripts.build_fan_details import control_fan_details
from tests.fan_binding_fixture import fan_binding_fixture
from tests.test_fan_control_layout import check_control_page


def main():
    temporary = ROOT / "tmp/pdfs/fan-control-layout"
    destination = ROOT / "output/pdf/fan-control-layout"
    temporary.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    data = control_fan_details()
    before = deepcopy(data)
    first = temporary / "isolated.pdf"
    generate_fan_details_pdf(data, str(first))
    assert data == before
    with fitz.open(first) as pdf:
        assert len(pdf) == 2
        for page in pdf:
            check_control_page(page)
    project, bound_data = fan_binding_fixture()
    before = deepcopy((project, bound_data))
    second = temporary / "building_control.pdf"
    result = generate_wastewater_fan_binding_preview(project, bound_data, str(second))
    assert not result.ready and (project, bound_data) == before
    with fitz.open(second) as pdf:
        assert len(pdf) == 7
        check_control_page(pdf[-1])
        assert "7 / 7" in pdf[-1].get_text()
        for page in list(pdf)[:-1]:
            assert "Не проектная документация" in page.get_text()
    # Keep this earlier deliverable scoped to the two isolated A3 controls.
    # Parent A1 note layout now has its own verify_building_note_layout.py QA.
    context = temporary / "full_context.pdf"
    merge_pdfs([str(first), str(second)], str(context), section_titles=[
        "Изолированные контрольные узлы: вытяжка и клапан",
        "Контроль привязки к синтетическому зданию. Не проектная документация",
    ])
    with fitz.open(context) as merged:
        assert len(merged) == 9
        index = 0
        for path in (first, second):
            with fitz.open(path) as part:
                for page in part:
                    assert page.get_pixmap().samples == merged[index].get_pixmap().samples
                    index += 1
        print(len(merged), "pages;", len(merged.get_toc()), "bookmarks; merge pixels unchanged")
    output = destination / "Проверка_контрольных_листов_фановой_вентиляции.pdf"
    merge_pdfs([str(first)], str(output), section_titles=["Контрольные узлы А3. Не проектная документация"])
    with fitz.open(output) as final, fitz.open(first) as source:
        assert len(final) == 2
        for page, original in zip(final, source, strict=True):
            check_control_page(page)
            assert page.get_pixmap().samples == original.get_pixmap().samples
    print("Deliverable: 2 A3 control pages. Parent A1 QA: verify_building_note_layout.py.")
    print(output)


if __name__ == "__main__":
    main()
