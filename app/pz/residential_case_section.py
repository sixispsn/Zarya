"""One-sheet K1/K2 section of an explicit residential regression case.

Vertical architectural levels use 1:50. Horizontal packing and fitting sizes
are schematic, not surveyed plan coordinates. Existing canonical fixture and
lower-node graphs supply the pipe geometry; no calculation is derived from ink.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

from app.architecture.residential_section_case import CaseCollector, ResidentialSectionCase
from app.calc.storm import StormInput, calculate_storm
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.drawing_sheet_style import FittingGraphicSize
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderPlacement, LeaderRequest
from app.pz.residential_plan_section import SectionBay, _floor
from app.pz.small_residential_preview import _arrow, _level_mark, _revision
from app.pz.small_residential_section import _label, _main_crossings, _slope_mark
from app.pz.small_residential_rainwater import HEATED_FUNNEL_OUTLET_ANCHOR
from app.pz.study_graphic_frame import study_notes_svg, study_section_frame, validate_study_section_frame
from app.pz.wastewater_basement_profile import STYLE, _line, _text
from app.pz.wastewater_drafting import render_lower_turn_assembly_svg
from app.pz.wastewater_ugo import REVISION_CENTRE_ANCHOR, render_ugo


LEFT, RIGHT, SCALE_Y, DATUM_Y, NODE_SCALE = 63., 548., 20., 303., .12
BAYS = (SectionBay('K1-1', 63, 160, 154, False), SectionBay('K1-2', 171, 268, 262, False),
        SectionBay('K1-3', 343, 440, 349, True), SectionBay('K1-4', 451, 548, 457, True))
K2_AXES = (326., 295.)  # Order along the K2 flow, independent from K1 ordering.


def ordinate(level: float) -> float:
    return DATUM_Y-SCALE_Y*level


def _level(value: float) -> str:
    return f'{value:+.3f}'.replace('.', ',')


def _callout(key: str, target: tuple[float, float], title: str, detail: str,
             knee: tuple[float, float], shelf_x: float) -> str:
    """Fixed reserved pocket; canonical leader grammar and physical text size."""
    lo, hi = sorted((knee[0], shelf_x))
    sy, font = knee[1], STYLE.font_size(3.5, 1)
    placement = LeaderPlacement(knee, (shelf_x, sy), (lo, sy-font-1, hi, sy+font+2),
                                (lo+1, sy-1), (lo+1, sy+font+1), font)
    return LeaderLayoutEngine(bounds=LeaderBounds(lo, sy-8, hi, sy+8), units_per_mm=1).render(
        LeaderRequest(key, key, target, title, detail), placement)


def _revision_on_main(key: str, x: float, y: float) -> str:
    return (f'<g data-main-revision="{escape(key)}">'+
            render_ugo('revision', x-REVISION_CENTRE_ANCHOR[0]*.2, y, scale=.2)+
            _text(x, y-3, 'R', height=2.5, anchor='middle')+'</g>')


def _position(station: float, stations: tuple[float, ...], axes: tuple[float, ...]) -> float:
    for a, b, x, xx in zip(stations, stations[1:], axes, axes[1:]):
        if a <= station <= b:
            return x+(station-a)/(b-a)*(xx-x)
    raise ValueError('annotation station outside the drawn collector')


def _architecture(case: ResidentialSectionCase) -> list[str]:
    roof, floor = ordinate(case.roof_m), ordinate(case.subfloor_m)
    parts = [_line(LEFT, roof, LEFT, floor+6, width=.35), _line(RIGHT, roof, RIGHT, floor+6, width=.35)]
    for z, label in ((case.roof_m, 'Кровля'), (case.subfloor_m, 'Техподполье')):
        parts.extend(_level_mark(ordinate(z), z, label))
    for name, z in [('roof', case.roof_m), *[(str(f), z) for f, z in case.floor_levels.items()]]:
        y = ordinate(z)
        parts.append(f'<rect data-floor-boundary="{name}" data-level-m="{z:g}" x="{LEFT}" y="{y:g}" '
                     f'width="{RIGHT-LEFT}" height="{case.slab_m*SCALE_Y:g}" '
                     'fill="url(#slab)" stroke="black" stroke-width=".25"/>')
    for f, z in case.floor_levels.items():
        fy = ordinate(z)
        top_z = case.roof_m if f == case.floors else case.floor_levels[f+1]
        top = ordinate(top_z-case.slab_m)
        parts.extend(_level_mark(fy, z, f'{f} этаж'))
        for index, bay in enumerate(BAYS, 1):
            wall = bay.right-20 if bay.mirrored else bay.left+20
            for x in (bay.left, wall, bay.right):
                parts.append(_line(x, top, x, fy, marker='data-room-boundary="true"'))
            kx = (wall+bay.right)/2 if bay.mirrored else (bay.left+wall)/2
            sx = (bay.left+wall)/2 if bay.mirrored else (wall+bay.right)/2
            parts.extend((_text(kx, top+7, 'Кухня-', anchor='middle', height=2.5),
                          _text(kx, top+12, 'гостиная', anchor='middle', height=2.5),
                          _text(sx, top+7, 'Санузел', anchor='middle'),
                          _text(sx, top+13, f'Квартира {(f-1)*4+index}', anchor='middle', height=2.5)))
        parts.extend((_text(307, top+8, 'Общий холл', anchor='middle', height=3.5),
                      _text(307, top+14, 'и лестница', anchor='middle', height=3.5)))
        for x in K2_AXES:
            parts.extend((_line(x-5, top+20, x-5, fy), _line(x+5, top+20, x+5, fy)))
    parts.extend((f'<rect x="{LEFT}" y="{floor:g}" width="{RIGHT-LEFT}" height="6" '
                  'fill="url(#slab)" stroke="black" stroke-width=".35"/>',
                  _text(369, floor-2, 'Неотапливаемое техподполье · h = '+
                        f'{case.subfloor_clear_m:.2f}'.replace('.', ',')+' м', height=2.5)))
    return parts


def _fan(case: ResidentialSectionCase) -> list[str]:
    graph = case.fan_graph()
    axes = {bay.stack: bay.axis for bay in BAYS}
    nodes = {n.node_id: n for n in graph.nodes}
    # Drawing x comes from one shared stack axis, never from a new top view.
    def point(n):
        rid = n.source_id if n.node_id != 'K1-FAN' else case.fan_terminal_riser
        return axes[rid], ordinate(n.level_m)
    parts = ['<g data-common-fan="K1-FAN" data-placement="guarded-roof-technical-strip">',
             '<rect x="142" y="63" width="325" height="28" fill="none" stroke="black" '
             'stroke-width=".25" stroke-dasharray="3 2"/>']
    for e in graph.edges:
        a, b = point(nodes[e.start]), point(nodes[e.end])
        parts.append(_line(*a, *b, width=.6, marker=f'data-fan-edge="{escape(e.edge_id)}"'))
    a = point(nodes['join:K1-4'])
    b = point(nodes['join:K1-1'])
    parts.extend((_slope_mark('fan-condensate', a, b, case.fan_slope, centre_x=218),
                  _label('fan-collector', 'К1 ⌀100', (374, a[1]+.15), (425, a[1]+.55)),
                  _callout('fan-zone', (171, ordinate(case.fan_start_m)-.1), 'Сборная вытяжка К1',
                           'Над кровлей, в ограждённой техзоне*', (128, 54), 251)))
    x, tip = point(nodes['K1-FAN'])
    roof = ordinate(case.roof_m)
    parts.extend((_callout('fan-terminal', (x, tip+9), 'Общая вытяжка четырёх стояков', 'Открытое устье без колпака; DN100', (397, 44), 526),
                  _line(x, tip, x+9, tip), _line(x, roof, x+9, roof), _line(x+7, tip, x+7, roof),
                  _line(x+6, tip+1, x+8, tip-1), _line(x+6, roof+1, x+8, roof-1),
                  _text(x+5, (tip+roof)/2, f'{case.fan_height_m*1000:.0f}', anchor='middle',
                        marker=f'transform="rotate(-90 {x+5:g} {(tip+roof)/2:g})"'),
                  f'<g data-fan-open-end="true" data-height-m="{case.fan_height_m:g}"/>', '</g>'))
    return parts


def _outlet(system: str, x: float, main_y: float, case: ResidentialSectionCase,
            collector: CaseCollector, direction: int) -> str:
    """Compact paired 45-degree turns, with an actual drop and no blind end."""
    axis_z = case.outlet_invert_m+collector.pipe.inner_diameter_mm/2000
    end_y = ordinate(axis_z)
    bend = 2.
    vx, end_x = x+direction*bend, (LEFT-13 if direction < 0 else RIGHT+13)
    if end_y-main_y < 4*bend:
        raise ValueError('outlet drop needs a different fitting composition')
    points = ((x, main_y), (vx, main_y+bend), (vx, end_y-bend), (vx+direction*bend, end_y), (end_x, end_y))
    parts = [f'<g data-section-outlet="{system}:outlet" data-outlet-x="{end_x:g}" '
             f'data-invert-m="{case.outlet_invert_m:g}" data-axis-level-m="{axis_z:g}">',
             '<polyline points="'+' '.join(f'{xx:g},{yy:g}' for xx, yy in points)+'" fill="none" stroke="black" stroke-width=".6"/>']
    for xx, yy in points[1:3]:
        parts.append(_line(xx-1, yy, xx+1, yy, width=.35))
    ry = (main_y+end_y)/2
    parts.extend((render_ugo('revision', vx, ry-REVISION_CENTRE_ANCHOR[0]*.2, scale=.2, rotation=90),
                  _text(vx-direction*3, ry+.5, 'R', height=2.5, anchor='middle'),
                  _arrow((end_x, end_y), (direction, 0), marker=system+'-outlet')))
    # Keep shelves outside the low underfloor room instead of stretching it.
    # Lift only the right-hand annotation above the full form-3 stamp.
    # Target, outlet pipe and all engineering elevations stay unchanged.
    knee = (68, 355) if direction < 0 else (523, 349)
    shelf = 150 if direction < 0 else 434
    parts.append(_callout(system+'-outlet-note', (end_x, end_y), 'Выпуск '+system.replace('K', 'К')+' DN100',
                          'Лоток '+_level(case.outlet_invert_m), knee, shelf))
    parts.append('</g>')
    return ''.join(parts)


def _collector(case: ResidentialSectionCase, collector: CaseCollector,
               axes: tuple[float, ...], direction: int, cross_axes: tuple[float, ...]) -> list[str]:
    system = collector.profile.system
    x_end = RIGHT-9 if direction > 0 else LEFT+9
    length = collector.profile.length_m
    assert length is not None
    parts: list[str] = []
    last: tuple[float, float] | None = None
    for i, (station, x, node) in enumerate(zip(collector.stations, axes, collector.nodes(), strict=True)):
        main_y = ordinate(collector.axis(station))
        top_y = main_y-76*NODE_SCALE
        def point(port: str) -> tuple[float, float]:
            p = node.port(port).point
            return x+direction*p.x_mm*NODE_SCALE, top_y+p.y_mm*NODE_SCALE
        if last is not None:
            end = point('main_in')
            parts.append(_main_crossings(last[0], end[0], last[1], cross_axes, end_y=end[1], bridge_up=True))
        mirror = f'translate({2*x:g} 0) scale(-1 1)' if direction < 0 else ''
        parts.extend((f'<g data-section-lower="{system}-{i+1}" data-axis-x="{x:g}" '
                      f'data-station-m="{station:g}" data-invert-m="{collector.invert(station):g}">',
                      f'<g transform="{mirror}">', render_lower_turn_assembly_svg(
                          node, x=x, y=top_y, scale=NODE_SCALE, pipe_width=.6,
                          graphic_size=FittingGraphicSize(100, 100, 1), annotations=False,
                          pipe_labels=False, flow_direction=False), '</g></g>'))
        last = point('main_out')
        if i == 0:
            target = point('cleanout_cap')
            knee = (139., 316.) if direction > 0 else (340., 332.)
            parts.append(_callout(system+'-start-cleanout', target, 'Прочистка', 'DN100', knee, knee[0]+direction*-36))
    assert last is not None
    end = (x_end, ordinate(collector.axis(length)))
    parts.append(_main_crossings(last[0], end[0], last[1], cross_axes, end_y=end[1], bridge_up=True))
    stations, drawing_x = (*collector.stations, length), (*axes, x_end)
    for i, station in enumerate(collector.revisions):
        xx = _position(station, stations, drawing_x)
        parts.append(_revision_on_main(f'{system}-{i+1}', xx, ordinate(collector.axis(station))))
    # Break labels sit in free line intervals; not on wyes, revision symbols or crossings.
    intervals = ((177., 218.), (379., 420.), (510., 535.)) if system == 'K1' else ((93., 131.), (200., 243.))
    def on_line(xx: float) -> float:
        for s, t, xa, xb in zip(stations, stations[1:], drawing_x, drawing_x[1:]):
            if min(xa, xb) <= xx <= max(xa, xb):
                return ordinate(collector.axis(s+(t-s)*(xx-xa)/(xb-xa)))
        raise ValueError('line label outside collector')
    for i, (a, b) in enumerate(intervals):
        parts.append(_label(f'{system}-main-{i}', system.replace('K', 'К')+' ⌀100', (a, on_line(a)), (b, on_line(b))))
    grade_centre = 400. if system == 'K1' else 166.
    assert collector.profile.slope is not None
    ga, gb = grade_centre-10*direction, grade_centre+10*direction
    arrow_x = 443 if system == 'K1' else 258
    parts.extend((_slope_mark(system+'-main', (ga, on_line(ga)), (gb, on_line(gb)), collector.profile.slope),
                  _arrow((arrow_x, on_line(arrow_x)), (direction, 0), marker=system+'-main-flow'),
                  _outlet(system, *end, case, collector, direction)))
    note_y = 351 if system == 'K1' else 357
    parts.append(_text(180, note_y, f'{system.replace("K", "К")}: лоток {_level(collector.invert(0))} ... '
                       f'{_level(collector.invert(length))}; L = {length:g} м*', height=2.5))
    return parts


def build_residential_case_svg(case: ResidentialSectionCase) -> str:
    case.validate()
    if (case.floors != 3 or case.floor_to_floor_m < 3.3 or ordinate(case.roof_m) < 90
            or not 334 <= ordinate(case.subfloor_m) <= 343 or len(case.catchments) != 2
            or case.catchments[0] != case.catchments[1]):
        raise ValueError('case needs a different sheet composition; do not clip floors or underfloor')
    water, rain = case.calculate()
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" '
             f'data-view="principle-section" data-release-ready="false" data-fixture-paths="{len(case.drainage_paths())}">',
             '<defs><pattern id="slab" width="5" height="5" patternUnits="userSpaceOnUse">'
             '<path d="M-1,1 L1,-1 M0,5 L5,0 M4,6 L6,4" stroke="black" stroke-width=".25"/>'
             '</pattern></defs><rect width="594" height="420" fill="white"/>',
             _text(29, 19, 'Принципиальная схема канализации и водостоков К1, К2', height=5),
             _text(29, 27, 'Жилой дом · 3 этажа · 12 квартир · развёрнутый разрез · учебный пример', height=3.5),
             *_architecture(case), *_fan(case)]
    templates = case.floors_graph()
    for bay, station in zip(BAYS, case.k1.stations, strict=True):
        top = ordinate(case.roof_m)
        bottom = ordinate(case.k1.axis(station))-76*NODE_SCALE
        parts.append(_line(bay.axis, top, bay.axis, bottom, width=.6,
                           marker=f'data-section-riser="{bay.stack}" data-axis-x="{bay.axis:g}"'))
        for f, z in case.floor_levels.items():
            fy = ordinate(z)
            parts.extend((_floor(templates[bay.stack, f], bay, f, floor_y=fy, grades=case.grades, revision=f in (1, case.floors)),
                          _label(f'{bay.stack}-F{f}', bay.stack.replace('K1-', 'Ст. К1-')+' ⌀100',
                                 (bay.axis, fy-53), (bay.axis, fy-32), height=2.5),
                          _arrow((bay.axis, fy-12), (0, 1), marker=f'{bay.stack}-F{f}-flow')))
    roof_y = ordinate(case.roof_m)
    for i, (x, station) in enumerate(zip(K2_AXES, case.k2.stations, strict=True), 1):
        fx, outlet_y = x-HEATED_FUNNEL_OUTLET_ANCHOR[0]*.25, roof_y+HEATED_FUNNEL_OUTLET_ANCHOR[1]*.25
        parts.extend((render_ugo('roof_funnel_heated', fx, roof_y, scale=.25),
                      _line(x, outlet_y, x, ordinate(case.k2.axis(station))-76*NODE_SCALE, width=.6,
                            marker=f'data-section-riser="K2-{i}" data-axis-x="{x:g}" data-k2-stack="true"')))
        for f, z in case.floor_levels.items():
            fy = ordinate(z)
            parts.extend((_label(f'K2-{i}-F{f}', f'К2-{i} ⌀100', (x, fy-43), (x, fy-20), height=2.5),
                          _arrow((x, fy-11), (0, 1), marker=f'K2-{i}-F{f}-flow')))
        parts.extend(_revision(x, ordinate(case.first_floor_m), SCALE_Y))
        parts.append(_text(x-3, ordinate(case.first_floor_m)-22, 'R', anchor='end', height=2.5))
    catchment = calculate_storm(StormInput(case.storm_input.city_code, case.catchments[0], 0,
                                          case.storm_input.period_years))
    funnel_flow = f'{catchment.q_total_l_per_s:.3f}'.replace('.', ',')
    parts.append(_callout('roof-funnels', (K2_AXES[1], roof_y), 'Воронки с обогревом: 2 шт.*',
                          f'По {case.catchments[0]:g} м²; q = {funnel_flow} л/с на воронку', (286, 53), 389))
    parts.extend(_collector(case, case.k1, tuple(b.axis for b in BAYS), 1, K2_AXES))
    parts.extend(_collector(case, case.k2, K2_AXES, -1, ()))
    # Common legend and notes, outside the underfloor; never inflate its height.
    parts.append('<g data-study-legend="true">')
    parts.append(_text(29, 369, 'Условные обозначения', height=3.5))
    for x, y, label in ((134, 369, 'R — ревизия'), (225, 369, 'Пр. — прочистка'),
                        (29, 376, 'К1 — бытовая канализация'), (200, 376, 'К2 — внутренний водосток')):
        parts.append(_text(x, y, label, height=3.5))
    parts.append('</g>')
    q1, q2 = (f'{q:.3f}'.replace('.', ',') for q in (water.sewage_flow, rain.q_total_l_per_s))
    notes = [
        f'1. {rain.city.name}; {case.residents} жителей. К1 по ф.(5): {q1} л/с, не расход выпуска; К2: {q2} л/с.',
        '2. Уровни по вертикали 1:50; ширина, УГО и фасонина условные. * — учебное допущение, не данные АР.',
        '3. К1: PP HT 50×1,8 / 110×2,7; К2: SML DN100 (110×3,5). DN и уклоны для компоновки, не окончательный подбор.',
        '4. Разработать: защиту от замерзания, опоры / УФ-защиту вытяжки, люки и доступ в техподполье.',
        '5. Уточнить: окна / балконы, крепления и герметичность К2, проходки, наружные сети и подпор.',
        f'6. Выпуски К1 и К2 раздельные. Лоток {_level(case.outlet_invert_m)}; проходки на уровне пола — по узлам КР. Для строительства не выпускать.',
    ]
    parts.extend((study_notes_svg(notes, x=29, y=384, width=366, bottom=411, pitch=5),
                  study_section_frame(), '</svg>'))
    return ''.join(parts)


def audit_residential_case_svg(case: ResidentialSectionCase, svg: str) -> tuple[str, ...]:
    root = ET.fromstring(svg)
    errors: list[str] = []
    def rows(key):
        return [e for e in root.iter() if e.get(key) is not None]
    if root.get('data-release-ready') != 'false' or any(e.tag.endswith('image') for e in root.iter()):
        errors.append('study must remain a vector non-release section')
    if len(rows('data-section-apartment')) != 4*case.floors or len(rows('data-floor-fixture')) != 16*case.floors:
        errors.append('lost apartment/fixture')
    expected_slopes: dict[str, tuple[float | None, int]] = {f'{b.stack}:F{f}-grade{dn}': (case.grades[0 if dn == 50 else 1], -1 if b.mirrored else 1)
                       for b in BAYS for f in case.floor_levels for dn in (50, 100)}
    expected_slopes.update({'K1-main': (case.k1.profile.slope, 1), 'K2-main': (case.k2.profile.slope, -1),
                            'fan-condensate': (case.fan_slope, -1)})
    slopes = rows('data-section-slope')
    if len(slopes) != len(expected_slopes) or {e.get('data-section-slope') for e in slopes} != set(expected_slopes):
        errors.append('lost pipe/fan slope')
    for e in slopes:
        expected = expected_slopes.get(e.get('data-section-slope', ''))
        if expected != (float(e.get('data-slope', 'nan')), int(e.get('data-direction', '0'))) or e.get('data-text-height-mm') != '3.5':
            errors.append('wrong slope value, direction or lettering size')
    if len(rows('data-floor-boundary')) != case.floors+1 or len(rows('data-riser-revision')) != 10:
        errors.append('lost level/revision')
    for name, x in [(b.stack, b.axis) for b in BAYS]+[(f'K2-{i+1}', x) for i, x in enumerate(K2_AXES)]:
        for key in ('data-section-riser', 'data-section-lower'):
            found = [e for e in rows(key) if e.get(key) == name]
            if len(found) != 1 or float(found[0].get('data-axis-x', 'nan')) != x:
                errors.append(name+': upper/lower axis mismatch')
        lower = next((e for e in rows('data-section-lower') if e.get('data-section-lower') == name), None)
        if lower is not None:
            node = next((e for e in lower.iter() if e.get('data-lower-connection')), None)
            if node is None or node.get('data-accessible-capped-end') != str(name in ('K1-1', 'K2-1')).lower():
                errors.append(name+': lost cleanout or capped throughflow')
    fan = rows('data-fan-open-end')
    if len(fan) != 1 or float(fan[0].get('data-height-m', 'nan')) != case.fan_height_m:
        errors.append('missing shared open fan terminal')
    outlets = rows('data-section-outlet')
    if {e.get('data-section-outlet') for e in outlets} != {'K1:outlet', 'K2:outlet'} or len(outlets) != 2:
        errors.append('separate outlets missing')
    for e in outlets:
        if LEFT <= float(e.get('data-outlet-x', 'nan')) <= RIGHT or float(e.get('data-invert-m', 'nan')) != case.subfloor_m:
            errors.append('outlet lost exterior continuation or floor invert')
    return tuple(errors)


def generate_residential_case_pdf(output: Path, case: ResidentialSectionCase, *, node: str, root: Path) -> str:
    import cairosvg  # type: ignore[import-untyped]

    case.verify_legacy(node, root)
    svg = build_residential_case_svg(case)
    validate_study_section_frame(svg)
    errors = audit_residential_case_svg(case, svg)
    if errors:
        raise ValueError('; '.join(errors))
    ensure_drafting_font_registered()
    output.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(output))
    return str(output)
