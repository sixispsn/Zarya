"""Single production dispatcher for the wastewater graphic package.

Every caller - the complete IOS package and the architecture workspace - goes
through this module.  The dispatcher has no legacy fallback and never invents
missing topology: each underlying canonical service either draws its confirmed
registry or emits its own incompleteness sheet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.pz.project import Project
from app.pz.wastewater_k3_scheme_service import (
    assess_wastewater_k3_scheme_readiness,
    generate_wastewater_k3_scheme,
)
from app.pz.wastewater_pressure_scheme_service import (
    assess_wastewater_pressure_scheme_readiness,
    generate_wastewater_pressure_scheme,
)
from app.pz.wastewater_scheme_service import (
    assess_wastewater_scheme_readiness,
    generate_wastewater_scheme,
)


WastewaterGraphicExportKey = Literal["k1-k2", "k3", "pressure"]


@dataclass(frozen=True)
class WastewaterGraphicExport:
    key: WastewaterGraphicExportKey
    filename: str
    title: str
    applicable: bool
    ready: bool
    reasons: tuple[str, ...] = ()
    requires_architecture_binding: bool = False


@dataclass(frozen=True)
class WastewaterGraphicGenerationResult:
    key: WastewaterGraphicExportKey
    output_path: str
    ready: bool
    backend: str
    reasons: tuple[str, ...] = ()


def assess_wastewater_graphic_exports(
    project: Project,
) -> tuple[WastewaterGraphicExport, ...]:
    """Describe every canonical graphic export without creating files."""
    k1_k2 = assess_wastewater_scheme_readiness(project)
    k3 = assess_wastewater_k3_scheme_readiness(project)
    pressure = assess_wastewater_pressure_scheme_readiness(project)
    return (
        WastewaterGraphicExport(
            key="k1-k2",
            filename="Схема_К1_К2.pdf",
            title="К1/К2",
            applicable=True,
            ready=k1_k2.ready,
            reasons=k1_k2.reasons,
            requires_architecture_binding=True,
        ),
        WastewaterGraphicExport(
            key="k3",
            filename="Схема_К3.pdf",
            title="К3",
            applicable=k3.applicable,
            ready=k3.ready,
            reasons=k3.reasons,
        ),
        WastewaterGraphicExport(
            key="pressure",
            filename="Схема_напорной_канализации.pdf",
            title="К1н/К3н",
            applicable=pressure.applicable,
            ready=pressure.ready,
            reasons=pressure.reasons,
        ),
    )


def wastewater_graphic_export(
    project: Project,
    key: WastewaterGraphicExportKey | str,
) -> WastewaterGraphicExport:
    for row in assess_wastewater_graphic_exports(project):
        if row.key == key:
            if not row.applicable:
                raise ValueError(
                    f"Графическая часть {row.title} не заявлена "
                    "в исходных данных проекта."
                )
            return row
    raise ValueError(f"Неизвестный вид графической части: {key}.")


def generate_wastewater_graphic_export(
    project: Project,
    key: WastewaterGraphicExportKey | str,
    output_path: str,
) -> WastewaterGraphicGenerationResult:
    """Generate one canonical PDF through a closed, explicit dispatch table."""
    row = wastewater_graphic_export(project, key)
    if row.key == "k1-k2":
        result = generate_wastewater_scheme(project, output_path)
    elif row.key == "k3":
        result = generate_wastewater_k3_scheme(project, output_path)
    elif row.key == "pressure":
        result = generate_wastewater_pressure_scheme(project, output_path)
    else:  # pragma: no cover - Literal plus the lookup above make this impossible.
        raise AssertionError(f"Unhandled wastewater graphic export: {row.key}")
    return WastewaterGraphicGenerationResult(
        key=row.key,
        output_path=result.output_path,
        ready=result.ready,
        backend=result.backend,
        reasons=result.reasons,
    )


__all__ = [
    "WastewaterGraphicExport",
    "WastewaterGraphicExportKey",
    "WastewaterGraphicGenerationResult",
    "assess_wastewater_graphic_exports",
    "generate_wastewater_graphic_export",
    "wastewater_graphic_export",
]
