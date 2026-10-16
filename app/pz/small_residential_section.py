"""Representative building cutaway, separate from the complete installation graph.

This opt-in composition view is NOT a hydraulic aggregate and NOT a release
adapter. A selected apartment is drawn in its rooms, never replaced by a detail
reference. Repeated off-plane branches have explicit coverage, while the full
model remains unchanged. Both different lower-node types must remain visible.
The degree of abstraction is a project presentation choice (GOST 21.620,
5.2.2.2), not an assertion that the standard permits silently omitting systems.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import isclose, isfinite
from pathlib import Path
import re
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.drawing_sheet_style import FittingGraphicSize
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderPlacement, LeaderRequest, _text_width
from app.pz.small_residential_combined import _installation_signature
from app.pz.small_residential_preview import (
    ApartmentPreview, ResidentialPreview, _arrow, _floor_geometry, _level_mark,
    _revision, _vent_annotation,
)
from app.pz.small_residential_rainwater import FUNNEL_OUTLET_ANCHOR, HEATED_FUNNEL_OUTLET_ANCHOR
from app.pz.study_graphic_frame import study_notes_svg, study_section_frame, validate_study_section_frame
from app.pz.wastewater_basement_profile import STYLE, _elev, _line, _text
from app.pz.wastewater_drafting import render_inline_pipe_label, render_lower_turn_assembly_svg
from app.pz.wastewater_floor_drafting import build_floor_graphic_annotations
from app.pz.wastewater_ugo import REVISION_CENTRE_ANCHOR, render_ugo
from app.pz.wastewater_suspended_profile import SuspendedCollectorProfile

if TYPE_CHECKING:
    from app.pz.small_residential_calculation import ResidentialCalculation
    from app.pz.small_residential_fan_binding import SectionFanBinding
    from app.pz.small_residential_basement_proposal import BasementRoutingProposal


@dataclass(frozen=True)
class SectionProjection:
    """Visible source IDs and their repeat coverage; never summed Q or pipe DN."""
    visible_lanes: tuple[int, ...]
    visible_apartments: tuple[ApartmentPreview, ...]
    apartment_repeats: tuple[tuple[str, str], ...]  # omitted source -> visible peer
    lower_repeats: tuple[tuple[int, int], ...]


def _lower_signature(node) -> tuple:
    return (
        node.system,
        tuple((p.port_id, p.point, p.role) for p in node.ports),
        tuple((s.start_port_id, s.end_port_id, s.dn_mm, s.carries_flow) for s in node.segments),
        tuple((f.kind, f.point, f.dn_mm) for f in node.fittings),
        node.service_path is not None,
    )


def build_section_projection(model: ResidentialPreview) -> SectionProjection:
    model.validate()
    if model.roof is None or len(model.lower_nodes) != 4:
        raise ValueError("section preview requires the four-riser model and confirmed roof")
    visible_lanes = (0, 3)
    visible = tuple(a for a in model.apartments if a.lane in visible_lanes)
    repeats = []
    for apt in model.apartments:
        if apt in visible:
            continue
        candidates = [a for a in visible if a.floor_number == apt.floor_number
                      and _installation_signature(a.assembly) == _installation_signature(apt.assembly)]
        if not candidates:
            raise ValueError(f"{apt.apartment_id}: different apartment must have its own section view")
        repeats.append((apt.apartment_id, candidates[0].apartment_id))
    # Keep the free initial end AND a passing wye. Never collapse a unique
    # maintenance/reducer configuration into a superficially similar drawing.
    lower_repeats = ((1, 3), (2, 3))
    for nodes in (model.lower_nodes, model.roof.lower_nodes):
        for source, peer in lower_repeats:
            if _lower_signature(nodes[source]) != _lower_signature(nodes[peer]):
                raise ValueError("different lower node needs its own visible fragment")
    return SectionProjection(visible_lanes, visible, tuple(repeats), lower_repeats)


def _label(key: str, value: str, a: tuple[float, float], b: tuple[float, float], height=3.5) -> str:
    return render_inline_pipe_label(line_id=key, label=value, start=a, end=b,
                                  font_size=STYLE.font_size(height, 1), padding=.7)


def _unmasked_label(key: str, value: str, a: tuple[float, float], b: tuple[float, float], height=3.5) -> ET.Element:
    label = ET.fromstring(_label(key, value, a, b, height))
    for child in tuple(label):
        if child.get("data-pipe-label-mask"):
            label.remove(child)
    return label


def _slope_mark(key: str, start: tuple[float, float], end: tuple[float, float],
                slope: float, *, centre_x: float | None = None, extra: str = "") -> str:
    """Final-paper annotation, never scaled/mirrored with a fixture fragment.

    The numeric value belongs to the model, not to the apparent paper slope.
    A short acute angle has its lower arm parallel to the text; no underline.
    """
    if not isfinite(slope) or slope <= 0 or start[0] == end[0]:
        raise ValueError("a slope mark needs a positive model grade and a horizontal run")
    direction = 1 if end[0] > start[0] else -1
    value = f"{slope:.3f}".replace(".", ",")
    width = _text_width(value, STYLE.font_size(3.5, 1))
    span, gap, arm = width+1.5+5., 1.5, 5.
    centre = (start[0]+end[0])/2 if centre_x is None else centre_x
    baseline = min(start[1], end[1])-3.5
    if direction > 0:
        text_x = centre-span/2
        arm_x = text_x+width+gap
    else:
        arm_x = centre-span/2+arm
        text_x = arm_x+gap
    apex = arm_x+direction*arm
    return "".join((
        f'<g data-section-slope="{escape(key)}" data-slope="{slope:g}" '
        f'data-direction="{direction}" data-start-x="{start[0]:g}" data-start-y="{start[1]:g}" '
        f'data-end-x="{end[0]:g}" data-end-y="{end[1]:g}" data-text-height-mm="3.5" '
        f'data-ink-x1="{centre-span/2:g}" data-ink-x2="{centre+span/2:g}" '
        f'data-ink-y1="{baseline-3.5:g}" data-ink-y2="{baseline:g}" '
        f'data-placement="above" data-sign-shape="acute-angle" {extra}>',
        _text(text_x, baseline, value, height=3.5),
        f'<path data-slope-angle="true" d="M{arm_x:g},{baseline-2.5:g} '
        f'L{apex:g},{baseline:g} L{arm_x:g},{baseline:g}" '
        'fill="none" stroke="black" stroke-width=".25"/>', '</g>',
    ))


def _leader(key: str, target: tuple[float, float], title: str, detail: str,
            bounds: tuple[float, float, float, float], side=1, height=3.5,
            vertical_offsets_mm=(18., 24., 30., 36.)) -> str:
    result = LeaderLayoutEngine(bounds=LeaderBounds(*bounds), units_per_mm=1,
                                vertical_offsets_mm=vertical_offsets_mm).place_and_render(
        LeaderRequest(key, key, target, title, detail, preferred_side=side, text_height_mm=height),
    )
    if "⌀" in detail:
        root = ET.fromstring(result)
        label = next(r for r in root if r.get("data-leader-detail"))
        xx, yy = float(label.attrib["x"]), float(label.attrib["y"])
        root.remove(label)
        # Canonical vector sign, independent of the installed font's cmap.
        root.append(_unmasked_label(key+"-diameter", detail, (xx-1, yy-height/2),
                                    (xx+13, yy-height/2), height=height))
        result = ET.tostring(root, encoding="unicode")
    return result


def _branch_leader(key: str, target: tuple[float, float], axis: float, fy: float, sign: int) -> str:
    """Short leader in the reserved WC/stack annotation pocket, clear of the WC."""
    font = STYLE.font_size(3.5, 1)
    knee, shelf_y = axis-sign*7, fy-36
    outer = knee-sign*24
    lo, hi = sorted((knee, outer))
    placement = LeaderPlacement((knee, shelf_y), (outer, shelf_y),
                                (lo, shelf_y-font-1, hi, shelf_y+font+2),
                                (lo+2, shelf_y-1), (lo+2, shelf_y+font+1), font)
    result = LeaderLayoutEngine(bounds=LeaderBounds(lo, fy-50, hi, fy-22), units_per_mm=1).render(
        LeaderRequest(key, key, target, "К1", ""), placement,
    )
    root = ET.fromstring(result)
    label = next(r for r in root if r.get("data-leader-detail"))
    root.remove(label)
    root.append(_unmasked_label(key+"-diameter", "⌀110", (lo+2, shelf_y+3), (hi-2, shelf_y+3)))
    return ET.tostring(root, encoding="unicode")


def _right_vent(axis: float, roof_y: float, tip: float, number: int) -> str:
    """Outward leader leaves the central funnel annotation corridor clear."""
    shelf, target_y = roof_y-20, (roof_y+tip)/2
    return "".join((
        f'<g data-fan-vent="К1-{number}" data-roof-y="{roof_y:g}" data-tip-y="{tip:g}" data-height-mm="200">',
        f'<path d="M{axis:g},{target_y:g} L{axis+12:g},{shelf:g} H{axis+67:g}" '
        'fill="none" stroke="black" stroke-width=".25"/>',
        _text(axis+14, shelf-2, "Фановый стояк"),
        ET.tostring(_unmasked_label(f"fan-{number}", f"К1-{number} ⌀110", (axis+16, shelf+5), (axis+57, shelf+5)), encoding="unicode"),
        _arrow((axis, target_y), (-12, target_y-shelf), marker=f"fan-{number}", length=1.5),
        _line(axis-14, tip, axis-1, tip), _line(axis-14, roof_y, axis-1, roof_y),
        _line(axis-11, tip-5, axis-11, roof_y+5, marker='data-vent-dimension-line="true"'),
        _arrow((axis-11, tip), (0, 1), marker=f"fan-{number}-dim-top", length=1.5),
        _arrow((axis-11, roof_y), (0, -1), marker=f"fan-{number}-dim-bottom", length=1.5),
        _text(axis-15, target_y+1, "200", anchor="end"), '</g>',
    ))


def _apartment(apt: ApartmentPreview, axis: float, fy: float, mirror: bool) -> str:
    """Place the existing vector fixture/trap graph directly in the section rooms."""
    f, s = apt.assembly, .34
    tx, ty = axis-f.port("riser_join").point.x_mm*s, fy-212*s
    sign = -1 if mirror else 1

    def point(port: str) -> tuple[float, float]:
        p = f.port(port).point
        xx = tx+p.x_mm*s
        return (2*axis-xx if mirror else xx, ty+p.y_mm*s)

    transform = f'translate({2*axis:g} 0) scale(-1 1)' if mirror else ""
    parts = [f'<g data-section-apartment="{apt.apartment_id}" data-floor="{apt.floor_number}" '
             f'data-source-lane="{apt.lane}" data-stack-x="{axis:g}">',
             f'<g data-fixture-projection="true" transform="{transform}"><g '
             f'transform="translate({tx:g} {ty:g}) scale({s})">{_floor_geometry(f, scale=s)}</g></g>']
    a, b = point("junction_2"), point("junction_3")
    a, b = sorted((a, b))
    parts.append(_label(f"{apt.apartment_id}-50", "К1 ⌀50", a, b, height=2.5))
    a, b = point("junction_4"), point("riser_branch_elbow")
    # Aim beside the slope caption, not through its characters.
    target = (b[0]-sign*1.5, b[1])
    # Readable leaders/text stay outside the mirrored geometry transform.
    parts.append(_branch_leader(f"{apt.apartment_id}-110", target, axis, fy, sign))
    annotations, _ = build_floor_graphic_annotations(f)
    for annotation in annotations:
        # Keep DN50 lettering between bath and washbasin, away from the room
        # partition. DN100 is annotated on its own short run after the WC.
        segment = f.segment("collector_2" if annotation.dn_mm == 50 else annotation.first_segment_id)
        start, end = point(segment.start_port_id), point(segment.end_port_id)
        parts.append(_slope_mark(f"{apt.apartment_id}-{annotation.annotation_id}",
                                 start, end, annotation.slope, centre_x=(start[0]+end[0])/2-sign*3,
                                 extra=f'data-first-segment="{annotation.first_segment_id}" '
                                       f'data-last-segment="{annotation.last_segment_id}" '
                                       f'data-dn="{annotation.dn_mm}"'))
    cx, cy = point("cleanout_cap")
    lo, hi = (70., 101.) if not mirror else (489., 531.)
    parts.append(_leader(f"{apt.apartment_id}-cleanout", (cx, cy), "Пр.", "DN50",
                         (lo, fy-42, hi, fy-13), side=-sign))
    # Mirror revision geometry and dimension as one unit to keep the dimension
    # outside the apartment branch; undo mirroring for text by using local x.
    if not mirror:
        parts.extend(_revision(axis, fy, 20))
    else:
        centre = fy-20
        parts.extend((f'<g data-riser-revision="true" data-centre-y="{centre:g}" data-floor-y="{fy:g}">',
                      render_ugo("revision", axis, centre-REVISION_CENTRE_ANCHOR[0]*.2, scale=.2, rotation=90),
                      _line(axis-7, centre, axis-7, fy), _line(axis-9, centre, axis-1, centre),
                      _line(axis-9, fy, axis-1, fy), _line(axis-8, centre+1, axis-6, centre-1),
                      _line(axis-8, fy+1, axis-6, fy-1),
                      _text(axis-9, fy-10, "1000", anchor="middle",
                            marker=f'transform="rotate(-90 {axis-9:g} {fy-10:g})"'), '</g>'))
    parts.append(_text(axis+10 if not mirror else axis-14, fy-22, "R"))
    parts.append('</g>')
    return "".join(parts)


def _main_crossings(x1: float, x2: float, y: float, crossings: tuple[float, ...],
                    end_y: float | None = None, *, bridge_up: bool = False) -> str:
    """Paper-only bridges: no new fitting, tee, hydraulic edge or junction dot."""
    parts: list[str] = []
    start = x1
    def ordinate(x: float) -> float:
        return y if end_y is None else y+(end_y-y)*(x-x1)/(x2-x1)
    for x in sorted(c for c in crossings if x1 < c < x2):
        a, z = ordinate(x-2), ordinate(x+2)
        rise = -3 if bridge_up else 3
        parts.extend((_line(start, ordinate(start), x-2, a, width=.6),
                      f'<path data-nonconnecting-crossing="K1-K2" data-crossing-x="{x:g}" '
                      f'd="M{x-2:g},{a:g} C{x-2:g},{a+rise:g} {x+2:g},{z+rise:g} {x+2:g},{z:g}" '
                      'fill="none" stroke="black" stroke-width=".6"/>'))
        start = x+2
    parts.append(_line(start, ordinate(start), x2, ordinate(x2), width=.6))
    return "".join(parts)


def _outlet_drop(system: str, *, start_x: float, main_y: float, outlet_y: float,
                 axis: float, out_x: float, wall: float, direction: int,
                 main_end_y: float | None = None, bend_mm: float = 6.) -> str:
    """Connected paper projection of a drop, not a measured vertical profile.

    Both turns have two 45-degree elbows, no artificial capped tee. The revision
    is placed ON the straight drop, not on an abandoned former riser below the
    suspended collector. Its mounting elevation remains an explicit unknown.
    """
    bend = bend_mm
    end_y = main_y if main_end_y is None else main_end_y
    top, bottom = end_y+bend, outlet_y-bend
    if bottom-top < 12 or direction*(axis-direction*bend-start_x) <= 0:
        raise ValueError("outlet drop needs room for the elbows and accessible revision")
    points = ((start_x, main_y), (axis-direction*bend, end_y), (axis, top),
              (axis, bottom), (axis+direction*bend, outlet_y), (out_x, outlet_y))
    body = [f'<g data-outlet-drop="{system}" data-elevation-status="requires_confirmation" '
            f'data-top-y="{top:g}" data-bottom-y="{bottom:g}" data-drop-axis="{axis:g}">']
    for i, (a, b) in enumerate(zip(points, points[1:])):
        body.append(_line(*a, *b, width=.6,
                          marker=f'data-drop-segment="{i}" data-system="{system}"'
                                 + (f' data-outlet="{system}"' if i == 4 else "")))
    graphic = FittingGraphicSize(100, 100, 1)
    for name, a, b, before, after in (
        ("upper", points[1], points[2], points[0], points[3]),
        ("lower", points[3], points[4], points[2], points[5]),
    ):
        middle = ((a[0]+b[0])/2, (a[1]+b[1])/2)
        body.extend((graphic.boundary(a, before, offset=2, dn=100, marker=f"{system}-{name}-elbow-in"),
                     graphic.boundary(middle, b, offset=0, dn=100, marker=f"{system}-{name}-elbow-joint"),
                     graphic.boundary(b, after, offset=2, dn=100, marker=f"{system}-{name}-elbow-out")))
    centre = (top+bottom)/2
    body.extend((f'<g data-drop-revision="{system}" data-centre-y="{centre:g}" '
                 'data-mounting-height-status="requires_confirmation">',
                 render_ugo("revision", axis, centre-REVISION_CENTRE_ANCHOR[0]*.14, scale=.14, rotation=90),
                 _text(axis-direction*7, centre+1, "R", anchor="end" if direction > 0 else "start"), '</g>',
                 _arrow((out_x-direction*8, outlet_y), (direction, 0), marker=f"{system}-outlet"),
                 f'<rect data-outlet-sleeve="{system}" x="{wall-1:g}" y="{outlet_y-2:g}" width="6" '
                 'height="4" fill="white" stroke="black" stroke-width=".25"/>',
                 _line(wall-1, outlet_y, wall+5, outlet_y, width=.6), '</g>'))
    return "".join(body)


def _compact_section_notes() -> str:
    """Appendix-B-like legend of actually used symbols, plus short scope notes."""
    parts = [_text(25, 308, "Условные обозначения", height=3.5),
             '<g data-section-legend="true">',
             '<rect x="25" y="312" width="560" height="36" fill="none" stroke="black" stroke-width=".25"/>']
    for grid_x in (52, 165, 192, 305, 332, 445, 472):
        parts.append(_line(grid_x, 312, grid_x, 348))
    for grid_y in (324, 336):
        parts.append(_line(25, grid_y, 585, grid_y))
    columns = (
        (("system_k1", "Бытовая канализация К1"), ("system_k2", "Внутренний водосток К2"),
         ("revision", "Ревизия"), ("cleanout", "Прочистка, заглушённый конец"),
         ("flow_direction", "Направление стока"), ("transition", "Переход диаметра")),
        (("sink", "Мойка"), ("washbasin", "Умывальник"), ("bath", "Ванна"),
         ("toilet", "Унитаз"), ("trap", "Гидрозатвор"), ("roof_funnel_heated", "Воронка с электрообогревом")),
    )
    entries = tuple(entry for column in columns for entry in column)
    for column in range(4):
        x = 38.5+140*column
        for index, (kind, title) in enumerate(entries[column*3:column*3+3]):
            yy = 318.+12*index
            parts.append(f'<g data-legend-kind="{kind}">')
            if kind.startswith("system_"):
                label = "К1" if kind == "system_k1" else "К2"
                parts.extend((_line(x-10, yy, x+10, yy, width=.6),
                              _label("legend-"+kind, label, (x-10, yy), (x+10, yy))))
            elif kind == "transition":
                parts.extend((_line(x-10, yy, x-3, yy, width=.6),
                              f'<path d="M{x-3:g},{yy:g} L{x+3:g},{yy-2:g} V{yy+2:g} Z" '
                              'fill="white" stroke="black" stroke-width=".25"/>',
                              _line(x+3, yy, x+10, yy, width=.6)))
            else:
                parts.append(render_ugo(kind, x, yy, scale=.14 if kind == "roof_funnel_heated" else .18))
                if kind == "revision":
                    parts.append(_text(x+7, yy+1, "R", height=3.5))
            parts.extend((_text(55+140*column, yy+1.2, title, height=3.5), '</g>'))
    parts.extend(('</g>', _text(25, 357, "Примечания", height=3.5),
                  '<g data-demo-scope-notes="true">'))
    notes = (
        "1. Условный разрез, компоновка по приложению В ГОСТ Р 21.620-2023. Это учебная схема, не рабочая документация.",
        "2. В модели 8 квартир, 32 прибора; по 4 стояка К1 и К2. Повторные квартиры 2, 3, 6, 7 и стояки 2, 3 не показаны; их связи сохранены в модели.",
        "3. К1: PP HT 50x1,8 / 110x2,7; К2: SML 110x3,5. Знак диаметра означает наружный размер; унитаз DN100. К1 и К2 не соединяются.",
        "4. Уклоны ветвей и подвальных линий приняты для примера. * Отметки выпусков предварительные; уклоны выпусков, лотки колодцев, привязки и доступ уточнить по АР/ТУ.",
        "5. Числа уклонов не определяются наклоном линий на листе. Уровни здания М 1:50; длины трасс условные. Расчётные проверки приведены отдельно.",
    )
    parts.append(study_notes_svg(notes, x=25, y=365, width=370, bottom=405,
                                 height=3.5, pitch=7.2))
    parts.append('</g>')
    return "".join(parts)


def build_small_residential_section_svg(
    model: ResidentialPreview, *, fan_binding: SectionFanBinding | None = None,
    basement_proposal: BasementRoutingProposal | None = None,
    calculation: ResidentialCalculation | None = None,
    compact_demo: bool = False,
) -> str:
    if compact_demo and (calculation is None or fan_binding is not None):
        raise ValueError("compact demo needs the explicit K1/K2 study and individual vents")
    if calculation:
        calculation.validate(model)
        if basement_proposal is not None and basement_proposal != calculation.basement:
            raise ValueError("drawing proposal differs from calculation")
        basement_proposal = calculation.basement
    projection = build_section_projection(model)
    if fan_binding is not None:
        fan_binding.validate(model)
    if basement_proposal is not None:
        basement_proposal.validate(model)
    roof, b = model.roof, model.basement
    assert roof is not None
    levels = {a.floor_number: a.assembly.floor_elevation_m for a in model.apartments}

    def y(z: float) -> float:
        return 290+(b.basement_floor_m-z)*20

    roof_y, first_y, base_y, ceiling_y = y(roof.elevation_m), y(b.first_floor_m), 290., y(b.ceiling_m)
    if roof_y < 90 or any(y(levels[n])-y(levels[n+1]) < 60 for n in (1,)):
        raise ValueError("levels need a different sheet layout, not shrinking fixture graphics")
    left, right = 105., 485.
    axes = {"K1": {0: 219., 3: 371.}, "K2": {0: 339., 3: 251.}}
    # A ceiling-relative presentation band, NOT an inferred invert elevation.
    # Its relation to the floor frame must never manufacture engineering data.
    main1, main2, s = ceiling_y+11, ceiling_y+19, .12
    outlet_levels = {"K1": y(b.proposed_invert_m), "K2": base_y-8}
    profiles = {
        "K1": SuspendedCollectorProfile("K1", outer_diameter_mm=model.stack_pipe.outer_diameter_mm,
                                       wall_thickness_mm=(model.stack_pipe.outer_diameter_mm
                                                          - model.stack_pipe.inner_diameter_mm)/2),
        "K2": SuspendedCollectorProfile("K2"),
    }
    node_main = {system: {lane: main for lane in projection.visible_lanes}
                 for system, main in (("K1", main1), ("K2", main2))}
    node_scales = {"K1": s, "K2": s}
    if basement_proposal:
        profiles["K1"] = basement_proposal.k1
        node_main["K1"] = {lane: y(basement_proposal.axis_at(basement_proposal.junction_chainages_m[lane]))
                           for lane in projection.visible_lanes}
        # DN100 compound fitting ~300 mm high at this paper scale, not a
        # 456 mm decorative bend intruding into the ceiling slab.
        node_scales["K1"] = .08
        main1 = node_main["K1"][0]
        outlet_levels["K1"] = y(b.proposed_invert_m + model.stack_pipe.inner_diameter_mm/2000)
    if calculation:
        profiles["K2"] = calculation.rain_profile
        node_main["K2"] = {lane: y(calculation.rain_axis_at(calculation.rain_chainages_m[lane]))
                           for lane in projection.visible_lanes}
        node_scales["K2"] = .05
        main2 = node_main["K2"][0]
        outlet_levels["K2"] = y(calculation.provisional_k2_outlet_m+calculation.rain_pipe.inner_diameter_mm/2000)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" '
        'data-residential-section="true" data-release-ready="false" data-model-apartments="8" '
        'data-visible-apartments="4" data-vertical-scale="50" '
        f'data-compact-demo="{str(compact_demo).lower()}" '
        f'data-fan-roof-mode="{"group_geometry_study" if fan_binding else "individual"}">',
        '<defs><pattern id="section-hatch" width="3" height="3" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="3" stroke="#777" stroke-width=".25"/></pattern></defs>',
        '<rect width="594" height="420" fill="white"/>',
        _text(25, 18, "К1 и К2. Принципиальная схема на условном разрезе здания", height=5),
        _text(25, 29, "Двухэтажный жилой дом, 8 квартир. Характерные помещения и ветви; повторения раскрыты в примечаниях.", height=3.5),
        _text(25, 39, "Контрольный вариант общей вытяжки, не изменение проекта. Уровни здания М 1:50; трассы показаны условно."
              if fan_binding else f"Неэксплуатируемая кровля {_elev(roof.elevation_m)}. К1: четыре самостоятельных фановых вывода; сборного трубопровода нет.", height=2.5),
        _text(25, 48, "К1 - бытовая канализация. К2 - внутренние водостоки. Системы и выпуски раздельные.", height=3.5),
        '<g data-projection-coverage="true" data-not-hydraulic-aggregation="true">',
    ]
    for source, peer in projection.apartment_repeats:
        parts.append(f'<g data-omitted-apartment="{escape(source)}" data-represented-by="{escape(peer)}"/>')
    for system in ("K1", "K2"):
        for source_lane, peer_lane in projection.lower_repeats:
            parts.append(f'<g data-off-plane-riser="{system}-{source_lane+1}" data-lower-peer="{system}-{peer_lane+1}"/>')
    if fan_binding is not None:
        for lane in set(range(len(model.lower_nodes))) - set(projection.visible_lanes):
            rid = next(a.stack_id for a in model.apartments if a.lane == lane)
            parts.append(f'<g data-fan-off-plane-riser="{escape(rid)}" '
                         f'data-terminal="{escape(fan_binding.terminal(rid).terminal_id)}" '
                         f'data-target-sheet="{fan_binding.target_sheet(rid)}"/>')
    else:
        for lane in range(len(model.lower_nodes)):
            rid = next(a.stack_id for a in model.apartments if a.lane == lane)
            visible = lane in projection.visible_lanes
            parts.append(f'<g data-independent-fan-riser="{escape(rid)}" '
                         f'data-source-lane="{lane}" data-own-open-end="true" '
                         f'data-visible="{str(visible).lower()}" '
                         f'data-roof-level-m="{roof.elevation_m:g}" '
                         f'data-tip-level-m="{roof.elevation_m+roof.vent_height_m:g}"/>')
    parts.append('</g>')
    if basement_proposal:
        parts.append(f'<g data-basement-proposal="educational" data-source="{escape(basement_proposal.source)}" '
                     'data-hydraulics-status="requires_inputs" data-maintenance-status="requires_AR">')
        for lane, station in enumerate(basement_proposal.junction_chainages_m):
            parts.append(f'<g data-proposed-k1-station="{lane}" data-chainage-m="{station:g}" '
                         f'data-invert-m="{basement_proposal.invert_at(station):g}"/>')
        parts.append('</g>')
    if calculation:
        parts.append(f'<g data-calculation-binding="educational" data-q-k1="{calculation.water.sewage_flow}" '
                     f'data-q-k2="{calculation.storm.q_total_l_per_s}" data-k2-outlet-invert="{calculation.provisional_k2_outlet_m}">')
        for lane, station in enumerate(calculation.rain_chainages_m):
            parts.append(f'<g data-proposed-k2-station="{lane}" data-chainage-m="{station:g}" '
                         f'data-invert-m="{calculation.rain_invert_at(station):g}"/>')
        parts.append('</g>')
    # One continuous architectural cutaway, not one box per apartment or system.
    for number, z in sorted(levels.items()):
        fy = y(z)
        top = roof_y if number == 2 else y(levels[number+1])
        parts.append(f'<g data-section-storey="{number}">')
        for x1, x2, name in ((105, 138, "Кухня"), (138, 235, "Санузел"),
                             (265, 325, "Общедомовой холл"), (355, 452, "Санузел"), (452, 485, "Кухня")):
            parts.append(f'<rect data-section-room="{name}" x="{x1}" y="{top:g}" width="{x2-x1}" '
                         f'height="{fy-top:g}" fill="none" stroke="black" stroke-width=".25"/>')
            if name == "Общедомовой холл":
                parts.extend((_text((x1+x2)/2, top+10, "Общедомовой", anchor="middle"),
                              _text((x1+x2)/2, top+17, "холл", anchor="middle")))
            else:
                parts.append(_text((x1+x2)/2, top+10, name, anchor="middle"))
        for x in (235, 325):
            parts.extend((f'<rect data-common-shaft-zone="true" x="{x}" y="{top:g}" width="30" '
                          f'height="{fy-top:g}" fill="none" stroke="black" stroke-width=".25"/>',
                          _text(x+15, top+10, "Шахта", height=2.5, anchor="middle")))
        parts.extend((_line(left, fy, right, fy, marker=f'data-floor-boundary="{number}"'), '</g>'))
        parts.extend(_level_mark(fy, z, f"{number} этаж"))
    parts.append(_line(left, roof_y, right, roof_y, width=.6, marker='data-confirmed-roof="true"'))
    parts.extend(_level_mark(roof_y, roof.elevation_m, "Кровля"))
    parts.extend(_level_mark(base_y, b.basement_floor_m, "Подвал"))
    for yy, hh, key in ((first_y, ceiling_y-first_y, "ceiling"), (base_y, 4, "floor")):
        parts.append(f'<rect data-basement-slab="{key}" x="{left:g}" y="{yy:g}" width="{right-left:g}" '
                     f'height="{hh:g}" fill="url(#section-hatch)" stroke="black" stroke-width=".25"/>')
    for xx in (left, right-4):
        parts.append(f'<rect data-building-wall="true" x="{xx:g}" y="{roof_y:g}" width="4" '
                     f'height="{base_y+4-roof_y:g}" fill="url(#section-hatch)" stroke="black" stroke-width=".25"/>')
    parts.extend((_text(267, base_y-6, "Подвал", height=3.5),
                  _line(right, y(b.ground_m), 584, y(b.ground_m)),
                  _text(490, y(b.ground_m)-3, f"Земля {_elev(b.ground_m)}", height=2.5)))
    parts.append(_leader("ceiling", (112, ceiling_y), "Низ перекрытия", _elev(b.ceiling_m),
                         (25, ceiling_y+1, 101, ceiling_y+29), side=-1))
    # Two selected stacks of each system; the repeated two are explicitly out of plane.
    for lane in projection.visible_lanes:
        axis = axes["K1"][lane]
        rid = next(a.stack_id for a in model.apartments if a.lane == lane)
        tip = y(fan_binding.port_level(rid)) if fan_binding else roof_y-roof.vent_height_m*20
        parts.append(_line(axis, tip, axis, node_main["K1"][lane]-76*node_scales["K1"], width=.6,
                           marker=f'data-k1-stack="{lane+1}"'))
        if fan_binding is not None:
            terminal = fan_binding.terminal(rid)
            sheet = fan_binding.target_sheet(rid)
            level = fan_binding.port_level(rid)
            dn = next(r.diameter_mm for r in fan_binding.data.risers if r.riser_id == rid)
            # Keep the full-size two-line callout above the roof, not in the
            # upper apartment's existing branch/revision annotation pocket.
            bounds = (axis-80, roof_y-22, axis-9, roof_y-3) if lane == 0 else (axis+9, roof_y-22, axis+80, roof_y-3)
            parts.extend((
                f'<g data-section-fan-port="{escape(rid)}" data-terminal="{escape(terminal.terminal_id)}" '
                f'data-target-sheet="{sheet}" data-level-m="{level:g}" data-x="{axis:g}" data-y="{tip:g}">',
                _leader(f"section-fan-{rid}", (axis, tip), f"{rid}, к листу {sheet}",
                        f"{_elev(level)}; DN{dn:g}", bounds, side=-1 if lane == 0 else 1,
                        vertical_offsets_mm=(tip-roof_y+12, tip-roof_y+18)),
                '</g>',
            ))
        elif lane == 0:
            parts.extend(_vent_annotation(axis, roof_y, tip, lane+1))
        else:
            parts.append(_right_vent(axis, roof_y, tip, lane+1))
        parts.append(_arrow((axis, first_y-9), (0, 1), marker=f"K1-{lane+1}"))
        # Labels in the upper room area, not on top of branch/revision geometry.
        for number, z in levels.items():
            fy = y(z)
            if fan_binding is not None and tip > fy-51:
                # The top end is below this old label band. Its DN is in the
                # port callout; never leave an inline label floating in air.
                continue
            parts.append(_label(f"K1-{lane+1}-floor-{number}", f"К1-{lane+1} ⌀110",
                                (axis, fy-51), (axis, fy-29), height=2.5))
    for apt in projection.visible_apartments:
        parts.append(_apartment(apt, axes["K1"][apt.lane], y(levels[apt.floor_number]), apt.lane == 3))
    for lane in projection.visible_lanes:
        axis = axes["K2"][lane]
        number = lane+1
        funnel_anchor = HEATED_FUNNEL_OUTLET_ANCHOR if calculation else FUNNEL_OUTLET_ANCHOR
        parts.extend((f'<rect x="{axis-6.5:g}" y="{roof_y-4:g}" width="13" height="9.9" fill="white"/>',
                      render_ugo("roof_funnel_heated" if calculation else "roof_funnel", axis-funnel_anchor[0]*.25, roof_y, scale=.25),
                      _line(axis, roof_y+funnel_anchor[1]*.25, axis, node_main["K2"][lane]-76*node_scales["K2"], width=.6,
                            marker=f'data-k2-stack="{number}" data-funnel-id="К2-Вр{number}"')))
        bound1, bound2 = (axis-60, axis-8) if lane == 3 else (axis+8, axis+75)
        parts.append(_leader(f"funnel-{number}", (axis, roof_y-1), f"Воронка К2-Вр{number}", "HL62.1/1*" if calculation else "DN по расчёту",
                             (bound1, 53, bound2, 71), side=-1 if lane == 3 else 1))
        for n, z in levels.items():
            fy = y(z)
            parts.append(_label(f"K2-{number}-floor-{n}", f"К2-{number} ⌀110" if calculation else f"К2-{number}",
                                (axis, fy-47), (axis, fy-24), height=3.5))
            parts.append(_arrow((axis, fy-12), (0, 1), marker=f"K2-{number}-floor-{n}"))
        # Once the base joins a suspended line there is no riser at +1 m above
        # the basement floor. Put its revision above the offset, on floor 1.
        parts.extend(_revision(axis, first_y, 20))
        parts.append(_text(axis-8, first_y-22, "R"))
    # Canonical first/free and last/passing junctions. Middle passing nodes are
    # projected out, not replaced by an artificial capped branch or new Q.
    endpoints: dict[str, tuple[float, float]] = {}
    for system, nodes, main, direction in (("K1", model.lower_nodes, main1, 1),
                                           ("K2", roof.lower_nodes, main2, -1)):
        last_out = None
        last_y = main
        ns = node_scales[system]
        for lane in projection.visible_lanes:
            axis, node = axes[system][lane], nodes[lane]
            main = node_main[system][lane]
            transform = f'translate({2*axis:g} 0) scale(-1 1)' if direction < 0 else ""
            parts.extend((f'<g data-lower-system="{system}" data-source-lane="{lane}" '
                          f'data-axis-x="{axis:g}" data-node-scale="{ns:g}" '
                          f'data-main-y="{main:g}" transform="{transform}">',
                          render_lower_turn_assembly_svg(node, x=axis, y=main-76*ns, scale=ns,
                                                         pipe_width=.6, graphic_size=FittingGraphicSize(100, 100, 1),
                                                         annotations=False, pipe_labels=False, flow_direction=False), '</g>'))
            if last_out is not None:
                incoming = axis+direction*node.port("main_in").point.x_mm*ns
                lo, hi = sorted((last_out, incoming))
                parts.append(f'<g data-projected-main="{system}" data-omitted-nodes="1 2" '
                             'data-placement="suspended" data-invert-status="requires_confirmation" '
                             f'data-grade-status="{"educational_proposal" if calculation or (basement_proposal and system == "K1") else "requires_inputs"}">')
                parts.append(_main_crossings(lo, hi, last_y, tuple(axes["K2"].values()), end_y=main, bridge_up=bool(calculation))
                             if system == "K1" else _line(lo, main, hi, last_y, width=.6))
                label_y = last_y+(main-last_y)*(295-lo)/(hi-lo) if system == "K1" else main
                if not calculation:
                    parts.append(_label(f"{system}-main", "К1 ⌀110" if system == "K1" else "К2",
                                        (280, label_y), (310, label_y)))
                if basement_proposal and system == "K1" and not calculation:
                    # Acute downhill sign, 3.5 mm cap-height and thin line.
                    assert basement_proposal.k1.slope is not None
                    parts.append(_slope_mark("K1-main", (lo, last_y), (hi, main),
                                             basement_proposal.k1.slope, centre_x=295,
                                             extra='data-proposal-slope="K1"'))
                parts.append('</g>')
            last_out = axis+direction*node.port("main_out").point.x_mm*ns
            last_y = main
        assert last_out is not None
        out_x = 536. if system == "K1" else 74.
        wall = right-4 if system == "K1" else left
        out_y = outlet_levels[system]
        end_y = None
        if basement_proposal and system == "K1":
            assert basement_proposal.k1.length_m is not None
            end_y = y(basement_proposal.axis_at(basement_proposal.k1.length_m))
        if calculation and system == "K2":
            assert calculation.rain_profile.length_m is not None
            end_y = y(calculation.rain_axis_at(calculation.rain_profile.length_m))
        parts.append(_outlet_drop(system, start_x=last_out, main_y=main, outlet_y=out_y,
                                  axis=458. if system == "K1" else 130., out_x=out_x,
                                  wall=wall, direction=direction,
                                  main_end_y=end_y, bend_mm=4. if calculation and system == "K2" else 6.))
        if calculation:
            grade = profiles[system].slope
            assert end_y is not None and grade is not None
            cx = 413. if system == "K1" else 181.
            end_x = 452. if system == "K1" else 134.
            ly = main+(end_y-main)*(cx-last_out)/(end_x-last_out)
            parts.append(_label(f"{system}-calculated-main", f"К{1 if system == 'K1' else 2} ⌀110",
                                (cx-17, ly), (cx+17, ly)))
            parts.append(_slope_mark(f"{system}-main", (last_out, main), (end_x, end_y),
                                     grade, centre_x=cx,
                                     extra=f'data-proposal-slope="{system}"'))
            if system == "K2":
                assert calculation.rain_profile.end_invert_m is not None
                parts.append(_leader("K2-main-end", (134., end_y), "Лоток К2*",
                                     _elev(calculation.rain_profile.end_invert_m),
                                     (143, 273, 225, 289), vertical_offsets_mm=(280-end_y,)))
        if basement_proposal and system == "K1":
            assert end_y is not None and basement_proposal.k1.end_invert_m is not None
            parts.append(_leader("K1-main-end", (452., end_y), "Лоток К1*",
                                 _elev(basement_proposal.k1.end_invert_m),
                                 (397, end_y+7, 447, end_y+29), side=-1))
        endpoints[system] = (out_x, out_y)
        if compact_demo:
            # The outside grade is not supplied by a manhole COVER elevation.
            # Never copy a collector grade onto the outlet as a fake result.
            middle = 505. if system == "K1" else 90.
            parts.append(_label(f"{system}-outlet-diameter", f"К{1 if system == 'K1' else 2} ⌀110",
                                (middle-10, out_y), (middle+10, out_y)))
            parts.extend((f'<g data-outlet-grade="{system}" data-status="requires_inputs">',
                          _text(middle, out_y-4, "Уклон уточнить*", height=3.5, anchor="middle"), '</g>'))
    # Maintenance leaders target actual cap ports AFTER the K2 paper mirror.
    for system, nodes, main, sign, bounds in (
        ("K1", model.lower_nodes, main1, 1, (153, main1+8, 209, main1+29)),
        ("K2", roof.lower_nodes, main2, -1, (344, main2+8, 397, main2+29)),
    ):
        cap = nodes[0].port("cleanout_cap").point
        target = (axes[system][0]+sign*cap.x_mm*node_scales[system], main)
        parts.append(_leader(f"{system}-cleanout", target, "Прочистка К1" if system == "K1" else "Пр. К2",
                             "DN100" if system == "K1" or calculation else "DN*", bounds, side=-sign))
    parts.append(_leader("K1-outlet", endpoints["K1"], "Выпуск К1", f"Лоток {_elev(b.proposed_invert_m)}*",
                         (490, ceiling_y+8, 585, outlet_levels["K1"]-3)))
    parts.append(_leader("K2-outlet", endpoints["K2"], "Выпуск К2", f"Лоток {_elev(calculation.provisional_k2_outlet_m)}*" if calculation else "Лоток уточнить",
                         (25, ceiling_y+(10 if calculation else 19), 100, outlet_levels["K2"]-3), side=-1))
    # A compact keyed schedule keeps missing engineering data visible without
    # attaching bogus numerical levels to paper-only main coordinates.
    for system, yy in (("K1", 310.), ("K2", 320.)):
        profile = profiles[system]
        if calculation or (basement_proposal and system == "K1"):
            passage = profile.passage_height_m(b.basement_floor_m)
            gap = profile.ceiling_clearance_m(b.ceiling_m)
            assert (passage is not None and gap is not None and profile.end_invert_m is not None
                    and profile.start_invert_m is not None)
            parts.extend((f'<g data-collector-profile="{system}" data-start-invert="{profile.start_invert_m:g}" '
                          f'data-end-invert="{profile.end_invert_m:g}" data-clearance-status="proposal_only" '
                          f'data-min-passage-m="{passage:g}" data-ceiling-gap-m="{gap:g}">',
                          "" if compact_demo else _text(25, yy, f"{system}, предложение: L={profile.length_m:g} м; уклон {profile.slope:.3f}; лоток {_elev(profile.start_invert_m)} / {_elev(profile.end_invert_m)}; проход {passage:.2f} м*; зазор {gap:.2f} м*.".replace('.', ',')),
                          '</g>'))
            continue
        parts.extend((f'<g data-collector-profile="{system}" data-start-invert="unknown" '
                      'data-end-invert="unknown" data-clearance-status="requires_inputs">',
                      _text(25, yy, f"{system}: лоток начала / конца - уточнить; L и уклон - задать; высоту прохода проверить по габариту трубы.", height=3.5),
                      '</g>'))
    # Key counts and omissions are on the sheet, not only in machine metadata.
    notes = (
        "1. Условный разрез с развёрткой приборов: показаны К1-1, К1-4 и К2-Вр1/Вр4 со стояками. Это выбранные ветви, не их объединение.",
        "2. Квартиры 2, 3, 6, 7 и К2-2/К2-3 - вне плоскости разреза. К1-2/К1-3 имеют свои фановые выводы, аналогичные К1-1/К1-4.",
        "3. Всего в модели: 8 квартир, 32 прибора, 4 стояка К1 и 4 воронки/стояка К2. Повторные проходные узлы магистралей графически свёрнуты.",
        "4. К1: предлагаемые трубы PP HT 50x1,8 / 110x2,7; подписи со знаком диаметра - наружные размеры. Присоединение унитаза DN100.",
        "5. * Лоток выпуска К1 -2,20 - предварительная граница по морозу, не высота коллектора. Опуски у стен; повороты - два отвода 45°.",
        "6. К2: DN*, материал, расход и лоток требуют подбора. Подвесные линии показаны условно, не в масштабе отметок; К2 с К1 не соединяется.",
        "7. Этажные ревизии - 1000 мм от пола; высоты ревизий на опусках уточнить. Соосные прочистки только на свободных началах.",
        "8. Обслуживание подвесных линий и вывод прочисток выше согласовать по СП 30, 18.26 / 21.8. Номера помещений и проходки - по АР.",
    )
    if fan_binding is not None:
        notes = (notes[0],
                 f"2. Повторные квартиры и К2-2/К2-3 вне плоскости разреза. Все фановые стояки К1, включая скрытые, раскрыты на листах 2-{fan_binding.sheet_total}.",
                 *notes[2:])
    else:
        notes = (*notes[:5],
                 "6. К2: DN, материал, расход и лоток - уточнить. К1: открытые устья без колпаков; расстояния до окон и УФ-защиту подтвердить.",
                 notes[6],
                 "8. Компоновка по приложению В ГОСТ Р 21.620-2023. Уровни здания М 1:50; трубы условно. Привязки и обслуживание - согласовать по АР/ВК.")
    if basement_proposal:
        notes = (*notes[:4],
                 "5. Подвал: учебный профиль К1 без плана АР; L и уклон предложены, гидравликой не подтверждены. Лоток выпуска -2,20* не лоток колодца.",
                 "6. * Проход только под К1: учтён запас габарита креплений 30 мм снизу / 20 мм сверху. Балки, К2 и другие сети пока не проверены.",
                 "7. Прочистки и ревизии сохранены; проходные узлы без заглушек. Доступ и вывод прочисток на этаж выше - согласовать по СП 30, 18.26.",
                 "8. К2: DN, материал, расход, уклон, отметки и проход требуют данных; показан условно. К1/К2 раздельны; выводы К1 открытые, самостоятельные.")
    if calculation:
        notes = (*notes[:4],
                 f"5. К1 по ф.(5): {calculation.water.sewage_flow:.3f} л/с, не расход выпуска; К2 {calculation.storm.q_total_l_per_s:.3f} л/с. {calculation.storm.city.name}, F={calculation.storm.f_calculated_m2:g} м². См. расчёт.".replace('.', ','),
                 "6. К2: SML DN100, 110x3,5; Di=103 мм; воронки HL62.1/1 с обогревом. Соединения с удерживающими хомутами; узел кровли согласовать.",
                 f"7. * Без АР: лоток выпуска К1 {_elev(b.proposed_invert_m)}, К2 {_elev(calculation.provisional_k2_outlet_m)} предложены; это не лотки колодцев. Присоединение и подпор не подтверждены.",
                 "8. Прочистки на свободных началах; проходные тройники открыты. Доступ по 18.26, балки и пересечения в плане требуют проверки. Не готовый ИОС3.")
    if compact_demo:
        parts.append(_compact_section_notes())
    else:
        parts.append(_text(25, 331, "Указания к условному разрезу. Это не готовый ИОС3", height=3.5))
        parts.append(study_notes_svg(notes, x=25, y=339, width=370, bottom=399))
    parts.extend((
                  _text(25, 411, "Компоновка для согласования. Исходная модель и расчётные алгоритмы не изменены.", height=2.5),
                  study_section_frame(sheet_total=fan_binding.sheet_total if fan_binding else 1), '</svg>'))
    return "".join(parts)


def audit_individual_fan_section(model: ResidentialPreview, svg: str) -> tuple[str, ...]:
    """The small house has no architectural space for a shared fan collector.

    This checks the selected independent endings, not the full SP/AR approval.
    Hidden identical branches remain separate risers with their own openings.
    """
    root = ET.fromstring(svg)
    roof = model.roof
    if roof is None or root.get("data-fan-roof-mode") != "individual":
        return ("Для этого жилого разреза требуются самостоятельные фановые выводы",)
    projection = build_section_projection(model)
    ids = {a.stack_id for a in model.apartments}
    visible = {a.stack_id for a in projection.visible_apartments}
    coverage = [r for r in root.iter() if r.get("data-independent-fan-riser")]
    vents = [r for r in root.iter() if r.get("data-fan-vent")]
    errors = []
    if len(coverage) != len(ids) or {r.get("data-independent-fan-riser") for r in coverage} != ids:
        errors.append("Потерян самостоятельный фановый вывод полной модели")
    if len(vents) != len(visible) or {r.get("data-fan-vent") for r in vents} != visible:
        errors.append("Потерян видимый фановый вывод на разрезе")
    if any(r.get("data-section-fan-port") or r.get("data-fan-off-plane-riser")
           or r.get("data-role") in {"common_vent", "vent_collector"} for r in root.iter()):
        errors.append("Необоснованное объединение вытяжек или ссылка на другой лист")
    for row in coverage:
        rid = row.get("data-independent-fan-riser")
        if (row.get("data-own-open-end") != "true"
                or row.get("data-visible") != str(rid in visible).lower()
                or not isclose(float(row.get("data-roof-level-m", "nan")), roof.elevation_m)
                or not isclose(float(row.get("data-tip-level-m", "nan")), roof.elevation_m+roof.vent_height_m)):
            errors.append("Неверное окончание скрытого/видимого стояка")
    for vent in vents:
        rid = vent.get("data-fan-vent")
        lane = next((a.lane for a in model.apartments if a.stack_id == rid), None)
        pipe = next((r for r in root.iter() if r.get("data-k1-stack") == str(lane+1)), None) if lane is not None else None
        apartment = next((r for r in root.iter() if r.get("data-section-apartment")
                          and r.get("data-source-lane") == str(lane)), None)
        axis = float(apartment.get("data-stack-x", "nan")) if apartment is not None else float("nan")
        tip_y = float(vent.get("data-tip-y", "nan"))
        roof_y = float(vent.get("data-roof-y", "nan"))
        expected_roof_y = 290+(model.basement.basement_floor_m-roof.elevation_m)*20
        if (pipe is None or not isclose(float(pipe.get("y1", "nan")), tip_y, abs_tol=.001)
                or not isclose(float(pipe.get("x1", "nan")), axis, abs_tol=.001)
                or not isclose(float(pipe.get("x2", "nan")), axis, abs_tol=.001)
                or not isclose(roof_y, expected_roof_y, abs_tol=.001)
                or not isclose(roof_y-tip_y, roof.vent_height_m*20, abs_tol=.001)
                or float(vent.get("data-height-mm", "nan")) != roof.vent_height_m*1000):
            errors.append("Фановая труба не доходит до устья/кровли или неверен размер")
    return tuple(errors)


def audit_basement_proposal_section(
    model: ResidentialPreview, proposal: BasementRoutingProposal, svg: str,
) -> tuple[str, ...]:
    """Export guard: a composed view must not lose access nodes or grade data.

    This verifies drawing-to-proposal consistency, not hydraulic performance or
    normative service accessibility. Those remain explicit unresolved inputs.
    """
    proposal.validate(model)
    root = ET.fromstring(svg)
    errors: list[str] = []
    def marked(key: str):
        return [r for r in root.iter() if r.get(key) is not None]
    def equal(row, key: str, expected: float) -> bool:
        try:
            return isclose(float(row.get(key, "nan")), expected, abs_tol=.001)
        except (ValueError, TypeError):
            return False

    if root.get("data-release-ready") != "false":
        errors.append("Учебная компоновка не является готовым ИОС3")
    station_rows = marked("data-proposed-k1-station")
    if len(station_rows) != len(proposal.junction_chainages_m):
        errors.append("Потеряны промежуточные стояки предложенного профиля")
    for lane, station in enumerate(proposal.junction_chainages_m):
        matching = [r for r in station_rows if r.get("data-proposed-k1-station") == str(lane)]
        if (len(matching) != 1 or not equal(matching[0], "data-chainage-m", station)
                or not equal(matching[0], "data-invert-m", proposal.invert_at(station))):
            errors.append(f"К1-{lane+1}: неверная привязка профиля")
    for system, nodes in (("K1", model.lower_nodes), ("K2", model.roof.lower_nodes if model.roof else ())):
        for lane in (0, 3):
            drawn = [r for r in marked("data-lower-system")
                     if r.get("data-lower-system") == system and r.get("data-source-lane") == str(lane)]
            if len(drawn) != 1:
                errors.append(f"{system}-{lane+1}: нижний узел отсутствует или дублирован")
                continue
            group = drawn[0]
            body = [r for r in group.iter() if r.get("data-lower-connection")]
            caps = [r for r in group.iter() if r.get("data-fitting") == "cleanout_cap_fitting"]
            if (len(body) != 1 or body[0].get("data-accessible-capped-end") != ("true" if lane == 0 else "false")
                    or len(caps) != (2 if lane == 0 else 0)):
                errors.append(f"{system}-{lane+1}: потеряна прочистка либо заглушён проходной узел")
            if lane == 0 and nodes:
                cap = nodes[0].port("cleanout_cap").point
                sign = 1 if system == "K1" else -1
                leaders = [r for r in marked("data-leader-id") if r.get("data-leader-id") == system+"-cleanout"]
                target_x = float(group.get("data-axis-x", "nan"))+sign*cap.x_mm*float(group.get("data-node-scale", "nan"))
                if (len(leaders) != 1 or not equal(leaders[0], "data-target-x", target_x)
                        or not equal(leaders[0], "data-target-y", float(group.get("data-main-y", "nan")))):
                    errors.append(f"{system}: выноска прочистки не привязана к заглушке")
            if system == "K1":
                yy = 290+(model.basement.basement_floor_m-proposal.axis_at(proposal.junction_chainages_m[lane]))*20
                if not equal(group, "data-main-y", yy):
                    errors.append(f"К1-{lane+1}: труба не на отметке предложенного профиля")
    return tuple(errors)


def audit_section_slopes(model: ResidentialPreview, svg: str, *,
                         calculation: ResidentialCalculation | None = None) -> tuple[str, ...]:
    """Fail export on lost, stale, mirrored or illegible grade annotations.

    This is a drafting contract, not a self-cleaning/hydraulic pass criterion.
    Unknown outlet grades must remain visibly unknown in the compact study.
    """
    root = ET.fromstring(svg)
    expected: dict[str, tuple[float, int]] = {}
    parents = {child: parent for parent in root.iter() for child in parent}
    for apt in build_section_projection(model).visible_apartments:
        for item in build_floor_graphic_annotations(apt.assembly)[0]:
            expected[f"{apt.apartment_id}-{item.annotation_id}"] = (item.slope, -1 if apt.lane == 3 else 1)
    if calculation:
        for system, profile, direction in (("K1", calculation.basement.k1, 1),
                                            ("K2", calculation.rain_profile, -1)):
            assert profile.slope is not None
            expected[system+"-main"] = (profile.slope, direction)
    errors = []
    for key, (value, direction) in expected.items():
        candidates = [r for r in root.iter() if r.get("data-section-slope") == key]
        if len(candidates) != 1:
            errors.append(f"{key}: уклон отсутствует или дублирован")
            continue
        row = candidates[0]
        text = next((r for r in row if r.tag.rsplit('}', 1)[-1] == "text"), None)
        angle = next((r for r in row if r.get("data-slope-angle")), None)
        try:
            ancestor: ET.Element | None = row
            while ancestor is not None:
                style = ancestor.get("style", "").replace(" ", "")
                if (ancestor.get("display") == "none" or ancestor.get("visibility") == "hidden"
                        or ancestor.get("opacity") == "0"
                        or any(v in style for v in ("display:none", "visibility:hidden", "opacity:0"))):
                    raise ValueError("hidden annotation")
                ancestor = parents.get(ancestor)
            if (float(row.get("data-slope", "nan")) != value
                    or int(row.get("data-direction", "0")) != direction
                    or row.get("data-text-height-mm") != "3.5"
                    or row.get("data-placement") != "above"
                    or row.get("data-sign-shape") != "acute-angle"
                    or text is None or angle is None):
                raise ValueError("binding")
            assert text is not None and angle is not None
            if (text.text != f"{value:.3f}".replace('.', ',')
                    or not isclose(float(text.get("font-size", "nan")), STYLE.font_size(3.5, 1), abs_tol=.001)
                    or float(text.get("y", "inf")) >= min(float(row.attrib["data-start-y"]), float(row.attrib["data-end-y"]))):
                raise ValueError("caption")
            points = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", angle.get("d", ""))]
            if (len(points) != 6 or points[3] != points[5] or points[0] != points[4]
                    or points[1] >= points[3] or (points[2]-points[0])*direction <= 0
                    or angle.get("stroke-width") != ".25" or angle.get("fill") != "none"):
                raise ValueError("angle")
        except (ValueError, TypeError, KeyError):
            errors.append(f"{key}: уклон/направление/размер или знак расходятся с моделью")
    if root.get("data-compact-demo") == "true":
        for system in ("K1", "K2"):
            grades = [r for r in root.iter() if r.get("data-outlet-grade") == system]
            if (len(grades) != 1 or grades[0].get("data-status") != "requires_inputs"
                    or "Уклон уточнить*" not in "".join(grades[0].itertext())):
                errors.append(f"{system}: не раскрыт отсутствующий уклон выпуска")
    return tuple(errors)


def generate_small_residential_section_pdf(
    output_path: str, model: ResidentialPreview, *,
    basement_proposal: BasementRoutingProposal | None = None,
    calculation: ResidentialCalculation | None = None,
    compact_demo: bool = False,
) -> str:
    import cairosvg  # type: ignore[import-untyped]

    svg = build_small_residential_section_svg(model, basement_proposal=basement_proposal, calculation=calculation,
                                             compact_demo=compact_demo)
    validate_study_section_frame(svg)
    if calculation:
        basement_proposal = calculation.basement
    errors = audit_individual_fan_section(model, svg) + audit_section_slopes(model, svg, calculation=calculation)
    if basement_proposal:
        errors += audit_basement_proposal_section(model, basement_proposal, svg)
    if calculation:
        errors += audit_calculated_section(model, calculation, svg)
    if errors:
        raise ValueError("; ".join(errors))
    ensure_drafting_font_registered()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(path))
    return str(path)


def audit_calculated_section(model: ResidentialPreview, calculation: ResidentialCalculation,
                             svg: str) -> tuple[str, ...]:
    """Protect engineering-to-paper binding, including the concealed K2 risers."""
    calculation.validate(model)
    root = ET.fromstring(svg)
    errors = []
    def rows(key):
        return [r for r in root.iter() if r.get(key) is not None]
    def matches(row, key, value):
        try:
            return isclose(float(row.get(key, "nan")), value, abs_tol=.001)
        except (TypeError, ValueError):
            return False
    def y(z):
        return 290+(model.basement.basement_floor_m-z)*20
    bindings = rows("data-calculation-binding")
    if (len(bindings) != 1 or not matches(bindings[0], "data-q-k1", calculation.water.sewage_flow)
            or not matches(bindings[0], "data-q-k2", calculation.storm.q_total_l_per_s)):
        errors.append("Расходы схемы и расчёта расходятся")
    for system, profile in (("K1", calculation.basement.k1), ("K2", calculation.rain_profile)):
        schedules = [r for r in rows("data-collector-profile") if r.get("data-collector-profile") == system]
        if (len(schedules) != 1 or not matches(schedules[0], "data-start-invert", profile.start_invert_m)
                or not matches(schedules[0], "data-end-invert", profile.end_invert_m)):
            errors.append(f"{system}: профиль схемы отличается от расчёта")
    for lane in range(4):
        stations = [r for r in rows("data-proposed-k2-station") if r.get("data-proposed-k2-station") == str(lane)]
        station = calculation.rain_chainages_m[lane]
        if (len(stations) != 1 or not matches(stations[0], "data-chainage-m", station)
                or not matches(stations[0], "data-invert-m", calculation.rain_invert_at(station))):
            errors.append(f"К2-{lane+1}: потерян пикет")
        if lane not in (0, 3):
            continue
        node = [r for r in rows("data-lower-system") if r.get("data-lower-system") == "K2"
                and r.get("data-source-lane") == str(lane)]
        stack = [r for r in rows("data-k2-stack") if r.get("data-k2-stack") == str(lane+1)]
        expected = y(calculation.rain_axis_at(station))
        if (len(node) != 1 or len(stack) != 1 or not matches(node[0], "data-main-y", expected)
                or not matches(stack[0], "y2", expected-76*float(node[0].get("data-node-scale", "nan")))
                or not matches(stack[0], "y1", y(6.6)+HEATED_FUNNEL_OUTLET_ANCHOR[1]*.25)):
            errors.append(f"К2-{lane+1}: разрыв трубы/воронки или неверная отметка")
    outlets = [r for r in rows("data-outlet") if r.get("data-outlet") == "K2"]
    if len(outlets) != 1 or not matches(outlets[0], "y2", y(calculation.provisional_k2_outlet_m+calculation.rain_pipe.inner_diameter_mm/2000)):
        errors.append("Отметка выпуска К2 расходится с расчётом")
    return tuple(errors)
