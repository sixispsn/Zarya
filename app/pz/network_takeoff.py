"""Quantity projection of a COMPLETE physical network, never of a drawing.

Lengths are explicit route inputs (or measured 3D polylines), not paper-space
coordinates. Route envelopes include fitting bodies: this is NOT a cut list.
Unknown lengths remain unknown; they do not silently become zero or a reserve.
This module does not select diameters, calculate hydraulics or approve designs.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import dist, fsum, isfinite

from app.data.sewer_pipe_catalog import SewerPipeGeometry


@dataclass(frozen=True)
class QuantityBasis:
    status: str  # proposed / confirmed
    source: str

    def validate(self) -> None:
        if self.status not in {"proposed", "confirmed"} or not self.source.strip():
            raise ValueError("quantity needs explicit provenance and confirmation status")


@dataclass(frozen=True)
class NetworkPoint:
    point_id: str
    system: str
    role: str  # source / junction / outlet / service / vent


@dataclass(frozen=True)
class QuantityRoute:
    route_id: str
    start: str
    end: str
    pipe: SewerPipeGeometry
    length_m: float | None
    role: str
    basis: QuantityBasis
    mode: str = "drain"  # drain / service / vent
    polyline_m: tuple[tuple[float, float, float], ...] = ()

    @classmethod
    def from_polyline(cls, *, points_m: tuple[tuple[float, float, float], ...], **kwargs):
        if (len(points_m) < 2 or any(len(p) != 3 or any(isinstance(v, bool) or not isfinite(v)
                for v in p) for p in points_m)):
            raise ValueError("a measured route needs finite 3D points in metres")
        length = fsum(dist(a, b) for a, b in zip(points_m, points_m[1:]))
        return cls(length_m=length, polyline_m=points_m, **kwargs)


@dataclass(frozen=True)
class QuantityComponent:
    component_id: str
    point_id: str
    kind: str
    name: str
    size: str
    quantity: int
    basis: QuantityBasis
    source_element_id: str
    product_family: str = ""


@dataclass(frozen=True)
class QuantityRow:
    system: str
    kind: str
    name: str
    size: str
    unit: str
    quantity: float | int
    status: str
    member_ids: tuple[str, ...]
    unknown_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class NetworkTakeoff:
    points: tuple[NetworkPoint, ...]
    routes: tuple[QuantityRoute, ...]
    components: tuple[QuantityComponent, ...]
    limitations: tuple[str, ...]

    def validate(self) -> None:
        ids = [p.point_id for p in self.points]
        physical_ids = [r.route_id for r in self.routes] + [c.component_id for c in self.components]
        if len(ids) != len(set(ids)) or len(physical_ids) != len(set(physical_ids)):
            raise ValueError("duplicate physical instance ID; shared objects cannot be counted twice")
        points = {p.point_id: p for p in self.points}
        if not points or not self.routes:
            raise ValueError("empty network")
        graph: dict[str, str] = {}
        used = set()
        for p in self.points:
            if not p.point_id or p.system not in {"K1", "K2", "K3"} or p.role not in {
                    "source", "junction", "outlet", "service", "vent"}:
                raise ValueError("invalid network point")
        for r in self.routes:
            r.basis.validate()
            if not r.route_id or not r.role or r.start not in points or r.end not in points:
                raise ValueError("route has missing endpoint or identity")
            if points[r.start].system != points[r.end].system:
                raise ValueError("cross-system connection is forbidden")
            if r.length_m is not None and (isinstance(r.length_m, bool)
                    or not isfinite(r.length_m) or r.length_m <= 0):
                raise ValueError("known route length must be finite and positive")
            if r.polyline_m:
                if (len(r.polyline_m) < 2 or any(len(p) != 3 or any(isinstance(v, bool)
                        or not isfinite(v) for v in p) for p in r.polyline_m)):
                    raise ValueError("invalid 3D route geometry")
                measured = fsum(dist(a, b) for a, b in zip(r.polyline_m, r.polyline_m[1:]))
                if r.length_m is None or abs(measured-r.length_m) > 1e-9:
                    raise ValueError("route length differs from its 3D geometry")
            p = r.pipe
            if ((p.outer_diameter_mm, p.wall_thickness_mm) not in p.series.sizes
                    or p.inner_diameter_mm <= 0):
                raise ValueError("pipe geometry differs from its catalogue")
            if r.mode not in {"drain", "service", "vent"}:
                raise ValueError("unknown route mode")
            expected = {"drain": {"source", "junction"}, "service": {"service"}, "vent": {"vent"}}
            if points[r.start].role not in expected[r.mode] or points[r.end].role not in {"junction", "outlet"}:
                raise ValueError("invalid route direction or terminal role")
            if r.start in graph:
                raise ValueError("ambiguous downstream path")
            graph[r.start] = r.end
            used.update((r.start, r.end))
        if used != set(points):
            raise ValueError("disconnected network point")
        # All physical branches, not just the displayed apartments, must reach
        # their own discharge boundary. A service cap is not a sewage source.
        for start, point in points.items():
            current, seen = start, set()
            while current in graph and current not in seen:
                seen.add(current)
                current = graph[current]
            if current in seen or points[current].role != "outlet":
                raise ValueError(f"{start}: no acyclic route to outlet")
            if points[current].system != point.system:
                raise ValueError("wrong discharge system")
        for c in self.components:
            c.basis.validate()
            if (not c.component_id or c.point_id not in points or not c.source_element_id
                    or not c.name or not c.kind or isinstance(c.quantity, bool)
                    or not isinstance(c.quantity, int) or c.quantity <= 0):
                raise ValueError("component needs a physical location, source and integer count")
            if c.kind == "cap" and points[c.point_id].role != "service":
                raise ValueError("cap cannot close a through-flow junction")

    def rows(self) -> tuple[QuantityRow, ...]:
        self.validate()
        points = {p.point_id: p for p in self.points}
        groups = defaultdict(list)
        for r in self.routes:
            p = r.pipe
            key = (points[r.start].system, p.series.series_id, p.outer_diameter_mm,
                   p.wall_thickness_mm, r.basis.status)
            groups[key].append(r)
        rows = []
        for key, routes in sorted(groups.items()):
            p = routes[0].pipe
            rows.append(QuantityRow(key[0], "route", p.series.name,
                f"{p.outer_diameter_mm:g} x {p.wall_thickness_mm:g}; Dвн {p.inner_diameter_mm:g}",
                "м", fsum(r.length_m for r in routes if r.length_m is not None), key[-1],
                tuple(r.route_id for r in routes), tuple(r.route_id for r in routes if r.length_m is None)))
        groups = defaultdict(list)
        for c in self.components:
            groups[(points[c.point_id].system, c.kind, c.name, c.size, c.product_family, c.basis.status)].append(c)
        for (system, kind, name, size, family, status), components in sorted(groups.items()):
            size = size + (f"; {family}" if family else "")
            rows.append(QuantityRow(system, kind, name, size, "шт", sum(c.quantity for c in components),
                                    status, tuple(c.component_id for c in components)))
        return tuple(rows)

    @property
    def fingerprint(self) -> str:
        self.validate()
        return sha256(json.dumps(asdict(self), sort_keys=True, ensure_ascii=False,
                                 allow_nan=False).encode()).hexdigest()

    @property
    def purchase_ready(self) -> bool:
        # Centreline envelopes lack socket depths and stock-length optimisation.
        return False
