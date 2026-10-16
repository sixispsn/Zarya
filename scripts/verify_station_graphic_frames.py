"""Frame-only QA copies. Never overwrites signed input or project delivery."""

# ruff: noqa: E402 -- standalone repository script bootstrap
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cairosvg
import fitz
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import mm

from app.intake import samara_study
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.fire_diaphragm_correction_report import correction_review_pdf
from app.pz.fire_pressure_review_report import render_pressure_review
from app.pz.fire_repair_review_report import render_repair_review
from app.pz.fire_review_scheme import generate_review_scheme
from app.pz.fire_station_design_report import render_station_design
from app.pz.fire_station_design_scheme import generate_design_scheme
from app.pz.fire_station_input_report import render_station_input_report
from app.pz.generator import merge_pdfs
from app.pz.water_building_section import build_water_section
from app.pz.wastewater_graphic_exports import generate_wastewater_graphic_export
from app.pz.wastewater_building_drafting import (
    build_residential_wastewater_reference_svg,
)
from tests.test_fire_review_binding import bundle, passing_model
from tests.test_station_graphic_frames import qa_document, check_text_frames
from tests.test_wastewater_building_drafting import _demo_assembly
from tests.test_water_unified_section import project as water_fixture
from tests.test_wastewater_pressure_scheme import _pressure_project
from scripts.build_samara_repair_review import calculate_repair_review
from scripts.build_samara_section_study import make_fire_station


def main():
    temp = ROOT / "tmp/pdfs/station-graphic-frame-review"
    out = ROOT / "output/pdf/station-graphic-frame-review"
    temp.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    ensure_drafting_font_registered()
    protected = [
        samara_study.CASE,
        ROOT / "legacy/sp30_calculator.html",
        ROOT / "legacy/archive/sp30_calculator.pre-2026-09-21.html",
    ]
    hashes = {p: sha256(p.read_bytes()).hexdigest() for p in protected}
    doc = qa_document()
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    signed_bundle = samara_study.build(draft, temp, render=False)[0]
    p = signed_bundle.project
    p.document = deepcopy(doc)
    before = deepcopy(asdict(p))
    r = p.fire_pumps.station_design
    generic = bundle(passing_model(), temp)
    generic.project.document = deepcopy(doc)
    generic_before = deepcopy(asdict(generic.project))
    print(
        "Recomputing historical repair case for its unchanged report body", flush=True
    )
    repair = calculate_repair_review()
    paths, titles = [], []

    def add(name, render, *, graphic=False):
        n = len(paths) + 1
        path = temp / f"{n:02}.pdf"
        render(path)
        if not graphic:
            check_text_frames(path.read_bytes(), len(PdfReader(path).pages))
        pdf = fitz.open(path)
        thumbnails = []
        for i, page in enumerate(pdf, 1):
            width, height = page.rect.width / mm, page.rect.height / mm
            if graphic:
                assert page.get_text().count("Изм.") == 1
                # Whole document graphic counts are first-sheet-only.
                region = fitz.Rect(
                    (width - 25) * mm,
                    (height - 30) * mm,
                    (width - 5) * mm,
                    (height - 20) * mm,
                )
                assert page.get_text(clip=region).strip() == (
                    str(len(pdf)) if i == 1 else ""
                )
            pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
            pix.save(temp / f"{n:02}-{i:02}.png")
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            im.thumbnail((650, 850))
            tile = Image.new("RGB", (670, 880), "#dddddd")
            tile.paste(im, ((670 - im.width) // 2, 25))
            ImageDraw.Draw(tile).text((10, 5), f"{n:02} / {i:02}", fill="black")
            thumbnails.append(tile)
        for start in range(0, len(thumbnails), 4):
            contact = Image.new("RGB", (1340, 1760), "white")
            for j, tile in enumerate(thumbnails[start : start + 4]):
                contact.paste(tile, ((j % 2) * 670, (j // 2) * 880))
            contact.save(temp / f"contact-{n:02}-{start // 4 + 1}.png")
        print(name, len(pdf), flush=True)
        paths.append(str(path))
        titles.append(name + " - контроль оформления")

    add(
        "Вводы и станция",
        lambda path: render_station_input_report(
            path, generic.project, generic.fire_station_result
        ),
    )
    add(
        "Проверка давления",
        lambda path: render_pressure_review(
            path, generic.project, generic.fire_pressure_review
        ),
    )
    add(
        "Расчёт и автоматика с приложением",
        lambda path: render_station_design(path, r, document=doc),
    )
    add(
        "Диафрагмы отдельно",
        lambda path: path.write_bytes(
            correction_review_pdf(r["repair_review"], document=doc)
        ),
    )
    add(
        "Исторические ремонтные режимы",
        lambda path: render_repair_review(path, repair, document=doc),
    )
    add(
        "Схемы В2 А3 и узлы А4",
        lambda path: generate_review_scheme(path, generic.project),
        graphic=True,
    )
    add(
        "Станция и сеть В2 А3",
        lambda path: generate_design_scheme(
            path, p, make_fire_station(samara_study.load_case()["payload"]["basis"])
        ),
        graphic=True,
    )

    def svg_pdf(path, svgs):
        writer = PdfWriter()
        for svg in svgs:
            writer.add_page(
                PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))).pages[0]
            )
        with path.open("wb") as stream:
            writer.write(stream)

    water = water_fixture()
    water.document = replace(doc, stage="П")
    add(
        "Водоснабжение А2",
        lambda path: svg_pdf(path, [build_water_section(water).svg]),
        graphic=True,
    )
    assembly = replace(_demo_assembly(), document=deepcopy(doc))
    add(
        "Водоотведение А2 вертикальный",
        lambda path: svg_pdf(
            path, [build_residential_wastewater_reference_svg(assembly)]
        ),
        graphic=True,
    )
    pressure = _pressure_project()
    pressure.document = deepcopy(doc)
    add(
        "Напорная канализация А1",
        lambda path: generate_wastewater_graphic_export(
            pressure, "pressure", str(path)
        ),
        graphic=True,
    )
    assert asdict(p) == before and asdict(generic.project) == generic_before
    assert {p: sha256(p.read_bytes()).hexdigest() for p in protected} == hashes
    target = out / "Проверка_рамок_станции_и_схем.pdf"
    merge_pdfs(paths, str(target), section_titles=titles)
    merged = fitz.open(target)
    offset = 0
    for path in paths:
        source = fitz.open(path)
        for page in source:
            assert merged[offset].get_pixmap().digest == page.get_pixmap().digest
            offset += 1
    assert offset == len(merged)
    print(f"{target}: {offset} pages; merged pixels match", flush=True)


if __name__ == "__main__":
    main()
