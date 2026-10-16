"""Production facade for the separate gravity K3 principle scheme."""
from __future__ import annotations

from dataclasses import dataclass, replace
from app.pz.wastewater_status_document import generate_status_pdf
from app.pz.project import Project
from app.pz.wastewater_k3_drafting import generate_wastewater_k3_pdf_from_project
from app.pz.wastewater_k3_project_inputs import (
    WastewaterK3ProjectInputs,
    k3_is_applicable,
    resolve_wastewater_k3_project_inputs,
)


@dataclass(frozen=True)
class WastewaterK3SchemeReadiness:
    applicable: bool
    ready: bool
    project_inputs: WastewaterK3ProjectInputs
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WastewaterK3SchemeGenerationResult:
    output_path: str
    applicable: bool
    ready: bool
    backend: str
    reasons: tuple[str, ...] = ()


def assess_wastewater_k3_scheme_readiness(
    project: Project,
) -> WastewaterK3SchemeReadiness:
    inputs = resolve_wastewater_k3_project_inputs(project)
    reasons = tuple(dict.fromkeys(row for row in inputs.diagnostics if row))
    return WastewaterK3SchemeReadiness(
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
    if cipher and not cipher.endswith(("-ИОС3", ".ИОС3", ".СК", ".К3")):
        cipher += ".ИОС3"
    if cipher and not cipher.endswith((".СК", ".СК.К3")):
        cipher += ".СК"
    if cipher and not cipher.endswith(".К3"):
        cipher += ".К3"
    return replace(
        project,
        document=replace(
            project.document,
            cipher=cipher,
            sheet_title="Принципиальная схема производственной канализации К3",
        ),
    )


def _generate_status_pdf(project: Project, output_path: str, reasons: tuple[str, ...]) -> str:
    return generate_status_pdf(project.document, reasons, output_path, kind="k3")


def generate_wastewater_k3_scheme(
    project: Project,
    output_path: str,
) -> WastewaterK3SchemeGenerationResult:
    """Generate a strict K3 PDF or an honest incompleteness sheet."""
    release_project = _release_project(project)
    readiness = assess_wastewater_k3_scheme_readiness(release_project)
    if not readiness.applicable:
        raise ValueError("К3 не заявлена в исходных данных проекта")
    if not readiness.ready:
        path = _generate_status_pdf(
            release_project,
            output_path,
            readiness.reasons,
        )
        return WastewaterK3SchemeGenerationResult(
            output_path=path,
            applicable=True,
            ready=False,
            backend="k3-incomplete-status",
            reasons=readiness.reasons,
        )
    path = generate_wastewater_k3_pdf_from_project(
        output_path,
        release_project,
    )
    return WastewaterK3SchemeGenerationResult(
        output_path=path,
        applicable=True,
        ready=True,
        backend="registry-k3-gravity-v1-paginated",
    )


__all__ = [
    "WastewaterK3SchemeGenerationResult",
    "WastewaterK3SchemeReadiness",
    "assess_wastewater_k3_scheme_readiness",
    "generate_wastewater_k3_scheme",
    "k3_is_applicable",
]
