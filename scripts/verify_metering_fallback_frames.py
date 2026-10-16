"""Frame QA only: synthetic copies, no signed input or project PDF overwritten."""

# ruff: noqa: E402
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cairosvg
import fitz
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.units import mm

from app.pz.generator import (
    _svg_to_a1_mm,
    generate_metering_scheme_pdf,
    generate_scheme_pdf,
    merge_pdfs,
)
from app.pz.scheme import build_scheme
from app.pz.wastewater_scheme import build_wastewater_scheme
from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics
from scripts.preview_metering_detail import review_project
from tests.test_metering_g1_switching import project as g1_project
from tests.test_metering_fallback_frames import check_graphic_page
from tests.test_station_graphic_frames import qa_document
from tests.test_wastewater_scheme_service import _project as sewer_project


def main():
    temp = ROOT / "tmp/pdfs/metering-fallback-frame-review"
    out = ROOT / "output/pdf/metering-fallback-frame-review"
    temp.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    protected = [
        ROOT / p
        for p in (
            "demo/samara_station_review.json",
            "legacy/sp30_calculator.html",
            "legacy/archive/sp30_calculator.pre-2026-09-21.html",
        )
    ]
    hashes = {p: sha256(p.read_bytes()).hexdigest() for p in protected}
    paths, titles = [], []
    cases = [
        ("ВУ: один ввод", review_project()),
        ("ВУ: общий Г.1", g1_project()),
        ("ВУ: три ввода", review_project()),
    ]
    cases[2][1].source.inputs_count = cases[2][1].meters.inputs_count = 3
    for name, p in cases:
        p.document = qa_document()
        before = deepcopy(asdict(p))
        path = temp / f"{len(paths) + 1:02}.pdf"
        generate_metering_scheme_pdf(p, str(path))
        assert asdict(p) == before
        paths.append(str(path))
        titles.append(name)
    for kind in ("water", "sewer"):
        p = review_project() if kind == "water" else sewer_project()
        p.document = qa_document()
        if kind == "sewer":
            assess_wastewater_diagnostics(p)
        before = deepcopy(asdict(p))
        path = temp / f"{len(paths) + 1:02}.pdf"
        if kind == "water":
            generate_scheme_pdf(p, str(path), scheme_result=build_scheme(p))
        else:
            svg = _svg_to_a1_mm(build_wastewater_scheme(p).svg)
            cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(path))
        assert asdict(p) == before
        paths.append(str(path))
        titles.append("Старая схема А1: " + ("В1" if kind == "water" else "К1/К2"))
    output = out / "Проверка_рамок_ВУ_и_старых_схем.pdf"
    merge_pdfs(paths, str(output), section_titles=titles)
    combined = fitz.open(output)
    offset = 0
    for n, path in enumerate(paths, 1):
        pdf = fitz.open(path)
        for i, page in enumerate(pdf, 1):
            width, height = (420, 297) if n <= 3 else (841, 594)
            check_graphic_page(page, width, height, i, len(pdf))
            a = page.get_pixmap()
            b = combined[offset + i - 1].get_pixmap()
            assert a.samples == b.samples
        offset += len(pdf)
        print(titles[n - 1], len(pdf), flush=True)
    assert offset == len(combined)
    reader = PdfReader(output)

    def walk(items):
        for item in items:
            if isinstance(item, list):
                yield from walk(item)
            else:
                assert 0 <= reader.get_destination_page_number(item) < offset
                yield item

    print("pages", offset, "bookmarks", len(list(walk(reader.outline))), flush=True)
    subprocess.run(
        ["pdftoppm", "-scale-to", "2200", "-png", str(output), str(temp / "page")],
        check=True,
    )
    images = sorted(temp.glob("page-*.png"))
    assert len(images) == offset
    for start in range(0, len(images), 4):
        contact = Image.new("RGB", (1600, 1160), "#dddddd")
        for j, path in enumerate(images[start : start + 4]):
            im = Image.open(path)
            im.thumbnail((780, 540))
            x, y = (j % 2) * 800, (j // 2) * 580
            contact.paste(im, (x + (800 - im.width) // 2, y + 25))
            ImageDraw.Draw(contact).text((x + 10, y + 5), path.stem, fill="black")
        contact.save(temp / f"contact-{start // 4 + 1:02}.png")
    # Detail crops supplement, not replace, full-sheet visual review.
    for i, page in enumerate(combined):
        w, h = page.rect.width / mm, page.rect.height / mm
        page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            clip=fitz.Rect((w - 191) * mm, (h - 61) * mm, w * mm, h * mm),
        ).save(temp / f"stamp-{i + 1:02}.png")
    assert all(
        sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items()
    )
    print(output, flush=True)


if __name__ == "__main__":
    main()
