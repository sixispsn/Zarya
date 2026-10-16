"""Synthetic Plan-to-Section presentation cases, not a project release."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfWriter
from app.pz.architecture_section_engine import (
    generate_architecture_section_control_pdf, load_architecture_plan_registry,
)


def long_registry(registry):
    name = "Синтетическое длинное имя для проверки переноса текста " * 7
    return replace(registry, source_ref="Контрольный источник; " * 23, floors=tuple(
        replace(floor, rooms=(replace(floor.rooms[0], name=name),) + floor.rooms[1:])
        for floor in registry.floors))


def main(publish=False):
    directory = ROOT / "tmp/pdfs/architecture-section-review"
    directory.mkdir(parents=True, exist_ok=True)
    registry = load_architecture_plan_registry(ROOT / "demo/architecture_section_registry.json")
    writer = PdfWriter()
    sources = []
    for name, data in (("normal", registry), ("long-labels", long_registry(registry))):
        path = directory / f"{name}.pdf"
        generate_architecture_section_control_pdf(str(path), data)
        sources.append(path)
        writer.append(path, outline_item=name)
    target = (ROOT / "output/pdf/architecture-section-review/Проверка_архитектурного_разреза.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.add_metadata({"/Title": "Синтетическая проверка архитектурного разреза. Не для выпуска"})
    writer.write(target)
    with fitz.open(target) as merged:
        assert len(merged) == 2
        for index, source in enumerate(sources):
            with fitz.open(source) as part:
                assert len(part) == 1
                assert part[0].get_pixmap().samples == merged[index].get_pixmap().samples
    print("2 pages; pixel-identical to public exports")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    main(parser.parse_args().publish)
