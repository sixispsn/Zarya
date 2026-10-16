"""Synthetic standalone basement controls plus their A1 stack integration."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfWriter
from app.pz.generator import generate_wastewater_basement_node_pdf, generate_wastewater_stack_node_pdf


def main(publish=False):
    directory = ROOT / "tmp/pdfs/basement-control-review"
    directory.mkdir(parents=True, exist_ok=True)
    variants = [
        ("missing", generate_wastewater_basement_node_pdf, {}),
        ("explicit", generate_wastewater_basement_node_pdf,
         dict(basement_floor_elevation_m=-3.2, outlet_invert_elevation_m=-1.75,
              collector_slope_per_mille=20, outlet_dn_mm=150)),
        ("missing-mark", generate_wastewater_basement_node_pdf, dict(outlet_id=" ")),
        ("stack", generate_wastewater_stack_node_pdf, dict(floors_above=9)),
    ]
    sources = []
    writer = PdfWriter()
    for name, export, kwargs in variants:
        path = directory / f"{name}.pdf"
        export(str(path), **kwargs)
        sources.append(path)
        writer.append(path, outline_item=name)
    target = (ROOT / "output/pdf/basement-control-review/Проверка_подвала.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.add_metadata({"/Title": "Синтетическая проверка подвала. Не для выпуска"})
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
