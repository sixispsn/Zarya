"""Opt-in composition study, NOT the production IOS3 release backend.

Reuse the residential room programme, canonical apartment installation graph,
accepted lower junctions and paper-space drafting primitives. Proposed routing
and catalogue sizes remain separate from confirmed Project.sewage. The preview
does not manufacture hydraulic results, lengths, roof levels or outside pipes.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import hypot, isfinite
from pathlib import Path
from xml.etree import ElementTree as ET

from app.architecture.residential_program import (
    BuildingProgramTopology, ResidentialProgramInput, build_residential_program,
)
from app.data.sewer_pipe_catalog import SewerPipeGeometry, sewer_pipe_geometry
from app.intake.request_dto import IOS2Request
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.drawing_sheet_style import FittingGraphicSize, apply_residential_paper_style
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderRequest
from app.pz.study_graphic_frame import study_notes_svg, study_section_frame, validate_study_section_frame
from app.pz.wastewater_basement_profile import BasementProfileInput, STYLE, _elev, _line, _text
from app.pz.wastewater_drafting import (
    WastewaterDraftAssembly, build_lower_turn_cleanout_assembly,
    build_lower_turn_through_junction_assembly, render_inline_pipe_label,
    render_lower_turn_assembly_svg,
)
from app.pz.wastewater_floor_drafting import (
    FloorFixtureInput, WastewaterFloorAssembly, build_typical_floor_assembly,
    render_typical_floor_assembly_svg,
)
from app.pz.wastewater_ugo import REVISION_CENTRE_ANCHOR, render_ugo


@dataclass(frozen=True)
class ApartmentPreview:
    apartment_id: str
    floor_number: int
    lane: int
    stack_id: str
    assembly: WastewaterFloorAssembly


@dataclass(frozen=True)
class ResidentialRoofPreview:
    """Confirmed roof, proposed four independent risers outside apartments.

    DN100 in canonical fitting geometry is ONLY a graphic template size. It is
    never labelled as a calculated K2 diameter or inserted into Project.pipes.
    SP30 18.18, 18.19 (amendment 3), 21.2, 21.5 and 21.15 (amendment 3).
    """
    elevation_m: float
    kind: str
    lower_nodes: tuple[WastewaterDraftAssembly, ...]
    placement_zone: str = "common_nonresidential"
    # Proposed positions from upper-left corner of the 21 x 12 m plan base.
    # All lie in the central shared hall (x=9..12, y=3..6), not apartments.
    funnel_positions_m: tuple[tuple[float, float], ...] = ((9.9, 3.6), (11.1, 3.6), (9.9, 5.2), (11.1, 5.2))

    @property
    def vent_height_m(self) -> float:
        if self.kind != "flat_non_accessible":
            raise ValueError("roof preview only supports the confirmed non-accessible flat roof")
        return .2  # SP 30.13330.2020, 18.18; unchanged by amendments 1-5.

    def flow_edges(self) -> tuple[tuple[str, str], ...]:
        edges = []
        for i, node in enumerate(self.lower_nodes):
            prefix = f"K2:base-{i}:"
            edges.append((f"K2:funnel-{i+1}", prefix + "riser_in"))
            edges.extend((prefix + s.start_port_id, prefix + s.end_port_id)
                         for s in node.segments if s.carries_flow)
            target = f"K2:base-{i+1}:main_in" if i+1 < len(self.lower_nodes) else "K2:outlet"
            edges.append((prefix + "main_out", target))
        return tuple(edges)

    def validate(self, highest_floor_m: float) -> None:
        if not isfinite(self.elevation_m) or self.elevation_m <= highest_floor_m:
            raise ValueError("roof must be above the top floor")
        _ = self.vent_height_m
        if len(self.lower_nodes) != 4 or self.placement_zone != "common_nonresidential":
            raise ValueError("four K2 risers must be proposed outside residential apartments")
        if len(self.funnel_positions_m) != 4:
            raise ValueError("each funnel needs a proposed plan position")
        for i, (x, y) in enumerate(self.funnel_positions_m):
            if not (9 < x < 12 and 3 < y < 6):
                raise ValueError("funnel position outside the proposed common hall")
            for xx, yy in self.funnel_positions_m[i+1:]:
                if not 1 <= hypot(x-xx, y-yy) <= 48:
                    raise ValueError("funnel spacing does not meet SP30 21.5")
        for i, node in enumerate(self.lower_nodes):
            if node.system != "K2" or node.validate():
                raise ValueError("invalid K2 lower node")
            if (node.service_path is not None) != (i == 0):
                raise ValueError("K2 capped cleanout is allowed only on the first free end")
        graph = dict(self.flow_edges())
        for i in range(4):
            current, seen = f"K2:funnel-{i+1}", set()
            while current != "K2:outlet":
                if current in seen or current not in graph or not current.startswith("K2:"):
                    raise ValueError("K2 must reach its own outlet without mixing with K1")
                seen.add(current)
                current = graph[current]


@dataclass(frozen=True)
class ResidentialPreview:
    programme: BuildingProgramTopology
    apartments: tuple[ApartmentPreview, ...]
    lower_nodes: tuple[WastewaterDraftAssembly, ...]
    basement: BasementProfileInput
    branch_pipe: SewerPipeGeometry
    stack_pipe: SewerPipeGeometry
    roof: ResidentialRoofPreview | None = None

    @property
    def release_ready(self) -> bool:
        return False

    def flow_edges(self) -> tuple[tuple[str, str], ...]:
        """Namespaced installation connections, independent of page coordinates."""
        edges: list[tuple[str, str]] = []
        for apt in self.apartments:
            floor = apt.assembly
            prefix = apt.apartment_id + ":"
            edges.extend((prefix + s.start_port_id, prefix + s.end_port_id)
                         for s in floor.segments if s.carries_flow)
            edges.extend((prefix + j.start_port_id, prefix + j.end_port_id)
                         for j in floor.direct_fitting_joints)
            edges.extend((prefix + f.trap_inlet_port_id, prefix + f.trap_outlet_port_id)
                         for f in floor.fixtures if f.trap_mode == "external")
        for lane, node in enumerate(self.lower_nodes):
            prefix = f"base-{lane}:"
            edges.extend((prefix + s.start_port_id, prefix + s.end_port_id)
                         for s in node.segments if s.carries_flow)
            pairs = sorted((a for a in self.apartments if a.lane == lane),
                           key=lambda a: a.floor_number)
            for low, high in zip(pairs, pairs[1:]):
                edges.append((high.apartment_id + ":riser_bottom", low.apartment_id + ":riser_top"))
            edges.append((pairs[0].apartment_id + ":riser_bottom", prefix + "riser_in"))
            target = f"base-{lane+1}:main_in" if lane + 1 < len(self.lower_nodes) else "outlet"
            edges.append((prefix + "main_out", target))
        return tuple(edges)

    def validate(self) -> None:
        self.basement.validate()
        if not self.apartments or not self.lower_nodes:
            raise ValueError("preview needs apartments and basement nodes")
        if len({a.apartment_id for a in self.apartments}) != len(self.apartments):
            raise ValueError("duplicate apartment IDs")
        if {a.lane for a in self.apartments} != set(range(len(self.lower_nodes))):
            raise ValueError("apartment columns and basement nodes disagree")
        for lane in range(len(self.lower_nodes)):
            pair = [a for a in self.apartments if a.lane == lane]
            if len(pair) != 2 or {a.floor_number for a in pair} != {1, 2} or len({a.stack_id for a in pair}) != 1:
                raise ValueError("each proposed riser must connect one apartment on each floor")
        for apt in self.apartments:
            if apt.assembly.validate():
                raise ValueError("invalid apartment installation graph")
        if self.roof is not None:
            self.roof.validate(max(a.assembly.floor_elevation_m for a in self.apartments))
        for i, node in enumerate(self.lower_nodes):
            if node.validate():
                raise ValueError("invalid lower installation graph")
            if (node.service_path is not None) != (i == 0):
                raise ValueError("only the first free main end may have a capped cleanout")
        adjacency: dict[str, list[str]] = {}
        for source, target in self.flow_edges():
            adjacency.setdefault(source, []).append(target)

        def reaches_outlet(node: str, path: frozenset[str]) -> bool:
            if node == "outlet":
                return True
            if node in path or node not in adjacency:
                return False
            return all(reaches_outlet(n, path | {node}) for n in adjacency[node])

        for apt in self.apartments:
            for fixture in apt.assembly.fixtures:
                source = apt.apartment_id + ":" + fixture.fixture_outlet_port_id
                if not reaches_outlet(source, frozenset()):
                    raise ValueError(f"{source}: no continuous path to building outlet")


def build_small_residential_preview(
    req: IOS2Request, *, basement: BasementProfileInput, source_ref: str,
    proposed_shafts: int, branch_outer_mm: float, stack_outer_mm: float,
    include_roof: bool = False,
) -> ResidentialPreview:
    """Explicit draft choice: vertical apartment pairs, one K1 collector.

    Currently accepts 1-4 vertically repeated apartments per floor, two floors.
    The caller must choose the proposed shaft count and exact catalogue sizes.
    It must never infer real stack coordinates or confirmed slopes from a JPG.
    """
    counts = req.apartments_by_floor
    if not (req.floors == 2 and 1 <= proposed_shafts <= 4):
        raise ValueError("this preview supports two floors and up to four apartment columns")
    if counts != {n: proposed_shafts for n in range(1, req.floors + 1)}:
        raise ValueError("preview needs confirmed identical apartment counts on every floor")
    if any(n not in req.floor_elevations_m for n in counts):
        raise ValueError("all floor elevations must be supplied")
    if basement.first_floor_m != req.floor_elevations_m[1]:
        raise ValueError("first floor differs from basement context")
    branch = sewer_pipe_geometry(req.wastewater_pipe_series_id, branch_outer_mm)
    stack = sewer_pipe_geometry(req.wastewater_pipe_series_id, stack_outer_mm)
    # Explicit interpretation for this proposed domestic fixture configuration.
    # Not a generic DN -> OD alias inside the catalogue or a hydraulic sizing.
    if branch.outer_diameter_mm != 50 or stack.outer_diameter_mm != 110:
        raise ValueError("this composition study uses explicit HT OD50 and OD110 choices")
    programme = build_residential_program(ResidentialProgramInput(
        floors_above=req.floors, floors_below=req.floors_below,
        apartments_total=req.apartments, source_ref=source_ref,
        apartments_by_floor=tuple(sorted(counts.items())),
        floor_elevations_m=tuple(sorted(req.floor_elevations_m.items())),
        sanitary_shafts_per_section=proposed_shafts, lift_shafts_per_section=0,
        apartment_sanitary_room_id="apartment_sanitary_unit_bath",
    ))
    apartments = []
    room_by_id = {r.room_id: r for r in programme.rooms}
    for floor in range(1, req.floors + 1):
        units = [a for a in programme.apartments if a.floor_number == floor]
        for lane, apt in enumerate(units):
            fixtures = []
            for f in programme.fixtures:
                if f.room_id not in apt.room_ids or "K1" not in f.service_ports:
                    continue
                kind = "sink" if f.archetype_id == "kitchen_sink" else f.archetype_id
                room = room_by_id[f.room_id]
                fixtures.append(FloorFixtureInput(
                    f.fixture_id, kind, "Кухня" if room.archetype_id == "apartment_kitchen" else "Санузел",
                    dn_mm=100 if kind == "toilet" else 50,
                ))
            assembly = build_typical_floor_assembly(
                fixtures=fixtures, assembly_id=apt.apartment_id, floor_no=floor,
                floor_elevation_m=req.floor_elevations_m[floor], riser_id=f"К1-{lane+1}",
                # Existing canonical layout gradients, NOT confirmed design slopes.
                # They are deliberately not exported as numerical design data.
                slope_dn50=.03, slope_dn100=.02,
            )
            apartments.append(ApartmentPreview(apt.apartment_id, floor, lane, f"К1-{lane+1}", assembly))
    lower = tuple(
        (build_lower_turn_cleanout_assembly if lane == 0 else build_lower_turn_through_junction_assembly)(
            assembly_id=f"base-{lane}", system="K1", dn_mm=100,
        ) for lane in range(proposed_shafts)
    )
    roof = None
    if include_roof:
        if req.wastewater_roof_relative_elevation_m is None or req.storm_funnels_count != 4:
            raise ValueError("explicit roof elevation and four confirmed funnels are required")
        roof = ResidentialRoofPreview(
            req.wastewater_roof_relative_elevation_m, req.wastewater_roof_kind,
            tuple((build_lower_turn_cleanout_assembly if i == 0 else build_lower_turn_through_junction_assembly)(
                assembly_id=f"K2-base-{i}", system="K2", dn_mm=100,
            ) for i in range(4)),
        )
    result = ResidentialPreview(programme, tuple(apartments), lower, basement, branch, stack, roof)
    result.validate()
    return result


def _floor_geometry(assembly: WastewaterFloorAssembly, *, scale: float) -> str:
    """Use existing fixtures, traps and joints; the composer owns annotations."""
    root = ET.fromstring(render_typical_floor_assembly_svg(
        assembly, scale=1, render_architecture=False, compact_fixture_annotations=True,
    ))
    for child in tuple(root):
        # Keep hydraulic geometry and fittings, without old pixel-size captions.
        keep = any(child.get(key) for key in (
            "data-floor-segment", "data-direct-fitting-joint", "data-floor-fixture",
            "data-floor-fitting", "data-diameter-transition-group",
        ))
        if not keep or child.get("data-role") == "riser":
            root.remove(child)
    return apply_residential_paper_style(
        ET.tostring(root, encoding="unicode"), fragment_scale=scale * 10 / 3,
    )


def build_small_residential_svg(model: ResidentialPreview) -> str:
    """A2 composition: confirmed floor spacing, schematic routing/room widths."""
    model.validate()
    b = model.basement
    levels = {a.floor_number: a.assembly.floor_elevation_m for a in model.apartments}
    highest = max(levels.values())
    # A consistent level transform also controls the basement. For this bounded
    # preview allow 1:50 or 1:100; room/fitting graphics are schematic, not AR.
    denominator = 50 if (highest - b.basement_floor_m) * 20 <= 190 else 100
    scale_y = 1000 / denominator
    y0 = 290 + b.basement_floor_m * scale_y
    def y(z: float) -> float:
        return y0 - z * scale_y

    floor_scale, floor_baseline = .28, 212.
    left, bay_width, wall_in, wall_out = 60., 105., 492., 496.
    top = y(model.roof.elevation_m) if model.roof else y(highest) - 58
    if top < 76 or any((levels[n+1]-levels[n])*scale_y < 58 for n in range(1, len(levels))):
        raise ValueError("confirmed levels need a different sheet layout; cannot squeeze room graphics")
    axes = [left + i * bay_width + 87 for i in range(len(model.lower_nodes))]
    main_y = y(b.proposed_invert_m)
    turn_scale, turn_y = .22, main_y - 76 * .22
    out_x = 536.
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" '
        'data-small-residential-preview="true" data-release-ready="false" '
        f'data-floor-scale-denominator="{denominator}">',
        '<defs><pattern id="slab-hatch" width="3" height="3" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="3" stroke="#777" stroke-width=".25"/></pattern></defs>',
        '<rect width="594" height="420" fill="white"/>',
        _text(25, 17, "К1. Двухэтажный жилой дом: квартиры - стояки - подвал - выпуск", height=5),
        _text(25, 26, "Компоновочный вариант по исходным планам. Требует согласования трасс и расчёта; не лист готового комплекта.", height=2.5),
        _text(25, 34, f"Межэтажные отметки М 1:{denominator}. Ширина помещений, приборы и прокладка показаны условно.", height=2.5),
        _text(25, 44, f"{len(model.apartments)} квартир | 4 прибора в каждой | {len(model.lower_nodes)} предлагаемых стояка К1 | 1 общий выпуск", height=3.5),
    ]
    # Room cells follow programme/shaft columns, not hand-painted independent floors.
    for apt in model.apartments:
        fy = y(levels[apt.floor_number])
        room_top = top if apt.floor_number == max(levels) else y(levels[apt.floor_number+1]) + 2
        x = left + apt.lane * bay_width
        parts.append(f'<g data-apartment="{apt.apartment_id}" data-floor="{apt.floor_number}" '
                     f'data-stack-id="{apt.stack_id}" data-lane="{apt.lane}">')
        for room, rx, rw in (("Кухня", x, 22), ("Санузел", x+22, 77)):
            parts.append(f'<rect data-preview-room="{room}" x="{rx:g}" y="{room_top:.3f}" '
                         f'width="{rw:g}" height="{fy-room_top:.3f}" fill="none" stroke="black" stroke-width=".25"/>')
            parts.append(_text(rx+rw/2, room_top+12, room, height=2.5, anchor="middle"))
        parts.append(_text(x+49, room_top+5, f"Квартира {int(apt.apartment_id[1:])}*", height=3.5, anchor="middle"))
        parts.append('</g>')
    # Shared floor outlines and known basement slab underside; other slab thicknesses
    # are not inferred from floor count. Roof level is used only if supplied.
    if model.roof:
        parts.append(_line(left, top, wall_out, top, width=.6, marker='data-confirmed-roof="true"'))
        parts.extend(_level_mark(top, model.roof.elevation_m, "Кровля"))
    for floor, z in sorted(levels.items()):
        fy = y(z)
        parts.append(_line(left, fy, wall_out, fy, marker=f'data-floor-boundary="{floor}" data-elevation-m="{z:g}"'))
        parts.extend(_level_mark(fy, z, f"{floor} этаж"))
    first_y, ceiling_y, base_y = y(b.first_floor_m), y(b.ceiling_m), y(b.basement_floor_m)
    parts.extend((
        f'<rect data-basement-slab="ceiling" x="{left:g}" y="{first_y:.3f}" width="{wall_out-left:g}" '
        f'height="{ceiling_y-first_y:.3f}" fill="url(#slab-hatch)" stroke="black" stroke-width=".25"/>',
        f'<rect data-basement-slab="floor" x="{left:g}" y="{base_y:.3f}" width="{wall_out-left:g}" '
        'height="4" fill="url(#slab-hatch)" stroke="black" stroke-width=".25"/>',
        f'<rect data-preview-wall="true" x="{wall_in:g}" y="{top:.3f}" width="4" height="{base_y+4-top:.3f}" '
        'fill="url(#slab-hatch)" stroke="black" stroke-width=".25"/>',
        _text(left+5, ceiling_y+8, "Подвал", height=3.5),
        _line(75, ceiling_y, 75, base_y, marker='data-clear-basement-height="true"'),
        _text(73, (ceiling_y+base_y)/2, f"{b.clear_height_m*1000:g}", anchor="end"),
    ))
    for yy in (ceiling_y, base_y):
        parts.extend((_line(72, yy, 78, yy), _line(73.5, yy+1.5, 76.5, yy-1.5)))
    parts.extend(_level_mark(base_y, b.basement_floor_m, "Пол подвала"))
    if model.roof:
        parts.append(_text(25, 56, "Плоская неэксплуатируемая кровля. Выводы К1: 200 мм над кровлей; К2 с четырьмя воронками - лист 2.", height=2.5))
    else:
        parts.append(_text(25, 58, "Вентиляционные части стояков: продолжение до кровли уточняется после получения её отметки.", height=2.5))
    for lane, axis in enumerate(axes):
        vent_top = top - model.roof.vent_height_m * scale_y if model.roof else top-6
        parts.append(_line(axis, vent_top, axis, turn_y, width=.6,
                           marker=f'data-stack-axis="К1-{lane+1}" data-lane="{lane}"'))
        if model.roof:
            parts.extend(_vent_annotation(axis, top, vent_top, lane+1))
        else:
            parts.append(_text(axis, top-10, f"Ст. К1-{lane+1}", height=3.5, anchor="middle"))
        parts.append(_arrow((axis, ceiling_y+7), (0, 1), marker=f"stack-{lane}"))
    # Existing floor graphs are placed against exactly those same riser axes.
    for apt in model.apartments:
        f = apt.assembly
        axis = axes[apt.lane]
        fy = y(levels[apt.floor_number])
        tx = axis - f.port("riser_join").point.x_mm * floor_scale
        ty = fy - floor_baseline * floor_scale
        parts.append(f'<g data-apartment-pipework="{apt.apartment_id}" data-stack-x="{axis:g}" '
                     f'transform="translate({tx:.4f} {ty:.4f}) scale({floor_scale})">'
                     f'{_floor_geometry(f, scale=floor_scale)}</g>')
        # A readable OD50 label fits between the bath and basin, clear of wyes.
        a, c = f.port("junction_2").point, f.port("junction_3").point
        parts.append(render_inline_pipe_label(
            line_id=f"{apt.apartment_id}-branch50", label="К1 ⌀50",
            start=(tx+a.x_mm*floor_scale, ty+a.y_mm*floor_scale),
            end=(tx+c.x_mm*floor_scale, ty+c.y_mm*floor_scale),
            font_size=STYLE.font_size(2.5, 1), padding=.5,
        ))
        parts.append(render_inline_pipe_label(
            line_id=f"{apt.apartment_id}-riser110", label="К1 ⌀110",
            start=(axis, fy-45), end=(axis, fy-28), font_size=STYLE.font_size(2.5, 1), padding=.5,
        ))
        parts.extend(_revision(axis, fy, scale_y))
        cap = f.port("cleanout_cap").point
        cx, cy = tx + cap.x_mm*floor_scale, ty+cap.y_mm*floor_scale
        parts.extend((
            f'<path data-floor-cleanout-leader="{apt.apartment_id}" d="M{cx:.3f},{cy:.3f} l-3,-6 h-6" '
            'fill="none" stroke="black" stroke-width=".25"/>',
            _text(cx-9, cy-7, "Пр.", height=2.5), _text(cx-9, cy-2.5, "50", height=2.5),
            _arrow((cx, cy), (3, 6), marker=f"{apt.apartment_id}-cleanout", length=1.4),
        ))
        # The short WC/riser connection is labelled outside the fittings.
        short = f.segment("collector_to_riser")
        pa, pb = f.port(short.start_port_id).point, f.port(short.end_port_id).point
        target = (tx+(pa.x_mm+pb.x_mm)/2*floor_scale, ty+(pa.y_mm+pb.y_mm)/2*floor_scale)
        knee = (axis-6, fy-23)
        parts.extend((
            f'<path data-wc-branch-leader="{apt.apartment_id}" d="M{target[0]:.3f},{target[1]:.3f} '
            f'L{knee[0]:.3f},{knee[1]:.3f} H{axis-22:.3f}" fill="none" stroke="black" stroke-width=".25"/>',
            _arrow(target, (target[0]-knee[0], target[1]-knee[1]), marker=f"{apt.apartment_id}-wc", length=1.4),
            render_inline_pipe_label(line_id=f"{apt.apartment_id}-wc110", label="⌀110",
                                     start=(axis-22, fy-26), end=(axis-6, fy-26),
                                     font_size=STYLE.font_size(2.5, 1), padding=.3),
        ))
        sa, sb = f.port("junction_1").point, f.port("junction_2").point
        parts.append(_arrow((tx+(sa.x_mm+sb.x_mm)/2*floor_scale, ty+(sa.y_mm+sb.y_mm)/2*floor_scale),
                            (sb.x_mm-sa.x_mm, sb.y_mm-sa.y_mm), marker=f"{apt.apartment_id}-flow"))
    # Canonical lower nodes: one free-end cleanout, three open through-wyes.
    leaders = LeaderLayoutEngine(bounds=LeaderBounds(90, ceiling_y+9, 588, base_y-1), units_per_mm=1)
    previous_out = None
    for lane, (axis, node) in enumerate(zip(axes, model.lower_nodes)):
        parts.append(render_lower_turn_assembly_svg(
            node, x=axis, y=turn_y, scale=turn_scale, pipe_width=.6,
            graphic_size=FittingGraphicSize(100, 100, 1), annotations=False,
            pipe_labels=False, flow_direction=False,
        ))
        if previous_out is not None:
            incoming = round(axis + node.port("main_in").point.x_mm * turn_scale, 1)
            parts.append(_line(previous_out, main_y, incoming, main_y, width=.6,
                               marker=f'data-basement-link="{lane-1}-{lane}"'))
            parts.append(render_inline_pipe_label(
                line_id=f"collector-{lane}", label="К1 ⌀110", start=(previous_out, main_y),
                end=(incoming, main_y), font_size=STYLE.font_size(3.5, 1), padding=1,
            ))
        previous_out = round(axis + node.port("main_out").point.x_mm * turn_scale, 1)
        if lane == 0:
            cap = node.port("cleanout_cap").point
            parts.append(leaders.place_and_render(LeaderRequest(
                "basement-cleanout", "base-0:cleanout_cap", (axis+cap.x_mm*turn_scale, main_y),
                "Прочистка", "DN100", preferred_side=-1, preferred_vertical=-1,
            )))
    assert previous_out is not None
    parts.extend((
        f'<rect data-outlet-sleeve="true" x="{wall_in-1:g}" y="{main_y-2:.3f}" width="6" height="4" '
        'fill="white" stroke="black" stroke-width=".25"/>',
        _line(previous_out, main_y, out_x, main_y, width=.6, marker='data-building-outlet="proposed"'),
        f'<path d="M511,{main_y-1.2:.3f} l3,1.2 l-3,1.2 Z" fill="black"/>',
        leaders.place_and_render(LeaderRequest(
            "outlet", "outlet", (out_x, main_y), "Выпуск К1", f"Лоток {_elev(b.proposed_invert_m)}*",
            preferred_side=1, preferred_vertical=-1,
        )),
        _line(wall_out, y(b.ground_m), 588, y(b.ground_m), color="#555"),
        _text(wall_out+3, y(b.ground_m)-3, f"Земля {_elev(b.ground_m)}", height=2.5),
        _text(25, 309, "Принятые для компоновки решения", height=3.5),
    ))
    notes = (
        "1. Четыре вертикальные пары квартир; стояки и сборная магистраль предложены, на исходных планах не показаны.",
        "2. Кухня и санузел каждой квартиры подключены общей ветвью; унитаз расположен у стояка. У начала ветви - прочистка (Пр.).",
        "3. Прочистка в подвале только на свободном конце; остальные нижние узлы проходные, без заглушки потока.",
        "4. Подписи с символом диаметра указывают наружный размер: PP HT 50x1,8 и 110x2,7 мм; присоединение унитаза DN100.",
        "5. Диаметр общей магистрали - вариант, не подбор. Расходы, длины, уклоны, наполнение и труба за стеной не определены.",
        "6. * Нумерация квартир условная. Лоток - предварительная граница по морозу; лоток колодца и профиль трассы не подтверждены.",
        ("7. Вытяжные части К1: СП 30, 18.18-18.21. Диаметр сохраняется; пластик защитить от УФ; зонты не устанавливать."
         if model.roof else
         "7. Отметки подключения приборов, кровля, вентиляция, проходки/огнезащита и доступность обслуживания требуют проработки."),
        "8. Ревизии показаны на обоих этажах; 1000 мм - принятое правило доступности Zarya. Состав ориентирован на ГОСТ Р 21.620-2023, прил. В.",
    )
    if model.roof:
        notes += ("Проверить по АР: не менее 4 м по горизонтали от фановых выводов до открываемых окон и балконов (СП 30, 18.18).",)
    parts.append(study_notes_svg(notes, x=25, y=317, width=370, bottom=397))
    parts.extend((
        _text(25, 404, "ЗАРЯ | Согласование компоновки К1", height=3.5),
        _text(25, 411, "Гидравлический расчёт и готовый комплект проектной документации этим листом не заменяются.", height=2.5),
        study_section_frame(system_label="К1", sheet_total=2 if model.roof else 1,
                            cipher="УЧЕБНЫЙ-К1К2.СХ" if model.roof else "УЧЕБНЫЙ-К1.СХ"), '</svg>',
    ))
    return "".join(parts)


def _vent_annotation(x: float, roof_y: float, tip_y: float, number: int) -> tuple[str, ...]:
    """Actual 200-mm extension, outside arrows when the 1:50 gap is only 4 mm."""
    polka_y, knee_x = roof_y-20, x-12
    target_y = (roof_y+tip_y)/2
    return (
        f'<g data-fan-vent="К1-{number}" data-roof-y="{roof_y:.3f}" data-tip-y="{tip_y:.3f}" '
        'data-height-mm="200">',
        f'<path d="M{x:.3f},{target_y:.3f} L{knee_x:.3f},{polka_y:.3f} H{x-67:.3f}" '
        'fill="none" stroke="black" stroke-width=".25"/>',
        _text(x-66, polka_y-2, "Фановый стояк", height=3.5),
        render_inline_pipe_label(line_id=f"vent-{number}", label=f"К1-{number} ⌀110",
                                 start=(x-64, polka_y+5), end=(x-23, polka_y+5),
                                 font_size=STYLE.font_size(3.5, 1), padding=.5),
        _arrow((x, target_y), (x-knee_x, target_y-polka_y), marker=f"vent-{number}", length=1.5),
        _line(x+1, tip_y, x+14, tip_y), _line(x+1, roof_y, x+14, roof_y),
        _line(x+11, tip_y-5, x+11, roof_y+5, marker='data-vent-dimension-line="true"'),
        _arrow((x+11, tip_y), (0, 1), marker=f"vent-{number}-dim-top", length=1.5),
        _arrow((x+11, roof_y), (0, -1), marker=f"vent-{number}-dim-bottom", length=1.5),
        _text(x+15, target_y+1, "200", height=3.5), '</g>',
    )


def _level_mark(y: float, elevation: float, label: str) -> tuple[str, ...]:
    return (
        f'<g data-level-mark="{escape(label)}" data-elevation-m="{elevation:g}">',
        _line(25, y-4, 55, y-4), _line(55, y-4, 55, y), _line(52, y, 60, y),
        f'<path d="M53,{y-2:.3f} L55,{y:.3f} L57,{y-2:.3f}" fill="none" stroke="black" stroke-width=".25"/>',
        _text(25, y-6, _elev(elevation)), _text(25, y-.5, label, height=2.5), '</g>',
    )


def _arrow(tip: tuple[float, float], direction: tuple[float, float], *, marker: str, length: float = 2.2) -> str:
    norm = hypot(*direction)
    ux, uy = direction[0]/norm, direction[1]/norm
    bx, by = tip[0]-length*ux, tip[1]-length*uy
    half = length/3
    return (f'<path data-direction-arrow="{escape(marker)}" '
            f'd="M{tip[0]:.3f},{tip[1]:.3f} L{bx-uy*half:.3f},{by+ux*half:.3f} '
            f'L{bx+uy*half:.3f},{by-ux*half:.3f} Z" fill="black"/>')


def _revision(x: float, floor_y: float, scale_y: float) -> tuple[str, ...]:
    centre = floor_y - scale_y
    return (
        f'<g data-riser-revision="true" data-centre-y="{centre:.3f}" data-floor-y="{floor_y:.3f}">',
        render_ugo("revision", x, centre-REVISION_CENTRE_ANCHOR[0]*.2, scale=.2, rotation=90),
        _line(x+6, centre, x+6, floor_y),
        _line(x+1, centre, x+8, centre), _line(x+1, floor_y, x+8, floor_y),
        _line(x+5, centre+1, x+7, centre-1), _line(x+5, floor_y+1, x+7, floor_y-1),
        _text(x+4, (centre+floor_y)/2, "1000", height=3.5, anchor="middle",
              marker=f'transform="rotate(-90 {x+4:.3f} {(centre+floor_y)/2:.3f})"'), '</g>',
    )


def generate_small_residential_pdf(output_path: str, model: ResidentialPreview) -> str:
    import cairosvg  # type: ignore[import-untyped]

    ensure_drafting_font_registered()
    path = Path(output_path)
    svg = build_small_residential_svg(model)
    validate_study_section_frame(svg, system_label="К1", sheet_total=2 if model.roof else 1,
                                 cipher="УЧЕБНЫЙ-К1К2.СХ" if model.roof else "УЧЕБНЫЙ-К1.СХ")
    if model.roof is None:
        pdf = cairosvg.svg2pdf(bytestring=svg.encode())
    else:
        from io import BytesIO
        from pypdf import PdfReader, PdfWriter
        from app.pz.small_residential_rainwater import build_small_residential_k2_svg

        k2_svg = build_small_residential_k2_svg(model)
        validate_study_section_frame(k2_svg, system_label="К2", sheet_no=2, sheet_total=2)
        writer = PdfWriter()
        for page_svg in (svg, k2_svg):
            page_pdf = cairosvg.svg2pdf(bytestring=page_svg.encode())
            writer.add_page(PdfReader(BytesIO(page_pdf)).pages[0])
        stream = BytesIO()
        writer.write(stream)
        pdf = stream.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf)
    return str(path)
