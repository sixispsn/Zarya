"""Vector building section from the second-house study, never a plan sheet.

The uncalibrated JPG supplies room/stack associations, NOT metre coordinates.
Canonical apartment assemblies are used as drawing templates only. Their
local origins and graphic slopes must not become this house's design levels
or grades. Unknown values remain explicit; this is not a production release.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

from app.architecture.residential_plan_study import PlanStudy
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.drawing_sheet_style import FittingGraphicSize
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderPlacement, LeaderRequest, _text_width
from app.pz.small_residential_preview import _arrow, _floor_geometry, _revision
from app.pz.small_residential_section import _label, _slope_mark
from app.pz.study_graphic_frame import study_notes_svg, study_section_frame, validate_study_section_frame
from app.pz.wastewater_basement_profile import STYLE, _line, _text
from app.pz.wastewater_drafting import render_lower_turn_assembly_svg
from app.pz.wastewater_floor_drafting import (
    FloorFixtureInput, WastewaterFloorAssembly, build_typical_floor_assembly,
)
from app.pz.wastewater_ugo import REVISION_CENTRE_ANCHOR, render_ugo

LEFT, RIGHT, ROOF, BASEMENT = 63., 545., 96., 306.
FLOOR_Y = {1: 242., 2: 170.}
FLOOR_SCALE = .31
MAIN_Y, NODE_SCALE = 270., .17


def _leader(key, target, title, detail, bounds, side=1, height=3.5,
            vertical_offsets_mm=(18., 24., 30., 36.), below=False):
    return LeaderLayoutEngine(bounds=LeaderBounds(*bounds), units_per_mm=1,
                              horizontal_offsets_mm=(4., 6., 10., 18., 24.),
                              vertical_offsets_mm=vertical_offsets_mm).place_and_render(
        LeaderRequest(key, key, target, title, detail, preferred_side=side,
                      preferred_vertical=1 if below else -1, text_height_mm=height))


@dataclass(frozen=True)
class SectionBay:
    stack: str
    left: float
    right: float
    axis: float
    mirrored: bool

    def point(self, assembly: WastewaterFloorAssembly, port: str, floor: int,
              *, floor_y: float | None = None) -> tuple[float, float]:
        p, join = assembly.port(port).point, assembly.port("riser_join").point
        sign = -1 if self.mirrored else 1
        fy = FLOOR_Y[floor] if floor_y is None else floor_y
        return self.axis+sign*(p.x_mm-join.x_mm)*FLOOR_SCALE, fy+(p.y_mm-212)*FLOOR_SCALE


def section_bays(study: PlanStudy) -> tuple[SectionBay, ...]:
    study.validate()
    if set(study.floors) != {1, 2} or len(study.routes) != 2:
        raise ValueError("this composition needs two observed floors and two sections")
    bays: list[SectionBay] = []
    # Pack schematic room bays by their order in AR. These are paper mm, not
    # scaled plan distances. The same bay axis drives floors AND lower nodes.
    for section, left in zip(sorted({r.section for r in study.routes}), (63., 309.), strict=True):
        groups = sorted((g for g in study.groups if g.section == section), key=lambda g: g.position[0])
        if len(groups) != 2:
            raise ValueError("a different room programme needs a different section composition")
        bays.extend((SectionBay(groups[0].stack, left, left+101, left+95, False),
                     SectionBay(groups[1].stack, left+135, left+236, left+141, True)))
    return tuple(bays)


def floor_templates(study: PlanStudy) -> dict[tuple[str, int], WastewaterFloorAssembly]:
    """Reuse accepted UGO, traps, reducer-before-WC and connected fitting graph.

    Zero is a local drawing origin, not an assigned floor elevation. Existing
    template DN50/100 and grades serve the symbols only; do not export these
    as confirmed engineering parameters for this new source.
    """
    return {(g.stack, floor): build_typical_floor_assembly(
        assembly_id=f"{g.stack}:F{floor}", riser_id=g.stack, floor_no=floor,
        floor_elevation_m=0., fixtures=tuple(
            FloorFixtureInput(kind, kind, "Кухня" if kind == "sink" else "Санузел")
            for kind in ("sink", "bath", "washbasin", "toilet")),
    ) for g in study.groups for floor in study.floors}


def fixture_paths(study: PlanStudy, templates: dict[tuple[str, int], WastewaterFloorAssembly]) -> dict[str, tuple[str, ...]]:
    """Check individual fixture outlets, not merely the earlier group nodes."""
    graph = dict(study.edges())
    sources: list[str] = []
    for (stack, floor), assembly in templates.items():
        if assembly.validate():
            raise ValueError("invalid canonical apartment")
        prefix = f"{stack}:F{floor}:"
        pairs = [(s.start_port_id, s.end_port_id) for s in assembly.segments if s.carries_flow]
        pairs += [(j.start_port_id, j.end_port_id) for j in assembly.direct_fitting_joints]
        pairs += [(f.trap_inlet_port_id, f.trap_outlet_port_id) for f in assembly.fixtures if f.trap_mode == "external"]
        graph.update((prefix+a, prefix+b) for a, b in pairs)
        # From the branch join into the study's vertical chain. Do not follow
        # the template's schematic below-floor tail as another real storey.
        graph[prefix+"riser_join"] = f"{stack}:F{floor}"
        sources.extend(prefix+f.fixture_outlet_port_id for f in assembly.fixtures)
    outlets = {r.outlet for r in study.routes}
    paths = {}
    for source in sources:
        path, current = [], source
        while current not in outlets:
            if current in path or current not in graph:
                raise ValueError(f"{source}: fixture disconnected from outlet")
            path.append(current)
            current = graph[current]
        paths[source] = tuple((*path, current))
    return paths


def _unknown_slope(key: str, x: float, y: float, direction: int) -> str:
    # Same 3.5 mm size and acute-angle convention as known-grade annotations.
    width = _text_width("н/д", STYLE.font_size(3.5, 1))
    span = width+1.5+4.
    arm_x = x+span/2-4 if direction > 0 else x-span/2+4
    text_x = x-span/2 if direction > 0 else arm_x+1.5
    return (f'<g data-unbound-slope="{escape(key)}" data-direction="{direction}" '
            'data-text-height-mm="3.5">'+_text(text_x, y, "н/д")+
            f'<path d="M{arm_x:g},{y-2.5:g} L{arm_x+direction*4:g},{y:g} L{arm_x:g},{y:g}" '
            'fill="none" stroke="black" stroke-width=".25"/></g>')


def _floor(assembly: WastewaterFloorAssembly, bay: SectionBay, floor: int, *,
           floor_y: float | None = None, grades: tuple[float, float] | None = None,
           revision: bool = True, grade_basis: str = "",
           outside_cleanout_labels: bool = False) -> str:
    fy, axis, s = FLOOR_Y[floor] if floor_y is None else floor_y, bay.axis, FLOOR_SCALE
    tx, ty = axis-assembly.port("riser_join").point.x_mm*s, fy-212*s
    mirror = f'translate({2*axis:g} 0) scale(-1 1)' if bay.mirrored else ""
    geometry = ET.fromstring(_floor_geometry(assembly, scale=s))
    geometry.attrib.pop("data-floor-elevation-m", None)
    sign = -1 if bay.mirrored else 1
    key = f"{bay.stack}:F{floor}"
    parts = [f'<g data-section-apartment="{key}" data-stack-x="{axis:g}" data-floor="{floor}" '
             f'data-engineering-state="{"normative-floor-branches" if grade_basis else "explicit-study" if grades else "unbound-template"}" '
             f'data-grade-basis="{escape(grade_basis)}">',
             f'<g transform="{mirror}"><g transform="translate({tx:g} {ty:g}) scale({s})">',
             ET.tostring(geometry, encoding="unicode"), '</g></g>']
    count = len(assembly.fixtures)
    for a, b, dn in ((f"junction_{count-2}", f"junction_{count-1}", 50), (f"junction_{count}", "riser_branch_elbow", 100)):
        p, q = bay.point(assembly, a, floor, floor_y=fy), bay.point(assembly, b, floor, floor_y=fy)
        centre = (p[0]+q[0])/2
        left, right = sorted((p, q))
        parts.append(_label(key+f"-dn{dn}", f"К1 ⌀{dn}"+('' if grades else '*'), left, right, height=2.5))
        if grades:
            parts.append(_slope_mark(key+f"-grade{dn}", p, q, grades[0 if dn == 50 else 1], centre_x=centre-sign*2,
                extra=f'data-grade-basis="{escape(grade_basis)}"' if grade_basis else ""))
        else:
            parts.append(_unknown_slope(key+f"-grade{dn}", centre-sign*2, min(p[1], q[1])-4, sign))
    cap = bay.point(assembly, "cleanout_cap", floor, floor_y=fy)
    # Dedicated annotation pocket above the kitchen sink. The oblique arm
    # passes OUTSIDE the sink/trap, rather than through their bounding box.
    knee = bay.right-2 if bay.mirrored else bay.left+2
    shelf = knee+sign*14
    if outside_cleanout_labels:
        # Compact A3 bays reserve the side margins for service annotations;
        # neither kitchen headings nor fixture symbols occupy this pocket.
        knee = bay.right+2 if bay.mirrored else bay.left-2
        shelf = bay.right+14 if bay.mirrored else bay.left-15
    lo, hi = sorted((knee, shelf))
    sy, font = fy-42, STYLE.font_size(3.5, 1)
    placement = LeaderPlacement((knee, sy), (shelf, sy), (lo, sy-font-1, hi, sy+font+2),
                                (lo+1, sy-1), (lo+1, sy+font+1), font)
    parts.append(LeaderLayoutEngine(bounds=LeaderBounds(lo, fy-50, hi, fy-30), units_per_mm=1).render(
        LeaderRequest(key+"-cleanout", key+"-cleanout", cap, "Пр.", "DN50"+('' if grades else '*')), placement))
    if not revision:
        return ''.join((*parts, '</g>'))
    if not bay.mirrored:
        parts.extend(_revision(axis, fy, 20))
    else:
        centre = fy-20
        parts.extend((f'<g data-riser-revision="true" data-centre-y="{centre:g}" data-floor-y="{fy:g}">',
                      render_ugo("revision", axis, centre-REVISION_CENTRE_ANCHOR[0]*.2, scale=.2, rotation=90),
                      _line(axis-6, centre, axis-6, fy), _line(axis-8, centre, axis-1, centre),
                      _line(axis-8, fy, axis-1, fy), _line(axis-7, centre+1, axis-5, centre-1),
                      _line(axis-7, fy+1, axis-5, fy-1),
                      _text(axis-8, fy-10, "1000", anchor="middle",
                            marker=f'transform="rotate(-90 {axis-8:g} {fy-10:g})"'), '</g>'))
    parts.extend((_text(axis+sign*10, fy-22, "R", anchor="middle"), '</g>'))
    return ''.join(parts)


def build_plan_section_svg(study: PlanStudy) -> str:
    bays, templates = section_bays(study), floor_templates(study)
    paths = fixture_paths(study, templates)
    axis = {b.stack: b.axis for b in bays}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" '
             f'data-view="principle-section" data-release-ready="false" data-fixture-paths="{len(paths)}">',
             '<defs><pattern id="slab" width="5" height="5" patternUnits="userSpaceOnUse">'
             '<path d="M-1,1 L1,-1 M0,5 L5,0 M4,6 L6,4" stroke="black" stroke-width=".25"/>'
             '</pattern></defs><rect width="594" height="420" fill="white"/>',
             _text(29, 19, "Принципиальная схема бытовой канализации К1", height=5),
             _text(29, 27, "Второй жилой пример · развёрнутый разрез двух секций", height=3.5)]
    # Architectural backdrop: no plan view, raster, dimension chain or fake AR
    # room numbers. Room width is composition; building levels remain unknown.
    parts.extend((f'<path d="M{LEFT-3:g},{ROOF:g} L100,78 H508 L{RIGHT+3:g},{ROOF:g}" '
                  'fill="none" stroke="black" stroke-width=".35"/>',
                  _line(LEFT, ROOF, RIGHT, ROOF, width=.35),
                  _line(LEFT, ROOF, LEFT, BASEMENT+8, width=.35),
                  _line(RIGHT, ROOF, RIGHT, BASEMENT+8, width=.35),
                  _line(LEFT+2, ROOF, LEFT+2, BASEMENT, width=.25),
                  _line(RIGHT-2, ROOF, RIGHT-2, BASEMENT, width=.25)))
    for floor, fy in sorted(FLOOR_Y.items(), reverse=True):
        top = ROOF+3 if floor == 2 else FLOOR_Y[2]+3
        parts.append(f'<rect data-floor-boundary="{floor}" x="{LEFT:g}" y="{fy:g}" width="{RIGHT-LEFT:g}" '
                     'height="3" fill="url(#slab)" stroke="black" stroke-width=".25"/>')
        parts.extend((_text(26, fy-7, f"{floor} этаж"), _text(26, fy-1, "отм. н/д", height=2.5),
                      _line(27, fy+1, LEFT, fy+1)))
        for index, bay in enumerate(bays):
            wall = bay.right-23 if bay.mirrored else bay.left+23
            for x in (bay.left, wall, bay.right):
                parts.append(_line(x, top, x, fy, marker='data-room-boundary="true"'))
            kitchen_x = (wall+bay.right)/2 if bay.mirrored else (bay.left+wall)/2
            sanitary_x = (bay.left+wall)/2 if bay.mirrored else (wall+bay.right)/2
            parts.extend((_text(kitchen_x, top+8, "Кухня", anchor="middle"),
                          _text(sanitary_x, top+8, "Санузел", anchor="middle"),
                          _text(kitchen_x, top+14, f"группа {index+1}", anchor="middle", height=2.5)))
        for x in (181., 427.):
            parts.extend((_text(x, top+9, "Лестничная", anchor="middle", height=2.5),
                          _text(x, top+15, "клетка", anchor="middle", height=2.5)))
    parts.extend((f'<rect x="{LEFT:g}" y="{BASEMENT:g}" width="{RIGHT-LEFT:g}" height="8" '
                  'fill="url(#slab)" stroke="black" stroke-width=".35"/>',
                  _line(304, ROOF, 304, BASEMENT, width=.25),
                  _text(26, BASEMENT-7, "Подвал"), _text(26, BASEMENT-1, "отм. н/д", height=2.5),
                  _line(27, BASEMENT+1, LEFT, BASEMENT+1),
                  _text(181, 299, "Подвал секции 1 (условно)", anchor="middle"),
                  _text(427, 299, "Подвал секции 2 (условно)", anchor="middle")))
    # Open fan terminals; dimensions are unbound, never inherited from the
    # first house's flat roof. No caps, ventilation duct or artificial merger.
    for bay in bays:
        x, tip, roof = bay.axis, 61., 78.
        parts.append(_line(x, tip, x, MAIN_Y-76*NODE_SCALE, width=.6,
                           marker=f'data-section-riser="{bay.stack}" data-axis-x="{x:g}"'))
        side = 1 if bay.mirrored else -1
        lo, hi = (x+9, x+59) if side > 0 else (x-59, x-9)
        parts.append(_leader(bay.stack+"-fan", (x, 68), "Фановый стояк", bay.stack.replace('K', 'К'),
                             (lo, 37, hi, 56), side=side))
        dx = x-side*6
        parts.extend((_line(x, tip, dx+side*2, tip), _line(x, roof, dx+side*2, roof),
                      _line(dx, tip, dx, roof), _arrow((dx, tip), (0, -1), marker=bay.stack+"-h1", length=1.5),
                      _arrow((dx, roof), (0, 1), marker=bay.stack+"-h2", length=1.5),
                      _text(dx-side*2, 71, "h*", anchor="end" if side > 0 else "start", height=2.5)))
        for floor in study.floors:
            fy = FLOOR_Y[floor]
            parts.append(_label(bay.stack+f"-F{floor}", bay.stack.replace('K', 'К')+" ⌀100*",
                                (x, fy-54), (x, fy-33), height=2.5))
            parts.append(_floor(templates[bay.stack, floor], bay, floor))
            parts.append(_arrow((x, fy-12), (0, 1), marker=f"{bay.stack}-F{floor}-flow"))
    # Start/through lower nodes are determined by the topology, not by left-
    # right ordering or stack number. The cap is always coaxial with the main.
    for route in study.routes:
        direction = route.direction
        nodes = study.lower_assemblies(route)
        last = None
        for stack, node in zip(route.ordered_stacks, nodes, strict=True):
            x, y = axis[stack], MAIN_Y-76*NODE_SCALE
            def point(port: str) -> tuple[float, float]:
                p = node.port(port).point
                return x+direction*p.x_mm*NODE_SCALE, y+p.y_mm*NODE_SCALE
            if last is not None:
                end = point("main_in")
                parts.append(_line(*last, *end, width=.6, marker=f'data-section-main="{route.route_id}"'))
            transform = f'translate({2*x:g} 0) scale(-1 1)' if direction < 0 else ''
            parts.append(f'<g data-section-lower="{stack}" data-axis-x="{x:g}" transform="{transform}">'+
                         render_lower_turn_assembly_svg(node, x=x, y=y, scale=NODE_SCALE, pipe_width=.6,
                                                        graphic_size=FittingGraphicSize(100, 100, 1),
                                                        pipe_labels=False, annotations=False, flow_direction=False)+'</g>')
            if node.service_path:
                cap = point("cleanout_cap")
                lo, hi = (x+10, x+52) if direction < 0 else (x-52, x-10)
                parts.append(_leader(stack+"-base-cleanout", cap, "Прочистка", "DN по расчёту",
                                     (lo, 248, hi, 266), side=-direction, vertical_offsets_mm=(16.,)))
            last = point("main_out")
        assert last is not None
        out_x = LEFT-15 if direction < 0 else RIGHT+15
        parts.append(_line(*last, out_x, MAIN_Y, width=.6,
                           marker=f'data-section-outlet="{route.outlet}" data-outlet-x="{out_x:g}"'))
        parts.append(_arrow((out_x, MAIN_Y), (direction, 0), marker=route.outlet))
        centre = (last[0]+out_x)/2
        parts.append(_label(route.route_id, "К1 · DN н/д", (centre-20, MAIN_Y), (centre+20, MAIN_Y)))
        parts.append(_unknown_slope(route.route_id, centre, MAIN_Y-5, direction))
        parts.append(_text((axis[route.ordered_stacks[0]]+axis[route.ordered_stacks[1]])/2,
                           MAIN_Y+7, route.route_id.replace('K', 'К'), anchor="middle", height=2.5))
        parts.append(_arrow(((axis[route.ordered_stacks[0]]+axis[route.ordered_stacks[1]])/2, MAIN_Y),
                            (direction, 0), marker=route.route_id+"-flow"))
        # Outlet captions below, clear of the main and the floor level marks.
        lo, hi = (70., 137.) if direction < 0 else (471., 538.)
        parts.append(_leader(route.outlet, (out_x-direction*2, MAIN_Y),
                             "Выпуск "+('1' if direction < 0 else '2'), "Лоток: отм. н/д",
                             (lo, 282, hi, 297), side=-direction, vertical_offsets_mm=(19.,), below=True))
    parts.append(_text(29, 329, "Условные обозначения", height=3.5))
    for x, kind, text in ((37, "sink", "Мойка"), (106, "bath", "Ванна"),
                          (175, "washbasin", "Умывальник"), (260, "toilet", "Унитаз"),
                          (337, "trap", "Гидрозатвор"), (440, "revision", "Ревизия")):
        parts.extend((render_ugo(kind, x, 337, scale=.14), _text(x+13, 342, text, height=3.5)))
    notes = (
        "1. Развёрнутый разрез без масштаба. Кухни и санузлы показаны по группам; трассы предложены для проверки компоновки.",
        "2. Подвал принят по фрагменту «План полов» по заданию пользователя. Отметки, длины, DN магистралей и уклоны не заданы (н/д).",
        "3. * DN50/100 у приборов и стояков - графический типовой вариант, не результат подбора. h* над кровлей требует исходных данных.",
        "4. Ревизии показаны на обоих этажах, 1000 мм от пола - принятое правило удобства обслуживания. Доступы и проходки уточнить по АР.",
        "5. К2 не назначена: водоотвод новой кровли не подтверждён. Для выпуска ИОС3 нужны данные по ГОСТ Р 21.620-2023, п. 5.2.2.4.",
    )
    parts.extend((study_notes_svg(notes, x=29, y=356, width=365, bottom=400, pitch=7),
                  _text(29, 410, "Исходные данные требуют дополнения", height=2.5),
                  study_section_frame(system_label="К1", cipher="УЧЕБНЫЙ-К1.СХ"), '</svg>'))
    return ''.join(parts)


def audit_plan_section_svg(study: PlanStudy, svg: str) -> tuple[str, ...]:
    """Composition guard only, not a certificate of regulatory compliance."""
    root = ET.fromstring(svg)
    errors = []
    def rows(key):
        return [r for r in root.iter() if r.get(key) is not None]
    if root.get("data-view") != "principle-section" or any(r.tag.endswith('image') for r in root.iter()):
        errors.append("plan/raster substituted for principle section")
    if root.get("data-release-ready") != "false":
        errors.append("uncalibrated study must not become a release")
    for bay in section_bays(study):
        risers = [r for r in rows("data-section-riser") if r.get("data-section-riser") == bay.stack]
        lower = [r for r in rows("data-section-lower") if r.get("data-section-lower") == bay.stack]
        if len(risers) != 1 or len(lower) != 1:
            errors.append(f"{bay.stack}: missing/duplicate riser or lower node")
            continue
        if any(float(r.get("data-axis-x", 'nan')) != bay.axis for r in (*risers, *lower)):
            errors.append(f"{bay.stack}: upper/lower axis mismatch")
        route = next(r for r in study.routes if bay.stack in r.ordered_stacks)
        capped = bay.stack == route.ordered_stacks[0]
        assembly = next((r for r in lower[0].iter() if r.get("data-lower-connection")), None)
        if assembly is None or assembly.get("data-accessible-capped-end") != str(capped).lower():
            errors.append(f"{bay.stack}: missing initial cleanout or capped throughflow")
    expected = {f"{g.stack}:F{f}" for g in study.groups for f in study.floors}
    apartments = rows("data-section-apartment")
    if len(apartments) != len(expected) or {r.get("data-section-apartment") for r in apartments} != expected:
        errors.append("missing/duplicate apartment branch")
    if len(rows("data-riser-revision")) != len(expected):
        errors.append("lost storey revision")
    if len(rows("data-unbound-slope")) != len(expected)*2+len(study.routes):
        errors.append("lost unknown-grade marker")
    for route in study.routes:
        outlets = [r for r in rows("data-section-outlet") if r.get("data-section-outlet") == route.outlet]
        if len(outlets) != 1:
            errors.append(f"{route.outlet}: missing/duplicate outlet")
        else:
            x = float(outlets[0].get("data-outlet-x", 'nan'))
            if not (x < LEFT if route.direction < 0 else x > RIGHT):
                errors.append(f"{route.outlet}: outlet ends inside the building")
    return tuple(errors)


def generate_plan_section_pdf(output: Path, study: PlanStudy) -> str:
    import cairosvg  # type: ignore[import-untyped]

    svg = build_plan_section_svg(study)
    validate_study_section_frame(svg, system_label="К1", cipher="УЧЕБНЫЙ-К1.СХ")
    errors = audit_plan_section_svg(study, svg)
    if errors:
        raise ValueError('; '.join(errors))
    ensure_drafting_font_registered()
    output.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(output))
    return str(output)
