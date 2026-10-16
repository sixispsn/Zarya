"""Production facade for the separate internal pressure-sewer scheme."""
from __future__ import annotations

from dataclasses import dataclass, replace
from app.pz.wastewater_status_document import generate_status_pdf
from app.pz.project import Project
from app.pz.wastewater_pressure_drafting import (
    generate_wastewater_pressure_pdf_from_project,
)
from app.pz.wastewater_pressure_project_inputs import (
    WastewaterPressureProjectInputs,
    pressure_sewer_is_applicable,
    resolve_wastewater_pressure_project_inputs,
)


@dataclass(frozen=True)
class WastewaterPressureSchemeReadiness:
    applicable: bool
    ready: bool
    project_inputs: WastewaterPressureProjectInputs
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WastewaterPressureSchemeGenerationResult:
    output_path: str
    applicable: bool
    ready: bool
    backend: str
    reasons: tuple[str, ...] = ()


def assess_wastewater_pressure_scheme_readiness(
    project: Project,
) -> WastewaterPressureSchemeReadiness:
    inputs = resolve_wastewater_pressure_project_inputs(project)
    reasons = tuple(dict.fromkeys(row for row in inputs.diagnostics if row))
    return WastewaterPressureSchemeReadiness(
        applicable=inputs.applicable,
        ready=inputs.complete,
        project_inputs=inputs,
        reasons=reasons,
    )


def _release_project(project: Project) -> Project:
    cipher = project.document.cipher or ""
    for marker in ("-ИОС2", ".ИОС2"):
        if cipher.endswith(marker):
            cipher = cipher[: -len(marker)] + marker[:-1] + "3"
            break
    if cipher and not cipher.endswith(("-ИОС3", ".ИОС3")):
        cipher += ".ИОС3"
    if cipher and not cipher.endswith(".СК.НК"):
        cipher += ".СК.НК"
    system = project.sewage.pump_system.replace("K", "К") or "К1/К3"
    return replace(
        project,
        document=replace(
            project.document,
            cipher=cipher,
            sheet_title=f"Напорная канализация {system}н",
        ),
    )


def _generate_status_pdf(project: Project, output_path: str, reasons: tuple[str, ...]) -> str:
    return generate_status_pdf(project.document, reasons, output_path, kind="pressure")


def generate_wastewater_pressure_scheme(
    project: Project,
    output_path: str,
) -> WastewaterPressureSchemeGenerationResult:
    release_project = _release_project(project)
    readiness = assess_wastewater_pressure_scheme_readiness(release_project)
    if not readiness.applicable:
        raise ValueError("Напорная К1/К3 не заявлена в исходных данных проекта")
    if not readiness.ready:
        path = _generate_status_pdf(release_project, output_path, readiness.reasons)
        return WastewaterPressureSchemeGenerationResult(
            output_path=path,
            applicable=True,
            ready=False,
            backend="pressure-sewer-incomplete-status",
            reasons=readiness.reasons,
        )
    path = generate_wastewater_pressure_pdf_from_project(output_path, release_project)
    return WastewaterPressureSchemeGenerationResult(
        output_path=path,
        applicable=True,
        ready=True,
        backend="pressure-sewer-confirmed-curve-v1",
    )


__all__ = [
    "WastewaterPressureSchemeGenerationResult",
    "WastewaterPressureSchemeReadiness",
    "assess_wastewater_pressure_scheme_readiness",
    "generate_wastewater_pressure_scheme",
    "pressure_sewer_is_applicable",
]
