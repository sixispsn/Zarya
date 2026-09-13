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
from app.pz.commission import CommissionReport  # noqa: E402
from app.pz.ios2_orchestrator import IOS2DesignBundle, design_ios2  # noqa: E402
from app.quality_gates import ReleaseQualityReport, build_release_quality_report  # noqa: E402


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


def blocker_snapshot(
    quality: ReleaseQualityReport,
    commission: CommissionReport,
) -> list[dict[str, str]]:
    """Точные замечания, включая причины агрегированных DOC-04/DOC-05.

    Разрешение одного DOC-кода не должно скрывать новые ошибки внутри матрицы.
    Снимок - отрицательный регрессионный эталон, а не допуск к выпуску.
    """
    findings: list[dict[str, str]] = []
    audits = {
        item["discipline"]: item for item in commission.normative_audits
    }
    for finding in quality.blocking_findings:
        discipline = {"DOC-04": "ИОС3", "DOC-05": "ИОС2"}.get(finding.code)
        rows = [
            row for row in audits.get(discipline, {}).get("rows", [])
            if row.get("blocks_release")
        ]
        if rows:
            findings.extend({
                "code": row["rule_id"],
                "detail": row["evidence"],
                "reference": row["reference"],
            } for row in rows)
        else:
            findings.append({
                "code": finding.code,
                "detail": finding.detail,
                "reference": finding.reference,
            })
    return sorted(findings, key=lambda row: (row["code"], row["detail"]))


def check_expected_blockers(
    actual: list[dict[str, str]],
    expected: list[dict[str, str]],
) -> None:
    """Запретить новые, изменённые и исчезнувшие без ревизии замечания."""
    def canonical(rows: list[dict[str, str]]) -> list[tuple[str, str, str]]:
        return sorted((row["code"], row["detail"], row["reference"]) for row in rows)
    if not expected:
        raise ValueError("эталон заблокированного примера не может быть пустым")
    if canonical(actual) != canonical(expected):
        raise RuntimeError(
            "замечания контрольного примера изменились; требуется инженерная ревизия. "
            "Фактически: " + json.dumps(actual, ensure_ascii=False, sort_keys=True)
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
    expected_blockers: dict[str, Any] | None = None,
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
    if bundle.commission_report is None:
        raise RuntimeError("контрольный комплект не сформировал комиссионный отчёт")
    quality = build_release_quality_report(
        preflight, bundle.commission_report,
    )
    actual_blockers = blocker_snapshot(quality, bundle.commission_report)
    if expected_blockers is not None:
        if (
            expected_blockers.get("schema_version") != "1.0"
            or expected_blockers.get("source") != str(source.relative_to(ROOT))
        ):
            raise ValueError("неподходящий эталон замечаний для контрольного проекта")
        check_expected_blockers(actual_blockers, expected_blockers["blockers"])
    elif actual_blockers:
        raise RuntimeError(
            "контрольный выпуск заблокирован: "
            + json.dumps(actual_blockers, ensure_ascii=False, sort_keys=True)
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
        "verification_mode": "expected_blocked" if expected_blockers else "release_ready",
        "release_ready": quality.can_release,
        "blocker_details": actual_blockers,
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
    parser.add_argument(
        "--expected-blockers", type=Path,
        help="точный отрицательный эталон; успешная проверка не разрешает выпуск",
    )
    args = parser.parse_args()
    manifest = verify_control_release(
        args.source.resolve(),
        args.output.resolve(),
        expected_blockers=(
            json.loads(args.expected_blockers.read_text(encoding="utf-8"))
            if args.expected_blockers else None
        ),
    )
    print(
        ("Регрессия неполного примера (НЕ допуск к выпуску): "
         if manifest["verification_mode"] == "expected_blocked" else "Quality gate: ")
        +
        f"{len(manifest['documents'])} PDF, "
        f"статус {manifest['quality']['state']}, "
        f"блокеры {manifest['quality']['blocking_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
