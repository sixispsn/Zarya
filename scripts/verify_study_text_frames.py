"""Educational frame QA; does not rewrite signed projects or historical PDFs."""
# ruff: noqa: E402 -- standalone repository script bootstrap
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz

from app.intake.studio_study import build_study, initialize_study, verify_legacy
from app.pz.generator import merge_pdfs
from app.pz.network_takeoff_pdf import generate_network_takeoff_pdf
from app.pz.small_residential_calculation_pdf import generate_residential_calculation_pdf
from app.pz.small_residential_takeoff import educational_residential_takeoff
from tests.test_study_document_frame import check_frames


def main():
    temporary = ROOT / "tmp/pdfs/study-text-frames/current"
    destination = ROOT / "output/pdf/study-text-frames"
    temporary.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    draft = {"revision": 0, "answers": {}, "documents": []}
    initialize_study(draft, "two", None)
    _, model, calc, water, storm, _ = build_study(draft)
    _, source_hash = verify_legacy(water, storm, calc.residents)
    network = educational_residential_takeoff(model, calc)
    before = deepcopy((model, calc, network, draft))
    calculation, takeoff = temporary / "calculation.pdf", temporary / "takeoff.pdf"
    generate_residential_calculation_pdf(str(calculation), model, calc, rain_source_sha256=source_hash)
    generate_network_takeoff_pdf(str(takeoff), network)
    assert (model, calc, network, draft) == before
    for path, width, cipher in ((calculation, 210, "УЧЕБНЫЙ-К1К2.Р"),
                                 (takeoff, 420, "УЧЕБНЫЙ-К1К2.ВО")):
        with fitz.open(path) as pdf:
            check_frames(pdf, width, cipher)
            print(path.name, len(pdf), "pages", flush=True)
    output = destination / "Проверка_рамок_учебных_приложений.pdf"
    merge_pdfs([str(calculation), str(takeoff)], str(output), section_titles=[
        "Учебный расчёт К1, К2 - проверка оформления",
        "Ведомость объёмов - не нормативная СО"])
    with fitz.open(output) as merged:
        index = 0
        for path in (calculation, takeoff):
            with fitz.open(path) as part:
                for page in part:
                    assert page.get_pixmap().samples == merged[index].get_pixmap().samples
                    index += 1
        assert index == len(merged)
        print(len(merged), "pages;", len(merged.get_toc()), "bookmarks; merge pixels unchanged")
    print(output)


if __name__ == "__main__":
    main()
