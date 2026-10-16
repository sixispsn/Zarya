"""Synthetic floor sheets through the public wrapper; no project release."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfWriter
from app.pz.generator import generate_wastewater_typical_floor_node_pdf
from app.pz.wastewater_floor_drafting import FloorFixtureInput


def main(publish=False):
    directory = ROOT / "tmp/pdfs/floor-control-review"
    directory.mkdir(parents=True, exist_ok=True)
    variants = [
        ("floor-2", dict(floor_no=2, floor_elevation_m=3.)),
        ("floor-10", dict(floor_no=10, floor_elevation_m=27.)),
        ("repeated-fixtures", dict(fixtures=[
            FloorFixtureInput("М1", "sink", "Кухня"),
            FloorFixtureInput("В1", "bath", "Санузел"),
            FloorFixtureInput("У1", "washbasin", "Санузел", 50, 2),
            FloorFixtureInput("Т1", "toilet", "Санузел", 100, 2),
        ])),
    ]
    sources = []
    writer = PdfWriter()
    for name, kwargs in variants:
        path = directory / f"{name}.pdf"
        generate_wastewater_typical_floor_node_pdf(str(path), **kwargs)
        sources.append(path)
        writer.append(path, outline_item=name)
    target = (ROOT / "output/pdf/floor-control-review/Проверка_типового_этажа.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.add_metadata({"/Title": "Синтетическая проверка типового этажа. Не для выпуска"})
    writer.write(target)
    with fitz.open(target) as merged:
        assert len(merged) == len(sources)
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
