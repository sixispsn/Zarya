"""Единая production-точка выпуска принципиальной схемы К1/К2.

Сервис намеренно не переключается на старый рендерер и не достраивает
отсутствующие элементы. Полный многостраничный PDF выпускается только из
прошедшего топологическую проверку реестра. При нехватке исходных данных
создаётся отдельный лист статуса без труб и фасонных частей.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from html import escape
from pathlib import Path
from textwrap import wrap

from app.pz.project import Project
from app.pz.wastewater_building_drafting import (
    generate_wastewater_building_pdf_from_project,
)
from app.pz.wastewater_project_inputs import (
    WastewaterBuildingProjectInputs,
    resolve_wastewater_building_project_inputs,
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


def generate_wastewater_scheme(
    project: Project,
    output_path: str,
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

    path = generate_wastewater_building_pdf_from_project(
        output_path,
        release_project,
        floor_height_m=float(project.sewage.floor_height_m),
        roof_kind=project.sewage.roof_kind,
    )
    return WastewaterSchemeGenerationResult(
        output_path=path,
        ready=True,
        backend="registry-building-v2-paginated",
    )
