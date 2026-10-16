"""Single production dispatcher for the wastewater graphic package.

Every caller - the complete IOS package and the architecture workspace - goes
through this module. A saved representative presentation may be drawn when no
network has been specified. It is always preliminary, never a release-ready
substitute for an incomplete/invalid engineering network.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.pz.project import Project
from app.pz.residential_concept_section import ResidentialConceptSection, FIXTURES
from app.pz.section_storm import SectionStormInput
from app.pz.section_main_hydraulics import current_k1_total, current_k1_hourly
from app.pz.wastewater_layout import WastewaterSchemeLayout
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
    presentation: str = "confirmed"
    available: bool = True


@dataclass(frozen=True)
class WastewaterGraphicGenerationResult:
    key: WastewaterGraphicExportKey
    output_path: str
    ready: bool
    backend: str
    reasons: tuple[str, ...] = ()


REPRESENTATIVE_NOTICE = (
    "Условный разрез. Диаметры магистралей, уклоны, отметки выпусков и "
    "решение вентиляции требуют подтверждения; не для подсчёта длин."
)


def representative_section_model(project: Project) -> ResidentialConceptSection:
    """Read CURRENT values, not a frozen Studio snapshot of the building."""
    choice = project.sewage.presentation
    if choice is None:
        raise ValueError("Представление разрезом не выбрано")
    codes = {code for code, _ in project.consumer_groups}
    missing = []
    if len(codes) != 1 or not codes <= FIXTURES.keys():
        missing.append("единый состав приборов жилой части")
    if not project.sewage.floor_height_m:
        missing.append("высота этажа")
    if choice.basement_kind == "unknown":
        missing.append("наличие подвала / техподполья")
    elif choice.basement_kind != "none" and project.sewage.basement_floor_elevation_m is None:
        missing.append("отметка пола подвала / техподполья")
    if project.sewage.roof_kind not in {"single_slope", "gable", "flat_accessible", "flat_non_accessible"}:
        missing.append("вид кровли / разрез АР для сложной кровли")
    if choice.drainage == "unknown":
        missing.append("внутренний или наружный водосток")
    if (choice.basement_kind == "none" and project.building.floors_below) or (
        choice.basement_kind in {"basement", "subfloor"} and not project.building.floors_below
    ):
        missing.append("согласование подземной части с конфигурацией здания")
    if missing:
        raise ValueError("Для разреза уточните: " + ", ".join(missing))
    model = ResidentialConceptSection(
        floors=project.building.floors_above,
        floor_height_m=project.sewage.floor_height_m,
        basement_kind=choice.basement_kind,
        basement_floor_m=project.sewage.basement_floor_elevation_m if choice.basement_kind != "none" else None,
        roof_kind=project.sewage.roof_kind, drainage=choice.drainage,
        consumer_code=next(iter(codes)), title=project.document.object_name or "Жилой дом",
        k1=choice.k1, k2=choice.k2, fan=choice.fan,
        funnel_heated=choice.funnel_heated, document=project.document,
        zero_absolute_m=choice.zero_absolute_m, zero_source_ref=choice.zero_source_ref,
        storm=SectionStormInput.from_project(project.storm),
        k1_total_flow_lps=current_k1_total(project.consumer_groups, project.sewage_max_fixture_lps),
        k1_hour_max_m3h=current_k1_hourly(project.consumer_groups),
        k1_fixture_max_lps=project.sewage_max_fixture_lps,
    )
    model.validate()
    return model


def _k1_k2_export(project: Project) -> WastewaterGraphicExport:
    strict = assess_wastewater_scheme_readiness(project)
    # Never conceal supplied network errors with a nicer generic picture.
    has_network = bool(project.sewage.pipes or project.sewage.elements or project.sewage.risers)
    if strict.ready or has_network or project.sewage.presentation is None:
        return WastewaterGraphicExport(
            key="k1-k2", filename="Схема_К1_К2.pdf", title="К1/К2",
            applicable=True, ready=strict.ready, reasons=strict.reasons,
            requires_architecture_binding=True,
        )
    try:
        model = representative_section_model(project)
    except ValueError as exc:
        return WastewaterGraphicExport(
            key="k1-k2", filename="Схема_К1_К2_предварительная.pdf",
            title="Принципиальный разрез ИОС3", applicable=True, ready=False,
            reasons=(str(exc),), presentation="representative", available=False,
        )
    return WastewaterGraphicExport(
        key="k1-k2", filename="Схема_К1_К2_предварительная.pdf",
        title="Принципиальный разрез ИОС3", applicable=True, ready=False,
        reasons=(model.design_notice,), presentation="representative",
    )


def representative_document_model(project: Project) -> ResidentialConceptSection | None:
    """PZ/spec use the SAME active presentation as the PDF, never stale choices.

    No surveyed pipes, hydraulic certification or quantities are inferred.
    A supplied engineering network takes precedence over presentation data.
    """
    row = _k1_k2_export(project)
    if row.presentation == "representative" and row.available:
        return representative_section_model(project)
    return None


def assess_wastewater_graphic_exports(
    project: Project,
) -> tuple[WastewaterGraphicExport, ...]:
    """Describe every canonical graphic export without creating files."""
    k3 = assess_wastewater_k3_scheme_readiness(project)
    pressure = assess_wastewater_pressure_scheme_readiness(project)
    return (
        _k1_k2_export(project),
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
    *,
    confirmed_layout: WastewaterSchemeLayout | None = None,
) -> WastewaterGraphicGenerationResult:
    """Generate one canonical PDF through a closed, explicit dispatch table."""
    row = wastewater_graphic_export(project, key)
    if not row.available:
        raise ValueError("; ".join(row.reasons))
    if row.key == "k1-k2":
        if row.presentation == "representative":
            if confirmed_layout is not None:
                raise ValueError("Подтверждённая компоновка не применяется к условному разрезу")
            from app.pz.residential_concept_section import generate_concept_section_pdf
            generate_concept_section_pdf(Path(output_path), representative_section_model(project))
            return WastewaterGraphicGenerationResult(
                key=row.key, output_path=str(output_path), ready=False,
                backend="representative-section", reasons=row.reasons,
            )
        result = generate_wastewater_scheme(
            project,
            output_path,
            confirmed_layout=confirmed_layout,
        )
    elif row.key == "k3":
        if confirmed_layout is not None:
            raise ValueError("подтверждённая компоновка К1/К2 неприменима к К3")
        result = generate_wastewater_k3_scheme(project, output_path)
    elif row.key == "pressure":
        if confirmed_layout is not None:
            raise ValueError(
                "подтверждённая самотечная компоновка неприменима к напорной схеме"
            )
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
