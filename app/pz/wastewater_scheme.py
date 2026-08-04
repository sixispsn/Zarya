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

    levels = _levels(project)
    top_floor = max(1, int(project.building.floors_above or 1))
    y_top, y_bottom = 175.0, 1235.0
    step = (y_bottom - y_top) / max(1, len(levels) - 1)
    floor_y = {floor: y_top + i * step for i, floor in enumerate(levels)}

    # Полосы этажей и отметки.
    for i, floor in enumerate(levels):
        y = floor_y[floor]
        line(350, y, 2135, y, 1.0, "#999")
        text(330, y - 7, _floor_title(floor, top_floor), 14, "end", "bold")
        text(330, y + 15, f"отм. {_fmt(_floor_mark(project, floor), 3)}", 11, "end", color=GRAY)
        if i and levels[i - 1] - floor > 1:
            mid = (floor_y[levels[i - 1]] + y) / 2
            line(345, mid - 12, 365, mid - 4, 1.4)
            line(345, mid + 4, 365, mid + 12, 1.4)
            text(376, mid + 5, f"этажи {floor + 1}–{levels[i - 1] - 1} повторяются", 11, color=GRAY)

    riser_pipes = [
        row for row in pipes
        if "стояк" in (row.purpose or "").lower()
    ]
    riser_pipes.sort(key=lambda row: (row.system, row.section_id))
    if not riser_pipes:
        warnings.append("не заданы трубопроводные участки с назначением «стояк»")
    x_min, x_max = 650.0, 1930.0
    riser_x: Dict[str, float] = {}
    if riser_pipes:
        dx = (x_max - x_min) / max(1, len(riser_pipes) - 1)
        for i, pipe in enumerate(riser_pipes):
            x = x_min + i * dx if len(riser_pipes) > 1 else (x_min + x_max) / 2
            riser_x[pipe.section_id] = x
            y1 = floor_y.get(top_floor + 1, y_top)
            y2 = floor_y.get(0, y_bottom)
            line(x, y1 - 28, x, y2 + 12, 3.2)
            for floor in levels:
                arrow(x, floor_y[floor] + 38, "down")
            mark = (
                f"{pipe.section_id}  {pipe.system}; "
                f"Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}"
            ).replace(".", ",")
            text(x - 13, (y1 + y2) / 2, mark, 14, "middle", "bold", rotate=-90)
            text(x, y1 - 40, pipe.room or pipe.purpose, 11, "middle", color=GRAY)

    # Горизонтальные участки группируются по системе и показывают уклон/отметки.
    horizontal = [row for row in pipes if row.section_id not in riser_x]
    grouped: Dict[str, List[SewerPipeSpec]] = {"K1": [], "K2": [], "K3": []}
    for pipe in horizontal:
        grouped.setdefault(pipe.system, []).append(pipe)
    base_y = {"K1": 1305.0, "K2": 1370.0, "K3": 1435.0}
    horizontal_xy: Dict[str, Tuple[float, float]] = {}
    for system in ("K1", "K2", "K3"):
        rows = grouped.get(system) or []
        if not rows:
            continue
        y = base_y[system]
        text(365, y + 5, system, 16, "end", "bold")
        seg_width = 1640.0 / len(rows)
        for i, pipe in enumerate(rows):
            x1 = 430 + i * seg_width
            x2 = 430 + (i + 1) * seg_width
            line(x1, y, x2, y, 3.2)
            arrow(x2 - 10, y)
            horizontal_xy[pipe.section_id] = ((x1 + x2) / 2, y)
            slope = f"; i={_fmt(pipe.slope_per_mille, 1)}‰" if pipe.slope_per_mille is not None else ""
            label = (
                f"{pipe.section_id}; Ø{pipe.outer_diameter_mm:g}×"
                f"{pipe.wall_thickness_mm:g}{slope}"
            ).replace(".", ",")
            text((x1 + x2) / 2, y - 12, label, 12, "middle", "bold")
            marks = ""
            if pipe.elevation_start_m is not None:
                marks = f"{_fmt(pipe.elevation_start_m)} → {_fmt(pipe.elevation_end_m)} м"
            text((x1 + x2) / 2, y + 22, marks or pipe.room, 10, "middle", color=GRAY)
        for pipe in riser_pipes:
            if pipe.system == system:
                line(riser_x[pipe.section_id], floor_y.get(0, y_bottom), riser_x[pipe.section_id], y, 2.4)
                G.append(f'<circle cx="{riser_x[pipe.section_id]:.1f}" cy="{y:.1f}" r="4" fill="{BLACK}"/>')

    # Элементы — только из реестра; одинаковые привязки слегка разводятся.
    used_slots: Dict[Tuple[str, int], int] = {}
    for element in sorted(elements, key=lambda row: (row.system, row.layout_column, row.floor_from, row.element_id)):
        target_x = riser_x.get(element.section_id)
        target_y: Optional[float] = None
        if target_x is not None:
            target_floor = element.floor_from
            if element.floor_to is not None:
                target_floor = round((element.floor_from + element.floor_to) / 2)
            target_floor = min(levels, key=lambda floor: abs(floor - target_floor))
            target_y = floor_y[target_floor]
        elif element.section_id in horizontal_xy:
            target_x, target_y = horizontal_xy[element.section_id]
        elif element.connects_to in horizontal_xy:
            target_x, target_y = horizontal_xy[element.connects_to]
        if target_x is None or target_y is None:
            warnings.append(f"{element.element_id}: элемент не размещён — нет привязанного участка")
            continue

        slot_key = (element.section_id, int(target_y))
        slot = used_slots.get(slot_key, 0)
        used_slots[slot_key] = slot + 1
        kind = element.kind
        if kind in ("revision", "fire_collar"):
            sy = target_y + slot * 28
            G.append(_symbol(kind, target_x, sy))
            label = f"{element.element_id}; {element.quantity} шт."
            if element.dn_mm:
                label += f"; DN{element.dn_mm}"
            text(target_x + 22, sy - 7, label, 10, "start")
            continue
        if kind in ("cleanout", "outlet", "pump", "ball_valve", "check_valve", "junction"):
            sx = target_x + (slot - 0.5) * 90
            G.append(_symbol(kind, sx, target_y))
            text(sx, target_y + 36, f"{element.element_id}; {element.quantity} шт.", 10, "middle")
            continue

        direction = -1 if (element.layout_column or 1) % 2 else 1
        sy = target_y + (slot - 0.5) * 38
        sx = target_x + direction * 100
        line(target_x, sy, sx - direction * 20, sy, 2.0)
        G.append(_symbol(kind, sx, sy))
        label_x = sx + direction * 30
        anchor = "end" if direction < 0 else "start"
        floor_text = (
            f"эт. {element.floor_from}–{element.floor_to}"
            if element.floor_to is not None and element.floor_to != element.floor_from
            else f"эт. {element.floor_from}"
        )
        text(label_x, sy - 9, f"{element.element_id}: {element.name}", 10, anchor, "bold")
        details = f"{element.quantity} шт.; {floor_text}"
        if element.dn_mm:
            details += f"; DN{element.dn_mm}"
        text(label_x, sy + 7, details, 9, anchor)
        if element.room_name:
            text(label_x, sy + 21, element.room_name, 9, anchor, color=GRAY)

    # Легенда и статус реестра.
    lx, ly, lw = 2185.0, 150.0, 550.0
    rect(lx, ly, lw, 650, sw=1.4)
    text(lx + 18, ly + 30, "УСЛОВНЫЕ ОБОЗНАЧЕНИЯ", 15, weight="bold")
    legend = [
        ("toilet", "санитарный прибор"),
        ("roof_funnel", "водосточная воронка"),
        ("revision", "ревизия"),
        ("cleanout", "прочистка"),
        ("fire_collar", "противопожарная муфта"),
        ("outlet", "направление выпуска"),
    ]
    for i, (kind, label) in enumerate(legend):
        yy = ly + 70 + i * 52
        G.append(_symbol(kind, lx + 42, yy))
        text(lx + 76, yy + 5, label, 12)
    line(lx + 24, ly + 394, lx + 70, ly + 394, 3.2)
    arrow(lx + 70, ly + 394)
    text(lx + 88, ly + 399, "трубопровод и направление стока", 12)
    text(lx + 18, ly + 440, f"Элементов в реестре: {audit.element_count}", 12, weight="bold")
    text(lx + 18, ly + 466, f"Позиций спецификации: {audit.spec_position_count}", 12)
    text(lx + 18, ly + 500, "Противопожарные преграды:", 11, weight="bold")
    text(lx + 18, ly + 520, _short(project.sewage.fire_barrier_note or "не заданы", 72), 10)
    text(lx + 18, ly + 550, "Деформационные швы:", 11, weight="bold")
    text(lx + 18, ly + 570, _short(project.sewage.deformation_joint_note or "не заданы", 72), 10)
    status = (
        "РЕЕСТР ПРОШЁЛ ПРОВЕРКУ"
        if audit.ready and not audit.warnings
        else "РЕЕСТР ПРОШЁЛ С ПРЕДУПРЕЖДЕНИЯМИ"
        if audit.ready
        else "РЕЕСТР ТРЕБУЕТ ДАННЫХ"
    )
    text(lx + 18, ly + 620, status, 12, weight="bold", color=BLACK if audit.ready else "#a00")

    # Таблица участков остаётся частью схемы и несёт обязательные DN/уклоны/отметки.
    tx, ty, tw = 350.0, 1480.0, 1785.0
    col = [0, 120, 330, 580, 830, 1050, 1250, 1430, 1785]
    row_h = 34.0
    rows = pipes[:6]
    th = row_h * (len(rows) + 1)
    rect(tx, ty, tw, th, sw=1.4)
    for c in col[1:-1]:
        line(tx + c, ty, tx + c, ty + th, 1.0)
    for i in range(1, len(rows) + 1):
        line(tx, ty + i * row_h, tx + tw, ty + i * row_h, 1.0)
    headers = ["Сист.", "Участок", "Помещение", "От → к", "Øнар×s", "Отметки", "i, ‰", "h/d"]
    for i, label in enumerate(headers):
        text(tx + (col[i] + col[i + 1]) / 2, ty + 22, label, 10, "middle", "bold")
    for r_index, pipe in enumerate(rows, 1):
        yy = ty + r_index * row_h + 22
        values = [
            pipe.system,
            pipe.section_id,
            _short(pipe.room, 30),
            _short(f"{pipe.from_node} → {pipe.to_node}", 28),
            f"{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}".replace(".", ","),
            (f"{_fmt(pipe.elevation_start_m)} → {_fmt(pipe.elevation_end_m)}"
             if pipe.elevation_start_m is not None else "—"),
            _fmt(pipe.slope_per_mille, 1),
            _fmt(pipe.fill_ratio, 2),
        ]
        for i, value in enumerate(values):
            text(tx + (col[i] + col[i + 1]) / 2, yy, value, 9, "middle")

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
