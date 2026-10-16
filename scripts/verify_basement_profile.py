"""Synthetic profile QA, without changing or confirming the example request."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfWriter
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_basement_profile import basement_profile_from_request, generate_basement_profile_pdf


def main(publish=False):
    directory = ROOT / "tmp/pdfs/basement-profile-review"
    directory.mkdir(parents=True, exist_ok=True)
    req = load_request_file(str(ROOT / "demo/residential_2floors_8apartments.yaml"))
    data = basement_profile_from_request(
        req, proposed_invert_m=-2.2, preview_dn_mm=100,
        proposed_invert_basis="Предварительный вариант, не готовая трасса.")
    variants = [
        ("dn100", data), ("dn150", replace(data, preview_dn_mm=150)),
        ("long-basis", replace(data, proposed_invert_basis=(
            "Основание контрольного варианта: отметка лотка задана вручную для проверки оформления. "
            "Это не подтверждение трассы, гидравлики или глубины заложения. Геометрия наружной сети, "
            "характеристики трубы, отметка присоединения и условия эксплуатации требуют отдельных "
            "исходных данных. Длинное пояснение включено целиком для проверки переноса строк; "
            "оно не меняет статус предварительного варианта и не переносится в подтверждённые "
            "данные проекта. Выдача предназначена только для просмотра контрольного примера."
        ))),
    ]
    writer = PdfWriter()
    sources = []
    for name, variant in variants:
        path = directory / f"{name}.pdf"
        generate_basement_profile_pdf(str(path), variant)
        sources.append(path)
        writer.append(path, outline_item=name)
    target = (ROOT / "output/pdf/basement-profile-review/Проверка_профиля_подвала.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    writer.add_metadata({"/Title": "Синтетическая проверка профиля подвала. Не для выпуска"})
    writer.write(target)
    with fitz.open(target) as merged:
        assert len(merged) == 3
        for index, source in enumerate(sources):
            with fitz.open(source) as part:
                assert len(part) == 1
                assert part[0].get_pixmap().samples == merged[index].get_pixmap().samples
    print("3 pages; pixel-identical to public exports")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    main(parser.parse_args().publish)
