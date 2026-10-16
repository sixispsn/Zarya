"""Synthetic public-service QA: three short and three two-page failure cases."""
# ruff: noqa: E402 -- repository bootstrap
from dataclasses import replace
from pathlib import Path
import sys
from unittest.mock import patch
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from pypdf import PdfReader, PdfWriter
from tests.test_wastewater_status_document import cases, long_reasons


def main(publish=False):
    directory = ROOT / "tmp/pdfs/wastewater-status-review"
    directory.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    sources = []
    for kind, project, module, assess, generate in cases():
        project.document.object_name = "Синтетическая проверка неполных данных. Не для выпуска"
        project.document.cipher = "QA-СТАТУС-ИОС3"
        readiness = getattr(module, assess)(project)
        for label, reasons in (("short", ("Контрольный пример: отсутствуют подтверждённые исходные данные.",)),
                               ("long", long_reasons(35))):
            output = directory / f"{kind}-{label}.pdf"
            blocked = replace(readiness, ready=False, reasons=reasons)
            with patch.object(module, assess, return_value=blocked):
                result = getattr(module, generate)(project, str(output))
            assert not result.ready and result.reasons == reasons
            reader = PdfReader(output)
            assert len(reader.pages) == (1 if label == "short" else 2)
            writer.append(reader, outline_item=f"{kind}: {label}")
            sources.append(output)
    writer.add_metadata({"/Title": "Проверка листов неполных данных. Не проектная документация"})
    target = (ROOT / "output/pdf/wastewater-status-review/Проверка_листов_неполных_данных.pdf"
              if publish else directory / "qa.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        writer.write(stream)
    with fitz.open(target) as merged:
        index = 0
        for source in sources:
            with fitz.open(source) as part:
                for page in part:
                    assert page.get_pixmap().samples == merged[index].get_pixmap().samples
                    index += 1
        assert index == len(merged) == 9
    print(target)
    print("9 pages; merged pages pixel-identical to public service outputs; ready=False")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="Save reviewed QA under output/pdf")
    main(parser.parse_args().publish)
