"""Proposed wet-zone/stack/collector bindings in uncalibrated plan coordinates.

This is an explicit review layer, not an AR importer or a production Project.
Image fractions are never converted into pipe lengths, levels, grades or Q.
The basement layout is the user-authorized reuse of the floor-finishes plan.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path

from app.pz.wastewater_drafting import (
    WastewaterDraftAssembly, build_lower_turn_cleanout_assembly,
    build_lower_turn_through_junction_assembly,
)

Point = tuple[float, float]
Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class WetGroupProposal:
    group_id: str
    section: str
    stack: str
    position: Point
    kitchen_box: Box
    sanitary_box: Box


@dataclass(frozen=True)
class BasementRouteProposal:
    route_id: str
    section: str
    ordered_stacks: tuple[str, ...]
    direction: int
    main_y: float
    outlet: str
    outlet_x: float


@dataclass(frozen=True)
class PlanStudy:
    study_id: str
    source_image: str
    floor_crop_px: Box
    basement_crop_px: Box
    basement_basis: str
    floors: tuple[int, ...]
    groups: tuple[WetGroupProposal, ...]
    stairs_boxes: tuple[Box, ...]
    routes: tuple[BasementRouteProposal, ...]

    @property
    def release_ready(self) -> bool:
        return False

    def group(self, stack: str) -> WetGroupProposal:
        return next(g for g in self.groups if g.stack == stack)

    def join(self, route: BasementRouteProposal, stack: str) -> Point:
        # A readable oblique merge in PLAN space, not a fitting measurement.
        x, _ = self.group(stack).position
        return x+route.direction*.035, route.main_y

    def cap(self, route: BasementRouteProposal) -> Point:
        x, y = self.join(route, route.ordered_stacks[0])
        return x-route.direction*.075, y

    def lower_assemblies(self, route: BasementRouteProposal) -> tuple[WastewaterDraftAssembly, ...]:
        # Reuse accepted free/through topology. DN100 is ONLY the existing
        # symbol template here; it is not shown/published as a calculated size.
        return tuple(build_lower_turn_cleanout_assembly(system="K1", dn_mm=100) if i == 0
                     else build_lower_turn_through_junction_assembly(system="K1", dn_mm=100)
                     for i, _ in enumerate(route.ordered_stacks))

    def edges(self) -> tuple[tuple[str, str], ...]:
        edges: list[tuple[str, str]] = []
        descending = sorted(self.floors, reverse=True)
        for group in self.groups:
            for i, floor in enumerate(descending):
                junction = f"{group.stack}:F{floor}"
                for zone in ("kitchen", "sanitary"):
                    edges.append((f"{group.group_id}:F{floor}:{zone}", junction))
                target = f"{group.stack}:F{descending[i+1]}" if i+1 < len(descending) else f"{group.stack}:base:riser_in"
                edges.append((junction, target))
        for route in self.routes:
            for i, (stack, node) in enumerate(zip(route.ordered_stacks, self.lower_assemblies(route), strict=True)):
                prefix = stack+":base:"
                edges.extend((prefix+s.start_port_id, prefix+s.end_port_id) for s in node.segments if s.carries_flow)
                target = route.ordered_stacks[i+1]+":base:main_in" if i+1 < len(route.ordered_stacks) else route.outlet
                edges.append((prefix+"main_out", target))
        return tuple(edges)

    def paths(self) -> dict[str, tuple[str, ...]]:
        edges = self.edges()
        graph = dict(edges)
        if len(graph) != len(edges):
            raise ValueError("a gravity port cannot branch into multiple outlets")
        result = {}
        for group in self.groups:
            route = next(r for r in self.routes if group.stack in r.ordered_stacks)
            for floor in self.floors:
                for zone in ("kitchen", "sanitary"):
                    source = f"{group.group_id}:F{floor}:{zone}"
                    path, current = [], source
                    while current != route.outlet:
                        if current in path or current not in graph:
                            raise ValueError(f"{source}: disconnected/cyclic/wrong-section route")
                        path.append(current)
                        current = graph[current]
                    result[source] = tuple((*path, current))
        return result

    def validate(self) -> None:
        if not self.basement_basis.strip() or not self.source_image:
            raise ValueError("source and explicit basement assumption required")
        if not self.floors or len(set(self.floors)) != len(self.floors) or min(self.floors) < 1:
            raise ValueError("invalid observed floor set")
        if not self.groups or len({g.stack for g in self.groups}) != len(self.groups) or len({g.group_id for g in self.groups}) != len(self.groups):
            raise ValueError("duplicate/empty groups or stacks")
        for crop in (self.floor_crop_px, self.basement_crop_px):
            if not (all(isfinite(v) for v in crop) and 0 <= crop[0] < crop[2] and 0 <= crop[1] < crop[3]):
                raise ValueError("invalid image crop")
        for group in self.groups:
            if not all(isfinite(v) and 0 < v < 1 for v in group.position):
                raise ValueError("stack outside study plan")
            for box in (group.kitchen_box, group.sanitary_box):
                if not all(isfinite(v) for v in box) or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                    raise ValueError("invalid wet-zone box")
        used = [s for r in self.routes for s in r.ordered_stacks]
        if len(used) != len(set(used)) or set(used) != {g.stack for g in self.groups}:
            raise ValueError("each stack must belong to exactly one collector")
        if len({r.outlet for r in self.routes}) != len(self.routes):
            raise ValueError("separate proposed collectors need distinct outlet IDs")
        for route in self.routes:
            if route.direction not in (-1, 1) or not isfinite(route.main_y) or not 0 < route.main_y < 1:
                raise ValueError("invalid routing direction/band")
            if not isfinite(route.outlet_x) or not (route.outlet_x < 0 if route.direction == -1 else route.outlet_x > 1):
                raise ValueError("outlet must pass the building wall")
            xs = [self.join(route, stack)[0] for stack in route.ordered_stacks]
            if any((b-a)*route.direction <= 0 for a, b in zip(xs, xs[1:])):
                raise ValueError("collector stack order is against flow")
            if any(self.group(s).section != route.section for s in route.ordered_stacks):
                raise ValueError("collector crosses the other section")
            for index, assembly in enumerate(self.lower_assemblies(route)):
                if assembly.validate() or (assembly.service_path is not None) != (index == 0):
                    raise ValueError("lost initial cleanout or capped throughflow")
        self.paths()


def load_plan_study(path: Path) -> PlanStudy:
    data = json.loads(path.read_text())
    if (data.get("coordinate_basis") != "manual_normalized_image_projection_not_metres"
            or data.get("interpretation_status") != "proposed_for_review"):
        raise ValueError("uncalibrated plan must remain a proposal")
    for field in ("floor_elevations_m", "basement_elevation_m", "basement_clear_height_m", "residents"):
        if data.get(field) is not None:
            raise ValueError(f"{field}: use a confirmed architecture adapter, not this uncalibrated study")
    if data.get("k2_status") != "not_defined_for_this_roof":
        raise ValueError("K2 needs an independent roof decision")
    result = PlanStudy(
        data["id"], data["source_image"], tuple(data["floor_crop_px"]), tuple(data["basement_crop_px"]),
        data["basement_basis"], tuple(data["floors"]),
        tuple(WetGroupProposal(g["id"], g["section"], g["stack"], tuple(g["position"]),
                              tuple(g["kitchen_box"]), tuple(g["sanitary_box"])) for g in data["wet_groups"]),
        tuple(tuple(b) for b in data["stairs_boxes"]),
        tuple(BasementRouteProposal(r["id"], r["section"], tuple(r["ordered_stacks"]), r["direction"],
                                    r["main_y"], r["outlet"], r["outlet_x"]) for r in data["basement_routes"]),
    )
    result.validate()
    return result
