"""Bind explicit fan graphs to the canonical building renderer (opt-in preview).

Not a second building renderer: floors, fixtures, revisions, basements and K2
come from wastewater_building_drafting. Only the upper K1 ports are replaced.
No automatic geometry, guessed membership, or change to the input Project.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from html import escape
from math import isclose
import re
from xml.etree import ElementTree as ET

from app.pz.drafting_font import DRAFTING_FONT_FAMILY
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderRequest
from app.pz.project import Project
from app.pz.wastewater_fan_drafting import (
    FanDetailsInput, _roof_svg, audit_fan_detail_svg, build_roof_detail_graph, render_valve_outline,
)
from app.pz.wastewater_floor_drafting import WastewaterFloorAssembly
from app.pz.wastewater_ventilation import audit_project_fan_ventilation, project_fan_risers


def fan_details_from_project(project: Project) -> FanDetailsInput:
    """Resolve only saved geometry; never infer group members or approval."""
    geometry = project.sewage.fan_geometry
    if geometry is None or not geometry.confirmed:
        raise ValueError("Геометрия фановых узлов не подтверждена")
    evidence = project.sewage.fan_ventilation
    if evidence is None:
        raise ValueError("Нет нормативных исходных данных фановой вентиляции")
    data = FanDetailsInput(
        roof_kind=project.sewage.roof_kind, risers=project_fan_risers(project),
        evidence=evidence, roofs=geometry.roofs, valves=geometry.valves,
        residential=project.building.purpose.value == "residential",
    )
    bind_project_fans(project, data)
    return data


@dataclass(frozen=True)
class FanBuildingBinding:
    data: FanDetailsInput
    floor_height_m: float
    top_floor_m: float
    roof_sheet_by_terminal: dict[str, int]

    def terminal(self, rid):
        return next(t for t in self.data.evidence.terminals if rid in t.riser_ids)

    def level(self, rid: str) -> float:
        terminal = self.terminal(rid)
        if terminal.kind == "valve":
            return next(d.connection_level_m for d in self.data.valves if d.terminal_id == terminal.terminal_id)
        return next(p.lower_port_m for d in self.data.roofs for p in d.risers if p.riser_id == rid)

    def local_y(self, rid: str) -> float:
        # Same local storey projection used by the existing revision renderer.
        # Physical elevations stay in the data/annotations, not inferred from SVG.
        return 228. - (self.level(rid)-self.top_floor_m)*247./self.floor_height_m

    def terminate_floor(self, floor: WastewaterFloorAssembly) -> WastewaterFloorAssembly:
        y = self.local_y(floor.riser_id)
        return replace(floor, ports=tuple(
            replace(port, point=replace(port.point, y_mm=y)) if port.port_id == "riser_top" else port
            for port in floor.ports
        ))

    def render_ending(self, rid: str, *, x: float, origin_y: float, source_sheet: int) -> str:
        t = self.terminal(rid)
        y = origin_y + self.local_y(rid)
        level = self.level(rid)
        common = (f'data-fan-building-port="{escape(rid)}" data-terminal="{escape(t.terminal_id)}" '
                  f'data-level-m="{level:g}" data-kind="{t.kind}" data-source-sheet="{source_sheet}" '
                  f'data-port-x="{x:g}" data-port-y="{y:g}"')
        if t.kind == "roof":
            sheet = self.roof_sheet_by_terminal[t.terminal_id]
            symbol = (f'<circle cx="{x:g}" cy="{y:g}" r="4" fill="white" stroke="black" stroke-width="1"/>')
            title, detail = f"К {t.terminal_id}, лист {sheet}", f"{rid}; отм. {level:+.2f}"
            target_sheet = f' data-target-sheet="{sheet}"'
        else:
            symbol = render_valve_outline(x, y, .12, stroke=1.)
            title, detail = "Воздушный клапан", f"{t.terminal_id}; отм. {level:+.2f}"
            target_sheet = ''
        leader = LeaderLayoutEngine(
            # Reserve the empty band above the upper room cells. A local box
            # next to the pipe overlaps the neighbouring kitchen's captions.
            bounds=LeaderBounds(x+45, origin_y-150, x+465, origin_y-35), units_per_mm=10/3,
            vertical_offsets_mm=(50., 60., 70., 80., 90.),
        ).place_and_render(LeaderRequest(
            t.terminal_id+rid, rid, (x, y-10 if t.kind == "valve" else y),
            title, detail, preferred_side=1,
        ))
        return f'<g {common}{target_sheet}>{symbol}{leader}</g>'


def bind_project_fans(project: Project, data: FanDetailsInput) -> FanBuildingBinding:
    """Fail closed if a detached graph doesn't describe THIS building."""
    data.validate()
    if project.sewage.fan_ventilation != data.evidence:
        raise ValueError("fan detail evidence differs from Project")
    if {r.riser_id: r for r in data.risers} != {r.riser_id: r for r in project_fan_risers(project)}:
        raise ValueError("fan detail risers/DN/outlets/modes differ from actual building topology")
    audit = audit_project_fan_ventilation(project)
    if not audit.ready:
        raise ValueError("project fan validation not complete: " + "; ".join(audit.reasons))
    if data.roof_kind != project.sewage.roof_kind or data.residential != (project.building.purpose.value == "residential"):
        raise ValueError("fan building use/roof kind mismatch")
    if data.roof_kind not in {"flat_accessible", "flat_non_accessible"}:
        raise ValueError("bound preview currently supports flat roofs only")
    h = project.sewage.floor_height_m
    roof = project.sewage.roof_relative_elevation_m
    if h is None or h <= 0 or roof is None:
        raise ValueError("explicit storey height and roof level required")
    top = (project.building.floors_above-1)*h
    # Current canonical floor layout is uniform. Do not shift an explicit roof
    # or a nonuniform storey silently to make an attractive drawing.
    if not isclose(roof, project.building.floors_above*h):
        raise ValueError("nonuniform roof/storey profile requires a dedicated layout adapter")
    if any(not isclose(z, (n-1)*h) for n, z in project.building.floor_elevations_m.items()):
        raise ValueError("nonuniform floor levels are not supported by this binding")
    if any(not isclose(d.roof_level_m, roof) for d in data.roofs):
        raise ValueError("detail roof level differs from building")
    if any(not isclose(d.floor_level_m, top) or not isclose(d.ceiling_level_m, roof) for d in data.valves):
        raise ValueError("valve floor/ceiling differs from upper building storey")
    from app.pz.wastewater_project_inputs import resolve_wastewater_building_project_inputs
    inputs = resolve_wastewater_building_project_inputs(project)
    if not inputs.complete:
        raise ValueError("building inputs incomplete: " + "; ".join(inputs.diagnostics))
    pages = max((len(inputs.k1_risers)+1)//2, (len(inputs.k2_risers)+1)//2)
    binding = FanBuildingBinding(data, h, top, {d.terminal_id: 2*pages+i+1 for i, d in enumerate(data.roofs)})
    for r in data.risers:
        # Keep registered 1 m revision below the cut/valve and above the floor
        # branch. Other mounting geometries must not be hidden by truncation.
        if not top+1.1 <= binding.level(r.riser_id) < roof:
            raise ValueError("fan port must be inside upper storey and above its revision")
        pipe = next(p for p in project.sewage.pipes if p.section_id == r.riser_id)
        if pipe.elevation_start_m is None or not isclose(pipe.elevation_start_m, binding.level(r.riser_id)):
            raise ValueError("fan port elevation differs from actual riser upper endpoint")
        if binding.terminal(r.riser_id).kind == "valve":
            detail = next(d for d in data.valves if d.terminal_id == binding.terminal(r.riser_id).terminal_id)
            if pipe.outer_diameter_mm != detail.connection_outer_diameter_mm:
                raise ValueError("valve connection OD differs from actual pipe; reducer is not modeled")
    return binding


def audit_bound_fan_svgs(binding: FanBuildingBinding, svgs: tuple[str, ...]) -> tuple[str, ...]:
    roots = [ET.fromstring(s) for s in svgs]
    errors: list[str] = []
    all_rows = [r for root in roots for r in root.iter()]
    if {r.get("data-fan-building-port") for r in all_rows if r.get("data-fan-building-port")} != {r.riser_id for r in binding.data.risers}:
        errors.append("building fan ports differ from declared K1 risers")
    for detail in binding.data.roofs:
        detail_roots = [root for root in roots if root.get("data-fan-roof-terminal") == detail.terminal_id]
        if len(detail_roots) != 1:
            errors.append(f"{detail.terminal_id}: roof graph sheet missing or duplicated")
            continue
        edges = [r for r in detail_roots[0].iter() if r.get("data-fan-edge")]
        graph = build_roof_detail_graph(binding.data, detail)
        actual = [(e.get("data-fan-edge"), e.get("data-start"), e.get("data-end"),
                   e.get("data-role"), float(e.get("data-dn", "nan"))) for e in edges]
        expected_edges = [(e.edge_id, e.start, e.end, e.role, e.dn_mm) for e in graph.edges]
        if sorted(actual) != sorted(expected_edges):
            errors.append(f"{detail.terminal_id}: drawn fan edges differ from connected graph")
    for rid in (r.riser_id for r in binding.data.risers):
        ports = [r for r in all_rows if r.get("data-fan-building-port") == rid]
        if len(ports) != 1:
            errors.append(f"{rid}: expected one building port")
            continue
        p = ports[0]
        top_floors = [r for r in all_rows if r.get("data-floor-riser-id") == rid]
        top = max(top_floors, key=lambda r: int(r.get("data-floor", "0")), default=None)
        upper = [] if top is None else [r for r in top.iter() if r.get("data-floor-segment") == "riser_upper"]
        if len(upper) != 1 or any(not isclose(float(upper[0].get(coord, "nan")), float(p.get(attr, "nan")), abs_tol=.06)
                                 for coord, attr in (("x1", "data-port-x"), ("y1", "data-port-y"))):
            errors.append(f"{rid}: ending is disconnected from the upper floor pipe")
        if p.get("data-terminal") != binding.terminal(rid).terminal_id or float(p.get("data-level-m", "nan")) != binding.level(rid):
            errors.append(f"{rid}: incorrect ending or elevation")
        if any(r.get("data-building-pipe-line") == rid+"-roof-vent" or r.get("data-vent-cap") == rid for r in all_rows):
            errors.append(f"{rid}: legacy independent roof ending remains")
        detail_ports = [r for r in all_rows if r.get("data-fan-detail-port") == rid]
        if p.get("data-kind") == "roof":
            if len(detail_ports) != 1 or detail_ports[0].get("data-source-sheet") != p.get("data-source-sheet"):
                errors.append(f"{rid}: reciprocal sheet link is missing")
            elif detail_ports[0].get("data-level-m") != p.get("data-level-m"):
                errors.append(f"{rid}: continuation elevations differ")
            else:
                detail_page = next(i for i, root in enumerate(roots, 1) if detail_ports[0] in list(root.iter()))
                if str(detail_page) != p.get("data-target-sheet") or detail_ports[0].get("data-terminal") != p.get("data-terminal"):
                    errors.append(f"{rid}: link points to the wrong sheet/group")
        elif detail_ports or len([r for r in p.iter() if r.get("data-valve-outline")]) != 1:
            errors.append(f"{rid}: valve is missing or also continues to roof")
    expected = {t.terminal_id for t in binding.data.evidence.terminals if t.kind == "roof"}
    endings = [r.get("data-end") for r in all_rows if r.get("data-role") == "common_vent"]
    if len(endings) != len(expected) or set(endings) != expected:
        errors.append("common atmospheric endings differ from declared groups")
    return tuple(errors)


def build_bound_fan_preview_svgs(project: Project, data: FanDetailsInput) -> tuple[str, ...]:
    from app.pz.wastewater_building_drafting import (
        build_wastewater_building_assembly, build_wastewater_building_svgs,
        audit_wastewater_building_svgs,
    )
    from app.pz.wastewater_project_inputs import resolve_wastewater_building_project_inputs

    binding = bind_project_fans(project, data)
    inputs = resolve_wastewater_building_project_inputs(project)
    assembly = build_wastewater_building_assembly(inputs, floor_height_m=binding.floor_height_m,
                                                  roof_kind=project.sewage.roof_kind, document=project.document)
    pages = tuple(_preview_basement_callouts(s) for s in build_wastewater_building_svgs(assembly, fan_binding=binding))
    findings = audit_wastewater_building_svgs(assembly, pages, sheet_total=len(pages)+len(data.roofs))
    if findings:
        raise ValueError("building audit: " + "; ".join(findings))
    source_sheets: dict[str, int] = {}
    for i, page in enumerate(pages, 1):
        for row in ET.fromstring(page).iter():
            rid = row.get("data-fan-building-port")
            if rid:
                source_sheets[rid] = i
    total = len(pages)+len(data.roofs)
    details = tuple(_roof_svg(data, d, len(pages)+i+1, total, source_sheets) for i, d in enumerate(data.roofs))
    for svg in details:
        if audit_fan_detail_svg(svg):
            raise ValueError("bound fan detail has annotation collisions")
    pages += details
    errors = audit_bound_fan_svgs(binding, pages)
    if errors:
        raise ValueError("fan binding audit: " + "; ".join(errors))
    # Every page clearly stays a control drawing, never a production release.
    stamped = []
    for svg in pages:
        root = ET.fromstring(svg)
        root.set("data-production-release", "false")
        root.set("data-bound-fan-preview", "true")
        if root.get("data-sheet-format") == "A1":
            text = ET.SubElement(root, "{http://www.w3.org/2000/svg}text", {
                "x": "1400", "y": "134", "font-size": "14", "font-family": DRAFTING_FONT_FAMILY,
            })
            text.text = "Контроль привязки фановых узлов. Не проектная документация."
        stamped.append(ET.tostring(root, encoding="unicode"))
    return tuple(stamped)


def _preview_basement_callouts(svg: str) -> str:
    """Use the common leader engine in the control's crowded K2 basement lane.

    Only annotation geometry changes; original callout targets/element IDs,
    cleanout configuration and all pipe geometry remain intact. Production
    layout/golden sheets are intentionally untouched.
    """
    root = ET.fromstring(svg)
    if root.get("data-sheet-role") != "basement":
        return svg
    engine = LeaderLayoutEngine(bounds=LeaderBounds(230, 300, 2420, 1490), units_per_mm=10/3)
    for group in root.iter():
        key = group.get("data-lower-node-callout")
        if not key:
            continue
        x, y = (float(group.get(f"data-callout-target-{axis}", "nan")) for axis in ("x", "y"))
        text = " ".join(group.itertext())
        dn = re.search(r"DN\d+(?:×\d+)?", text)
        if dn is None:
            raise ValueError("basement annotation has no source DN")
        elbows = [r.get("data-lower-elbow-reference", "") for r in group if r.get("data-lower-elbow-reference")]
        title = "Прочистка" if group.get("data-callout-target-kind") == "cleanout-cap" else "Косой тройник 45°"
        leader = ET.fromstring(engine.place_and_render(LeaderRequest(
            key+"-preview", key, (x, y), title, dn.group(0), preferred_side=1, preferred_vertical=1,
        )))
        group[:] = list(leader)
        group.set("data-callout-target-x", f"{x:.3f}")
        group.set("data-callout-target-y", f"{y:.3f}")
        group.set("data-elbow-source-ids", ", ".join(elbows))
    return ET.tostring(root, encoding="unicode")
