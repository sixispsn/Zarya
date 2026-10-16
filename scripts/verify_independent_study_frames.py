"""Reproduce bounded study-layout QA, without changing signed project artifacts."""
# ruff: noqa: E402 -- standalone repository script bootstrap
from copy import deepcopy
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from PIL import Image, ImageDraw

from app.architecture.residential_plan_study import load_plan_study
from app.pz.generator import merge_pdfs
from app.pz.residential_plan_section import generate_plan_section_pdf
from app.pz.residential_plan_study_pdf import generate_plan_study_pdf
from app.pz.small_residential_preview import generate_small_residential_pdf
from app.pz.small_residential_combined import generate_small_residential_combined_pdf
from tests.test_independent_study_frames import check_page
from tests.test_small_residential_scheme import model


def qa_source(path):
    """Clearly synthetic substrate; not fabricated architecture or a replacement AR."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1500, 1123), "white")
    draw = ImageDraw.Draw(image)
    for y in range(0, 1123, 50):
        for x in range(0, 1500, 250):
            draw.text((x, y), "QA ONLY - NO SOURCE PLAN", fill="#555555")
    image.save(path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Original plan; otherwise use an explicitly synthetic QA substrate")
    args = parser.parse_args()
    temporary = ROOT / "tmp/pdfs/independent-study-frames"
    destination = ROOT / "output/pdf/independent-study-frames"
    temporary.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    study = load_plan_study(ROOT / "demo/residential_second_layout.study.json")
    original = deepcopy(study)
    paths, titles = [], []
    path = temporary / "second.pdf"
    generate_plan_section_pdf(path, study)
    paths.append(str(path))
    titles.append("Второй жилой пример - учебный разрез К1")
    for name, roof, combined in (("preview", False, False), ("preview_roof", True, False), ("combined", True, True)):
        m = model(include_roof=roof)
        before = deepcopy(m)
        path = temporary / f"{name}.pdf"
        (generate_small_residential_combined_pdf if combined else generate_small_residential_pdf)(str(path), m)
        assert m == before
        paths.append(str(path))
        titles.append({"preview": "К1 - кровля не задана", "preview_roof": "Предварительная компоновка - два листа К1/К2",
                       "combined": "Общий учебный лист К1/К2"}[name])
    for path in paths:
        with fitz.open(path) as pdf:
            for i, page in enumerate(pdf, 1):
                check_page(page, sheet_no=i, sheet_total=len(pdf))
    source = args.source or qa_source(temporary / "synthetic" / study.source_image)
    path = temporary / "plan_debug.pdf"
    generate_plan_study_pdf(path, study, source)
    assert study == original
    paths.append(str(path))
    titles.append("Непроектная разметка - " + ("исходный JPG" if args.source else "QA, исходный JPG отсутствует"))
    output = destination / "Проверка_самостоятельных_учебных_листов.pdf"
    merge_pdfs(paths, str(output), section_titles=titles)
    with fitz.open(output) as merged:
        page_index = 0
        for path in paths:
            with fitz.open(path) as part:
                for page in part:
                    assert page.get_pixmap().samples == merged[page_index].get_pixmap().samples
                    page_index += 1
        assert len(merged) == 6
        print(len(merged), "pages;", len(merged.get_toc()), "bookmarks; merge pixels unchanged")
    if not args.source:
        print("Plan debug uses a labelled synthetic substrate, not the missing original JPG")
    print(output)


if __name__ == "__main__":
    main()
