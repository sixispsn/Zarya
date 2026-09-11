"""Единая production-точка выпуска принципиальной схемы К1/К2.

Сервис намеренно не переключается на старый рендерер и не достраивает
отсутствующие элементы. Полный многостраничный PDF выпускается только из
прошедшего топологическую проверку реестра. При нехватке исходных данных
создаётся отдельный лист статуса без труб и фасонных частей.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from html import escape
from io import BytesIO
from pathlib import Path
from textwrap import wrap

from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.project import Project
from app.pz.wastewater_building_drafting import (
    audit_confirmed_architecture_basement_svgs,
    build_confirmed_architecture_basement_svgs,
    build_wastewater_building_assembly,
    generate_wastewater_building_pdf_from_project,
)
from app.pz.wastewater_project_inputs import (
    WastewaterBuildingProjectInputs,
    resolve_wastewater_building_project_inputs,
)
from app.pz.wastewater_layout import (
    WastewaterLayoutMode,
    WastewaterSchemeLayout,
    audit_wastewater_layout,
)


@dataclass(frozen=True)
class WastewaterSchemeReadiness:
    ready: bool
    project_inputs: WastewaterBuildingProjectInputs
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WastewaterSchemeGenerationResult:
    output_path: str
    ready: bool
    backend: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfirmedArchitectureBasementReadiness:
    ready: bool
    riser_axis_ratio_by_id: tuple[tuple[str, float], ...]
    missing_riser_ids: tuple[str, ...]
    reasons: tuple[str, ...]


def assess_confirmed_architecture_basement_readiness(
    layout: WastewaterSchemeLayout,
    project_inputs: WastewaterBuildingProjectInputs,
) -> ConfirmedArchitectureBasementReadiness:
    """Resolve the lowest confirmed AR axis for every K1/K2 riser."""
    expected_ids = {
        row.stack.riser_id for row in project_inputs.k1_risers
    } | {
        row.riser_id for row in project_inputs.k2_risers
    }
    reasons: list[str] = []
    if not layout.spaces:
        reasons.append(
            "Для привязки подвала нужны подтверждённые границы помещений по разрезу АР."
        )
        return ConfirmedArchitectureBasementReadiness(
            False,
            (),
            tuple(sorted(expected_ids)),
            tuple(reasons),
        )
    source_left = min(row.frame.x for row in layout.spaces)
    source_right = max(row.frame.x2 for row in layout.spaces)
    if source_right - source_left <= 0.1:
        reasons.append("Ширина подтверждённого архитектурного разреза равна нулю.")
        return ConfirmedArchitectureBasementReadiness(
            False,
            (),
            tuple(sorted(expected_ids)),
            tuple(reasons),
        )

    axis_ratios: dict[str, float] = {}
    for riser_id in sorted(expected_ids):
        route = next(
            (
                row for row in layout.routes
                if row.section_id == riser_id and len(row.points) >= 2
            ),
            None,
        )
        if route is None:
            continue
        axis_ratios[riser_id] = (
            route.points[-1].x - source_left
        ) / (source_right - source_left)
    missing = tuple(sorted(expected_ids - set(axis_ratios)))
    if missing:
        reasons.append(
            "Подвал и выпуски не добавлены: подтвердите оси стояков на нижнем "
            "показанном этаже: " + ", ".join(missing) + "."
        )
    outside = tuple(sorted(
        riser_id
        for riser_id, ratio in axis_ratios.items()
        if not 0.0 <= ratio <= 1.0
    ))
    if outside:
        reasons.append(
            "Оси стояков вышли за подтверждённый контур разреза: "
            + ", ".join(outside) + "."
        )
    ready = bool(expected_ids) and not missing and not outside
    return ConfirmedArchitectureBasementReadiness(
        ready,
        tuple(sorted(axis_ratios.items())),
        missing,
        tuple(reasons),
    )


def assess_wastewater_scheme_readiness(
    project: Project,
) -> WastewaterSchemeReadiness:
    """Проверить достаточность точных данных до запуска отрисовщика."""
    inputs = resolve_wastewater_building_project_inputs(project)
    reasons = list(inputs.diagnostics)
    if project.sewage.floor_height_m is None:
        reasons.append(
            "Не задана точная высота типового этажа по архитектурным данным."
        )
    elif project.sewage.floor_height_m <= 0:
        reasons.append("Высота типового этажа должна быть положительной.")
    if project.sewage.roof_kind == "unknown":
        reasons.append(
            "Не подтверждён вид и доступность кровли для выпуска вентиляции."
        )
    # К3 выпускается самостоятельным каноническим листом. Наличие её строк в
    # общем реестре не должно блокировать уже подтверждённую схему К1/К2.
    unique = tuple(dict.fromkeys(reason for reason in reasons if reason))
    return WastewaterSchemeReadiness(
        ready=inputs.complete and not unique,
        project_inputs=inputs,
        reasons=unique,
    )


def _status_svg(project: Project, reasons: tuple[str, ...]) -> str:
    lines: list[str] = []
    for index, reason in enumerate(reasons[:14], start=1):
        wrapped = wrap(reason, width=105) or [reason]
        lines.append(f"{index}. {wrapped[0]}")
        lines.extend(f"   {part}" for part in wrapped[1:])
    if len(reasons) > 14:
        lines.append(f"… ещё замечаний: {len(reasons) - 14}")
    text_rows = "".join(
        f'<text x="74" y="{190 + index * 21}" font-size="13">'
        f'{escape(line)}</text>'
        for index, line in enumerate(lines)
    )
    object_name = project.document.object_name or "Объект не указан"
    cipher = project.document.cipher or "Шифр не указан"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" '
        'height="594mm" viewBox="0 0 841 594">'
        '<rect width="841" height="594" fill="white"/>'
        '<rect x="20" y="15" width="816" height="574" fill="none" '
        'stroke="#000" stroke-width="0.7"/>'
        '<g font-family="DejaVu Sans, sans-serif" fill="#111">'
        '<text x="56" y="65" font-size="12" font-weight="bold">'
        'ИОС3 · КОНТРОЛЬ ПОЛНОТЫ ИСХОДНЫХ ДАННЫХ</text>'
        '<text x="56" y="112" font-size="25" font-weight="bold">'
        'ПРИНЦИПИАЛЬНАЯ СХЕМА НЕ СФОРМИРОВАНА</text>'
        '<text x="56" y="145" font-size="14">'
        'Рендерер не добавляет условные трубы, прочистки, переходы и отметки.</text>'
        f'<text x="56" y="168" font-size="12">{escape(object_name)} · '
        f'{escape(cipher)}</text>'
        + text_rows
        + '<text x="56" y="548" font-size="11">После заполнения реестра '
        'будет выпущен многостраничный векторный PDF: этажи и нижние узлы.</text>'
        '<text x="56" y="571" font-size="10">ГОСТ Р 21.620-2023 · '
        'внутренние К1/К2 · без подмены стадии Р</text>'
        '</g></svg>'
    )


def _generate_incomplete_status_pdf(
    project: Project,
    output_path: str,
    reasons: tuple[str, ...],
) -> str:
    ensure_drafting_font_registered()
    import cairosvg

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(
        bytestring=_status_svg(project, reasons).encode("utf-8"),
        write_to=str(path),
    )
    return str(path)


def _release_project(project: Project) -> Project:
    """Дать графической части самостоятельный шифр ИОС3.СК."""
    cipher = project.document.cipher or ""
    for marker in ("-ИОС2", ".ИОС2"):
        if cipher.endswith(marker):
            cipher = cipher[: -len(marker)] + marker[:-1] + "3"
            break
    if cipher and not cipher.endswith(("-ИОС3", ".ИОС3", ".СК")):
        cipher += ".ИОС3"
    if cipher and not cipher.endswith(".СК"):
        cipher += ".СК"
    return replace(
        project,
        document=replace(
            project.document,
            cipher=cipher,
            sheet_title="Принципиальная схема внутренних систем К1 и К2",
        ),
    )


def _write_svg_pages(output_path: str, svgs: tuple[str, ...]) -> str:
    ensure_drafting_font_registered()
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for svg in svgs:
        page_pdf = BytesIO()
        cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=page_pdf)
        page_pdf.seek(0)
        writer.append(PdfReader(page_pdf))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer.write(stream)
    return str(path)


def generate_wastewater_scheme(
    project: Project,
    output_path: str,
    *,
    confirmed_layout: WastewaterSchemeLayout | None = None,
) -> WastewaterSchemeGenerationResult:
    """Выпустить канонический PDF либо честный лист неполноты.

    Ошибка графического аудита готовой схемы не перехватывается и не ведёт к
    fallback: такой дефект должен остановить выпуск и тесты.
    """
    readiness = assess_wastewater_scheme_readiness(project)
    release_project = _release_project(project)
    if not readiness.ready:
        path = _generate_incomplete_status_pdf(
            release_project,
            output_path,
            readiness.reasons,
        )
        return WastewaterSchemeGenerationResult(
            output_path=path,
            ready=False,
            backend="incomplete-status",
            reasons=readiness.reasons,
        )

    if confirmed_layout is not None:
        if confirmed_layout.mode != WastewaterLayoutMode.CONFIRMED_ARCHITECTURE:
            raise ValueError(
                "для выпуска по АР требуется подтверждённая архитектурная компоновка"
            )
        layout_audit = audit_wastewater_layout(project, confirmed_layout)
        if not layout_audit.ready:
            raise ValueError(
                "подтверждённая архитектурная компоновка не прошла аудит: "
                + "; ".join(row.message for row in layout_audit.errors)
            )
        from app.pz.wastewater_structure_renderer import (
            WastewaterStructureScope,
            build_wastewater_structure_svg,
            generate_wastewater_structure_pdf,
        )

        basement_readiness = assess_confirmed_architecture_basement_readiness(
            confirmed_layout,
            readiness.project_inputs,
        )
        if basement_readiness.ready:
            assembly = build_wastewater_building_assembly(
                readiness.project_inputs,
                floor_height_m=float(project.sewage.floor_height_m),
                roof_kind=project.sewage.roof_kind,
                document=release_project.document,
            )
            axis_ratios = dict(basement_readiness.riser_axis_ratio_by_id)
            basement_page_count = (
                (len(assembly.project_inputs.k1_risers) + 1) // 2
                + (len(assembly.project_inputs.k2_risers) + 1) // 2
            )
            sheet_total = 1 + basement_page_count
            basement_svgs = build_confirmed_architecture_basement_svgs(
                assembly,
                riser_axis_ratio_by_id=axis_ratios,
                first_sheet_no=2,
                sheet_total=sheet_total,
            )
            findings = audit_confirmed_architecture_basement_svgs(
                assembly,
                basement_svgs,
                riser_axis_ratio_by_id=axis_ratios,
            )
            if findings:
                raise ValueError(
                    "аудит подвала по подтверждённым осям АР не пройден: "
                    + "; ".join(findings)
                )
            first_svg = build_wastewater_structure_svg(
                release_project,
                confirmed_layout,
                scope=WastewaterStructureScope.FULL_FLOOR_STACK,
                sheet_no=1,
                sheet_total=sheet_total,
            )
            path = _write_svg_pages(
                output_path,
                (first_svg,) + basement_svgs,
            )
            return WastewaterSchemeGenerationResult(
                output_path=path,
                ready=True,
                backend="confirmed-architecture-layout-v2-basement",
            )

        path = generate_wastewater_structure_pdf(
            release_project,
            confirmed_layout,
            output_path,
            scope=WastewaterStructureScope.FULL_FLOOR_STACK,
        )
        return WastewaterSchemeGenerationResult(
            output_path=path,
            ready=True,
            backend="confirmed-architecture-layout-v1",
            reasons=basement_readiness.reasons,
        )

    path = generate_wastewater_building_pdf_from_project(
        output_path,
        release_project,
        floor_height_m=float(project.sewage.floor_height_m),
        roof_kind=project.sewage.roof_kind,
    )
    return WastewaterSchemeGenerationResult(
        output_path=path,
        ready=True,
        backend=(
            "registry-building-v3-residential-appendix-v"
            if project.building.purpose.value == "residential"
            else "registry-building-v2-paginated"
        ),
    )
