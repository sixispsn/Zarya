"""Synthetic short/long expert response QA through the public generator."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfWriter
from app.pz.defense import generate_expert_response_pdf
from tests.test_defense_pdf_layout import response_case


def main(publish=False):
    directory = ROOT / "tmp/pdfs/defense-review"
    directory.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    sources = []
    for long, label in ((False, "short"), (True, "long")):
        output = directory / f"{label}.pdf"
        case = list(response_case(long))
        generate_expert_response_pdf(*case, str(output))
        writer.append(output, outline_item=label)
        sources.append(output)
    target = (ROOT / "output/pdf/defense-review/Проверка_ответа_эксперту.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.add_metadata({"/Title": "Синтетическая проверка ответа эксперту. Не для выпуска"})
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
