"""Векторная принципиальная схема К1/К2/К3 по реестру элементов.

Компоновка следует рекомендуемому примеру приложения В ГОСТ Р 21.620-2023,
а состав данных — обязательному п. 5.2.2.4. Схема не достраивает приборы,
фасонные части или связи, которых нет в реестре/топологии проекта.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Dict, Iterable, List, Optional, Tuple

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_registry import audit_wastewater_registry


W, H = 2803, 1980  # А1, альбомная ориентация: 841×594
PXMM = W / 841
FONT = "Arial, DejaVu Sans, sans-serif"
BLACK = "#111"
GRAY = "#777"


@dataclass
class WastewaterSchemeResult:
    svg: str
    width: int = W
    height: int = H
    warnings: List[str] = field(default_factory=list)


def _fmt(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def _short(value: str, limit: int) -> str:
    value = value or ""
    return value if len(value) <= limit else value[: max(1, limit - 1)] + "…"


def _levels(project: Project) -> List[int]:
    n = max(1, int(project.building.floors_above or 1))
    if n <= 6:
        return list(range(n + 1, -1, -1))
    required = {n + 1, n, max(2, n // 2), 2, 1, 0}
    for row in project.sewage.elements:
        if 0 <= row.floor_from <= n + 1:
            required.add(row.floor_from)
        if row.floor_to is not None and 0 <= row.floor_to <= n + 1:
            required.add(row.floor_to)
    ordered = sorted(required, reverse=True)
    if len(ordered) <= 10:
        return ordered
    priority = [n + 1, n, max(2, n // 2), 2, 1, 0]
    selected = set(priority)
    for value in ordered:
        if len(selected) >= 10:
            break
        selected.add(value)
    return sorted(selected, reverse=True)


def _floor_title(floor: int, top: int) -> str:
    if floor == top + 1:
        return "Кровля"
    if floor == 0:
        return "Техподполье"
    return f"{floor} этаж"


def _floor_mark(project: Project, floor: int) -> float:
    n = max(1, int(project.building.floors_above or 1))
    height = float(project.building.height_m or n * 3.0)
    step = height / n
    if floor == n + 1:
        return height
    if floor == 0:
        lows = [
            value
            for pipe in project.sewage.pipes
            for value in (pipe.elevation_start_m, pipe.elevation_end_m)
            if value is not None and value <= 0
        ]
        return max(lows) if lows else -0.2
    return (floor - 1) * step


def _symbol(kind: str, x: float, y: float) -> str:
    """Компактные условные знаки; буквенные знаки даны также в легенде."""
    s = BLACK
    if kind == "toilet":
        return (
            f'<path d="M{x-18},{y-12} h25 v10 q0,17 -13,17 '
            f'q-13,0 -13,-17 z" fill="none" stroke="{s}" stroke-width="2"/>'
            f'<rect x="{x+8}" y="{y-10}" width="10" height="19" '
            f'fill="none" stroke="{s}" stroke-width="2"/>'
        )
    if kind in ("washbasin", "sink"):
        return (
            f'<path d="M{x-18},{y-10} h36 q0,20 -18,20 q-18,0 -18,-20" '
            f'fill="none" stroke="{s}" stroke-width="2"/>'
            f'<circle cx="{x}" cy="{y}" r="2.5" fill="{s}"/>'
        )
    if kind == "bath":
        return (
            f'<rect x="{x-22}" y="{y-10}" width="44" height="20" rx="5" '
            f'fill="none" stroke="{s}" stroke-width="2"/>'
        )
    if kind in ("shower", "floor_drain", "trap"):
        return (
            f'<rect x="{x-10}" y="{y-10}" width="20" height="20" '
            f'fill="none" stroke="{s}" stroke-width="2"/>'
            f'<path d="M{x-8},{y-8} L{x+8},{y+8} M{x+8},{y-8} L{x-8},{y+8}" '
            f'stroke="{s}" stroke-width="1.5"/>'
        )
    if kind == "roof_funnel":
        return (
            f'<circle cx="{x}" cy="{y}" r="14" fill="none" stroke="{s}" '
            f'stroke-width="2"/><path d="M{x-12},{y} h24 M{x},{y-12} v24" '
            f'stroke="{s}" stroke-width="2"/>'
        )
    if kind == "revision":
        return (
            f'<rect x="{x-12}" y="{y-12}" width="24" height="24" '
            f'fill="white" stroke="{s}" stroke-width="2"/>'
            f'<text x="{x}" y="{y+6}" text-anchor="middle" font-family="{FONT}" '
            f'font-size="17" fill="{s}">Р</text>'
        )
    if kind == "cleanout":
        return (
            f'<circle cx="{x}" cy="{y}" r="13" fill="white" stroke="{s}" '
            f'stroke-width="2"/><text x="{x}" y="{y+5}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="12" fill="{s}">Пр</text>'
        )
    if kind == "fire_collar":
        return (
            f'<rect x="{x-15}" y="{y-7}" width="30" height="14" '
            f'fill="white" stroke="{s}" stroke-width="2"/>'
            f'<path d="M{x-10},{y-7} v14 M{x+10},{y-7} v14" stroke="{s}"/>'
        )
    if kind == "pump":
        return (
            f'<circle cx="{x}" cy="{y}" r="17" fill="white" stroke="{s}" '
            f'stroke-width="2"/><path d="M{x-7},{y+8} L{x+10},{y} L{x-7},{y-8} Z" '
            f'fill="none" stroke="{s}" stroke-width="2"/>'
        )
    if kind in ("ball_valve", "check_valve"):
        return (
            f'<path d="M{x-14},{y-10} L{x},{y} L{x-14},{y+10} Z '
            f'M{x+14},{y-10} L{x},{y} L{x+14},{y+10} Z" '
            f'fill="white" stroke="{s}" stroke-width="2"/>'
        )
    if kind == "outlet":
        return f'<path d="M{x-18},{y} h36 l-11,-8 m11,8 l-11,8" fill="none" stroke="{s}" stroke-width="2.5"/>'
    if kind in ("tee", "elbow", "transition", "junction"):
        return f'<circle cx="{x}" cy="{y}" r="5" fill="{s}"/>'
    return (
        f'<circle cx="{x}" cy="{y}" r="11" fill="white" stroke="{s}" '
        f'stroke-width="2"/><text x="{x}" y="{y+5}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="13" fill="{s}">Э</text>'
    )


def build_wastewater_scheme(project: Project) -> WastewaterSchemeResult:
    doc = project.document
    pipes = list(project.sewage.pipes or [])
    elements = list(project.sewage.elements or [])
    audit = audit_wastewater_registry(project)
    warnings = list(audit.errors) + list(audit.warnings)
    G: List[str] = []

    def line(x1, y1, x2, y2, width=2.0, color=BLACK, dash=""):
        dashed = f' stroke-dasharray="{dash}"' if dash else ""
        G.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
            f'y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"{dashed}/>'
        )

    def rect(x, y, width, height, stroke=BLACK, fill="none", sw=1.5):
        G.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" '
            f'height="{height:.1f}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{sw}"/>'
        )

    def text(x, y, value, size=14, anchor="start", weight="normal", color=BLACK,
             rotate: Optional[float] = None):
        transform = (
            f' transform="rotate({rotate:.1f},{x:.1f},{y:.1f})"'
            if rotate is not None else ""
        )
        G.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}"{transform}>{escape(str(value))}</text>'
        )

    def arrow(x, y, direction="right"):
        if direction == "down":
            G.append(f'<path d="M{x-7},{y-10} L{x},{y} L{x+7},{y-10} Z" fill="{BLACK}"/>')
        else:
            G.append(f'<path d="M{x-12},{y-7} L{x},{y} L{x-12},{y+7} Z" fill="{BLACK}"/>')

    # Заголовок и нормативная граница листа.
    text(108, 78, "Принципиальная схема внутренних систем К1, К2 и К3", 24, weight="bold")
    text(
        108, 108,
        "ГОСТ Р 21.620-2023: состав по п. 5.2.2.4; компоновка по рекомендуемому приложению В",
        13, color=GRAY,
    )

    top_floor = max(1, int(project.building.floors_above or 1))
    representative = [top_floor, max(2, top_floor // 2), 2, 1]
    floors: List[int] = []
    for floor in representative:
        if 1 <= floor <= top_floor and floor not in floors:
            floors.append(floor)
    levels = [top_floor + 1] + floors + [0]
    y_positions = [172.0, 318.0, 535.0, 752.0, 969.0, 1210.0]
    if len(levels) != len(y_positions):
        y_positions = [172.0 + i * (1038.0 / max(1, len(levels) - 1)) for i in range(len(levels))]
    floor_y = dict(zip(levels, y_positions))

    text(375, 142, "К1 · ХОЗЯЙСТВЕННО-БЫТОВАЯ КАНАЛИЗАЦИЯ", 14, weight="bold")
    text(1730, 142, "К2 · ВНУТРЕННИЙ ВОДОСТОК", 14, weight="bold")

    # Этажные уровни и пропуски этажей. На листе показаны характерные этажи,
    # а не произвольно восстановленная рабочая аксонометрия.
    for index, floor in enumerate(levels):
        y = floor_y[floor]
        line(350, y, 2160, y, 1.0, "#999")
        text(330, y - 8, _floor_title(floor, top_floor), 14, "end", "bold")
        text(330, y + 14, f"отм. {_fmt(_floor_mark(project, floor), 3)}", 10, "end", color=GRAY)
        if index and levels[index - 1] - floor > 1:
            mid = (floor_y[levels[index - 1]] + y) / 2
            line(352, mid - 13, 372, mid - 5, 1.3)
            line(352, mid + 5, 372, mid + 13, 1.3)
            text(382, mid + 5, f"этажи {floor + 1}–{levels[index - 1] - 1} повторяются", 10, color=GRAY)

    riser_pipes = sorted(
        (row for row in pipes if "стояк" in (row.purpose or "").lower()),
        key=lambda row: (row.system, row.section_id),
    )
    if not riser_pipes:
        warnings.append("не заданы трубопроводные участки с назначением «стояк»")
    k1_risers = [row for row in riser_pipes if row.system == "K1"]
    k2_risers = [row for row in riser_pipes if row.system == "K2"]
    k3_risers = [row for row in riser_pipes if row.system == "K3"]

    def distributed_x(rows: List[SewerPipeSpec], x1: float, x2: float) -> Dict[str, float]:
        if not rows:
            return {}
        if len(rows) == 1:
            return {rows[0].section_id: (x1 + x2) / 2}
        dx = (x2 - x1) / (len(rows) - 1)
        return {row.section_id: x1 + i * dx for i, row in enumerate(rows)}

    riser_x: Dict[str, float] = {}
    riser_x.update(distributed_x(k1_risers, 720.0, 1370.0))
    riser_x.update(distributed_x(k2_risers, 1840.0, 2070.0))
    riser_x.update(distributed_x(k3_risers, 1620.0, 1740.0))
    roof_y = floor_y[top_floor + 1]
    basement_y = floor_y[0]
    for pipe in riser_pipes:
        x = riser_x[pipe.section_id]
        line(x, roof_y - 22, x, basement_y + 20, 3.0)
        for floor in floors:
            arrow(x, floor_y[floor] + 44, "down")
        mark = (
            f"{pipe.section_id}; Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}"
        ).replace(".", ",")
        text(x - 12, (roof_y + basement_y) / 2, mark, 12, "middle", "bold", rotate=-90)
        text(x, roof_y - 35, _short(pipe.room or pipe.purpose, 30), 9, "middle", color=GRAY)
        if pipe.system == "K1":
            # Фановая часть стояка выше кровли.
            line(x, roof_y - 52, x, roof_y - 22, 3.0)
            line(x - 10, roof_y - 52, x + 10, roof_y - 52, 2.0)
            text(x + 16, roof_y - 47, "вент. часть", 9, color=GRAY)

    fixture_kinds = {"toilet", "washbasin", "sink", "bath", "shower", "floor_drain", "trap"}
    placed_ids = set()

    def section_elements(section_id: str, kinds: Optional[set] = None) -> List[SewerElementSpec]:
        found = [row for row in elements if row.section_id == section_id]
        if kinds is not None:
            found = [row for row in found if row.kind in kinds]
        return sorted(found, key=lambda row: (row.kind, row.element_id))

    def applies(row: SewerElementSpec, floor: int) -> bool:
        end = row.floor_to if row.floor_to is not None else row.floor_from
        return row.floor_from <= floor <= end

    # Типовые группы приборов показываются у каждого подтверждённого стояка К1.
    # Количество и диапазон этажей подписываются из реестра; скрытые приборы не создаются.
    for riser_index, pipe in enumerate(k1_risers):
        x = riser_x[pipe.section_id]
        direction = -1 if riser_index % 2 == 0 else 1
        fixtures = section_elements(pipe.section_id, fixture_kinds)
        revisions = section_elements(pipe.section_id, {"revision"})
        collars = section_elements(pipe.section_id, {"fire_collar"})
        for floor in floors:
            y = floor_y[floor]
            active = [row for row in fixtures if applies(row, floor)]
            if active:
                cell_x = x - 360 if direction < 0 else x + 30
                rect(cell_x, y - 104, 330, 94, stroke="#777", fill="white", sw=1.0)
                text(cell_x + 10, y - 86, "типовая санитарная группа", 9, weight="bold")
                branch_end = x + direction * 300
                line(x, y - 27, branch_end, y - 27 + direction * 4, 2.0)
                slots = min(4, len(active))
                for slot, row in enumerate(active[:slots]):
                    sx = x + direction * (72 + slot * 68)
                    sy = y - 28 + direction * (slot * 1.2)
                    G.append(_symbol(row.kind, sx, sy))
                    short_kind = {
                        "toilet": "Ун", "washbasin": "Ум", "sink": "Мой",
                        "bath": "Ван", "shower": "Душ", "floor_drain": "Тр",
                        "trap": "Гз",
                    }.get(row.kind, "Э")
                    text(sx, y - 49, f"{short_kind} DN{row.dn_mm or '—'}", 7.5, "middle")
                    placed_ids.add(row.element_id)
                slopes = sorted({row.slope_per_mille for row in active if row.slope_per_mille is not None})
                slope_note = "/".join(_fmt(value, 0) for value in slopes) if slopes else "—"
                text(cell_x + 10, y - 66, f"ответвления i={slope_note}‰; к {pipe.section_id}", 8, color=GRAY)
                if floor == floors[0]:
                    ids = ", ".join(row.element_id for row in active)
                    total = ", ".join(f"{row.element_id} — {row.quantity} шт." for row in active)
                    text(cell_x + 10, y - 15, _short(ids, 55), 7.5, color=GRAY)
                    text(cell_x + 10, y + 9, _short(total, 62), 7.5, color=GRAY)
            for row in revisions:
                if row.floor_from == floor:
                    sy = y - 58
                    G.append(_symbol("revision", x, sy))
                    text(x + 18, sy - 9, f"{row.element_id}; DN{row.dn_mm or '—'}", 8)
                    placed_ids.add(row.element_id)
            for row in collars:
                if applies(row, floor):
                    G.append(_symbol("fire_collar", x, y + 2))
                    if floor == floors[0]:
                        text(x + 20, y + 8, f"{row.element_id}; {row.quantity} шт.", 8)
                    placed_ids.add(row.element_id)

    # Водосточные воронки и кровельные уклоны — по реестру К2.
    for pipe in k2_risers:
        x = riser_x[pipe.section_id]
        funnels = section_elements(pipe.section_id, {"roof_funnel"})
        for row in funnels:
            count_drawn = min(2, max(1, row.quantity))
            positions = [x] if count_drawn == 1 else [x - 55, x + 55]
            for sx in positions:
                sy = roof_y - 6
                G.append(_symbol("roof_funnel", sx, sy))
                line(sx, sy + 14, x, roof_y + 22, 2.2)
                line(sx - 48, roof_y - 25, sx, sy - 14, 1.4)
                line(sx + 48, roof_y - 25, sx, sy - 14, 1.4)
            slope = f"; i={_fmt(row.slope_per_mille, 0)}‰" if row.slope_per_mille is not None else ""
            text(x, roof_y + 48, f"{row.element_id}; {row.quantity} шт.; DN{row.dn_mm or '—'}{slope}", 8, "middle", "bold")
            placed_ids.add(row.element_id)
        cleanouts = section_elements(pipe.section_id, {"cleanout"})
        for offset, row in enumerate(cleanouts):
            sy = basement_y - 26 - offset * 34
            G.append(_symbol("cleanout", x, sy))
            text(x + 20, sy + 4, f"{row.element_id}; DN{row.dn_mm or '—'}", 8)
            placed_ids.add(row.element_id)

    # Магистрали, выпуски, отметки и уклоны. Геометрия берётся только из
    # подтверждённых участков, без расчёта промежуточных фасонных частей.
    horizontal = [row for row in pipes if row.section_id not in riser_x]
    grouped: Dict[str, List[SewerPipeSpec]] = {"K1": [], "K2": [], "K3": []}
    for pipe in horizontal:
        grouped.setdefault(pipe.system, []).append(pipe)
    main_y = {"K1": 1328.0, "K2": 1415.0, "K3": 1492.0}
    horizontal_xy: Dict[str, Tuple[float, float]] = {}
    for system in ("K1", "K2", "K3"):
        rows = grouped.get(system) or []
        if not rows:
            continue
        y = main_y[system]
        start_x = 390.0 if system != "K2" else 1695.0
        end_x = 2140.0
        text(start_x - 22, y + 5, system, 15, "end", "bold")
        segment = (end_x - start_x) / len(rows)
        for index, pipe in enumerate(rows):
            x1, x2 = start_x + index * segment, start_x + (index + 1) * segment
            line(x1, y, x2, y, 3.0)
            arrow(x2 - 6, y)
            horizontal_xy[pipe.section_id] = ((x1 + x2) / 2, y)
            slope = f"; i={_fmt(pipe.slope_per_mille, 1)}‰" if pipe.slope_per_mille is not None else ""
            label = (
                f"{pipe.section_id}; Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}{slope}"
            ).replace(".", ",")
            text((x1 + x2) / 2, y - 13, label, 10, "middle", "bold")
            marks = (
                f"отм. {_fmt(pipe.elevation_start_m)} → {_fmt(pipe.elevation_end_m)} м"
                if pipe.elevation_start_m is not None else _short(pipe.room, 35)
            )
            text((x1 + x2) / 2, y + 21, marks, 9, "middle", color=GRAY)
        for pipe in riser_pipes:
            if pipe.system == system:
                x = riser_x[pipe.section_id]
                line(x, basement_y, x, y, 2.4)
                G.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{BLACK}"/>')

    # Элементы на горизонтальных участках, включая оба выпуска.
    slot_by_section: Dict[str, int] = {}
    line_kinds = {"cleanout", "outlet", "pump", "ball_valve", "check_valve", "junction", "sump"}
    for row in elements:
        if row.element_id in placed_ids or row.kind not in line_kinds:
            continue
        target = horizontal_xy.get(row.section_id)
        if target is None:
            continue
        tx0, ty0 = target
        slot = slot_by_section.get(row.section_id, 0)
        slot_by_section[row.section_id] = slot + 1
        sx = tx0 + (slot - 0.5) * 90
        G.append(_symbol(row.kind, sx, ty0))
        text(sx, ty0 + 38, f"{row.element_id}; {row.quantity} шт.; DN{row.dn_mm or '—'}", 8, "middle")
        if row.connects_to:
            text(sx, ty0 + 52, f"к {row.connects_to}", 8, "middle", color=GRAY)
        placed_ids.add(row.element_id)

    for row in elements:
        if row.element_id not in placed_ids:
            warnings.append(f"{row.element_id}: элемент не размещён — нет поддержанной привязки на схеме")

    # Компактная легенда и расчётный паспорт освобождают лист от пустого поля.
    lx, ly, lw = 2190.0, 145.0, 545.0
    rect(lx, ly, lw, 316, sw=1.4)
    text(lx + 16, ly + 28, "УСЛОВНЫЕ ОБОЗНАЧЕНИЯ", 13, weight="bold")
    legend = [
        ("toilet", "унитаз"), ("washbasin", "умывальник / мойка"),
        ("bath", "ванна"), ("roof_funnel", "водосточная воронка"),
        ("revision", "ревизия"), ("cleanout", "прочистка"),
        ("fire_collar", "противопожарная муфта"), ("outlet", "выпуск"),
    ]
    for index, (kind, label) in enumerate(legend):
        col_index, row_index = index % 2, index // 2
        sx = lx + 36 + col_index * 270
        sy = ly + 68 + row_index * 54
        G.append(_symbol(kind, sx, sy))
        text(sx + 28, sy + 4, label, 9)
    line(lx + 18, ly + 284, lx + 62, ly + 284, 3.0)
    arrow(lx + 62, ly + 284)
    text(lx + 76, ly + 288, "трубопровод и направление стока", 9)

    storm_result = project.storm.result
    sewage_result = project.sewage.result
    rect(lx, 478, lw, 334, sw=1.4)
    text(lx + 16, 506, "РАСЧЁТНЫЕ ДАННЫЕ СХЕМЫ", 13, weight="bold")
    q_k1 = (
        f"{_fmt(sewage_result.total.q_sewage_lps, 3)} л/с"
        if sewage_result is not None else "см. лист расчёта"
    )
    q_k2 = (
        f"{_fmt(storm_result.q_total_l_per_s, 3)} л/с"
        if storm_result is not None else "см. лист расчёта"
    )
    city = (
        storm_result.city.name if storm_result is not None
        else "Москва" if project.storm.city_code.lower() == "moscow"
        else project.storm.city_code or "не задан"
    )
    data_rows = [
        ("К1 · расчётный расход", q_k1),
        ("К1 · точка выпуска", project.sewage.discharge_point_k1 or "не задана"),
        ("К2 · район строительства", city),
        ("К2 · площадь кровли", f"{_fmt(project.storm.roof_area_m2, 1)} м²"),
        ("К2 · расчётный расход", q_k2),
        ("К2 · воронки / стояки", f"{project.storm.funnels_count} / {project.storm.risers_count} шт."),
        ("К2 · нагрузка на воронку", f"{_fmt(project.storm.max_funnel_flow_lps, 2)} л/с"),
        ("К2 · точка выпуска", project.sewage.discharge_point_k2 or "не задана"),
    ]
    for index, (label, value) in enumerate(data_rows):
        yy = 538 + index * 32
        text(lx + 16, yy, label, 9, color=GRAY)
        text(lx + lw - 16, yy, value, 10, "end", "bold")
        line(lx + 16, yy + 8, lx + lw - 16, yy + 8, 0.6, "#bbb")

    rect(lx, 829, lw, 374, sw=1.4)
    text(lx + 16, 857, "ПРОЕКТНЫЕ УКАЗАНИЯ", 13, weight="bold")
    notes = [
        "1. Схема принципиальная; трассы и фасонные части уточняются по планам",
        "   и аксонометрическим схемам стадии Р.",
        "2. Приборы, ревизии, муфты, прочистки и выпуски показаны только",
        "   по подтверждённому реестру элементов проекта.",
        "3. Вентиляционные части стояков К1 вывести выше кровли.",
        "4. К2 проложить с электрообогревом воронок по заданию ЭОМ.",
        "5. Отметки низа труб и уклоны горизонтальных участков — по таблице.",
        "6. Противопожарная заделка пересечений — по узлам КР.",
    ]
    for index, note in enumerate(notes):
        text(lx + 16, 889 + index * 25, note, 8.5)
    text(lx + 16, 1100, "Реестр элементов", 9, color=GRAY)
    text(lx + lw - 16, 1100, f"{audit.element_count} элементов / {audit.spec_position_count} позиций", 10, "end", "bold")
    text(lx + 16, 1128, "Противопожарные преграды", 9, color=GRAY)
    text(lx + 16, 1147, _short(project.sewage.fire_barrier_note or "не заданы", 78), 8.5)
    status = (
        "РЕЕСТР ПРОШЁЛ ПРОВЕРКУ" if audit.ready and not audit.warnings
        else "РЕЕСТР ПРОШЁЛ С ПРЕДУПРЕЖДЕНИЯМИ" if audit.ready
        else "РЕЕСТР ТРЕБУЕТ ДАННЫХ"
    )
    text(lx + 16, 1182, status, 10, weight="bold", color=BLACK if audit.ready else "#a00")

    # Таблица участков на самом листе несёт DN, отметки, уклоны и наполнение.
    tx, ty, tw = 350.0, 1515.0, 1795.0
    col = [0, 105, 300, 540, 810, 1015, 1220, 1390, 1795]
    row_h = 26.0
    rows = pipes[:8]
    th = row_h * (len(rows) + 1)
    rect(tx, ty, tw, th, sw=1.4)
    for c in col[1:-1]:
        line(tx + c, ty, tx + c, ty + th, 1.0)
    for index in range(1, len(rows) + 1):
        line(tx, ty + index * row_h, tx + tw, ty + index * row_h, 1.0)
    headers = ["Сист.", "Участок", "Помещение", "От → к", "Øнар×s", "Отметки", "i, ‰", "h/d / L, м"]
    for index, label in enumerate(headers):
        text(tx + (col[index] + col[index + 1]) / 2, ty + 18, label, 8, "middle", "bold")
    for row_index, pipe in enumerate(rows, 1):
        yy = ty + row_index * row_h + 18
        values = [
            pipe.system,
            pipe.section_id,
            _short(pipe.room, 30),
            _short(f"{pipe.from_node} → {pipe.to_node}", 31),
            f"{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}".replace(".", ","),
            (f"{_fmt(pipe.elevation_start_m)} → {_fmt(pipe.elevation_end_m)}"
             if pipe.elevation_start_m is not None else "—"),
            _fmt(pipe.slope_per_mille, 1),
            f"{_fmt(pipe.fill_ratio, 2)} / {_fmt(pipe.length_m, 1)}",
        ]
        for index, value in enumerate(values):
            text(tx + (col[index] + col[index + 1]) / 2, yy, value, 7.5, "middle")

    # Рамка и основной штамп формы 3.
    fx0, fy0, fx1, fy1 = 20 * PXMM, 5 * PXMM, W - 5 * PXMM, H - 5 * PXMM
    rect(fx0, fy0, fx1 - fx0, fy1 - fy0, sw=2.0)

    def mmx(value):
        return fx1 - (185 - value) * PXMM

    def mmy(value):
        return fy1 - (55 - value) * PXMM

    rect(mmx(0), mmy(0), 185 * PXMM, 55 * PXMM, fill="white", sw=2.0)
    line(mmx(65), mmy(0), mmx(65), mmy(55), 1.6)
    for cx in (7, 17, 25, 37, 53):
        line(mmx(cx), mmy(0), mmx(cx), mmy(25), 1.0)
    for cx in (17, 37, 53):
        line(mmx(cx), mmy(25), mmx(cx), mmy(55), 1.0)
    line(mmx(135), mmy(25), mmx(135), mmy(55), 1.3)
    for cx in (150, 165):
        line(mmx(cx), mmy(25), mmx(cx), mmy(40), 1.0)
    for yy in range(5, 55, 5):
        line(mmx(0), mmy(yy), mmx(65), mmy(yy), 1.0)
    line(mmx(65), mmy(10), mmx(185), mmy(10), 1.0)
    line(mmx(65), mmy(25), mmx(185), mmy(25), 1.0)
    line(mmx(135), mmy(30), mmx(185), mmy(30), 1.0)
    line(mmx(65), mmy(40), mmx(185), mmy(40), 1.0)
    for label, c0, c1 in (
        ("Изм.", 0, 7), ("Кол.уч.", 7, 17), ("Лист", 17, 25),
        ("№ док.", 25, 37), ("Подп.", 37, 53), ("Дата", 53, 65),
    ):
        text(mmx((c0 + c1) / 2), mmy(25) - 4, label, 8, "middle")
    signers = (
        ("Разраб.", doc.developer_name, 30),
        ("Проверил", doc.inspector_name, 35),
        ("Нач. отдела", doc.dept_head_name, 40),
        ("ГИП", doc.gip_name, 45),
        ("Н. контр.", doc.norm_control_name, 55),
    )
    for label, name, row in signers:
        text(mmx(1) + 2, mmy(row) - 4.5, label, 8.5)
        if name:
            text(mmx(27), mmy(row) - 4.5, _short(name, 18), 8.5, "middle")
    text(mmx(125), mmy(8), _short(doc.cipher or "", 34), 14, "middle")
    text(mmx(125), mmy(19), _short(doc.object_name or "", 68), 9, "middle")
    text(mmx(100), mmy(34.5), _short(doc.object_part or "", 38), 11, "middle")
    text(mmx(142.5), mmy(30) - 4, "Стадия", 7.5, "middle")
    text(mmx(157.5), mmy(30) - 4, "Лист", 7.5, "middle")
    text(mmx(175), mmy(30) - 4, "Листов", 7.5, "middle")
    text(mmx(142.5), mmy(37), doc.stage_label or "П", 11, "middle")
    text(mmx(157.5), mmy(37), "1", 11, "middle")
    text(mmx(175), mmy(37), "1", 11, "middle")
    text(mmx(100), mmy(47), "Принципиальная схема внутренних систем", 10, "middle")
    text(mmx(100), mmy(53), "К1, К2 и К3", 12, "middle", "bold")
    text(mmx(160), mmy(49), _short(doc.organization or "", 30), 9, "middle")

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}"><rect width="{W}" height="{H}" fill="white"/>'
        + "".join(G)
        + "</svg>"
    )
    return WastewaterSchemeResult(svg=svg, warnings=warnings)


def render_wastewater_scheme_png(
    result: WastewaterSchemeResult,
    path: str,
    scale: float = 1.0,
) -> str:
    import cairosvg

    cairosvg.svg2png(bytestring=result.svg.encode("utf-8"), write_to=path, scale=scale)
    return path
