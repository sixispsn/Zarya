"""Production facade for the separate internal pressure-sewer scheme."""
from __future__ import annotations

from dataclasses import dataclass, replace
from html import escape
from pathlib import Path
from textwrap import wrap

from app.pz.project import Project
from app.pz.wastewater_building_drafting import (
    _FRAME_BOTTOM,
    _FRAME_LEFT,
    _FRAME_RIGHT,
    _FRAME_TOP,
    _title_block_svg,
)
from app.pz.wastewater_drafting import BLACK, FONT
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


def _status_svg(project: Project, reasons: tuple[str, ...]) -> str:
    lines: list[str] = []
    for index, reason in enumerate(reasons[:18], start=1):
        parts = wrap(reason, width=118) or [reason]
        lines.append(f"{index}. {parts[0]}")
        lines.extend(f"   {part}" for part in parts[1:])
    if len(reasons) > 18:
        lines.append(f"… ещё замечаний: {len(reasons) - 18}")
    rows = "".join(
        f'<text x="190" y="{530 + index * 40}" font-family="{FONT}" '
        f'font-size="18">{escape(line)}</text>'
        for index, line in enumerate(lines)
    )
    return "".join((
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        'viewBox="0 0 2800 1980">',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="190" y="190" font-family="{FONT}" font-size="21" '
        'font-weight="bold">ИОС3 · НАПОРНАЯ КАНАЛИЗАЦИЯ · КОНТРОЛЬ ДАННЫХ</text>',
        f'<text x="190" y="300" font-family="{FONT}" font-size="43" '
        'font-weight="bold">СХЕМА НЕ СФОРМИРОВАНА</text>',
        f'<text x="190" y="365" font-family="{FONT}" font-size="21">'
        'Генератор не подбирает условный насос и не достраивает напорную сеть.</text>',
        f'<text x="190" y="420" font-family="{FONT}" font-size="17">'
        f'{escape(project.document.object_name or "Объект не указан")}</text>',
        rows,
        f'<text x="190" y="1690" font-family="{FONT}" font-size="17">'
        'После заполнения реестра будут выпущены схема и лист рабочей точки.</text>',
        f'<text x="190" y="1730" font-family="{FONT}" font-size="15">'
        'СП 30.13330.2020, пп. 18.31–18.32 · ГОСТ Р 21.620-2023</text>',
        _title_block_svg(
            project.document,
            sheet_no=1,
            sheet_total=1,
            title="Контроль данных напорной канализации",
            system_label="К1н / К3н",
        ),
        '</svg>',
    ))


def _generate_status_pdf(project: Project, output_path: str, reasons: tuple[str, ...]) -> str:
    import cairosvg

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(
        bytestring=_status_svg(project, reasons).encode("utf-8"),
        write_to=str(path),
    )
    return str(path)


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
