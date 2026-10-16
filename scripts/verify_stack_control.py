"""Synthetic compressed/expanded A1 stack controls through the public wrapper."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfWriter
from app.pz.generator import generate_wastewater_stack_node_pdf


def main(publish=False):
    directory = ROOT / "tmp/pdfs/stack-control-review"
    directory.mkdir(parents=True, exist_ok=True)
    variants = [
        ("typical", dict(floors_above=9)),
        ("expanded", dict(floors_above=6, collapse_typical_floors=False,
                          basement_floor_elevation_m=-3.2, outlet_invert_elevation_m=-1.75,
                          basement_collector_slope_per_mille=20., outlet_id="К1-7")),
    ]
    sources = []
    writer = PdfWriter()
    for name, kwargs in variants:
        path = directory / f"{name}.pdf"
        generate_wastewater_stack_node_pdf(str(path), **kwargs)
        sources.append(path)
        writer.append(path, outline_item=name)
    target = (ROOT / "output/pdf/stack-control-review/Проверка_стояка.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.add_metadata({"/Title": "Синтетическая проверка стояка. Не для выпуска"})
    writer.write(target)
    with fitz.open(target) as merged:
        assert len(merged) == 5
        index = 0
        for source in sources:
            with fitz.open(source) as part:
                for page in part:
                    assert page.get_pixmap().samples == merged[index].get_pixmap().samples
                    index += 1
    print("5 pages; pixel-identical to public wrapper outputs")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    main(parser.parse_args().publish)
