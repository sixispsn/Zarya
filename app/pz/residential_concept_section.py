"""Representative residential cutaway for Studio's private preview.

Paper geometry is NOT a surveyed network. Reuse canonical UGO and fitting
assemblies; keep this model out of Project.sewer_pipes and every takeoff path.
Only the full production adapter can certify an IOS3 drawing for release.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, isclose
from pathlib import Path
from html import escape
from textwrap import wrap
from xml.etree import ElementTree as ET

from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.drawing_sheet_style import FittingGraphicSize
from app.pz.residential_case_section import _callout, _revision_on_main
from app.pz.residential_plan_section import SectionBay, _floor, _unknown_slope
from app.pz.small_residential_preview import _arrow
from app.pz.small_residential_rainwater import FUNNEL_OUTLET_ANCHOR, HEATED_FUNNEL_OUTLET_ANCHOR
from app.pz.small_residential_section import _label, _main_crossings, _slope_mark
from app.pz.wastewater_presentation import SectionMainInput, RepresentativeSectionInput
from app.pz.wastewater_basement_profile import STYLE, _line, _text
from app.pz.wastewater_building_drafting import _building_section_break_svg, drawing_frame_svg
from app.pz.project import DocumentInfo
from app.pz.wastewater_drafting import (
    build_lower_turn_cleanout_assembly, build_lower_turn_through_junction_assembly,
    render_inline_pipe_label, render_lower_turn_assembly_svg,
)
from app.pz.wastewater_floor_drafting import FloorFixtureInput, build_typical_floor_assembly
from app.pz.wastewater_ugo import render_ugo
from app.pz.section_level_mark import level_mark, level_text
from app.pz.section_fan import SectionFanInput, resolve_section_fan
from app.pz.section_fan_drawing import common_fan_svg, fan_dimension
from app.pz.section_storm import SectionStormInput
from app.pz.section_main_hydraulics import assess_section_main
from app.pz.building_cutaway import representative_floors


LEFT, RIGHT, K2_AXIS, NODE_SCALE = 55., 277., 166., .16
BAYS = (SectionBay("К1-А", 55, 152, 146, False), SectionBay("К1-Б", 180, 277, 186, True))
FIXTURES = {
    "residential_full_bath": ("sink", "bath", "washbasin", "toilet"),
    "residential_sit_bath": ("sink", "bath", "washbasin", "toilet"),
    "residential_central_hw": ("sink", "shower", "washbasin", "toilet"),
    "residential_no_bath": ("sink", "washbasin", "toilet"),
}


@dataclass(frozen=True)
class ResidentialConceptSection:
    floors: int
    floor_height_m: float
    basement_kind: str
    basement_floor_m: float | None
    roof_kind: str
    drainage: str
    consumer_code: str
    title: str = "Жилой дом"
    k1: SectionMainInput = SectionMainInput()
    k2: SectionMainInput = SectionMainInput()
    fan: SectionFanInput = SectionFanInput()
    funnel_heated: bool | None = None
    document: DocumentInfo | None = field(default=None, compare=False)
    storm: SectionStormInput = SectionStormInput()
    k1_total_flow_lps: float | None = None
    zero_absolute_m: float | None = None
    zero_source_ref: str = ""
    k1_hour_max_m3h: float | None = None
    k1_fixture_max_lps: float | None = None

    @property
    def datum(self):
        return RepresentativeSectionInput(zero_absolute_m=self.zero_absolute_m,
                                          zero_source_ref=self.zero_source_ref)

    @property
    def main_checks(self):
        return tuple(assess_section_main(system, data, q_hour_max_m3h=self.k1_hour_max_m3h,
            fixture_max_lps=self.k1_fixture_max_lps) for system, data in self.mains)

    @property
    def fan_plan(self):
        return resolve_section_fan(self.roof_kind, self.floors, self.floor_height_m, self.fan)

    @property
    def mains(self):
        return (("К1", self.k1),) + ((("К2", self.k2),) if self.drainage == "internal" else ())

    @property
    def fan_notice(self):
        return self.fan_plan.notice

    @property
    def boundary_notice(self):
        return ("Проверяется внутренняя сеть относительно здания. Наружная трасса не моделируется. "
                "Отметки лотков выпусков не подтверждают самотёк до приёмника "
                "и защиту от подпора наружной сети. Для этого нужны условия подключения и отметки приёмника.")

    @property
    def design_notice(self):
        pending = [f"{name}: {', '.join(row.missing)}" for name, row in self.mains if row.missing]
        return ("Характерный разрез; не для подсчёта длин. " +
                ("Уточнить — " + "; ".join(pending) + ". " if pending else
                 "DN магистралей, уклоны и выпуски заданы проектировщиком. ") +
                "Вентиляция, привязка к АР и обслуживание всей сети требуют проверки. " + self.boundary_notice)

    @property
    def shown_floors(self):
        return representative_floors(self.floors)

    @property
    def technical_space_levels(self):
        """AR space exists independently of a confirmed fan collector.

        These are supplied elevations, not an extra residential storey or an
        inferred ventilation route. Incomplete/conflicting inputs stay unknown.
        """
        d = self.fan
        declared = {"cold": "cold_attic", "warm": "warm_attic", "technical": "technical_storey"}
        if (d.space not in declared.values()
                or d.building_attic_kind not in {"unknown", *declared}
                or (d.building_attic_kind != "unknown" and declared[d.building_attic_kind] != d.space)
                or d.space_floor_m is None or d.roof_level_m is None
                or not self.floors*self.floor_height_m <= d.space_floor_m < d.roof_level_m):
            return None
        return d.space_floor_m, d.roof_level_m

    def validate(self):
        self.datum  # Validate supplied datum even when no outlet is known yet.
        if isinstance(self.floors, bool) or not isinstance(self.floors, int) or not 1 <= self.floors <= 200:
            raise ValueError("representative section supports 1–200 floors")
        if not isfinite(self.floor_height_m) or self.floor_height_m <= 0:
            raise ValueError("floor height must be explicit and positive")
        if self.basement_kind not in {"none", "basement", "subfloor"}:
            raise ValueError("basement choice is required")
        if self.basement_kind != "none" and (self.basement_floor_m is None or
                not isfinite(self.basement_floor_m) or self.basement_floor_m >= 0):
            raise ValueError("basement needs an explicit negative elevation")
        if self.roof_kind not in {"flat_non_accessible", "flat_accessible", "single_slope", "gable"}:
            raise ValueError("roof profile needs architectural input")
        if self.drainage not in {"internal", "external"} or self.consumer_code not in FIXTURES:
            raise ValueError("unsupported residential section input")
        if self.funnel_heated is not None and type(self.funnel_heated) is not bool:
            raise ValueError("funnel heating must be explicitly true/false or unknown")

    def apartment(self, floor, stack):
        # Zero is the fixture builder's local drawing origin, never an AR mark.
        return build_typical_floor_assembly(
            assembly_id=f"{stack}:{floor}", floor_no=floor, riser_id=stack,
            floor_elevation_m=0., fixtures=tuple(
                FloorFixtureInput(kind, kind, "Кухня" if kind == "sink" else "Санузел")
                for kind in FIXTURES[self.consumer_code]), riser_dn_mm=self.fan.working_diameter_mm,
        )

    def lower_nodes(self):
        riser_dn = self.fan.working_diameter_mm or 100
        dn = self.k1.dn_mm or riser_dn  # Graphic template only if no assigned DN.
        return (build_lower_turn_cleanout_assembly(assembly_id="К1-А-низ", dn_mm=dn, riser_dn_mm=riser_dn),
                build_lower_turn_through_junction_assembly(assembly_id="К1-Б-низ", dn_mm=dn, riser_dn_mm=riser_dn))

    def storm_lower_node(self):
        dn = self.storm.selected_riser_dn_mm or 100
        return build_lower_turn_cleanout_assembly(assembly_id="К2-низ", system="K2",
                                                  dn_mm=self.k2.dn_mm or dn, riser_dn_mm=dn)

    def flow_paths(self):
        """Every visible source reaches its own system's outlet, without cycles.

        Canonical service branches are not wastewater sources. Omitted storeys
        are a display compression, never extra measured pipe lengths.
        """
        self.validate()
        graph, sources = {}, []
        for bay, lower in zip(BAYS, self.lower_nodes(), strict=True):
            if lower.validate():
                raise ValueError("invalid lower node")
            lp = bay.stack + ":lower:"
            graph.update((lp+s.start_port_id, lp+s.end_port_id) for s in lower.segments if s.carries_flow)
            floors = sorted(self.shown_floors)
            for n, floor in enumerate(floors):
                a = self.apartment(floor, bay.stack)
                if a.validate():
                    raise ValueError("invalid apartment assembly")
                prefix = f"{bay.stack}:{floor}:"
                pairs = [(s.start_port_id, s.end_port_id) for s in a.segments if s.carries_flow]
                pairs += [(j.start_port_id, j.end_port_id) for j in a.direct_fitting_joints]
                pairs += [(f.trap_inlet_port_id, f.trap_outlet_port_id) for f in a.fixtures if f.trap_mode == "external"]
                graph.update((prefix+x, prefix+y) for x, y in pairs)
                graph[prefix+"riser_join"] = (f"{bay.stack}:{floors[n-1]}:riser_join" if n else lp+"riser_in")
                sources.extend(prefix+f.fixture_outlet_port_id for f in a.fixtures)
        graph["К1-А:lower:main_out"] = "К1-Б:lower:main_in"
        graph["К1-Б:lower:main_out"] = "К1:outlet"
        if self.drainage == "internal":
            lower = self.storm_lower_node()
            graph.update(("К2:lower:"+s.start_port_id, "К2:lower:"+s.end_port_id)
                         for s in lower.segments if s.carries_flow)
            graph["К2:funnel"] = "К2:lower:riser_in"
            graph["К2:lower:main_out"] = "К2:outlet"
            sources.append("К2:funnel")
        paths = {}
        for source in sources:
            current, path = source, []
            target = "К2:outlet" if source.startswith("К2:") else "К1:outlet"
            while current != target:
                if current in path or current not in graph:
                    raise ValueError(f"disconnected or mixed-system flow: {source}")
                path.append(current)
                current = graph[current]
            paths[source] = tuple((*path, current))
        return paths


def build_concept_section_svg(model: ResidentialConceptSection) -> str:
    paths = model.flow_paths()
    count = len(model.shown_floors)
    fan = model.fan_plan
    common = fan.kind == "common"
    technical = model.technical_space_levels is not None
    # Reserve the full 55-mm inscription and a separate notes band.
    first_y = 254. if count == 3 else 232. if count == 2 else 210.
    pitch = (48. if model.floors > 3 else 54.) if common or technical else (54. if model.floors > 3 else 60.)
    floors_y = {n: first_y-index*pitch for index, n in enumerate(model.shown_floors)}
    if model.floors > 3:
        floors_y[model.floors] -= 18
    technical_floor_y = min(floors_y.values())-pitch
    roof_y, base_y = technical_floor_y-(26 if common or technical else 0), first_y+58
    main_y, storm_y = first_y+23, first_y+41
    common_svg, fan_ports = (common_fan_svg(fan, roof_y, technical_floor_y, internal_storm=model.drainage == "internal")
                             if common else ("", {}))

    def main_label(system, data, a, b):
        return _label(system+"-main", f"{system.upper().replace('K', 'К')} ⌀ {data.dn_mm or '—'}", a, b, height=2.5)

    def slope(key, data, x, y, direction):
        return (_unknown_slope(key, x, y-5, direction) if data.slope is None else
                _slope_mark(key, (x-15*direction, y), (x+15*direction, y), data.slope))

    def outlet_notes(system, data, x, y):
        target = data.discharge_point or "Приёмник не задан"
        if len(target) > 28:
            target = target[:27] + "…"
        mark = (_text(x, y+11, "Лоток не задан", height=2.5) if data.outlet_invert_m is None else
                level_mark("outlet-"+system, RIGHT+6 if system == "К1" else LEFT-6, y,
                           data.outlet_invert_m, "Лоток"))
        absolute = model.datum.absolute_level(data.outlet_invert_m)
        absolute_label = ("Абс. " + level_text(absolute) if absolute is not None else "Абс. отм. не задана")
        return ''.join((f'<g data-outlet-annotation="{system}" data-absolute-m="{absolute}">',
                        _text(x, y+7, "Выпуск "+system, height=2.5), mark,
                        _text(x, y+11, absolute_label, height=2.5),
                        _text(x, y+15, target, height=2.5), '</g>'))

    def main_start(system, data, target, x, y, reference_x):
        if data.start_invert_m is None or not data.source_ref.strip():
            return ''
        # The thin extension terminates at the actual MAIN port, never at a
        # guessed paper-to-model elevation or at the nearby cleanout cap.
        return (f'<g data-main-start="{system}" data-target-x="{target[0]:g}" '
                f'data-target-y="{target[1]:g}">' +
                level_mark("main-start-"+system, x, y, data.start_invert_m,
                           "Лоток "+system, reference_x=reference_x) + '</g>')
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="420mm" viewBox="0 0 297 420" '
             f'data-view="representative-section" data-release-ready="false" data-takeoff-eligible="false" '
             f'data-section-fan-kind="{fan.kind}" data-path-count="{len(paths)}">',
             f'<desc>{escape(model.fan_notice)}</desc>',
             '<defs><pattern id="slab" width="5" height="5" patternUnits="userSpaceOnUse">'
             '<path d="M-1,1 L1,-1 M0,5 L5,0 M4,6 L6,4" stroke="black" stroke-width=".25"/>'
             '</pattern></defs><rect width="297" height="420" fill="white"/>',
             _text(26, 18, "Система водоотведения", height=5),
             _text(26, 26, "Предварительный разрез К1" + (" + К2" if model.drainage == "internal" else ""))]
    if model.floors <= 3:
        parts.append(_text(26, 33, "Характерные группы приборов. Компоновка условная, без масштаба.", height=2.5))
    # Architecture: one shared axis system drives rooms, risers and lower nodes.
    for x in (LEFT, RIGHT):
        parts.append(_line(x, roof_y, x, base_y+5, width=.35))
    for x in (LEFT+2, RIGHT-2):
        parts.append(_line(x, roof_y, x, base_y+5))
    for floor, fy in floors_y.items():
        top = fy-pitch
        parts.extend((f'<rect data-floor-boundary="{floor}" x="{LEFT:g}" y="{fy:g}" width="{RIGHT-LEFT:g}" height="2" '
                      'fill="url(#slab)" stroke="black" stroke-width=".25"/>',
                      level_mark(f"floor-{floor}", 50, fy, (floor-1)*model.floor_height_m,
                                 f"{floor} этаж*", reference_x=LEFT)))
        for bay in BAYS:
            wall = bay.right-24 if bay.mirrored else bay.left+24
            for x in (wall, bay.left, bay.right):
                parts.append(_line(x, top, x, fy, marker='data-room-boundary="true"'))
            kitchen = (wall+bay.right)/2 if bay.mirrored else (wall+bay.left)/2
            sanitary = (wall+bay.left)/2 if bay.mirrored else (wall+bay.right)/2
            parts.extend((_text(kitchen, top+9, "Кухня", anchor="middle", height=2.5),
                          _text(sanitary, top+9, "Санузел", anchor="middle", height=2.5)))
        if model.drainage == "internal":
            parts.append(_text(K2_AXIS-8, top+9, "Шахта", anchor="middle", height=2.5))
        else:
            parts.extend((_text(K2_AXIS, top+9, "Общие", anchor="middle", height=2.5),
                          _text(K2_AXIS, top+14, "зоны", anchor="middle", height=2.5)))
    if model.basement_kind != "none":
        parts.extend((f'<rect data-basement-floor="true" x="{LEFT}" y="{base_y:g}" width="{RIGHT-LEFT}" height="5" '
                      'fill="url(#slab)" stroke="black" stroke-width=".35"/>',
                      level_mark("basement", 50, base_y, model.basement_floor_m,
                                 "Подвал" if model.basement_kind == "basement" else "Техподп.", reference_x=LEFT),
                      _text(209, base_y-4, "Разводка под перекрытием*", height=2.5)))
    else:
        parts.append(_text(190, base_y-4, "Подземная часть условно", height=2.5))

    def roof_at(x):
        if model.roof_kind == "gable":
            return roof_y-12*(1-abs(x-(LEFT+RIGHT)/2)/((RIGHT-LEFT)/2))
        if model.roof_kind == "single_slope":
            return roof_y-12*(RIGHT-x)/(RIGHT-LEFT)
        return roof_y

    roof_points = [(LEFT, roof_at(LEFT)), ((LEFT+RIGHT)/2, roof_at((LEFT+RIGHT)/2)), (RIGHT, roof_at(RIGHT))]
    parts.extend(('<polyline points="'+' '.join(f'{x:g},{y:g}' for x, y in roof_points)+
                  '" fill="none" stroke="black" stroke-width=".35"/>',
                  _line(LEFT, roof_y+2, RIGHT, roof_y+2),
                  "" if common or technical else _text(26, roof_y-2, "Кровля*", height=2.5)))
    if technical and not common:
        space_level, roof_level = model.technical_space_levels
        parts.extend((
            '<g data-technical-space="true">',
            _line(LEFT, technical_floor_y, RIGHT, technical_floor_y, width=.35),
            level_mark("fan-space", 50, technical_floor_y, space_level, "Тех. уровень", reference_x=LEFT),
            level_mark("fan-roof", 50, roof_y, roof_level, "Кровля", reference_x=LEFT),
            _text(61, roof_y+8, {"technical_storey":"Технический этаж", "warm_attic":"Тёплый чердак",
                               "cold_attic":"Холодный чердак"}[model.fan.space], height=2.5),
            '</g>',
        ))
    for bay in BAYS:
        x, local_roof = bay.axis, roof_at(bay.axis)
        pending_fan = fan.kind == "pending"
        tip = fan_ports[x] if common else local_roof+3 if pending_fan else local_roof-10
        top_lower = main_y-76*NODE_SCALE
        parts.append(_line(x, tip, x, top_lower, width=.6,
                           marker=f'data-section-riser="{bay.stack}" data-axis-x="{x:g}"'))
        if pending_fan:
            parts.append(_arrow((x, tip), (0, -1), marker=bay.stack+"-fan-pending"))
            parts.append(_callout(bay.stack+"-fan", (x, tip+3), "Вытяжка "+bay.stack, "Решение уточнить",
                                  (x+(-20 if not bay.mirrored else 20), roof_y-20), 65 if not bay.mirrored else 272))
        elif not common:
            parts.append(f'<g data-fan-open-terminal="{bay.stack}"/>')
            detail = f"Открытое устье · DN{fan.diameter_mm}" if fan.diameter_mm else "Открытое устье · DN уточнить"
            parts.append(_callout(bay.stack+"-fan", (x, tip), "Фановый стояк "+bay.stack, detail,
                                  (x+(-20 if not bay.mirrored else 20), roof_y-20), 65 if not bay.mirrored else 272))
            parts.append(fan_dimension(bay.stack, x, local_roof, tip, fan.dimension, dx=-7 if not bay.mirrored else 7))
        for floor, fy in floors_y.items():
            apartment = model.apartment(floor, bay.stack)
            parts.append(_floor(apartment, bay, floor, floor_y=fy,
                                grades=(apartment.slope(50), apartment.slope(100)),
                                grade_basis="СП 30.13330.2020, п. 17.3; поэтажный отвод",
                                outside_cleanout_labels=True,
                                revision=(floor in {1, model.floors} or (floor-1) % 3 == 0)))
            label = f'К1 ⌀{model.fan.working_diameter_mm}' if model.fan.working_diameter_mm else 'К1 ⌀100*'
            parts.append(render_inline_pipe_label(line_id=f'{bay.stack}-{floor}', label=label,
                start=(x, fy-53), end=(x, fy-33), font_size=STYLE.font_size(2.5, 1), padding=1))
        parts.append(_arrow((x, first_y+12), (0, 1), marker=bay.stack+"-flow"))
    # Basement: initial free end stays capped; second stack enters a THROUGH wye.
    last = None
    for bay, node in zip(BAYS, model.lower_nodes(), strict=True):
        y = main_y-76*NODE_SCALE
        def point(port):
            p = node.port(port).point
            return bay.axis+p.x_mm*NODE_SCALE, y+p.y_mm*NODE_SCALE
        if last:
            end = point("main_in")
            parts.append(_main_crossings(last[0], end[0], main_y, (K2_AXIS,) if model.drainage == "internal" else (), bridge_up=True))
        parts.extend((f'<g data-section-lower="{bay.stack}" data-axis-x="{bay.axis}">',
                      render_lower_turn_assembly_svg(node, x=bay.axis, y=y, scale=NODE_SCALE, pipe_width=.6,
                          graphic_size=FittingGraphicSize(model.k1.dn_mm or model.fan.working_diameter_mm or 100,
                              model.fan.working_diameter_mm or 100, 1), annotations=False, pipe_labels=False, flow_direction=False), '</g>'))
        if node.service_path:
            parts.append(_callout("k1-cleanout", point("cleanout_cap"), "Пр.",
                                  f"DN{model.k1.dn_mm}" if model.k1.dn_mm else "DN уточнить", (104, main_y+9), 123))
            target = point("main_out")
            parts.append(main_start("К1", model.k1, target, 134, main_y, target[0]))
        last = point("main_out")
    parts.extend((_line(*last, RIGHT+10, main_y, width=.6, marker='data-section-outlet="К1"'),
                  _arrow((RIGHT+10, main_y), (1, 0), marker="К1-outlet"),
                  main_label("k1", model.k1, (212, main_y), (250, main_y)),
                  slope("k1-main", model.k1, 233, main_y, 1),
                  _revision_on_main("k1-through-service", 208, main_y),
                  outlet_notes("К1", model.k1, 223, main_y)))
    if model.drainage == "internal":
        fy = roof_at(K2_AXIS)
        anchor = HEATED_FUNNEL_OUTLET_ANCHOR if model.funnel_heated else FUNNEL_OUTLET_ANCHOR
        sx = K2_AXIS-anchor[0]*.25
        funnel_out = fy+anchor[1]*.25
        symbol = "roof_funnel_heated" if model.funnel_heated else "roof_funnel"
        parts.extend((f'<rect x="{K2_AXIS-6.5:g}" y="{fy-4:g}" width="13" height="10" fill="white"/>',
                      f'<g data-section-funnel="{symbol}" data-heating-known="{str(model.funnel_heated is not None).lower()}" '
                      f'data-outlet-x="{K2_AXIS:g}" data-outlet-y="{funnel_out:g}">'
                      + render_ugo(symbol, sx, fy, scale=.25) + '</g>',
                      _line(K2_AXIS, funnel_out, K2_AXIS, storm_y-76*NODE_SCALE, width=.6,
                            marker='data-section-riser="К2" data-axis-x="166"'),
                      _arrow((K2_AXIS, first_y+12), (0, 1), marker="К2-flow")))
        dn = model.storm.selected_riser_dn_mm
        parts.append(f'<g data-storm-riser-dn="{dn}" data-storm-riser-status="{model.storm.riser_status}">')
        for fy in floors_y.values():
            label = f'К2 ⌀{dn}' if dn else 'К2 ⌀ —'
            parts.append(render_inline_pipe_label(line_id=f'k2-{fy}', label=label,
                start=(K2_AXIS, fy-44), end=(K2_AXIS, fy-23), font_size=STYLE.font_size(2.5, 1), padding=1))
        parts.append('</g>')
        lower = model.storm_lower_node()
        target = (K2_AXIS-lower.port("main_out").point.x_mm*NODE_SCALE, storm_y)
        parts.append(main_start("К2", model.k2, target, 150, storm_y, target[0]))
        parts.extend((f'<g data-section-lower="К2" data-axis-x="166" transform="translate({2*K2_AXIS:g} 0) scale(-1 1)">',
                      render_lower_turn_assembly_svg(lower, x=K2_AXIS, y=storm_y-76*NODE_SCALE, scale=NODE_SCALE, pipe_width=.6,
                          graphic_size=FittingGraphicSize(model.k2.dn_mm or dn or 100, dn or 100, 1), annotations=False, pipe_labels=False, flow_direction=False), '</g>',
                      _line(K2_AXIS-112*NODE_SCALE, storm_y, LEFT-10, storm_y, width=.6, marker='data-section-outlet="К2"'),
                      _arrow((LEFT-10, storm_y), (-1, 0), marker="К2-outlet"),
                      main_label("k2", model.k2, (75, storm_y), (116, storm_y)),
                      slope("k2-main", model.k2, 95, storm_y, -1),
                      outlet_notes("К2", model.k2, 61, storm_y),
                      _callout("k2-cleanout", (K2_AXIS-12*NODE_SCALE, storm_y), "Пр.",
                               f"DN{model.k2.dn_mm}" if model.k2.dn_mm else "DN уточнить", (181, storm_y+9), 207)))
    parts.append(common_svg)
    if model.floors > 3:
        upper, lower, scale = floors_y[model.floors], floors_y[2]-pitch, .15
        cy = (upper+lower)/2
        parts.append('<g transform="scale(.15)">'+_building_section_break_svg(
            break_id="typical-floors", wall_left=LEFT/scale, wall_right=RIGHT/scale, center_y=cy/scale,
            label="", partition_xs=tuple(x/scale for x in (79, 152, 180, 253)),
            upper_storey_bottom=upper/scale, lower_storey_top=lower/scale)+'</g>')
        parts.append(_text(58, cy+1, f"Пропущено этажей: {model.floors-3}*", height=2.5))
    notes = [
        "Характерный разрез: типовые группы К1 и ветвь К2. Число символов не задаёт количество элементов дома."
        if model.drainage == "internal" else "Характерный разрез К1. Число символов не задаёт количество элементов дома.",
        "Поэтажные отводы: DN50 - 0,030; DN100 - 0,020 (СП 30.13330.2020, п. 17.3).",
        "Магистрали: заданные параметры; н/д - нет данных. Гидравлика всей сети не подтверждена.",
        ("Относительный 0,00 = абс. " + level_text(model.zero_absolute_m) + " м; размещение уточнить по АР."
         if model.datum.absolute_level(0) is not None else
         "Абсолютная привязка 0,00 не задана; показаны относительные отметки. Не для подсчёта длин."),
        "Наружная сеть не моделируется; защита от подпора требует условий подключения.",
        ("Воронка с электрообогревом." if model.funnel_heated else "Воронка без электрообогрева."
         if model.funnel_heated is False else "Тип воронки и необходимость электрообогрева уточнить.")
        if model.drainage == "internal" else "Наружный водосток; К2 внутри здания не показана.",
        "Комплект требует дополнения: ГОСТ Р 21.620-2023, п. 5.2.2. Это не документ к выпуску.",
    ]
    checks = model.main_checks
    notes[2] = "; ".join(row.short for row in checks) + ". Не проверка всей сети."
    for row in checks:
        result = row.result
        attrs = (f' data-q-lps="{result.design_flow_lps}" data-inner-mm="{result.inner_diameter_mm}" '
                 f'data-velocity-mps="{result.velocity_mps}" data-fill="{result.fill_ratio}"' if result else '')
        parts.append(f'<g data-main-hydraulics="{row.system}" data-status="{row.status}"{attrs}><desc>{escape(row.note)}</desc></g>')
    result = checks[0].result
    if result is not None:
        def value(x):
            return f"{x:.3f}".replace('.', ',') if x is not None else '—'
        parts.append(_text(61, first_y+12,
            f"К1: Q={value(result.design_flow_lps)} л/с; V={value(result.velocity_mps)} м/с; h/d={value(result.fill_ratio)}",
            height=2.5, marker='data-main-result-note="К1"'))
    sources = {}
    for system, data in (("К1", model.k1), ("К2", model.k2)):
        if system == "К2" and model.drainage != "internal":
            continue
        if data.source_ref:
            # Full provenance is retained in the SVG/PZ, not squeezed into the
            # signature cells or silently abbreviated into another statement.
            parts.append('<desc>'+escape(f"{system}: {data.source_ref}")+'</desc>')
            sources.setdefault(data.source_ref, []).append(system)
    lines = [line for note in notes for line in wrap(note, width=110)]
    if model.zero_source_ref:
        parts.append('<desc>'+escape("Основание нуля: "+model.zero_source_ref)+'</desc>')
        label = "Привязка 0,00: " + model.zero_source_ref
        lines.append(label if len(label) <= 110 else label[:109]+'…')
    for source, systems in sources.items():
        label = ', '.join(systems)+': '+source
        # Two independent sources have two reserved lines. Full wording stays
        # in the source metadata/PZ; an ellipsis visibly marks a long reference.
        lines.append(label if len(label) <= 110 else label[:109]+'…')
    note_pitch = min(4.5, 34 / max(1, len(lines)-1))
    for i, note in enumerate(lines):
        parts.append(_text(26, 322+i*note_pitch, note, height=2.5, marker='data-section-note="true"'))
    # A reserved basement pocket: state the selected riser's check separately
    # from an unverified main, without claiming that the entire K2 is sized.
    if model.drainage == "internal":
        status = {"verified":"проверен по нагрузке", "pending":"нагрузка не проверена", "fail":"нагрузка НЕ ДОПУСТИМА"}[model.storm.riser_status]
        caption = (f'Стояк К2 DN{model.storm.selected_riser_dn_mm}: {status}'
                   if model.storm.selected_riser_dn_mm else 'К2: характерная ветвь; DN не задан')
        if model.storm.aggregate_riser_status == "fail":
            caption = 'К2: суммарная способность стояков НЕДОСТАТОЧНА'
        parts.append(_text(61, first_y+19, caption, height=2.5,
                           marker='data-storm-status-note="true"'))
        parts.append(f'<g data-storm-aggregate-status="{model.storm.aggregate_riser_status}" '
                     f'data-storm-project-funnels="{model.storm.funnels_count}">'
                     f'<desc>{escape(model.storm.quantity_notice)}</desc></g>')
        parts.append('<desc>'+escape(model.storm.notice)+'</desc>')
    parts.extend((drawing_frame_svg(model.document or DocumentInfo(object_name=model.title),
                  width_mm=297, height_mm=420, title="Принципиальный разрез",
                  system_label="К1, К2" if model.drainage == "internal" else "К1"), '</svg>'))
    return ''.join(parts)


def audit_concept_section_svg(model: ResidentialConceptSection, svg: str) -> tuple[str, ...]:
    root, errors = ET.fromstring(svg), []
    if root.get("data-release-ready") != "false" or root.get("data-takeoff-eligible") != "false":
        errors.append("representative geometry cannot certify release/takeoff")
    for bay, node in zip(BAYS, model.lower_nodes(), strict=True):
        rows = [r for r in root.iter() if r.get("data-section-lower") == bay.stack]
        if len(rows) != 1 or float(rows[0].get("data-axis-x", 'nan')) != bay.axis:
            errors.append("upper/lower riser axis mismatch")
        elif not any(r.get("data-accessible-capped-end") == str(node.service_path is not None).lower() for r in rows[0].iter()):
            errors.append("missing initial cleanout or capped through junction")
    outlets = {r.get("data-section-outlet"): r for r in root.iter() if r.get("data-section-outlet")}
    expected_outlets = [("К1", RIGHT, 1)]
    if model.drainage == "internal":
        expected_outlets.append(("К2", LEFT, -1))
    for system, wall, side in expected_outlets:
        r = outlets.get(system)
        if r is None or side*(float(r.get("x2", 'nan'))-wall) <= 0:
            errors.append("outlet does not cross wall: "+system)
    expected_marks = {f"floor-{n}": (n-1)*model.floor_height_m for n in model.shown_floors}
    if model.basement_kind != "none":
        expected_marks["basement"] = model.basement_floor_m
    expected_marks.update(("outlet-"+system, data.outlet_invert_m) for system, data in model.mains
                          if data.outlet_invert_m is not None)
    expected_marks.update(("main-start-"+system, data.start_invert_m) for system, data in model.mains
                          if data.start_invert_m is not None and data.source_ref.strip())
    for system, data in model.mains:
        rows = [r for r in root.iter() if r.get("data-outlet-annotation") == system]
        absolute = model.datum.absolute_level(data.outlet_invert_m)
        label = "Абс. " + level_text(absolute) if absolute is not None else "Абс. отм. не задана"
        if len(rows) != 1 or rows[0].get("data-absolute-m") != str(absolute) or label not in ''.join(rows[0].itertext()):
            errors.append("missing or invented absolute outlet level: "+system)
    fan = model.fan_plan
    if model.technical_space_levels is not None:
        expected_marks.update({"fan-space": model.technical_space_levels[0],
                               "fan-roof": model.technical_space_levels[1]})
        if fan.kind != "common" and len([r for r in root.iter() if r.get("data-technical-space")]) != 1:
            errors.append("technical space lost while fan decision is pending/individual")
    if root.get("data-section-fan-kind") != fan.kind:
        errors.append("fan decision differs from shared input")
    terminals = [r for r in root.iter() if r.get("data-fan-open-terminal")]
    if len(terminals) != {"pending":0, "individual":2, "common":1}[fan.kind]:
        errors.append("missing or invented fan terminal")
    dims = [r for r in root.iter() if r.get("data-fan-dimension")]
    if len(dims) != len(terminals) or any(r.get("data-value") != fan.dimension for r in dims):
        errors.append("fan height differs from shared input")
    if fan.kind == "common":
        dn_rows = [r for r in root.iter() if r.get("data-fan-collector-dn") is not None]
        if len(dn_rows) != 1 or dn_rows[0].get("data-fan-collector-dn") != str(fan.diameter_mm or 0):
            errors.append("fan diameter differs from working risers")
        expected_marks.update({"fan-roof":model.fan.roof_level_m, "fan-space":model.fan.space_floor_m})
        expected_marks.update({"fan-collector-low":model.fan.collector_low_m,
                               "fan-collector-high":model.fan.collector_high_m})
        members = [r.get("data-fan-member") for r in root.iter() if r.get("data-fan-member")]
        groups = [r for r in root.iter() if r.get("data-common-fan")]
        if members != list(model.fan.member_ids[:2]) or len(groups) != 1 or groups[0].get("data-fan-group-size") != str(len(model.fan.member_ids)):
            errors.append("representative fan group differs from declared members")
        ports = [r for r in root.iter() if r.get("data-fan-member")]
        collectors = [r for r in root.iter() if r.get("data-fan-collector")]
        if len(collectors) != 1 or not list(collectors[0]):
            errors.append("missing common fan collector")
        elif len(ports) >= 2:
            lines = [r for r in collectors[0] if r.tag.endswith("line")]
            for line, port, end in ((lines[0], ports[0], "1"), (lines[-1], ports[-1], "2")) if lines else ():
                if any(not isclose(float(line.get(axis+end, 'nan')), float(port.get("data-fan-member-"+axis, 'nan')),
                                   rel_tol=0, abs_tol=.001)
                       for axis in ("x", "y")):
                    errors.append("disconnected common fan collector")
            if not lines:
                errors.append("missing common fan collector")
        for bay, port in zip(BAYS, ports[:2]):
            riser = next((r for r in root.iter() if r.get("data-section-riser") == bay.stack), None)
            # SVG line primitives serialize paper coordinates to 0.001 mm.
            if riser is None or any(not isclose(float(riser.get(axis+"1", 'nan')), float(port.get("data-fan-member-"+axis, 'nan')),
                                                rel_tol=0, abs_tol=.001)
                                    for axis in ("x", "y")):
                errors.append("riser disconnected from common fan collector")
    marks = {r.get("data-level-mark"): r for r in root.iter() if r.get("data-level-mark")}
    if set(marks) != set(expected_marks):
        errors.append("missing or invented elevation mark")
    for key, value in expected_marks.items():
        r = marks.get(key)
        if r is not None and (float(r.get("data-elevation-m", 'nan')) != value or
                not any(c.get("data-level-arrow") for c in r) or not any(c.get("data-level-shelf") for c in r)):
            errors.append("invalid elevation symbol: "+key)
    if len([r for r in root.iter() if r.get("data-section-apartment")]) != 2*len(model.shown_floors):
        errors.append("lost representative apartment")
    for bay in BAYS:
        for floor in model.shown_floors:
            labels = [r for r in root.iter() if r.get("data-pipe-line-id") == f'{bay.stack}-{floor}']
            # Rendering the line label and the fittings use the same explicit
            # working DN; the legacy DN100 template remains visibly starred.
            expected = f'К1 ⌀{model.fan.working_diameter_mm}' if model.fan.working_diameter_mm else 'К1 ⌀100*'
            if len(labels) != 1 or labels[0].get("data-inline-pipe-label") != expected:
                errors.append("working riser label differs from current DN")
    # The same frame factory supplies the expected grid, so a local shortcut
    # cannot masquerade as form 3 by merely retaining its data attribute.
    expected_frame = ET.fromstring(drawing_frame_svg(DocumentInfo(), width_mm=297, height_mm=420,
                                                    title="", system_label=""))
    frames = [r for r in root.iter() if r.get("data-drawing-frame")]
    def grid(element):
        return [(r.tag.rsplit('}', 1)[-1], sorted(r.attrib.items())) for r in element.iter()
                if r.tag.rsplit('}', 1)[-1] in {"rect", "line"}]
    if len(frames) != 1 or grid(frames[0]) != grid(expected_frame):
        errors.append("missing or nonstandard shared drawing frame")
    notes = [r for r in root.iter() if r.get("data-section-note")]
    if not notes or any(not 318 <= float(r.get("y", 'nan')) <= 357 for r in notes):
        errors.append("notes overlap drawing or title block")
    slopes = {r.get("data-section-slope"): r for r in root.iter() if r.get("data-section-slope")}
    for system, data in model.mains:
        key = system.lower().replace('к', 'k') + '-main'
        row = slopes.get(key)
        if data.slope is not None and (row is None or float(row.get("data-slope", 'nan')) != data.slope):
            errors.append("main slope differs from current inputs: " + system)
        if data.slope is None and row is not None:
            errors.append("invented main slope: " + system)
        checks = [r for r in root.iter() if r.get("data-main-hydraulics") == system]
        expected = next(c for c in model.main_checks if c.system == system)
        if len(checks) != 1 or checks[0].get("data-status") != expected.status:
            errors.append("main hydraulics differs from current inputs: " + system)
        elif expected.result is not None:
            for attr, key in (("data-q-lps", "design_flow_lps"), ("data-inner-mm", "inner_diameter_mm"),
                              ("data-velocity-mps", "velocity_mps"), ("data-fill", "fill_ratio")):
                if checks[0].get(attr) != str(getattr(expected.result, key)):
                    errors.append("stale main hydraulic result: " + system)
    for bay in BAYS:
        for floor in model.shown_floors:
            apartment = model.apartment(floor, bay.stack)
            for dn in (50, 100):
                row = slopes.get(f"{bay.stack}:F{floor}-grade{dn}")
                if row is None or float(row.get("data-slope", 'nan')) != apartment.slope(dn) or "17.3" not in row.get("data-grade-basis", ""):
                    errors.append("missing or untraceable floor-branch slope")
    if model.drainage == "internal":
        quantities = [r for r in root.iter() if r.get("data-storm-project-funnels") is not None]
        if (len(quantities) != 1 or quantities[0].get("data-storm-project-funnels") != str(model.storm.funnels_count)
                or quantities[0].get("data-storm-aggregate-status") != model.storm.aggregate_riser_status):
            errors.append("storm quantity/aggregate status differs from project inputs")
        storm_rows = [r for r in root.iter() if r.get("data-storm-riser-dn") is not None]
        dn = model.storm.selected_riser_dn_mm
        expected_label = f'К2 ⌀{dn}' if dn else 'К2 ⌀ —'
        if (len(storm_rows) != 1 or storm_rows[0].get("data-storm-riser-dn") != str(dn)
                or storm_rows[0].get("data-storm-riser-status") != model.storm.riser_status
                or len([r for r in storm_rows[0].iter() if r.get("data-inline-pipe-label") == expected_label]) != len(model.shown_floors)):
            errors.append("storm diameter/status differs from current inputs")
        funnels = [r for r in root.iter() if r.get("data-section-funnel")]
        expected = "roof_funnel_heated" if model.funnel_heated else "roof_funnel"
        if len(funnels) != 1 or funnels[0].get("data-section-funnel") != expected:
            errors.append("funnel symbol differs from design choice")
        elif not any(r.get("data-ugo") == expected for r in funnels[0].iter()):
            errors.append("missing canonical funnel vector")
        else:
            funnel = funnels[0]
            riser = next((r for r in root.iter() if r.get("data-section-riser") == "К2"), None)
            if riser is None or any(not isclose(float(riser.get(axis+"1", 'nan')),
                                                float(funnel.get("data-outlet-"+axis, 'nan')),
                                                rel_tol=0, abs_tol=.001) for axis in ("x", "y")):
                errors.append("storm riser disconnected from funnel")
            if funnel.get("data-heating-known") != str(model.funnel_heated is not None).lower():
                errors.append("unknown funnel heating presented as confirmed")
    return tuple(errors)


def generate_concept_section_pdf(output: Path, model: ResidentialConceptSection) -> str:
    import cairosvg

    svg = build_concept_section_svg(model)
    errors = audit_concept_section_svg(model, svg)
    if errors:
        raise ValueError('; '.join(errors))
    ensure_drafting_font_registered()
    output.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(output))
    return str(output)
