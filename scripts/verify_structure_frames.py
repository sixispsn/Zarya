"""Frame-only QA of intermediate sewer sheets; no project issue or deployment."""

# ruff: noqa: E402
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.units import mm

from app.pz.generator import merge_pdfs
from app.pz.project import Project
from app.pz.architecture_section_engine import (
    build_architecture_section,
    architecture_section_to_wastewater_layout,
)
from app.pz.wastewater_structure_renderer import (
    WastewaterStructureScope as Scope,
    build_wastewater_structure_svg,
    generate_wastewater_structure_pdf,
)
from tests.test_architecture_section_engine import _registry
from tests.test_metering_fallback_frames import check_graphic_page
from tests.test_station_graphic_frames import qa_document
from tests.test_wastewater_structure_frame import review_case


def main():
    include_basement = "--with-basement" in sys.argv
    folder = (
        "basement-frame-clearance" if include_basement else "structure-frame-review"
    )
    temp = ROOT / "tmp/pdfs" / folder / "current"
    out = ROOT / "output/pdf" / folder
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
    p, layout = review_case()
    # Default preserves the previous four-page review; the explicit new run
    # adds the corrected basement body and checks its printed clearance.
    scopes = (
        tuple(Scope) if include_basement else (Scope.FOUNDATION, Scope.FULL_FLOOR_STACK)
    )
    cases = [
        (p, layout, scope, i, len(scopes), 841, 594)
        for i, scope in enumerate(scopes, 1)
    ]
    confirmed = architecture_section_to_wastewater_layout(
        build_architecture_section(_registry())
    )
    cases.append(
        (
            Project(document=qa_document()),
            confirmed,
            Scope.FULL_FLOOR_STACK,
            1,
            1,
            841,
            594,
        )
    )
    cases.append(
        (
            p,
            replace(layout, sheet_width_mm=1189, sheet_height_mm=841),
            Scope.FULL_FLOOR_STACK,
            1,
            1,
            1189,
            841,
        )
    )
    titles = [
        "Плита подвала",
        "Поэтажный каркас",
        "Подтверждённые помещения",
        "Контроль размеров А0",
    ]
    if include_basement:
        titles.insert(1, "Подвальная магистраль К1: зазор до штампа")
    paths = []
    for n, (p, layout, scope, number, total, width, height) in enumerate(cases, 1):
        before = deepcopy((asdict(p), asdict(layout)))
        path = temp / f"{n:02}.pdf"
        generate_wastewater_structure_pdf(
            p, layout, str(path), scope, sheet_no=number, sheet_total=total
        )
        assert (asdict(p), asdict(layout)) == before
        pdf = fitz.open(path)
        assert len(pdf) == 1
        check_graphic_page(pdf[0], width, height, number, total)
        if scope == Scope.BASEMENT_K1_MAIN:
            from tests.test_basement_stamp_clearance import check_clearance

            svg = build_wastewater_structure_svg(
                p, layout, scope, sheet_no=number, sheet_total=total
            )
            check_clearance(pdf[0], svg)
            pdf[0].get_pixmap(
                matrix=fitz.Matrix(3, 3),
                clip=fitz.Rect(635 * mm, 510 * mm, 690 * mm, 555 * mm),
            ).save(temp / "clearance.png")
        pdf[0].get_pixmap(
            matrix=fitz.Matrix(2, 2),
            clip=fitz.Rect(
                (width - 191) * mm, (height - 61) * mm, width * mm, height * mm
            ),
        ).save(temp / f"stamp-{n:02}.png")
        paths.append(str(path))
    filename = (
        "Проверка_зазора_плиты_и_штампа.pdf"
        if include_basement
        else "Проверка_рамок_этапов_канализации.pdf"
    )
    output = out / filename
    merge_pdfs(paths, str(output), section_titles=titles)
    pdf = fitz.open(output)
    reader = PdfReader(output)
    assert len(pdf) == len(cases) == len(reader.outline)
    for i, path in enumerate(paths):
        assert fitz.open(path)[0].get_pixmap().samples == pdf[i].get_pixmap().samples
        assert reader.get_destination_page_number(reader.outline[i]) == i
    subprocess.run(
        ["pdftoppm", "-scale-to", "2400", "-png", str(output), str(temp / "page")],
        check=True,
    )
    images = sorted(temp.glob("page-*.png"))
    assert len(images) == len(cases)
    for start in range(0, len(images), 4):
        contact = Image.new("RGB", (1600, 1160), "#dddddd")
        for j, path in enumerate(images[start : start + 4]):
            im = Image.open(path)
            im.thumbnail((780, 540))
            x, y = (j % 2) * 800, (j // 2) * 580
            contact.paste(im, (x + (800 - im.width) // 2, y + 25))
            ImageDraw.Draw(contact).text((x + 10, y + 5), path.stem, fill="black")
        contact.save(temp / f"contact-{start // 4 + 1:02}.png")
    assert all(sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items())
    print(
        f"{len(cases)} pages, {len(cases)} bookmarks; physical frames and merge pixels verified."
    )
    print(output)


if __name__ == "__main__":
    main()
