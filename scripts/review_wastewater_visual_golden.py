"""Render exact candidate snapshots for review, never accept/update hashes."""
# ruff: noqa: E402 -- repository script bootstrap
from io import BytesIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cairosvg
from pypdf import PdfReader, PdfWriter

from tests.test_wastewater_visual_golden import _production_svgs, _visual_digest


def main():
    directory = ROOT / "tmp/pdfs/wastewater-golden-review"
    directory.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for kind, pages in _production_svgs().items():
        for index, svg in enumerate(pages, 1):
            name = f"{kind}-{index}"
            (directory / f"{name}.svg").write_text(svg, encoding="utf-8")
            pdf = cairosvg.svg2pdf(bytestring=svg.encode())
            writer.append(PdfReader(BytesIO(pdf)), outline_item=name)
            print(name, _visual_digest(svg))
    writer.add_metadata({"/Title": "Внутренняя проверка эталонов. Не проектная документация"})
    output = directory / "candidates.pdf"
    with output.open("wb") as stream:
        writer.write(stream)
    print("Internal QA only (not project documentation):", output)


if __name__ == "__main__":
    main()
