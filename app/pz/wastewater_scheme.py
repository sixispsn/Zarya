"""Принципиальная схема К1/К2/К3 по явному топологическому графу.

Геометрия листа строится только из подтверждённых рёбер ``from_node`` /
``to_node`` и привязок элементов к этажным ответвлениям. Генератор не соединяет
стояки и магистрали по близости координат и не восстанавливает помещения.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from html import escape
from typing import Dict, Iterable, List, Optional, Tuple

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec
from app.pz.section_scaffold import build_section_scaffold
from app.pz.wastewater_registry import audit_wastewater_registry
from app.pz.wastewater_sp30 import audit_wastewater_sp30
from app.pz.wastewater_topology import SewerBranch, build_wastewater_topology
from app.pz.wastewater_ugo import project_legend_definitions, render_ugo


W, H = 2803, 1980  # А1, 841×594 мм
PXMM = W / 841
FONT = "osifont"
BLACK = "#000"
GRAY = "#555"
LIGHT = "#999"


@dataclass
class WastewaterSchemeResult:
    svg: str
    width: int = W
    height: int = H
    warnings: List[str] = field(default_factory=list)


class WastewaterSchemeScope(str, Enum):
    """Слой штатного генератора, используемый при поступенчатой сборке."""

    FULL = "full"
    BASEMENT_K1_MAIN = "basement_k1_main"


def _fmt(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def _short(value: str, limit: int) -> str:
    value = value or ""
    return value if len(value) <= limit else value[: max(1, limit - 1)] + "…"


def _applies(element: SewerElementSpec, floor: int) -> bool:
    end = element.floor_to if element.floor_to is not None else element.floor_from
    return element.floor_from <= floor <= end


def build_wastewater_scheme(
    project: Project,
    scope: WastewaterSchemeScope = WastewaterSchemeScope.FULL,
    *,
    focus_section_id: Optional[str] = None,
) -> WastewaterSchemeResult:
    doc = project.document
    elements = list(project.sewage.elements or [])
    topology = build_wastewater_topology(project)
    audit = audit_wastewater_registry(project)
    sp30_audit = audit_wastewater_sp30(project)
    warnings = list(dict.fromkeys(audit.errors + audit.warnings))
    full_scope = scope == WastewaterSchemeScope.FULL
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

    scaffold = build_section_scaffold(project)
    top_floor = scaffold.floors
    bands = list(scaffold.bands)
    visible_floors = [band.floor for band in bands]
    building_x1, building_x2 = scaffold.x_left, scaffold.x_right
    roof_y = scaffold.roof_y
    basement_y = scaffold.basement_y
    y_tech = scaffold.tech_y
    y_zero = scaffold.zero_y
    y_ground_bottom = scaffold.ground_bottom_y

    # Заголовок остаётся над архитектурным разрезом и не подменяет название в штампе.
    text(200, 42, "Принципиальная схема внутренних систем канализации и водоотведения", 19, weight="bold")
    text(
        200, 64,
        "ГОСТ Р 21.620-2023, п. 5.2.2.4; компоновка по рекомендуемому приложению В",
        10, color=GRAY,
    )

    def level_mark(y: float, title: str, mark: Optional[float]):
        line(scaffold.x_mark - 6, y, building_x1, y, 0.9)
        line(scaffold.x_mark - 7, y - 9, scaffold.x_mark, y, 1.1)
        line(scaffold.x_mark + 7, y - 9, scaffold.x_mark, y, 1.1)
        line(scaffold.x_mark, y, scaffold.x_mark, y - 26, 1.1)
        line(scaffold.x_mark - 102, y - 26, scaffold.x_mark, y - 26, 1.1)
        mark_text = (
            f"{mark:+.3f}".replace(".", ",")
            if mark is not None else "отм. по АР"
        )
        text(scaffold.x_mark - 4, y - 31, mark_text, 11, "end")
        text(scaffold.x_mark - 4, y - 11, title, 10, "end")

    # Тот же архитектурный каркас, масштаб и ритм этажей, что на листе В1/В2.
    for y in (roof_y, y_tech, y_zero, y_ground_bottom, basement_y):
        line(building_x1, y, building_x2, y, 1.2)
    line(building_x1, roof_y, building_x1, basement_y, 1.2)
    line(building_x2, roof_y, building_x2, basement_y, 1.2)
    for band in bands:
        line(building_x1, band.bottom_y, building_x2, band.bottom_y, 1.2)
        line(building_x1, band.bottom_y - scaffold.floor_band_h, building_x2,
             band.bottom_y - scaffold.floor_band_h, 1.2)

    floor_height = float(project.building.height_m or top_floor * 3.0) / max(1, top_floor)
    level_mark(roof_y, "Кровля", float(project.building.height_m or top_floor * floor_height))
    for band in bands:
        level_mark(band.bottom_y, f"{band.floor} этаж", (band.floor - 1) * floor_height)
    level_mark(y_zero, "1 этаж", 0.0)
    # Отметка лотка трубы не является отметкой пола/уровня. Пока отметка
    # техподполья не пришла из АР, на разрезе оставляем явное поле уточнения.
    level_mark(basement_y, "Техподполье", None)

    risers_by_system: Dict[str, List[SewerPipeSpec]] = {"K1": [], "K2": [], "K3": []}
    for pipe in topology.risers.values():
        risers_by_system.setdefault(pipe.system, []).append(pipe)
    for rows in risers_by_system.values():
        rows.sort(key=lambda row: row.section_id)

    def assign_axes(rows: List[SewerPipeSpec], candidates: List[float], system: str) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for index, row in enumerate(rows):
            if index >= len(candidates):
                warnings.append(
                    f"{system}: на принципиальном листе показаны первые {len(candidates)} стояков; "
                    "для остальных требуется дополнительный лист"
                )
                break
            result[row.section_id] = candidates[index]
        return result

    # Оси сгруппированы в тех же двух сантехнических шахтах, что В1/В2.
    riser_x: Dict[str, float] = {}
    riser_x.update(assign_axes(
        risers_by_system.get("K1", []),
        [scaffold.shaft_left_x, scaffold.shaft_right_x,
         scaffold.shaft_left_x - 24, scaffold.shaft_right_x + 24],
        "К1",
    ))
    riser_x.update(assign_axes(
        risers_by_system.get("K2", []),
        [scaffold.shaft_left_x + 24, scaffold.shaft_right_x - 24],
        "К2",
    ))
    riser_x.update(assign_axes(
        risers_by_system.get("K3", []),
        [scaffold.shaft_left_x - 24, scaffold.shaft_right_x + 24],
        "К3",
    ))
    present = [system for system in ("K1", "K2", "K3") if risers_by_system.get(system)]

    branches_by_riser: Dict[str, List[SewerBranch]] = {}
    for branch in topology.branches:
        branches_by_riser.setdefault(branch.riser_id, []).append(branch)
    for rows in branches_by_riser.values():
        rows.sort(key=lambda row: (row.room_number, row.pipe.section_id))

    left_slots = [scaffold.room_slots[0], scaffold.room_slots[1]]
    right_slots = [scaffold.room_slots[-2], scaffold.room_slots[-1]]
    branch_slots: Dict[str, List[Tuple[float, float]]] = {}
    for index, riser in enumerate(risers_by_system.get("K1", [])):
        slots = left_slots if index % 2 == 0 else right_slots
        branch_slots[riser.section_id] = [(slot.x0, slot.x1) for slot in slots]
        if len(branches_by_riser.get(riser.section_id, [])) > len(slots):
            warnings.append(
                f"{riser.section_id}: на характерном этаже показаны первые {len(slots)} ветви; "
                "остальные требуют отдельного фрагмента"
            )

    def room_shell(y_top: float, y_bottom: float):
        room_h = y_bottom - y_top
        for slot in scaffold.room_slots:
            rect(slot.x0, y_top, slot.x1 - slot.x0, room_h, sw=1.2)
            if slot.role == "shaft_left":
                text((slot.x0 + slot.x1) / 2, y_top + 18, "сантехническая шахта 1", 8, "middle")
            elif slot.role == "shaft_right":
                text((slot.x0 + slot.x1) / 2, y_top + 18, "сантехническая шахта 2", 8, "middle")
            elif slot.role in {"service", "lift"}:
                text((slot.x0 + slot.x1) / 2, y_top + 22, "планировочная", 7.5, "middle", color=GRAY)
                text((slot.x0 + slot.x1) / 2, y_top + 35, "часть по АР", 7.5, "middle", color=GRAY)

    for band in bands:
        room_shell(band.room_top_y, band.room_bottom_y)
        rect(building_x1, band.room_bottom_y, building_x2 - building_x1,
             scaffold.corridor_h, sw=1.2)
    # Первый этаж показан полноразмерной полосой в том же разрезе.
    room_shell(y_tech, y_zero)
    rect(building_x1, y_zero, building_x2 - building_x1,
         y_ground_bottom - y_zero, sw=1.2)

    def draw_branch(branch: SewerBranch, floor: int, x0: float, x1: float,
                    y_top: float, y_bottom: float, riser_axis: float,
                    branch_index: int):
        if not (branch.floor_from <= floor <= branch.floor_to):
            return
        room_h = y_bottom - y_top
        text(x0 + 8, y_top + 17,
             _short(f"№ {branch.room_number} · {branch.pipe.section_id}", 32),
             8.2, weight="bold")
        text(x0 + 8, y_top + 32, _short(branch.room_name, 38), 7.2, color=GRAY)
        side = 1 if riser_axis > (x0 + x1) / 2 else -1
        branch_y = y_bottom - 22 - branch_index * 24
        start_x = x0 + 18 if side > 0 else x1 - 18
        elbow_x = x1 - 16 if side > 0 else x0 + 16
        line(start_x, branch_y, elbow_x, branch_y, 2.2)
        line(elbow_x, branch_y, riser_axis, branch_y + 5, 2.2)
        arrow(riser_axis - 10 if side > 0 else riser_axis + 10,
              branch_y + 5, "right" if side > 0 else "left", 0.5)
        text((elbow_x + riser_axis) / 2, branch_y - 9,
             branch_mark(branch.pipe), 7.4, "middle", color=GRAY)
        fixtures = [row for row in branch.elements if _applies(row, floor)]
        if not fixtures:
            return
        usable_left, usable_right = x0 + 28, x1 - 28
        step = (usable_right - usable_left) / max(1, len(fixtures))
        symbol_y = y_top + min(92.0, room_h * 0.48)
        for element_index, row in enumerate(fixtures):
            sx = usable_left + (element_index + 0.5) * step
            G.append(render_ugo(row.kind, sx, symbol_y, scale=0.72))
            line(sx, symbol_y + 20, sx, branch_y - 7, 1.45)
            line(sx, branch_y - 7, sx + (7 if side > 0 else -7), branch_y, 1.45)
            qty = f"{row.typical_quantity} шт." if row.typical_quantity else "1 шт."
            text(sx, symbol_y + 34, f"{qty}; DN{row.dn_mm or '—'}", 6.8, "middle")
        lowest = min(
            (row.elevation_m for row in fixtures if row.elevation_m is not None),
            default=None,
        )
        if lowest is not None:
            text(x1 - 7, y_top + 47, f"низ {_fmt(lowest, 3)}", 6.8, "end", color=GRAY)

    def draw_floor_branches(floor: int, y_top: float, y_bottom: float):
        for riser_id, slots in branch_slots.items():
            axis = riser_x.get(riser_id)
            if axis is None:
                continue
            for index, branch in enumerate(branches_by_riser.get(riser_id, [])[:len(slots)]):
                x0, x1 = slots[index]
                draw_branch(branch, floor, x0, x1, y_top, y_bottom, axis, index)

    if full_scope:
        for band in bands:
            draw_floor_branches(band.floor, band.room_top_y, band.room_bottom_y)
        draw_floor_branches(1, y_tech, y_zero)

    main_y = {"K1": 1490.0, "K3": 1560.0, "K2": 1640.0}
    # Узел присоединения магистрали расположен после составного нижнего
    # поворота. Смещение образует две смены направления по 45°, а не один
    # графический отвод 87,5° (СП 30.13330.2020, п. 18.4).
    lower_bend_dx = 20.0
    main_connection_x = {
        riser_id: x + lower_bend_dx for riser_id, x in riser_x.items()
    }
    # Стояки проходят по общим шахтам; нижний поворот привязан к своей магистрали.
    for riser_id, pipe in topology.risers.items():
        x = riser_x.get(riser_id)
        if x is None:
            continue
        if not full_scope:
            continue
        target_y = main_y.get(pipe.system, 1490.0)
        start_y = roof_y if pipe.system == "K2" else roof_y - 30
        line(x, start_y, x, target_y - lower_bend_dx, 2.6)
        G.append(
            f'<path d="M{x:.1f},{target_y-lower_bend_dx:.1f} '
            f'L{x+lower_bend_dx:.1f},{target_y:.1f}" fill="none" '
            f'stroke="{BLACK}" stroke-width="2.6"/>'
        )
        label = f"Ст.{riser_id} Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}".replace(".", ",")
        label_y = 610.0 if x < (scaffold.shaft_left_x + scaffold.shaft_right_x) / 2 else 650.0
        text(x + (13 if pipe.system != "K2" else -13), label_y,
             label, 9, "middle", "bold", rotate=-90)
        for band in bands:
            arrow(x, band.bottom_y - 10, "down", 0.52)
        arrow(x, y_zero - 10, "down", 0.52)
        if pipe.system in {"K1", "K3"}:
            line(x, roof_y - 48, x, roof_y - 30, 2.6)
            line(x - 9, roof_y - 48, x + 9, roof_y - 48, 1.6)
            text(x + 13, roof_y - 35, "+0,200", 7.2, color=GRAY)

    # Кровельные воронки и сборные участки показываются составным знаком УГО.
    for row in elements if full_scope else []:
        if row.kind != "roof_funnel":
            continue
        x = riser_x.get(row.section_id)
        if x is None:
            warnings.append(f"{row.element_id}: воронка не связана с известным стояком")
            continue
        count = min(3, max(1, row.quantity))
        offsets = [0.0] if count == 1 else [(-42 + i * 84 / (count - 1)) for i in range(count)]
        symbol_kind = (
            "roof_funnel_heated"
            if "электрообогрев" in (row.name or "").lower()
            else "roof_funnel"
        )
        for offset in offsets:
            sx, sy = x + offset, roof_y - 12
            G.append(render_ugo(symbol_kind, sx, sy, scale=0.72))
            line(sx, sy + 17, sx, roof_y + 25, 1.8)
            line(sx, roof_y + 25, x, roof_y + 36, 1.8)
        text(x, roof_y + 55,
             f"{row.element_id}; {row.quantity} шт.; DN{row.dn_mm or '—'}",
             7.5, "middle", "bold")

    # Ревизии и противопожарные муфты ставятся только из реестра.
    band_by_floor = {band.floor: band for band in bands}
    rupture_y = None
    if scaffold.has_rupture and len(bands) >= 2:
        rupture_y = (bands[-1].bottom_y + bands[-2].room_top_y) / 2
    for row in elements if full_scope else []:
        x = riser_x.get(row.section_id)
        if x is None:
            continue
        if row.kind == "revision":
            if row.floor_from == 1:
                sy = y_zero - 45
            elif row.floor_from in band_by_floor:
                sy = band_by_floor[row.floor_from].bottom_y - 45
            else:
                continue
            G.append(
                f'<g data-element-id="{escape(row.element_id)}">'
                f'{render_ugo("revision", x, sy, scale=0.64, rotation=90)}</g>'
            )
            text(x + 15, sy + 3, f"R · {row.element_id}", 7.1)
        elif row.kind == "fire_collar":
            shown = [1] + visible_floors
            for floor in shown:
                if not _applies(row, floor):
                    continue
                sy = y_zero if floor == 1 else band_by_floor[floor].bottom_y
                G.append(render_ugo("fire_collar", x, sy, scale=0.54, rotation=90))

    if full_scope and any(row.kind == "fire_collar" for row in elements):
        line(building_x1, y_ground_bottom - 1, building_x2, y_ground_bottom - 1, 3.2)
        text(building_x1 + 8, y_ground_bottom - 9,
             "противопожарное перекрытие; муфты в проходках по узлам КР", 7.8, color=GRAY)

    # Магистрали и выпуски — рёбра явного графа from_node/to_node.
    external_defaults = {"K1": 2160.0, "K3": 2220.0, "K2": 2160.0}
    node_x: Dict[str, float] = dict(main_connection_x)
    stage_focus = focus_section_id
    if not full_scope and not stage_focus:
        stage_focus = next(
            (row.section_id for row in topology.mains if row.system == "K1"),
            None,
        )
    if not full_scope and not stage_focus:
        raise ValueError("для поступенчатого листа отсутствует подвальная магистраль К1")

    for system in ("K1", "K3", "K2"):
        rows = [row for row in topology.mains if row.system == system]
        if not full_scope:
            rows = [row for row in rows if row.section_id == stage_focus]
        if not rows:
            continue
        for _ in range(len(rows) + 2):
            changed = False
            for pipe in rows:
                a, b = pipe.from_node, pipe.to_node
                if a in node_x and b not in node_x:
                    node_x[b] = max(node_x[a] + 260, external_defaults[system])
                    changed = True
                elif b in node_x and a not in node_x:
                    node_x[a] = min(node_x[b] - 260, external_defaults[system] - 260)
                    changed = True
            if not changed:
                break
        unknown = sorted({node for pipe in rows for node in (pipe.from_node, pipe.to_node) if node not in node_x})
        for index, node in enumerate(unknown):
            node_x[node] = external_defaults[system] + index * 90
        y = main_y[system]
        if not full_scope:
            # На первом инженерном слое показываем только реальные нижние
            # окончания стояков, к которым присоединён выбранный участок.
            endpoint_nodes = {node for row in rows for node in (row.from_node, row.to_node)}
            for node in sorted(endpoint_nodes):
                x = node_x.get(node)
                if x is None:
                    continue
                riser_axis = riser_x.get(node, x - lower_bend_dx)
                line(riser_axis, y_ground_bottom, riser_axis,
                     y - lower_bend_dx, 2.6)
                G.append(
                    f'<path d="M{riser_axis:.1f},{y-lower_bend_dx:.1f} '
                    f'L{x:.1f},{y:.1f}" fill="none" stroke="{BLACK}" '
                    'stroke-width="2.6"/>'
                )
        text(min(node_x.get(row.from_node, 1000) for row in rows) - 30,
             y + 5, system, 13, "end", "bold")
        for pipe in rows:
            x1, x2 = node_x[pipe.from_node], node_x[pipe.to_node]
            line(x1, y, x2, y, 2.8)
            arrow((x1 + x2) / 2, y, "right" if x2 >= x1 else "left", 0.62)
            text((x1 + x2) / 2, y - 13, pipe_mark(pipe), 8.5, "middle", "bold")
            relative = f"отн. {_fmt(pipe.elevation_start_m, 2)} → {_fmt(pipe.elevation_end_m, 2)}"
            absolute = ""
            if pipe.absolute_elevation_start_m is not None:
                absolute = (
                    f"; абс. {_fmt(pipe.absolute_elevation_start_m, 2)} → "
                    f"{_fmt(pipe.absolute_elevation_end_m, 2)}"
                )
            text((x1 + x2) / 2, y + 18, relative + absolute, 7.3, "middle", color=GRAY)
            if pipe.absolute_elevation_start_m is not None:
                leader_end = min(x2 + 92, 2650)
                line(x2, y, min(x2 + 20, leader_end), y - 34, 1.0)
                line(min(x2 + 20, leader_end), y - 34, leader_end, y - 34, 1.0)
                text(min(x2 + 25, leader_end), y - 40,
                     f"Выпуск {pipe.section_id} Ø{pipe.outer_diameter_mm:g}",
                     7.4, weight="bold")
                text(min(x2 + 25, leader_end), y - 24,
                     f"абс. {_fmt(pipe.absolute_elevation_end_m, 3)}", 7.0, color=GRAY)
                outlet = next((row for row in elements if row.kind == "outlet" and row.section_id == pipe.section_id), None)
                if outlet is not None:
                    G.append(render_ugo("outlet", x2, y, scale=0.55))
        if full_scope:
            terminal_nodes = {
                row.to_node for row in rows
                if not any(other.from_node == row.to_node for other in rows)
            }
            for node in terminal_nodes:
                text(node_x[node], y + 38, f"к {node}", 7.2, "middle", "bold")

    # Прочистки — на подтверждённых участках/стояках.
    for row in elements if full_scope else []:
        if row.kind != "cleanout":
            continue
        sx = sy = None
        pipe = None
        if row.connects_to and row.connects_to in node_x:
            sx = node_x[row.connects_to]
            pipe = next(
                (p for p in topology.mains if p.section_id == row.section_id),
                None,
            )
            sy = main_y[pipe.system] if pipe is not None else None
        else:
            pipe = next((p for p in topology.mains if p.section_id == row.section_id), None)
        if (
            not row.connects_to
            and pipe is not None
            and pipe.from_node in node_x
            and pipe.to_node in node_x
        ):
            sx = (node_x[pipe.from_node] + node_x[pipe.to_node]) / 2
            sy = main_y[pipe.system]
        elif not row.connects_to:
            riser = topology.risers.get(row.section_id)
            sx = riser_x.get(row.section_id)
            sy = main_y.get(riser.system, 1490.0) - 34 if riser else None
        if sx is not None and sy is not None:
            G.append(
                f'<g data-element-id="{escape(row.element_id)}">'
                f'{render_ugo("cleanout", sx, sy, scale=0.60)}</g>'
            )
            text(sx, sy + 27, row.element_id, 6.8, "middle")

    # Графический разрыв повторяющихся этажей выполняется после трубопроводов.
    if rupture_y is not None:
        gap = 24.0
        G.append(
            f'<rect x="{building_x1-5:.1f}" y="{rupture_y-gap/2:.1f}" '
            f'width="{building_x2-building_x1+10:.1f}" height="{gap:.1f}" fill="white"/>'
        )
        for yy in (rupture_y - gap / 2, rupture_y + gap / 2):
            for z in (building_x1 + 520, building_x2 - 520):
                line(z - 9, yy, z - 3, yy - 12, 0.9)
                line(z - 3, yy - 12, z + 3, yy + 12, 0.9)
                line(z + 3, yy + 12, z + 9, yy, 0.9)
        omitted_start = (bands[-2].floor + 1) if len(bands) >= 2 else 2
        omitted_end = top_floor - 1
        if omitted_end >= omitted_start:
            text(building_x1 + 16, rupture_y + 4,
                 f"этажи {omitted_start}–{omitted_end} повторяются", 7.8, color=GRAY)
        # Ревизии на конкретном пропущенном этаже не теряются в графическом
        # разрыве: знак и марка остаются на оси соответствующего стояка.
        omitted_revisions: Dict[str, List[SewerElementSpec]] = {}
        for row in elements if full_scope else []:
            if row.kind == "revision" and omitted_start <= row.floor_from <= omitted_end:
                omitted_revisions.setdefault(row.section_id, []).append(row)
        for section_id, rows in sorted(omitted_revisions.items()):
            x = riser_x.get(section_id)
            if x is None:
                continue
            rows.sort(key=lambda row: (row.floor_from, row.element_id))
            ids = " ".join(escape(row.element_id) for row in rows)
            floors = ", ".join(str(row.floor_from) for row in rows)
            G.append(
                f'<g data-element-ids="{ids}">'
                f'{render_ugo("revision", x, rupture_y, scale=0.64, rotation=90)}</g>'
            )
            text(x + 15, rupture_y + 3, f"R · эт. {floors}", 7.1)

    if full_scope:
        # Компактная легенда и исходные данные размещаются ниже разреза, как в приложении В.
        lx, ly, lw = 200.0, 1742.0, 1240.0
        legend = project_legend_definitions(project)
        legend_rows = max(1, (len(legend) + 1) // 2)
        legend_row_h = 22.0
        legend_h = 29.0 + legend_rows * legend_row_h
        rect(lx, ly, lw, legend_h, sw=1.2, fill="white")
        text(lx + 8, ly + 19, "УСЛОВНЫЕ ОБОЗНАЧЕНИЯ", 8.8, weight="bold")
        text(lx + lw - 8, ly + 19, "нормативная трассировка - лист 2", 6.5, "end", color=GRAY)
        line(lx, ly + 27, lx + lw, ly + 27, 0.9)
        col_w = lw / 2
        line(lx + col_w, ly + 27, lx + col_w, ly + legend_h, 0.8)
        for index, definition in enumerate(legend):
            col_index = index // legend_rows
            row_index = index % legend_rows
            x0 = lx + col_index * col_w
            y0 = ly + 27 + row_index * legend_row_h
            if row_index:
                line(x0, y0, x0 + col_w, y0, 0.55, LIGHT)
            sx, sy = x0 + 31, y0 + legend_row_h / 2
            G.append(render_ugo(definition.key, sx, sy, scale=0.46))
            text(sx + 25, sy + 3, _short(definition.label, 62), 6.7)

        info_x, info_y, info_w, info_h = 1460.0, ly, 680.0, legend_h
        rect(info_x, info_y, info_w, info_h, sw=1.2, fill="white")
        text(info_x + 10, info_y + 19, "ДАННЫЕ И УКАЗАНИЯ К СХЕМЕ", 8.8, weight="bold")
        line(info_x, info_y + 27, info_x + info_w, info_y + 27, 0.9)
        storm = project.storm.result
        sewage = project.sewage.result
        q_k1 = _fmt(sewage.total.q_sewage_lps, 3) + " л/с" if sewage else "см. расчёт"
        q_k2 = _fmt(storm.q_total_l_per_s, 3) + " л/с" if storm else "см. расчёт"
        info_rows = [
            f"Граф: {'проверен' if topology.ready else 'требует данных'}; "
            f"стояки / ветви / магистрали: {len(topology.risers)} / {len(topology.branches)} / {len(topology.mains)}",
            f"К1: Q={q_k1}; сброс в {project.sewage.discharge_point_k1 or 'не задан'}",
            f"К2: Q={q_k2}; сброс в {project.sewage.discharge_point_k2 or 'не задан'}",
            "Трассы — только по from_node/to_node; планировка — по АР.",
            "Проходки — по узлам КР; электрообогрев воронок — по заданию ЭОМ.",
            (
                "СП 30: ревизии и повороты проверены; п. 18.30 — после "
                "линейной привязки точек обслуживания."
                if sp30_audit.ready
                else "СП 30: монтажная топология требует исправления."
            ),
        ]
        for index, value in enumerate(info_rows):
            text(info_x + 10, info_y + 44 + index * 18, _short(value, 100), 6.9)
        status_color = BLACK if topology.ready else "#a00"
        text(info_x + info_w - 10, info_y + info_h - 9,
             "ТОПОЛОГИЯ ПРОШЛА ПРОВЕРКУ" if topology.ready else "ТОПОЛОГИЯ НЕПОЛНА",
             7.5, "end", "bold", status_color)
        if warnings:
            text(info_x + 10, info_y + info_h - 9, _short(warnings[0], 64), 6.2, color=status_color)

    if not full_scope:
        # Плита из приложения В: конструктивная штриховка показана только на
        # промежуточном листе, пока нижняя зона не занята легендой.
        slab_y, slab_h = basement_y, 74.0
        rect(building_x1, slab_y, building_x2 - building_x1, slab_h, sw=1.5, fill="white")
        step = 26.0
        x = building_x1 - slab_h
        while x < building_x2:
            line(max(building_x1, x), slab_y + slab_h,
                 min(building_x2, x + slab_h), slab_y, 0.85, color=GRAY)
            x += step

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
    shown_present = present if full_scope else ["К1"]
    text(mmx(100), mmy(47), "Принципиальная схема внутренних систем", 10, "middle")
    text(mmx(100), mmy(53), ", ".join(shown_present) or "К1", 12, "middle", "bold")
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
