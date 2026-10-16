"""Synthetic normal and expanded typological reports; never a project release."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfWriter
from app.architecture.program_report import generate_building_program_report_pdf
from tests.test_building_program_report_layout import report_case


def main(publish=False):
    directory = ROOT / "tmp/pdfs/building-program-review"
    directory.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    sources = []
    for long, label in ((False, "normal"), (True, "long")):
        output = directory / f"{label}.pdf"
        generate_building_program_report_pdf(report_case(directory / label, long), output)
        writer.append(output, outline_item=label)
        sources.append(output)
    target = (ROOT / "output/pdf/building-program-review/Проверка_типологической_модели.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.add_metadata({"/Title": "Синтетическая проверка типологической модели. Не для выпуска"})
    writer.write(target)
    with fitz.open(target) as merged:
        index = 0
        for source in sources:
            with fitz.open(source) as part:
                for page in part:
                    assert page.get_pixmap().samples == merged[index].get_pixmap().samples
                    index += 1
        assert index == len(merged)
        print(f"{index} pages; pixel-identical to public generator outputs")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    main(parser.parse_args().publish)
