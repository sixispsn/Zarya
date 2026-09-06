#!/usr/bin/env python3
"""Интеграционный quality gate полного контрольного комплекта Zarya."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intake.preflight import preflight_request  # noqa: E402
from app.intake.project_builder import build_project  # noqa: E402
from app.intake.yaml_io import load_request_file  # noqa: E402
from app.pz.ios2_orchestrator import IOS2DesignBundle, design_ios2  # noqa: E402
from app.quality_gates import build_release_quality_report  # noqa: E402


REQUIRED_DOCUMENTS = (
    "pz_pdf",
    "spec_pdf",
    "scheme_pdf",
    "metering_scheme_pdf",
    "pump_zone_scheme_pdf",
    "pump_selection_pdf",
    "v1_calculation_pdf",
    "wastewater_pz_pdf",
    "wastewater_calculation_pdf",
    "wastewater_scheme_pdf",
    "wastewater_diagnostic_pdf",
    "wastewater_ugo_pdf",
    "wastewater_spec_pdf",
    "wastewater_package_pdf",
    "wastewater_balance_pdf",
    "balance_pdf",
    "commission_control_pdf",
)
RENDER_DOCUMENTS = (
    "pz_pdf",
    "scheme_pdf",
    "wastewater_scheme_pdf",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inspect_pdf(path: Path) -> dict[str, Any]:
    reader = PdfReader(path)
    if not reader.pages:
        raise RuntimeError(f"{path.name}: PDF не содержит страниц")
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if "⟦" in text or "⟧" in text:
        raise RuntimeError(f"{path.name}: найдены незаполненные плейсхолдеры")
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "pages": len(reader.pages),
        "sha256": _sha256(path),
    }


def _render_first_pages(
    bundle: IOS2DesignBundle,
    output: Path,
) -> list[dict[str, Any]]:
    executable = shutil.which("pdftoppm")
    if executable is None:
        return []
    render_dir = output / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for attribute in RENDER_DOCUMENTS:
        source = Path(str(getattr(bundle, attribute)))
        target = render_dir / source.stem
        subprocess.run(
            [
                executable,
                "-f", "1",
                "-singlefile",
                "-r", "96",
                "-png",
                str(source),
                str(target),
            ],
            check=True,
        )
        png = target.with_suffix(".png")
        if not png.is_file() or png.stat().st_size < 1000:
            raise RuntimeError(f"{source.name}: первая страница не отрендерена")
        rendered.append({
            "source": source.name,
            "name": png.name,
            "bytes": png.stat().st_size,
            "sha256": _sha256(png),
        })
    return rendered


def verify_control_release(
    source: Path,
    output: Path,
    *,
    allowed_blockers: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    request = load_request_file(str(source))
    preflight = preflight_request(request)
    if not preflight.can_release:
        codes = ", ".join(row.code for row in preflight.release_blockers)
        raise RuntimeError(f"контрольный ProjectIntent не прошёл Preflight: {codes}")

    output.mkdir(parents=True, exist_ok=True)
    bundle = design_ios2(build_project(request), output_dir=str(output))
    missing = [
        attribute
        for attribute in REQUIRED_DOCUMENTS
        if not getattr(bundle, attribute, None)
    ]
    if missing:
        raise RuntimeError(
            "контрольный комплект не сформировал документы: " + ", ".join(missing)
        )

    pdfs = sorted(
        {
            Path(str(getattr(bundle, attribute)))
            for attribute in REQUIRED_DOCUMENTS
        },
        key=lambda path: path.name,
    )
    documents = [_inspect_pdf(path) for path in pdfs]
    quality = build_release_quality_report(
        preflight, bundle.commission_report,
    )
    blocker_codes = {row.code for row in quality.blocking_findings}
    unexpected = blocker_codes - allowed_blockers
    if unexpected:
        raise RuntimeError(
            "новые блокеры контрольного выпуска: " + ", ".join(sorted(unexpected))
        )

    manifest = {
        "schema_version": "1.0",
        "source": str(source.relative_to(ROOT)),
        "build_commit": os.environ.get("ZARYA_BUILD_COMMIT", "unknown"),
        "preflight": {
            "can_release": preflight.can_release,
            "issue_count": len(preflight.issues),
        },
        "quality": quality.to_dict(),
        "allowed_blockers": sorted(allowed_blockers),
        "documents": documents,
        "renders": _render_first_pages(bundle, output),
    }
    (output / "quality-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "demo" / "demo_project.yaml",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-blocker", action="append", default=[])
    args = parser.parse_args()
    manifest = verify_control_release(
        args.source.resolve(),
        args.output.resolve(),
        allowed_blockers=frozenset(args.allow_blocker),
    )
    print(
        "Quality gate: "
        f"{len(manifest['documents'])} PDF, "
        f"статус {manifest['quality']['state']}, "
        f"блокеры {manifest['quality']['blocking_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
