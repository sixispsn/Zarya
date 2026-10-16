"""Bounded educational A2 frame QA; never regenerates the signed Samara case."""
# ruff: noqa: E402 -- standalone repository script bootstrap
from copy import deepcopy
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from app.intake.studio_study import build_study, initialize_study, verify_legacy
from app.pz.generator import merge_pdfs
from app.pz.residential_case_section import generate_residential_case_pdf
from app.pz.small_residential_basement_proposal import educational_basement_proposal
from app.pz.small_residential_section import generate_small_residential_section_pdf
from tests.test_study_graphic_frame import check_graphic_pdf


def main():
    temporary = ROOT / "tmp/pdfs/study-graphic-frames/current"
    destination = ROOT / "output/pdf/study-graphic-frames"
    temporary.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    draft = {"revision": 0, "answers": {}, "documents": []}
    initialize_study(draft, "two", None)
    _, model, calc, water, storm, _ = build_study(draft)
    node, _ = verify_legacy(water, storm, calc.residents)
    before = deepcopy((model, calc, draft))
    paths, titles = [], []
    for name, title, kwargs in (
        ("compact", "Два этажа - компактный учебный разрез Studio", dict(calculation=calc, compact_demo=True)),
        ("plain", "Два этажа - незаданные профили", {}),
        ("calculated", "Два этажа - расчётное приложение и подробные примечания", dict(calculation=calc)),
        ("proposal", "Два этажа - предварительная подвальная прокладка", dict(basement_proposal=educational_basement_proposal(model))),
    ):
        path = temporary / f"{name}.pdf"
        generate_small_residential_section_pdf(str(path), model, **kwargs)
        paths.append(str(path))
        titles.append(title)
    assert (model, calc, draft) == before
    draft = {"revision": 0, "answers": {}, "documents": []}
    initialize_study(draft, "three", None)
    case = build_study(draft)[1]
    before = deepcopy(case)
    path = temporary / "case.pdf"
    generate_residential_case_pdf(path, case, node=node, root=ROOT)
    assert case == before
    paths.append(str(path))
    titles.append("Три этажа - учебный разрез Studio")
    for path in paths:
        with fitz.open(path) as pdf:
            assert len(pdf) == 1
            check_graphic_pdf(pdf[0])
    output = destination / "Проверка_рамок_учебных_разрезов.pdf"
    merge_pdfs(paths, str(output), section_titles=titles)
    with fitz.open(output) as merged:
        assert len(merged) == len(paths)
        for i, path in enumerate(paths):
            with fitz.open(path) as part:
                assert part[0].get_pixmap().samples == merged[i].get_pixmap().samples
        print(len(merged), "pages;", len(merged.get_toc()), "bookmarks; merge pixels unchanged")
    print(output)


if __name__ == "__main__":
    if not os.environ.get("NODE_BINARY"):
        print("Set NODE_BINARY if node is not on PATH", flush=True)
    main()
