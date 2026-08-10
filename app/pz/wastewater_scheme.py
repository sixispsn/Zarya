"""Принципиальная схема К1/К2/К3 по явному топологическому графу.

Геометрия листа строится только из подтверждённых рёбер ``from_node`` /
``to_node`` и привязок элементов к этажным ответвлениям. Генератор не соединяет
стояки и магистрали по близости координат и не восстанавливает помещения.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Dict, Iterable, List, Optional, Tuple

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_registry import audit_wastewater_registry
from app.pz.wastewater_topology import SewerBranch, build_wastewater_topology
from app.pz.wastewater_ugo import project_legend_definitions, render_ugo


W, H = 2803, 1980  # А1, 841×594 мм
PXMM = W / 841
FONT = "Arial, DejaVu Sans, sans-serif"
BLACK = "#111"
GRAY = "#666"
LIGHT = "#aaa"


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


def _floor_title(floor: int, top: int) -> str:
    if floor == top + 1:
        return "Кровля"
    if floor == 0:
        return "Техподполье"
    return f"{floor} этаж"


def _floor_mark(project: Project, floor: int) -> float:
    n = max(1, int(project.building.floors_above or 1))
    height = float(project.building.height_m or n * 3.0)
    if floor == n + 1:
        return height
    if floor == 0:
        lows = [
            mark
            for pipe in project.sewage.pipes
            for mark in (pipe.elevation_start_m, pipe.elevation_end_m)
            if mark is not None and mark <= 0
        ]
        return max(lows) if lows else 0.0
    return (floor - 1) * height / n


def _representative_floors(top: int) -> List[int]:
    if top <= 6:
        return list(range(top, 0, -1))
    # Как в приложении В: рядом показываются два верхних и два нижних этажа,
    # между ними - характерный средний этаж с графическим разрывом.
    values = [top, top - 1, max(2, top // 2), 2, 1]
    result: List[int] = []
    for value in values:
        if 1 <= value <= top and value not in result:
            result.append(value)
    return result


def _applies(element: SewerElementSpec, floor: int) -> bool:
    end = element.floor_to if element.floor_to is not None else element.floor_from
    return element.floor_from <= floor <= end


def build_wastewater_scheme(project: Project) -> WastewaterSchemeResult:
    doc = project.document
    elements = list(project.sewage.elements or [])
    topology = build_wastewater_topology(project)
    audit = audit_wastewater_registry(project)
    warnings = list(dict.fromkeys(audit.errors + audit.warnings))
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

    def arrow(x, y, direction="right", scale=1.0):
        if direction == "left":
            G.append(
                f'<path d="M{x+11*scale},{y-7*scale} L{x},{y} '
                f'L{x+11*scale},{y+7*scale} Z" fill="{BLACK}"/>'
            )
        elif direction == "down":
            G.append(
                f'<path d="M{x-7*scale},{y-11*scale} L{x},{y} '
                f'L{x+7*scale},{y-11*scale} Z" fill="{BLACK}"/>'
            )
        else:
            G.append(
                f'<path d="M{x-11*scale},{y-7*scale} L{x},{y} '
                f'L{x-11*scale},{y+7*scale} Z" fill="{BLACK}"/>'
            )

    def pipe_mark(pipe: SewerPipeSpec) -> str:
        value = (
            f"{pipe.section_id} Ø{pipe.outer_diameter_mm:g}×"
            f"{pipe.wall_thickness_mm:g}"
        )
        if pipe.slope_per_mille is not None:
            value += f" i={pipe.slope_per_mille:g}‰"
        return value.replace(".", ",")

    def branch_mark(pipe: SewerPipeSpec) -> str:
        """Compact mark for a branch already identified in the room heading."""
        value = f"Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}"
        if pipe.slope_per_mille is not None:
            value += f"; i={pipe.slope_per_mille:g}‰"
        return value.replace(".", ",")

    def wrap_lines(value: str, width: int, limit: int = 2) -> List[str]:
        words = (value or "").split()
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if len(lines) > limit:
            lines = lines[:limit]
            lines[-1] = _short(lines[-1], max(4, width - 1))
        return lines or [""]

    # Заголовок.
    text(108, 74, "Принципиальная схема внутренних систем канализации и водоотведения", 22, weight="bold")
    text(
        108, 101,
        "ГОСТ Р 21.620-2023, п. 5.2.2.4; компоновка по рекомендуемому приложению В",
        12, color=GRAY,
    )

    top_floor = max(1, int(project.building.floors_above or 1))
    floors = _representative_floors(top_floor)
    levels = [top_floor + 1] + floors + [0]
    y_values = [165.0 + i * (1125.0 / max(1, len(levels) - 1)) for i in range(len(levels))]
    floor_y = dict(zip(levels, y_values))
    roof_y = floor_y[top_floor + 1]
    basement_y = floor_y[0]

    building_x1, building_x2 = 300.0, 2480.0
    line(building_x1, roof_y - 32, building_x1, basement_y + 18, 2.0)
    line(building_x2, roof_y - 32, building_x2, basement_y + 18, 2.0)
    for index, floor in enumerate(levels):
        y = floor_y[floor]
        line(building_x1, y, building_x2, y, 1.3, "#777")
        text(276, y - 12, _floor_title(floor, top_floor), 14, "end", "bold")
        text(276, y + 10, f"отм. {_fmt(_floor_mark(project, floor), 3)}", 9.5, "end", color=GRAY)
        if index and levels[index - 1] - floor > 1:
            omitted = levels[index - 1] - floor - 1
            mid = (floor_y[levels[index - 1]] + y) / 2
            # Разрыв повторяющихся этажей, как в приложении В.
            line(1110, mid - 10, 1132, mid + 10, 1.8)
            line(1132, mid - 10, 1154, mid + 10, 1.8)
            text(1170, mid + 5, f"пропущено {omitted} однотипных этажей", 9, color=GRAY)

    # Противопожарное перекрытие показывается только при подтверждённых муфтах.
    if any(row.kind == "fire_collar" for row in elements):
        line(building_x1, basement_y - 1, building_x2, basement_y - 1, 4.0, "#444")
        text(building_x1 + 8, basement_y - 10, "противопожарное перекрытие; проходки по узлам КР", 8.5, color=GRAY)

    risers_by_system: Dict[str, List[SewerPipeSpec]] = {"K1": [], "K2": [], "K3": []}
    for pipe in topology.risers.values():
        risers_by_system.setdefault(pipe.system, []).append(pipe)
    for rows in risers_by_system.values():
        rows.sort(key=lambda row: row.section_id)

    def distribute(rows: List[SewerPipeSpec], start: float, end: float) -> Dict[str, float]:
        if not rows:
            return {}
        if len(rows) == 1:
            return {rows[0].section_id: (start + end) / 2}
        step = (end - start) / (len(rows) - 1)
        return {row.section_id: start + index * step for index, row in enumerate(rows)}

    riser_x: Dict[str, float] = {}
    riser_x.update(distribute(risers_by_system.get("K1", []), 760, 1420))
    riser_x.update(distribute(risers_by_system.get("K3", []), 1580, 1720))
    riser_x.update(distribute(risers_by_system.get("K2", []), 2040, 2320))

    present = [system for system in ("K1", "K3", "K2") if risers_by_system.get(system)]
    system_titles = {
        "K1": (360, "К1 · ХОЗЯЙСТВЕННО-БЫТОВАЯ КАНАЛИЗАЦИЯ"),
        "K3": (1510, "К3 · ПРОИЗВОДСТВЕННАЯ КАНАЛИЗАЦИЯ"),
        "K2": (1930, "К2 · ВНУТРЕННИЙ ВОДОСТОК"),
    }
    for system in present:
        x, label = system_titles[system]
        text(x, 132, label, 12, weight="bold")

    # Условный архитектурный разрез нужен для читаемости инженерной схемы.
    # Помещения с приборами формируются ниже из реестра; остальная планировка
    # намеренно не восстанавливается и отсылается к разделу АР.
    room_band_h = 138.0
    for floor in floors:
        y = floor_y[floor]
        rect(760, y - room_band_h, 660, room_band_h, stroke="#999", fill="white", sw=0.9)
        text(1090, y - room_band_h / 2 - 4, "планировочная часть по АР", 8.2, "middle", color=GRAY)
        text(1090, y - room_band_h / 2 + 11, "помещения без подключений не раскрыты", 7.3, "middle", color=GRAY)
        line(1072, y - room_band_h / 2 + 30, 1090, y - room_band_h / 2 + 43, 1.4)
        line(1090, y - room_band_h / 2 + 30, 1108, y - room_band_h / 2 + 43, 1.4)
        rect(1880, y - room_band_h, 600, room_band_h, stroke="#999", fill="white", sw=0.9)
        text(2180, y - room_band_h + 18, "зона внутреннего водостока", 7.8, "middle", color=GRAY)
        for shaft_x in riser_x.values():
            if 1880 < shaft_x < 2480:
                rect(shaft_x - 34, y - room_band_h, 68, room_band_h, stroke="#777", fill="white", sw=1.0)

    # Стояки, вентиляционные части и направление стока.
    for riser_id, pipe in topology.risers.items():
        x = riser_x.get(riser_id)
        if x is None:
            continue
        line(x, roof_y - 44, x, basement_y + 25, 3.0)
        arrow(x, (roof_y + basement_y) / 2, "down", 0.78)
        label = (
            f"{riser_id} Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}"
        ).replace(".", ",")
        text(x - 10, (roof_y + basement_y) / 2 - 35, label, 10, "middle", "bold", rotate=-90)
        text(x + 12, roof_y - 24, _short(pipe.room, 31), 8, color=GRAY)
        if pipe.system in {"K1", "K3"}:
            line(x, roof_y - 74, x, roof_y - 44, 3.0)
            line(x - 10, roof_y - 74, x + 10, roof_y - 74, 2.0)
            text(x + 15, roof_y - 61, "+0,200 над кровлей", 8, color=GRAY)

    # Этажные ответвления и помещения — строго по ветвям топологического графа.
    branches_by_riser: Dict[str, List[SewerBranch]] = {}
    for branch in topology.branches:
        branches_by_riser.setdefault(branch.riser_id, []).append(branch)
    for riser_id, branches in branches_by_riser.items():
        x = riser_x.get(riser_id)
        if x is None:
            continue
        k1_rows = risers_by_system.get("K1", [])
        riser_index = next((i for i, row in enumerate(k1_rows) if row.section_id == riser_id), 0)
        side = -1 if riser_index % 2 == 0 else 1
        span = 460.0
        cell_w = span / max(1, len(branches))
        ordered = sorted(branches, key=lambda row: (row.room_number, row.pipe.section_id))
        for floor in floors:
            active = [row for row in ordered if row.floor_from <= floor <= row.floor_to]
            if not active:
                continue
            y = floor_y[floor]
            for branch_index, branch in enumerate(active):
                if side < 0:
                    cell_x = x - span + branch_index * cell_w
                else:
                    cell_x = x + branch_index * cell_w
                cell_right = cell_x + cell_w
                rect(cell_x, y - room_band_h, cell_w, room_band_h, stroke="#555", fill="white", sw=1.2)
                text(
                    cell_x + 8,
                    y - 119,
                    _short(f"№ {branch.room_number} · {branch.pipe.section_id}", 31),
                    9.0,
                    weight="bold",
                )
                text(cell_x + 8, y - 102, _short(branch.room_name, 34), 8.0, color=GRAY)
                branch_y = y - 18
                start_x = cell_x + 16 if side < 0 else cell_right - 16
                end_x = x
                line(start_x, branch_y, end_x, branch_y + (2 if side < 0 else -2), 2.2)
                arrow(
                    x - 12 if side < 0 else x + 12,
                    branch_y + (2 if side < 0 else -2),
                    "right" if side < 0 else "left",
                    0.55,
                )
                text(
                    (start_x + end_x) / 2,
                    branch_y - 10,
                    branch_mark(branch.pipe),
                    8.0,
                    "middle",
                    weight="bold",
                    color=GRAY,
                )
                fixtures = [row for row in branch.elements if _applies(row, floor)]
                if not fixtures:
                    continue
                usable_left = cell_x + 25
                usable_right = cell_right - 25
                step = (usable_right - usable_left) / max(1, len(fixtures))
                for element_index, row in enumerate(fixtures):
                    sx = usable_left + (element_index + 0.5) * step
                    sy = y - 69
                    G.append(render_ugo(row.kind, sx, sy, scale=0.72))
                    # Подключение прибора к ветви с характерным поворотом.
                    line(sx, sy + 20, sx, branch_y - 7, 1.45)
                    line(sx, branch_y - 7, sx + (8 if side < 0 else -8), branch_y, 1.45)
                    qty = f"{row.typical_quantity} шт." if row.typical_quantity else "—"
                    text(sx, y - 42, f"{qty}; DN{row.dn_mm or '—'}", 7.7, "middle")
                lowest = min(
                    (row.elevation_m for row in fixtures if row.elevation_m is not None),
                    default=None,
                )
                if lowest is not None:
                    text(
                        cell_right - 8,
                        y - 86,
                        f"низ {_fmt(lowest, 3)}",
                        7.5,
                        "end",
                        color=GRAY,
                    )

    # Ревизии и противопожарные муфты — на фактических стояках и этажах.
    for row in elements:
        x = riser_x.get(row.section_id)
        if x is None:
            continue
        if row.kind == "revision" and row.floor_from in floor_y:
            sy = floor_y[row.floor_from] - 45
            G.append(render_ugo("revision", x, sy, scale=0.65, rotation=90))
            text(x + 15, sy + 4, f"R · {row.element_id}", 7.5)
        elif row.kind == "fire_collar":
            for floor in floors:
                if _applies(row, floor):
                    G.append(render_ugo("fire_collar", x, floor_y[floor], scale=0.58, rotation=90))

    # Кровельные воронки. Электрообогрев отражается составным знаком приложения В.
    line(building_x1, roof_y - 38, building_x1, roof_y, 2.0)
    line(building_x2, roof_y - 38, building_x2, roof_y, 2.0)
    for row in elements:
        if row.kind != "roof_funnel":
            continue
        x = riser_x.get(row.section_id)
        if x is None:
            warnings.append(f"{row.element_id}: воронка не связана с известным стояком")
            continue
        count = min(3, max(1, row.quantity))
        offsets = [0] if count == 1 else [(-58 + i * 116 / (count - 1)) for i in range(count)]
        symbol_kind = (
            "roof_funnel_heated"
            if "электрообогрев" in (row.name or "").lower()
            else "roof_funnel"
        )
        for offset in offsets:
            sx, sy = x + offset, roof_y - 10
            G.append(render_ugo(symbol_kind, sx, sy, scale=0.82))
            line(sx, sy + 18, sx, roof_y + 30, 1.8)
            line(sx, roof_y + 30, x, roof_y + 42, 1.8)
            roof_slope = row.slope_per_mille if row.slope_per_mille is not None else 0.0
            text((sx + x) / 2, roof_y + 23, f"i={_fmt(roof_slope, 0)}‰", 7.2, "middle")
        text(
            x,
            roof_y + 59,
            f"{row.element_id}; {row.quantity} шт.; DN{row.dn_mm or '—'}",
            8.0,
            "middle",
            "bold",
        )

    # Магистрали и выпуски строятся как рёбра графа между узлами.
    main_y = {"K1": 1375.0, "K3": 1420.0, "K2": 1470.0}
    external_defaults = {"K1": 1690.0, "K3": 1820.0, "K2": 2570.0}
    node_x: Dict[str, float] = dict(riser_x)
    for system in ("K1", "K3", "K2"):
        rows = [row for row in topology.mains if row.system == system]
        if not rows:
            continue
        for _ in range(len(rows) + 2):
            changed = False
            for pipe in rows:
                a, b = pipe.from_node, pipe.to_node
                if a in node_x and b not in node_x:
                    node_x[b] = max(node_x[a] + 250, external_defaults[system])
                    changed = True
                elif b in node_x and a not in node_x:
                    node_x[a] = min(node_x[b] - 250, external_defaults[system] - 250)
                    changed = True
            if not changed:
                break
        unknown = sorted({n for row in rows for n in (row.from_node, row.to_node) if n not in node_x})
        for index, node in enumerate(unknown):
            node_x[node] = external_defaults[system] + index * 120

        y = main_y[system]
        text(min(node_x.get(row.from_node, 1000) for row in rows) - 28, y + 5, system, 14, "end", "bold")
        for pipe in rows:
            x1, x2 = node_x[pipe.from_node], node_x[pipe.to_node]
            line(x1, y, x2, y, 3.0)
            direction = "right" if x2 >= x1 else "left"
            arrow((x1 + x2) / 2, y, direction, 0.72)
            text((x1 + x2) / 2, y - 15, pipe_mark(pipe), 10, "middle", "bold")
            relative = f"отн. {_fmt(pipe.elevation_start_m, 2)} → {_fmt(pipe.elevation_end_m, 2)}"
            absolute = ""
            if pipe.absolute_elevation_start_m is not None:
                absolute = (
                    f"; абс. {_fmt(pipe.absolute_elevation_start_m, 2)} → "
                    f"{_fmt(pipe.absolute_elevation_end_m, 2)}"
                )
            text((x1 + x2) / 2, y + 21, relative + absolute, 8.4, "middle", color=GRAY)
            if pipe.absolute_elevation_start_m is not None:
                leader_end = min(x2 + 118, 2715)
                line(x2, y, min(x2 + 22, leader_end), y + 24, 1.1)
                line(min(x2 + 22, leader_end), y + 24, leader_end, y + 24, 1.1)
                text(
                    min(x2 + 28, leader_end),
                    y + 17,
                    f"Выпуск {pipe.section_id} Ø{pipe.outer_diameter_mm:g}",
                    8.0,
                    weight="bold",
                )
                text(
                    min(x2 + 28, leader_end),
                    y + 37,
                    f"абс. {_fmt(pipe.absolute_elevation_end_m, 3)}",
                    7.5,
                    color=GRAY,
                )
        for riser in risers_by_system.get(system, []):
            x = riser_x[riser.section_id]
            line(x, basement_y, x, y - 14, 2.5)
            G.append(
                f'<path d="M{x:.1f},{y-14:.1f} Q{x:.1f},{y:.1f} '
                f'{x+14:.1f},{y:.1f}" fill="none" stroke="{BLACK}" '
                f'stroke-width="2.5"/>'
            )
            G.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{BLACK}"/>')
        terminal_nodes = {
            row.to_node for row in rows
            if not any(other.from_node == row.to_node for other in rows)
        }
        for node in terminal_nodes:
            text(node_x[node], y + 52, f"к {node}", 7.5, "middle", "bold")

    # Прочистки на техподполье — только на подтверждённых участках.
    for row in elements:
        if row.kind != "cleanout":
            continue
        pipe = next((p for p in topology.mains if p.section_id == row.section_id), None)
        if pipe is not None and pipe.from_node in node_x and pipe.to_node in node_x:
            sx = (node_x[pipe.from_node] + node_x[pipe.to_node]) / 2
            sy = main_y[pipe.system]
        else:
            sx = riser_x.get(row.section_id)
            sy = basement_y - 24
        if sx is not None:
            G.append(render_ugo("cleanout", sx, sy, scale=0.62))
            text(sx, sy + 30, row.element_id, 7, "middle")

    # Компактная легенда внизу листа, как в приложении В.
    lx, ly, lw = 300.0, 1545.0, 1190.0
    legend = project_legend_definitions(project)
    legend_rows = max(1, (len(legend) + 1) // 2)
    legend_row_h = 29.0
    legend_h = 42.0 + legend_rows * legend_row_h
    rect(lx, ly, lw, legend_h, sw=1.4, fill="white")
    text(lx, ly - 11, "УСЛОВНЫЕ ОБОЗНАЧЕНИЯ", 10.5, weight="bold")
    col_w = lw / 2
    line(lx + col_w, ly, lx + col_w, ly + legend_h, 1.0)
    line(lx, ly + 30, lx + lw, ly + 30, 1.0)
    text(lx + lw - 8, ly + 20, "нормативная трассировка - лист 2", 7.2, "end", color=GRAY)
    for index, definition in enumerate(legend):
        col_index = index // legend_rows
        row_index = index % legend_rows
        x0 = lx + col_index * col_w
        y0 = ly + 30 + row_index * legend_row_h
        if row_index:
            line(x0, y0, x0 + col_w, y0, 0.65, "#999")
        sx = x0 + 38
        sy = y0 + legend_row_h / 2
        G.append(render_ugo(definition.key, sx, sy, scale=0.56))
        label_lines = wrap_lines(definition.label, 56, 2)
        baseline = sy - 3 if len(label_lines) > 1 else sy + 3
        for line_index, value in enumerate(label_lines):
            text(sx + 31, baseline + line_index * 10, value, 7.6)

    # Краткие проектные сведения на том же графическом листе.
    info_x, info_y, info_w, info_h = 1520.0, ly, 960.0, legend_h
    rect(info_x, info_y, info_w, info_h, sw=1.4, fill="white")
    text(info_x + 14, info_y + 22, "ДАННЫЕ И УКАЗАНИЯ К СХЕМЕ", 10.5, weight="bold")
    line(info_x, info_y + 30, info_x + info_w, info_y + 30, 1.0)
    storm = project.storm.result
    sewage = project.sewage.result
    q_k1 = _fmt(sewage.total.q_sewage_lps, 3) + " л/с" if sewage else "см. расчёт"
    q_k2 = _fmt(storm.q_total_l_per_s, 3) + " л/с" if storm else "см. расчёт"
    info_rows = [
        ("Граф", "проверен" if topology.ready else "требует данных"),
        ("Стояки / ветви / магистрали", f"{len(topology.risers)} / {len(topology.branches)} / {len(topology.mains)}"),
        ("К1", f"Q={q_k1}; сброс в {project.sewage.discharge_point_k1 or 'не задан'}"),
        ("К2", f"Q={q_k2}; сброс в {project.sewage.discharge_point_k2 or 'не задан'}"),
    ]
    for index, (label, value) in enumerate(info_rows):
        yy = info_y + 48 + index * 23
        text(info_x + 14, yy, label, 7.7, color=GRAY)
        text(info_x + 300, yy, value, 8.2, weight="bold")
    notes = [
        "1. Трассы показаны только по явным from_node/to_node и привязкам реестра.",
        "2. Повторяющиеся этажи показаны характерными; точная планировка - по АР.",
        "3. Электрообогрев воронок - по заданию ЭОМ; проходки - по узлам КР.",
        "4. Фасонные части и монтажные размеры уточняются на стадии Р.",
    ]
    for index, note in enumerate(notes):
        text(info_x + 14, info_y + 145 + index * 17, note, 7.3)
    status_color = BLACK if topology.ready else "#a00"
    text(
        info_x + info_w - 14,
        info_y + info_h - 12,
        "ТОПОЛОГИЯ ПРОШЛА ПРОВЕРКУ" if topology.ready else "ТОПОЛОГИЯ НЕПОЛНА",
        8.5,
        "end",
        weight="bold",
        color=status_color,
    )
    if warnings:
        text(info_x + 14, info_y + info_h - 12, _short(warnings[0], 94), 7.0, color=status_color)

    # Рамка и основная надпись формы 3.
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
    text(mmx(157.5), mmy(37), doc.sheet_no or "1", 11, "middle")
    text(mmx(175), mmy(37), doc.sheet_total or "2", 11, "middle")
    text(mmx(100), mmy(47), "Принципиальная схема внутренних систем", 10, "middle")
    text(mmx(100), mmy(53), ", ".join(present) or "К1, К2, К3", 12, "middle", "bold")
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
