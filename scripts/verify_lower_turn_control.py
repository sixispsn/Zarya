"""Three synthetic terminal-node control exports through the public wrapper."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfWriter
from app.pz.generator import generate_wastewater_lower_turn_node_pdf


def main(publish=False):
    directory = ROOT / "tmp/pdfs/lower-turn-review"
    directory.mkdir(parents=True, exist_ok=True)
    sources = []
    writer = PdfWriter()
    for system, dn in (("K1", 100), ("K2", 150), ("K3", 50)):
        path = directory / f"{system}-DN{dn}.pdf"
        generate_wastewater_lower_turn_node_pdf(str(path), system=system, dn_mm=dn)
        sources.append(path)
        writer.append(path, outline_item=f"{system} DN{dn}")
    target = (ROOT / "output/pdf/lower-turn-review/Проверка_нижнего_узла.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.add_metadata({"/Title": "Синтетическая проверка нижнего узла. Не для выпуска"})
    writer.write(target)
    with fitz.open(target) as merged:
        assert len(merged) == 3
        for index, source in enumerate(sources):
            with fitz.open(source) as part:
                assert len(part) == 1
                assert part[0].get_pixmap().samples == merged[index].get_pixmap().samples
    print("3 pages; pixel-identical to public wrapper outputs")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    main(parser.parse_args().publish)
