"""Control report of a saved typological model, not AR or an engineering scheme.

Only presentation and pagination live here. Aggregation and handoff use the
existing model; no pipe geometry, hydraulic result or project stage is inferred.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html import escape
from io import BytesIO
import os
from pathlib import Path
import tempfile
from typing import Any

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table,
    TableStyle,
)
from reportlab.platypus.doctemplate import LayoutError

from app.architecture.engineering_handoff import build_engineering_handoff
from app.architecture.program_store import BuildingProgramDraft
from app.pz.drafting_font import DRAFTING_FONT_PATH


PAGE_WIDTH_MM = 420.0
PAGE_HEIGHT_MM = 297.0
_ROWS_PER_REGISTER_PAGE = 18
_FONT = "BuildingProgramReport"
_WIDTH = 384 * mm


class ProgramReportLayoutError(ValueError):
    """A complete readable report cannot be laid out; old output is retained."""


@dataclass(frozen=True)
class _SourceGroup:
    room_label: str
    fixture_label: str
    service_ports: tuple[str, ...]
    level_ids: tuple[str, ...]
    count: int


def _level_label(level_id: str, floor_number: int | None, role: str) -> str:
    if role == "roof":
        return "Кровля"
    if floor_number is None:
        return level_id
    if floor_number < 0:
        return f"Подземный {abs(floor_number)}"
    return f"Этаж {floor_number}"


def _level_span(draft: BuildingProgramDraft, level_ids: tuple[str, ...]) -> str:
    level_map = {row.level_id: row for row in draft.topology.levels}
    levels = [level_map[level_id] for level_id in level_ids]
    positive = sorted(
        row.floor_number
        for row in levels
        if row.floor_number is not None and row.floor_number > 0
    )
    other = [
        _level_label(row.level_id, row.floor_number, row.role)
        for row in levels
        if row.floor_number is None or row.floor_number <= 0
    ]
    parts: list[str] = []
    if positive:
        if positive == list(range(positive[0], positive[-1] + 1)):
            parts.append(
                f"Этажи {positive[0]}-{positive[-1]}"
                if len(positive) > 1
                else f"Этаж {positive[0]}"
            )
        else:
            parts.append("Этажи " + ", ".join(str(row) for row in positive))
    parts.extend(other)
    return "; ".join(parts) or "-"


def _source_groups(draft: BuildingProgramDraft) -> tuple[_SourceGroup, ...]:
    rooms = {row.room_id: row for row in draft.topology.rooms}
    grouped: dict[
        tuple[str, str, tuple[str, ...]],
        tuple[set[str], int],
    ] = {}
    for fixture in draft.topology.fixtures:
        room = rooms[fixture.room_id]
        key = (room.label, fixture.label, fixture.service_ports)
        level_ids, count = grouped.setdefault(key, (set(), 0))
        level_ids.add(room.level_id)
        grouped[key] = (level_ids, count + 1)
    return tuple(
        _SourceGroup(
            room_label=key[0],
            fixture_label=key[1],
            service_ports=key[2],
            level_ids=tuple(sorted(value[0])),
            count=value[1],
        )
        for key, value in sorted(grouped.items())
    )


def _role_label(role: str) -> str:
    return {
        "roof": "кровля",
        "residential": "жилой",
        "underground": "подземный",
    }.get(role, role)



def _register_rows(draft: BuildingProgramDraft) -> list[list[str]]:
    topology = draft.topology
    rooms_by_level = Counter(row.level_id for row in topology.rooms)
    apartments_by_floor = Counter(row.floor_number for row in topology.apartments)
    fixture_level: dict[str, str] = {
        row.room_id: row.level_id for row in topology.rooms
    }
    fixtures_by_level = Counter(
        fixture_level[row.room_id] for row in topology.fixtures
    )
    system_by_level: dict[str, Counter[str]] = {}
    for fixture in topology.fixtures:
        level_id = fixture_level[fixture.room_id]
        target = system_by_level.setdefault(level_id, Counter())
        target.update(fixture.service_ports)
    shafts_by_floor: Counter[int] = Counter()
    for shaft in topology.sanitary_shafts:
        shafts_by_floor.update(shaft.served_floors)


    rows = []
    for level in topology.levels:
        systems = system_by_level.get(level.level_id, Counter())
        rows.append([
            _level_label(level.level_id, level.floor_number, level.role),
            _role_label(level.role),
            str(apartments_by_floor[level.floor_number] if level.floor_number is not None else 0),
            str(rooms_by_level[level.level_id]),
            str(fixtures_by_level[level.level_id]),
            str(shafts_by_floor[level.floor_number] if level.floor_number is not None else 0),
            *(str(systems[system]) for system in ("V1", "T3", "K1", "K2", "K3")),
        ])
    return rows


def _paragraph(value: object, *, size: float = 11, heading: bool = False) -> Paragraph:
    return Paragraph(escape(str(value)), ParagraphStyle(
        "program", fontName=_FONT, fontSize=size, leading=size * 1.3,
        spaceAfter=3 * mm if heading else 1.2 * mm,
        keepWithNext=heading, splitLongWords=True,
    ))


def _table(headers: Sequence[object], rows: Sequence[Sequence[object]], widths: Sequence[float]) -> Table:
    data = [[_paragraph(value) for value in row] for row in [headers, *rows]]
    result = Table(data, colWidths=[width * mm for width in widths],
                   repeatRows=1, hAlign="LEFT", splitByRow=1, splitInRow=0)
    result.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#7b8591")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf0f3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4 * mm),
    ]))
    return result


class _NumberedCanvas(Canvas):
    """Add total page count without rebuilding or recalculating the model."""

    # ReportLab's page-state reset exists at runtime but is absent from its stubs.
    _startPage: Callable[[], None]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont(_FONT, 10)
            self.drawString(18 * mm, 12 * mm,
                            "Контроль типологической основы. Не является планом АР или схемой инженерных сетей.")
            self.drawRightString(402 * mm, 12 * mm, f"Лист {self.getPageNumber()} из {total}")
            super().showPage()
        super().save()


def generate_building_program_report_pdf(
    draft: BuildingProgramDraft,
    output_path: str | Path,
) -> str:
    """Render all groups/questions and register rows; publish atomically."""
    if _FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_FONT, str(DRAFTING_FONT_PATH)))
    topology = draft.topology
    handoff = build_engineering_handoff(topology, basis_confirmed=draft.basis_confirmed)
    story = [
        _paragraph("КОНТРОЛЬНЫЙ ЛИСТ ТИПОЛОГИЧЕСКОЙ МОДЕЛИ", size=18, heading=True),
        _paragraph(draft.title, size=15),
        _paragraph(f"ID {draft.model_id} / topology {draft.topology_sha256}"),
        _paragraph("ОСНОВА ПОДТВЕРЖДЕНА" if draft.basis_confirmed else "ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ"),
        _paragraph(f"Основание данных: {topology.source_ref}"),
        _table(["УРОВНЕЙ", "КВАРТИР", "ПОМЕЩЕНИЙ", "ПРИБОРОВ", "ШАХТ"], [[
            len(topology.levels), len(topology.apartments), len(topology.rooms),
            len(topology.fixtures), len(topology.sanitary_shafts),
        ]], [76.8] * 5),
        Spacer(1, 3 * mm),
        _paragraph("ФУНКЦИОНАЛЬНЫЕ СВЯЗИ", size=14, heading=True),
        _paragraph("Каждая строка взята из реестра модели; линии труб здесь намеренно отсутствуют."),
    ]
    groups = _source_groups(draft)
    if groups:
        story.append(_table(["ПОМЕЩЕНИЕ -> ПРИБОР", "УРОВНИ", "КОЛ.", "ПОРТЫ"], [
            [f"{group.room_label} -> {group.fixture_label}", _level_span(draft, group.level_ids),
             group.count, ", ".join(group.service_ports)] for group in groups
        ], [190, 100, 24, 70]))
    else:
        story.append(_paragraph("Зарегистрированные связи помещений и приборов отсутствуют."))
    story.extend([Spacer(1, 3 * mm), _paragraph("ВОРОТА ПЕРЕДАЧИ", size=14, heading=True)])
    for status in handoff.systems:
        state = "состав готов" if status.quantities_ready else f"блокировок: {len(status.quantity_blockers)}"
        story.append(_paragraph(
            f"{status.system}: источников: {status.fixture_source_count}; {state}; схема: ждёт геометрию АР"
        ))
    story.extend([Spacer(1, 3 * mm), _paragraph("НЕЗАКРЫТЫЕ ВОПРОСЫ", size=14, heading=True)])
    for index, question in enumerate(topology.questions, 1):
        story.append(_paragraph(f"{index}. {question.prompt}"))
    if not topology.questions:
        story.append(_paragraph(
            "Типологические вопросы закрыты. Геометрия АР по-прежнему обязательна для схем."
        ))
    rows = _register_rows(draft)
    for offset in range(0, len(rows), _ROWS_PER_REGISTER_PAGE):
        chunk = rows[offset:offset + _ROWS_PER_REGISTER_PAGE]
        story.extend([
            PageBreak(),
            _paragraph("РЕЕСТР УРОВНЕЙ И ИНЖЕНЕРНЫХ ИСТОЧНИКОВ", size=18, heading=True),
            _paragraph(draft.title, size=15),
            _paragraph(f"Реестр уровней {offset + 1}-{offset + len(chunk)} из {len(rows)}"),
            _table(["УРОВЕНЬ", "НАЗНАЧЕНИЕ", "КВ.", "ПОМ.", "ПРИБ.", "ШАХТ",
                    "В1", "Т3", "К1", "К2", "К3"], chunk, [64, 68] + [28] * 9),
            Spacer(1, 3 * mm),
            _paragraph("Числа в колонках систем - количество приборов с соответствующим сервисным портом, а не расход и не число труб."),
        ])
    output = BytesIO()
    document = BaseDocTemplate(output, pagesize=(PAGE_WIDTH_MM * mm, PAGE_HEIGHT_MM * mm),
                               title="Контроль типологической модели", author="ЗАРЯ")
    frame = Frame(18 * mm, 22 * mm, _WIDTH, 260 * mm,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    document.addPageTemplates(PageTemplate(id="report", frames=[frame]))
    try:
        document.build(story, canvasmaker=_NumberedCanvas)
    except LayoutError as exc:
        raise ProgramReportLayoutError(
            "Контрольный отчёт: строка таблицы не помещается целиком на листе. "
            "Проверьте длину полей; прежний PDF сохранён."
        ) from exc
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".building-report-",
                                         suffix=".pdf", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(output.getvalue())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(path)


__all__ = ["PAGE_HEIGHT_MM", "PAGE_WIDTH_MM", "ProgramReportLayoutError",
           "generate_building_program_report_pdf"]
