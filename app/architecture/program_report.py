"""Visual control report for a saved typological building programme.

The report makes programme relations reviewable before any engineering route is
generated.  It shows only registered levels, rooms, fixtures, service ports and
handoff blockers.  It never draws pipes or substitutes missing AR geometry.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path
import tempfile
from textwrap import wrap

from app.architecture.engineering_handoff import build_engineering_handoff
from app.architecture.program_store import BuildingProgramDraft


PAGE_WIDTH_MM = 420.0
PAGE_HEIGHT_MM = 297.0
_ROWS_PER_REGISTER_PAGE = 18


@dataclass(frozen=True)
class _SourceGroup:
    room_label: str
    fixture_label: str
    service_ports: tuple[str, ...]
    level_ids: tuple[str, ...]
    count: int


def _text(
    value: str,
    *,
    x: float,
    y: float,
    size: float = 3.4,
    weight: int = 400,
    fill: str = "#111625",
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x:g}" y="{y:g}" font-size="{size:g}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">'
        f"{escape(value)}</text>"
    )


def _multiline(
    value: str,
    *,
    x: float,
    y: float,
    width_chars: int,
    size: float = 3.2,
    line_height: float = 4.4,
    weight: int = 400,
    fill: str = "#111625",
    max_lines: int = 3,
) -> str:
    lines = wrap(value, width=max(8, width_chars)) or [value]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .") + "..."
    return "".join(
        _text(
            row,
            x=x,
            y=y + index * line_height,
            size=size,
            weight=weight,
            fill=fill,
        )
        for index, row in enumerate(lines)
    )


def _page_shell(body: str, *, page_number: int, title: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{PAGE_WIDTH_MM:g}mm" height="{PAGE_HEIGHT_MM:g}mm" '
        f'viewBox="0 0 {PAGE_WIDTH_MM:g} {PAGE_HEIGHT_MM:g}">'
        '<rect width="420" height="297" fill="#f7f8fb"/>'
        '<rect x="8" y="8" width="404" height="281" rx="3" fill="#ffffff" '
        'stroke="#a8afbd" stroke-width="0.35"/>'
        '<rect x="8" y="8" width="404" height="25" rx="3" fill="#111625"/>'
        '<rect x="8" y="29" width="404" height="4" fill="#111625"/>'
        '<rect x="8" y="29" width="34" height="4" fill="#ff6b35"/>'
        '<g font-family="DejaVu Sans, Arial, sans-serif">'
        + _text(
            title,
            x=18,
            y=23,
            size=6.4,
            weight=700,
            fill="#ffffff",
        )
        + _text(
            "ZARYA / BUILDING PROGRAM",
            x=402,
            y=22.5,
            size=3.0,
            weight=700,
            fill="#ff9a75",
            anchor="end",
        )
        + body
        + '<line x1="18" y1="278" x2="402" y2="278" '
        'stroke="#d7dbe3" stroke-width="0.3"/>'
        + _text(
            "Контроль типологической основы. Не является планом АР или схемой инженерных сетей.",
            x=18,
            y=284,
            size=2.75,
            fill="#6b7280",
        )
        + _text(
            f"Лист {page_number}",
            x=402,
            y=284,
            size=2.75,
            weight=700,
            fill="#6b7280",
            anchor="end",
        )
        + "</g></svg>"
    )


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


def _status_badge(draft: BuildingProgramDraft) -> str:
    ready = draft.basis_confirmed
    fill = "#dff8f3" if ready else "#fff0e8"
    stroke = "#00a88f" if ready else "#ff6b35"
    label = "ОСНОВА ПОДТВЕРЖДЕНА" if ready else "ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ"
    return (
        f'<rect x="315" y="42" width="87" height="11" rx="5.5" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="0.35"/>'
        + _text(
            label,
            x=358.5,
            y=49.1,
            size=2.65,
            weight=700,
            fill=stroke,
            anchor="middle",
        )
    )


def _overview_page(draft: BuildingProgramDraft) -> str:
    topology = draft.topology
    handoff = build_engineering_handoff(
        topology,
        basis_confirmed=draft.basis_confirmed,
    )
    groups = _source_groups(draft)
    body = (
        _text(draft.title, x=18, y=48, size=5.5, weight=700)
        + _text(
            f"ID {draft.model_id} / topology {draft.topology_sha256[:16]}...",
            x=18,
            y=54,
            size=2.8,
            fill="#6b7280",
        )
        + _status_badge(draft)
    )

    metrics = (
        ("УРОВНЕЙ", len(topology.levels)),
        ("КВАРТИР", len(topology.apartments)),
        ("ПОМЕЩЕНИЙ", len(topology.rooms)),
        ("ПРИБОРОВ", len(topology.fixtures)),
        ("ШАХТ", len(topology.sanitary_shafts)),
    )
    for index, (label, value) in enumerate(metrics):
        x = 18 + index * 51.5
        body += (
            f'<rect x="{x:g}" y="62" width="47" height="20" rx="2" '
            'fill="#f1f3f7" stroke="#d7dbe3" stroke-width="0.25"/>'
            + _text(str(value), x=x + 4, y=73.5, size=6.2, weight=700)
            + _text(label, x=x + 4, y=78.3, size=2.35, weight=700, fill="#687083")
        )

    body += (
        _text("ФУНКЦИОНАЛЬНЫЕ СВЯЗИ", x=18, y=94, size=3.15, weight=700, fill="#ff6b35")
        + _text(
            "Каждая строка взята из реестра модели; линии труб здесь намеренно отсутствуют.",
            x=18,
            y=100,
            size=2.85,
            fill="#687083",
        )
        + '<rect x="18" y="105" width="262" height="10" fill="#2c3241"/>'
        + _text("ПОМЕЩЕНИЕ -> ПРИБОР", x=22, y=111.7, size=2.7, weight=700, fill="#ffffff")
        + _text("УРОВНИ", x=149, y=111.7, size=2.7, weight=700, fill="#ffffff")
        + _text("КОЛ.", x=225, y=111.7, size=2.7, weight=700, fill="#ffffff")
        + _text("ПОРТЫ", x=246, y=111.7, size=2.7, weight=700, fill="#ffffff")
    )
    visible_groups = groups[:8]
    for index, group in enumerate(visible_groups):
        y = 115 + index * 12
        fill = "#ffffff" if index % 2 == 0 else "#f7f8fb"
        body += (
            f'<rect x="18" y="{y:g}" width="262" height="12" fill="{fill}" '
            'stroke="#d7dbe3" stroke-width="0.18"/>'
            + _multiline(
                f"{group.room_label} -> {group.fixture_label}",
                x=22,
                y=y + 4.8,
                width_chars=50,
                size=2.75,
                line_height=3.4,
                max_lines=2,
            )
            + _multiline(
                _level_span(draft, group.level_ids),
                x=149,
                y=y + 4.8,
                width_chars=27,
                size=2.65,
                line_height=3.4,
                fill="#4b5563",
                max_lines=2,
            )
            + _text(str(group.count), x=232, y=y + 7.2, size=3.0, weight=700, anchor="middle")
            + _text(", ".join(group.service_ports), x=246, y=y + 7.2, size=2.8, weight=700)
        )
    if len(groups) > len(visible_groups):
        body += _text(
            f"Ещё типов связей: {len(groups) - len(visible_groups)} - см. реестр уровней.",
            x=18,
            y=216,
            size=2.7,
            fill="#687083",
        )

    body += _text("ВОРОТА ПЕРЕДАЧИ", x=292, y=94, size=3.15, weight=700, fill="#ff6b35")
    for index, status in enumerate(handoff.systems):
        y = 103 + index * 25
        ready = status.quantities_ready
        accent = "#00a88f" if ready else "#ff6b35"
        fill = "#eefbf8" if ready else "#fff7f2"
        body += (
            f'<rect x="292" y="{y:g}" width="110" height="21" rx="2" '
            f'fill="{fill}" stroke="{accent}" stroke-width="0.35"/>'
            + _text(status.system, x=298, y=y + 8, size=4.4, weight=700, fill=accent)
            + _text(
                f"источников: {status.fixture_source_count}",
                x=318,
                y=y + 7.2,
                size=2.7,
                weight=700,
            )
            + _text(
                "состав готов" if ready else f"блокировок: {len(status.quantity_blockers)}",
                x=318,
                y=y + 12.6,
                size=2.7,
                fill=accent,
            )
            + _text(
                "схема: ждёт геометрию АР",
                x=318,
                y=y + 17.5,
                size=2.45,
                fill="#687083",
            )
        )

    question_y = max(222.0, 119.0 + len(visible_groups) * 12)
    body += (
        _text("НЕЗАКРЫТЫЕ ВОПРОСЫ", x=18, y=question_y, size=3.15, weight=700, fill="#ff6b35")
    )
    questions = topology.questions[:4]
    if not questions:
        body += _text(
            "Типологические вопросы закрыты. Геометрия АР по-прежнему обязательна для схем.",
            x=18,
            y=question_y + 7,
            size=2.9,
            weight=700,
            fill="#008a76",
        )
    else:
        for index, question in enumerate(questions):
            body += (
                f'<circle cx="20" cy="{question_y + 7 + index * 9:g}" r="1.4" fill="#ff6b35"/>'
                + _multiline(
                    question.prompt,
                    x=25,
                    y=question_y + 8 + index * 9,
                    width_chars=105,
                    size=2.75,
                    line_height=3.6,
                    max_lines=2,
                )
            )
    body += _text(
        f"Основание данных: {topology.source_ref}",
        x=18,
        y=271,
        size=2.65,
        fill="#687083",
    )
    return _page_shell(
        body,
        page_number=1,
        title="КОНТРОЛЬНЫЙ ЛИСТ ТИПОЛОГИЧЕСКОЙ МОДЕЛИ",
    )


def _role_label(role: str) -> str:
    return {
        "roof": "кровля",
        "residential": "жилой",
        "underground": "подземный",
    }.get(role, role)


def _register_pages(draft: BuildingProgramDraft) -> list[str]:
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

    levels = list(topology.levels)
    pages: list[str] = []
    for offset in range(0, len(levels), _ROWS_PER_REGISTER_PAGE):
        chunk = levels[offset : offset + _ROWS_PER_REGISTER_PAGE]
        page_number = 2 + len(pages)
        body = (
            _text(draft.title, x=18, y=47, size=5.2, weight=700)
            + _text(
                f"Реестр уровней {offset + 1}-{offset + len(chunk)} из {len(levels)}",
                x=18,
                y=54,
                size=2.9,
                fill="#687083",
            )
            + '<rect x="18" y="63" width="384" height="11" fill="#2c3241"/>'
        )
        columns = (
            ("УРОВЕНЬ", 22),
            ("НАЗНАЧЕНИЕ", 76),
            ("КВ.", 139),
            ("ПОМ.", 160),
            ("ПРИБ.", 186),
            ("ШАХТ", 215),
            ("В1", 251),
            ("Т3", 279),
            ("К1", 307),
            ("К2", 335),
            ("К3", 363),
        )
        for label, x in columns:
            body += _text(label, x=x, y=70.2, size=2.55, weight=700, fill="#ffffff")
        for index, level in enumerate(chunk):
            y = 74 + index * 10.4
            fill = "#ffffff" if index % 2 == 0 else "#f4f6f9"
            systems = system_by_level.get(level.level_id, Counter())
            apartment_count = (
                apartments_by_floor[level.floor_number]
                if level.floor_number is not None
                else 0
            )
            shaft_count = (
                shafts_by_floor[level.floor_number]
                if level.floor_number is not None
                else 0
            )
            body += (
                f'<rect x="18" y="{y:g}" width="384" height="10.4" fill="{fill}" '
                'stroke="#d7dbe3" stroke-width="0.18"/>'
                + _text(
                    _level_label(level.level_id, level.floor_number, level.role),
                    x=22,
                    y=y + 6.7,
                    size=2.75,
                    weight=700,
                )
                + _text(_role_label(level.role), x=76, y=y + 6.7, size=2.7, fill="#4b5563")
                + _text(str(apartment_count), x=143, y=y + 6.7, size=2.8, anchor="middle")
                + _text(str(rooms_by_level[level.level_id]), x=166, y=y + 6.7, size=2.8, anchor="middle")
                + _text(str(fixtures_by_level[level.level_id]), x=194, y=y + 6.7, size=2.8, anchor="middle")
                + _text(str(shaft_count), x=223, y=y + 6.7, size=2.8, anchor="middle")
            )
            for system, x in (("V1", 255), ("T3", 283), ("K1", 311), ("K2", 339), ("K3", 367)):
                body += _text(str(systems[system]), x=x, y=y + 6.7, size=2.8, anchor="middle")
        body += (
            _text(
                "Числа в колонках систем - количество приборов с соответствующим сервисным портом, а не расход и не число труб.",
                x=18,
                y=268,
                size=2.75,
                fill="#687083",
            )
        )
        pages.append(_page_shell(
            body,
            page_number=page_number,
            title="РЕЕСТР УРОВНЕЙ И ИНЖЕНЕРНЫХ ИСТОЧНИКОВ",
        ))
    return pages


def generate_building_program_report_pdf(
    draft: BuildingProgramDraft,
    output_path: str | Path,
) -> str:
    """Write a paginated, vector PDF for visual programme verification."""
    import cairosvg  # type: ignore[import-untyped]
    from pypdf import PdfReader, PdfWriter

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pages = [_overview_page(draft), *_register_pages(draft)]
    writer = PdfWriter()
    with tempfile.TemporaryDirectory(prefix="zarya-building-report-") as tmp_dir:
        for index, svg in enumerate(pages, start=1):
            page_path = Path(tmp_dir) / f"page-{index}.pdf"
            cairosvg.svg2pdf(
                bytestring=svg.encode("utf-8"),
                write_to=str(page_path),
            )
            writer.append(PdfReader(page_path))
        with path.open("wb") as stream:
            writer.write(stream)
    return str(path)


__all__ = [
    "PAGE_HEIGHT_MM",
    "PAGE_WIDTH_MM",
    "generate_building_program_report_pdf",
]
