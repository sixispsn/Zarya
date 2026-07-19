#!/usr/bin/env python3
"""Собрать воспроизводимый комиссионный комплект Demo Release 0.1."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.ios2_orchestrator import design_ios2


INPUT = ROOT / "demo" / "demo_project.yaml"
OUTPUT = ROOT / "demo_backup"


def _pdf_text(path: Path) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)


def main() -> int:
    request = load_request_file(str(INPUT))
    project = build_project(request)
    OUTPUT.mkdir(exist_ok=True)
    for old in OUTPUT.glob("*.pdf"):
        old.unlink()

    bundle = design_ios2(project, output_dir=str(OUTPUT))
    shutil.copy2(INPUT, OUTPUT / "demo_project.yaml")

    pdfs = [Path(x) for x in (
        bundle.pz_pdf, bundle.spec_pdf, bundle.scheme_pdf,
        bundle.hydraulic_pdf, bundle.resilience_pdf,
    ) if x]
    if len(pdfs) != 5:
        raise RuntimeError(f"ожидалось 5 PDF, получено {len(pdfs)}")

    placeholders = {}
    for pdf in pdfs:
        text = _pdf_text(pdf)
        if "⟦" in text or "⟧" in text:
            placeholders[pdf.name] = "обнаружены незаполненные поля"
    if placeholders:
        raise RuntimeError(f"комплект содержит плейсхолдеры: {placeholders}")

    presentation = OUTPUT / "Zarya_Demo_Release_0.1.pptx"
    manifest = {
        "release": "Demo Release 0.1",
        "input": INPUT.name,
        "test_command": "OSIFONT_PATH=/System/Library/Fonts/Supplemental/Arial.ttf venv/bin/pytest -q",
        "documents": [
            {
                "name": pdf.name,
                "bytes": pdf.stat().st_size,
                "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            }
            for pdf in pdfs
        ],
        "presentation": (
            {
                "name": presentation.name,
                "bytes": presentation.stat().st_size,
                "sha256": hashlib.sha256(presentation.read_bytes()).hexdigest(),
            }
            if presentation.exists()
            else None
        ),
        "calculation": {
            "fire_flow_lps": bundle.project.fire.q_total,
            "fire_cabinets_placed": bundle.project.fire.pk_total,
            "dictating_cabinets": bundle.project.fire.dictating_cabinet_id,
            "required_head_m": round(bundle.project.fire.required_head_m or 0.0, 2),
            "available_head_m": bundle.project.fire.available_head_m,
            "fire_pump": bundle.project.fire_pumps.model,
            "fire_pump_design_q_m3h": bundle.project.fire_pumps.q_design_m3h,
            "fire_pump_design_h_m": bundle.project.fire_pumps.h_design_m,
            "fire_pump_working_q_m3h": bundle.project.fire_pumps.wp_q,
            "fire_pump_working_h_m": bundle.project.fire_pumps.wp_h,
        },
        "status": bundle.status,
        "warnings": bundle.warnings,
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Собрано: {OUTPUT} ({len(pdfs)} PDF)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
