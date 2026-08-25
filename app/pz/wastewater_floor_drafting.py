"""Parametric drafting model for one internal K1 floor module.

The module is deliberately smaller than a complete building schematic.  It
turns explicit fixture inputs into a connected installation graph that can be
repeated by a later storey/stack composer.  Pipes start at fixture outlets,
fixtures without an integral trap receive a separate trap, all branches merge
into one gravity collector and the toilet is the last fixture before the
riser.

The cleanout is not a decorative 45-degree stub.  The first 45-degree wye has
an accessible capped straight end, collinear with the downstream collector.
This implements the service rule discussed with the user and satisfies the
beginning-of-branch condition in SP 30.13330.2020, 18.26 for three or more
fixtures without another cleaning device.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import hypot
from pathlib import Path
from typing import Iterable

from app.pz.wastewater_drafting import (
    BLACK,
    FONT,
    GRAY,
    SERVICE,
    DraftFitting,
    DraftPipeSegment,
    DraftPoint,
    DraftPort,
    DraftServicePath,
)
from app.pz.wastewater_ugo import (
    fixture_trap_mode,
    get_ugo_connection_anchor,
    render_ugo,
)


_FIXTURE_DEFAULT_DN = {
    "sink": 50,
    "washbasin": 50,
    "bath": 50,
    "shower": 50,
    "floor_drain": 50,
    "toilet": 100,
}
_FIXTURE_ORDER = {
    "sink": 10,
    "shower": 20,
    "bath": 30,
    "washbasin": 40,
    "floor_drain": 50,
    "toilet": 100,
}
_FIXTURE_LABEL = {
    "sink": "Мойка",
    "washbasin": "Умывальник",
    "bath": "Ванна",
    "shower": "Душевой поддон",
    "floor_drain": "Трап",
    "toilet": "Унитаз",
}

# Symbol geometry ratios relative to the local drafting coordinates.  They
# keep the UGO connection anchors coincident with semantic graph ports at any
# page scale.
_FIXTURE_SYMBOL_RATIO = 0.36
_TRAP_SYMBOL_RATIO = 0.28
_TRAP_DX = 37.0 * _TRAP_SYMBOL_RATIO
_TRAP_DY = 40.0 * _TRAP_SYMBOL_RATIO


@dataclass(frozen=True)
class FloorFixtureInput:
    fixture_id: str
    kind: str
    room_label: str
    dn_mm: int | None = None


@dataclass(frozen=True)
class FloorFixtureDraft:
    fixture_id: str
    kind: str
    room_label: str
    dn_mm: int
    trap_mode: str
    fixture_outlet_port_id: str
    junction_port_id: str
    connection_segment_ids: tuple[str, ...]
    trap_inlet_port_id: str = ""
    trap_outlet_port_id: str = ""


@dataclass(frozen=True)
class WastewaterFloorAssembly:
    assembly_id: str
    system: str
    floor_no: int
    floor_elevation_m: float
    riser_id: str
    fixtures: tuple[FloorFixtureDraft, ...]
    ports: tuple[DraftPort, ...]
    segments: tuple[DraftPipeSegment, ...]
    fittings: tuple[DraftFitting, ...]
    branch_segment_ids: tuple[str, ...]
    riser_segment_ids: tuple[str, ...]
    service_path: DraftServicePath
    slope_by_dn: tuple[tuple[int, float], ...]

    def port(self, port_id: str) -> DraftPort:
        try:
            return next(row for row in self.ports if row.port_id == port_id)
        except StopIteration as exc:
            raise KeyError(f"unknown floor port: {port_id}") from exc

    def segment(self, segment_id: str) -> DraftPipeSegment:
        try:
            return next(row for row in self.segments if row.segment_id == segment_id)
        except StopIteration as exc:
            raise KeyError(f"unknown floor segment: {segment_id}") from exc

    def fitting(self, fitting_id: str) -> DraftFitting:
        try:
            return next(row for row in self.fittings if row.fitting_id == fitting_id)
        except StopIteration as exc:
            raise KeyError(f"unknown floor fitting: {fitting_id}") from exc

    def slope(self, dn_mm: int) -> float:
        rows = dict(self.slope_by_dn)
        try:
            return rows[dn_mm]
        except KeyError as exc:
            raise KeyError(f"no design slope for DN{dn_mm}") from exc

    def validate(self) -> list[str]:
        """Check topology, gravity direction, traps and cleanout access."""
        errors: list[str] = []
        port_ids = [row.port_id for row in self.ports]
        segment_ids = [row.segment_id for row in self.segments]
        fitting_ids = [row.fitting_id for row in self.fittings]
        fixture_ids = [row.fixture_id for row in self.fixtures]
        for label, values in (
            ("port", port_ids),
            ("segment", segment_ids),
            ("fitting", fitting_ids),
            ("fixture", fixture_ids),
        ):
            duplicates = sorted({value for value in values if values.count(value) > 1})
            if duplicates:
                errors.append(f"duplicate {label} IDs: {', '.join(duplicates)}")

        known_ports = set(port_ids)
        known_segments = set(segment_ids)
        for segment in self.segments:
            if segment.start_port_id not in known_ports:
                errors.append(
                    f"{segment.segment_id}: unknown start port {segment.start_port_id}"
                )
                continue
            if segment.end_port_id not in known_ports:
                errors.append(
                    f"{segment.segment_id}: unknown end port {segment.end_port_id}"
                )
                continue
            start = self.port(segment.start_port_id).point
            end = self.port(segment.end_port_id).point
            if start.distance_to(end) <= 1e-9:
                errors.append(f"{segment.segment_id}: zero-length pipe")
            if segment.dn_mm <= 0:
                errors.append(f"{segment.segment_id}: DN must be positive")
            if segment.carries_flow and end.y_mm < start.y_mm - 1e-9:
                errors.append(f"{segment.segment_id}: gravity path rises")

        for fitting in self.fittings:
            missing = set(fitting.connected_segment_ids) - known_segments
            if missing:
                errors.append(
                    f"{fitting.fitting_id}: unknown segments "
                    f"{', '.join(sorted(missing))}"
                )

        toilets = [row for row in self.fixtures if row.kind == "toilet"]
        if len(toilets) != 1:
            errors.append("floor module must contain exactly one toilet")
        elif self.fixtures[-1].fixture_id != toilets[0].fixture_id:
            errors.append("toilet must be the last fixture before the riser")
        if any(row.kind not in _FIXTURE_DEFAULT_DN for row in self.fixtures):
            errors.append("floor module contains an unsupported fixture UGO")

        for fixture in self.fixtures:
            if fixture.kind == "toilet" and fixture.dn_mm < 100:
                errors.append(f"{fixture.fixture_id}: toilet connection must be DN100")
            if fixture.dn_mm < 50:
                errors.append(f"{fixture.fixture_id}: fixture connection must be at least DN50")
            expected_trap = fixture_trap_mode(fixture.kind)
            if fixture.trap_mode != expected_trap:
                errors.append(
                    f"{fixture.fixture_id}: expected {expected_trap} trap mode"
                )
            if expected_trap == "external":
                if not fixture.trap_inlet_port_id or not fixture.trap_outlet_port_id:
                    errors.append(f"{fixture.fixture_id}: external trap is missing")
            elif fixture.trap_inlet_port_id or fixture.trap_outlet_port_id:
                errors.append(f"{fixture.fixture_id}: integral trap must not be duplicated")
            if not fixture.connection_segment_ids:
                errors.append(f"{fixture.fixture_id}: fixture is not connected")
            else:
                try:
                    connection = [
                        self.segment(row) for row in fixture.connection_segment_ids
                    ]
                except KeyError as exc:
                    errors.append(str(exc))
                    continue
                if connection[0].start_port_id != fixture.fixture_outlet_port_id:
                    errors.append(
                        f"{fixture.fixture_id}: connection does not start at fixture"
                    )
                if connection[-1].end_port_id != fixture.junction_port_id:
                    errors.append(
                        f"{fixture.fixture_id}: connection misses common branch"
                    )

        try:
            branch = [self.segment(row) for row in self.branch_segment_ids]
        except KeyError as exc:
            errors.append(str(exc))
            branch = []
        for upstream, downstream in zip(branch, branch[1:]):
            if upstream.end_port_id != downstream.start_port_id:
                errors.append(
                    f"branch discontinuity: {upstream.segment_id} -> "
                    f"{downstream.segment_id}"
                )
            if downstream.dn_mm < upstream.dn_mm:
                errors.append(
                    f"branch diameter decreases: DN{upstream.dn_mm} -> "
                    f"DN{downstream.dn_mm}"
                )

        path = self.service_path
        try:
            access = self.port(path.access_port_id)
        except KeyError as exc:
            errors.append(str(exc))
        else:
            if not access.accessible:
                errors.append("cleanout cap must be accessible")
            if not path.point_ids or path.point_ids[0] != path.access_port_id:
                errors.append("cleanout cable must start at the capped end")
            if not path.point_ids or path.point_ids[-1] != "riser_join":
                errors.append("cleanout cable must reach the riser junction")
            missing = set(path.serviced_segment_ids) - known_segments
            if missing:
                errors.append(
                    "cleanout path references unknown segments: "
                    + ", ".join(sorted(missing))
                )

        # The cap, first junction and next collector point must be collinear
        # and face in the same direction.  This rejects the obsolete arbitrary
        # diagonal cleanout symbol on a straight pipe.
        if branch:
            try:
                access_segment = next(
                    row for row in self.segments if row.role == "cleanout_access"
                )
                cap = self.port(access_segment.start_port_id).point
                first = self.port(access_segment.end_port_id).point
                next_point = self.port(branch[0].end_port_id).point
                ax, ay = cap.vector_to(first)
                bx, by = first.vector_to(next_point)
                cross = ax * by - ay * bx
                dot = ax * bx + ay * by
                if abs(cross) > 1e-6 or dot <= 0:
                    errors.append(
                        "cleanout cap must be collinear with downstream collector"
                    )
            except StopIteration:
                errors.append("floor module needs a physical cleanout access segment")
        return errors


def default_typical_floor_fixtures() -> tuple[FloorFixtureInput, ...]:
    """Fixture set used only by the isolated approval example."""
    return (
        FloorFixtureInput("К1-Мой1", "sink", "Кухня"),
        FloorFixtureInput("К1-Ван1", "bath", "Санузел"),
        FloorFixtureInput("К1-Ум1", "washbasin", "Санузел"),
        FloorFixtureInput("К1-Ун1", "toilet", "Санузел"),
    )


def build_typical_floor_assembly(
    *,
    fixtures: Iterable[FloorFixtureInput] | None = None,
    assembly_id: str = "К1-Этаж-02",
    system: str = "K1",
    floor_no: int = 2,
    floor_elevation_m: float = 3.0,
    riser_id: str = "К1-Ст1",
    slope_dn50: float = 0.03,
    slope_dn100: float = 0.02,
) -> WastewaterFloorAssembly:
    """Build one connected gravity branch from fixtures to a K1 riser.

    ``slope_dn50`` and ``slope_dn100`` are explicit design inputs.  Their
    defaults reproduce SP 30.13330.2020, 17.3 and 19.1 for the approval
    example; a project topology may override them after hydraulic checking.
    """
    if system != "K1":
        raise ValueError("typical sanitary floor module currently supports K1 only")
    if floor_no < 1:
        raise ValueError("floor_no must be positive")
    if not riser_id.strip():
        raise ValueError("riser_id must not be empty")
    if slope_dn50 <= 0 or slope_dn100 <= 0:
        raise ValueError("design slopes must be positive")

    raw = tuple(fixtures or default_typical_floor_fixtures())
    if len(raw) < 3:
        raise ValueError("floor module needs at least three fixtures")
    if len({row.fixture_id for row in raw}) != len(raw):
        raise ValueError("fixture_id values must be unique")
    unsupported = sorted({row.kind for row in raw} - set(_FIXTURE_DEFAULT_DN))
    if unsupported:
        raise ValueError("unsupported fixture kinds: " + ", ".join(unsupported))
    if sum(row.kind == "toilet" for row in raw) != 1:
        raise ValueError("floor module must contain exactly one toilet")

    ordered_inputs = tuple(
        row
        for _, row in sorted(
            enumerate(raw), key=lambda pair: (_FIXTURE_ORDER[pair[1].kind], pair[0])
        )
    )
    resolved: list[tuple[FloorFixtureInput, int]] = []
    for row in ordered_inputs:
        dn = row.dn_mm or _FIXTURE_DEFAULT_DN[row.kind]
        if dn < 50:
            raise ValueError(f"{row.fixture_id}: fixture connection must be at least DN50")
        if row.kind == "toilet" and dn < 100:
            raise ValueError(f"{row.fixture_id}: toilet connection must be DN100")
        resolved.append((row, dn))

    ports: list[DraftPort] = []
    segments: list[DraftPipeSegment] = []
    fittings: list[DraftFitting] = []
    floor_fixtures: list[FloorFixtureDraft] = []

    junction_x = [70.0 + index * 60.0 for index in range(len(resolved))]
    junction_y = [205.0]
    joined_dn = resolved[0][1]
    branch_dns: list[int] = []
    for index in range(len(resolved) - 1):
        joined_dn = max(joined_dn, resolved[index][1])
        branch_dns.append(joined_dn)
        slope = slope_dn100 if joined_dn >= 100 else slope_dn50
        dx = junction_x[index + 1] - junction_x[index]
        junction_y.append(junction_y[-1] + dx * slope)
    joined_dn = max(joined_dn, resolved[-1][1])
    outlet_dn = joined_dn

    junction_ids: list[str] = []
    for index, (x_mm, y_mm) in enumerate(zip(junction_x, junction_y), start=1):
        port_id = f"junction_{index}"
        junction_ids.append(port_id)
        ports.append(DraftPort(port_id, DraftPoint(x_mm, y_mm), "fixture_wye"))

    riser_x = junction_x[-1] + 52.0
    riser_y = junction_y[-1] + 52.0 * (
        slope_dn100 if outlet_dn >= 100 else slope_dn50
    )
    ports.extend(
        (
            DraftPort("riser_top", DraftPoint(riser_x, 5.0), "riser_from_above"),
            DraftPort("riser_join", DraftPoint(riser_x, riser_y), "riser_branch_joint"),
            DraftPort("riser_bottom", DraftPoint(riser_x, 252.0), "riser_to_below"),
        )
    )

    cap_x = junction_x[0] - 32.0
    cap_y = junction_y[0] - 32.0 * (
        slope_dn100 if resolved[0][1] >= 100 else slope_dn50
    )
    ports.append(
        DraftPort(
            "cleanout_cap",
            DraftPoint(cap_x, cap_y),
            "service_access",
            accessible=True,
        )
    )
    segments.append(
        DraftPipeSegment(
            "cleanout_access",
            "cleanout_cap",
            junction_ids[0],
            resolved[0][1],
            "cleanout_access",
            carries_flow=False,
        )
    )

    branch_segment_ids: list[str] = []
    for index in range(len(junction_ids) - 1):
        segment_id = f"collector_{index + 1}"
        branch_segment_ids.append(segment_id)
        segments.append(
            DraftPipeSegment(
                segment_id,
                junction_ids[index],
                junction_ids[index + 1],
                branch_dns[index],
                "common_floor_branch",
            )
        )
    branch_segment_ids.append("collector_to_riser")
    segments.append(
        DraftPipeSegment(
            "collector_to_riser",
            junction_ids[-1],
            "riser_join",
            outlet_dn,
            "common_floor_branch",
        )
    )
    segments.extend(
        (
            DraftPipeSegment(
                "riser_upper",
                "riser_top",
                "riser_join",
                max(100, outlet_dn),
                "riser",
            ),
            DraftPipeSegment(
                "riser_lower",
                "riser_join",
                "riser_bottom",
                max(100, outlet_dn),
                "riser",
            ),
        )
    )

    for index, ((source, dn), junction_id) in enumerate(
        zip(resolved, junction_ids), start=1
    ):
        junction = next(row.point for row in ports if row.port_id == junction_id)
        elbow_id = f"{source.fixture_id}_elbow"
        elbow = DraftPoint(junction.x_mm - 18.0, junction.y_mm - 18.0)
        ports.append(DraftPort(elbow_id, elbow, "connection_elbow_45"))
        mode = fixture_trap_mode(source.kind)
        fixture_outlet_id = f"{source.fixture_id}_outlet"
        connection_ids: list[str] = []
        trap_inlet_id = ""
        trap_outlet_id = ""
        if mode == "external":
            trap_inlet_id = f"{source.fixture_id}_trap_in"
            trap_outlet_id = f"{source.fixture_id}_trap_out"
            trap_in = DraftPoint(elbow.x_mm - _TRAP_DX, 82.0)
            trap_out = DraftPoint(elbow.x_mm, 82.0 + _TRAP_DY)
            fixture_outlet = DraftPoint(trap_in.x_mm, 62.0)
            ports.extend(
                (
                    DraftPort(fixture_outlet_id, fixture_outlet, "fixture_outlet"),
                    DraftPort(trap_inlet_id, trap_in, "trap_inlet"),
                    DraftPort(trap_outlet_id, trap_out, "trap_outlet"),
                )
            )
            before_id = f"{source.fixture_id}_to_trap"
            vertical_id = f"{source.fixture_id}_vertical"
            diagonal_id = f"{source.fixture_id}_diagonal"
            segments.extend(
                (
                    DraftPipeSegment(
                        before_id,
                        fixture_outlet_id,
                        trap_inlet_id,
                        dn,
                        "fixture_connection",
                    ),
                    DraftPipeSegment(
                        vertical_id,
                        trap_outlet_id,
                        elbow_id,
                        dn,
                        "fixture_connection",
                    ),
                    DraftPipeSegment(
                        diagonal_id,
                        elbow_id,
                        junction_id,
                        dn,
                        "fixture_connection",
                    ),
                )
            )
            connection_ids.extend((before_id, vertical_id, diagonal_id))
            fittings.append(
                DraftFitting(
                    f"{source.fixture_id}_trap",
                    "trap",
                    trap_in,
                    dn,
                    (before_id, vertical_id),
                )
            )
        else:
            fixture_outlet = DraftPoint(elbow.x_mm, 62.0)
            ports.append(
                DraftPort(fixture_outlet_id, fixture_outlet, "fixture_outlet")
            )
            vertical_id = f"{source.fixture_id}_vertical"
            diagonal_id = f"{source.fixture_id}_diagonal"
            segments.extend(
                (
                    DraftPipeSegment(
                        vertical_id,
                        fixture_outlet_id,
                        elbow_id,
                        dn,
                        "fixture_connection",
                    ),
                    DraftPipeSegment(
                        diagonal_id,
                        elbow_id,
                        junction_id,
                        dn,
                        "fixture_connection",
                    ),
                )
            )
            connection_ids.extend((vertical_id, diagonal_id))

        fittings.append(
            DraftFitting(
                f"{source.fixture_id}_elbow_45",
                "elbow_45",
                elbow,
                dn,
                tuple(connection_ids[-2:]),
            )
        )
        upstream_segment = (
            "cleanout_access" if index == 1 else branch_segment_ids[index - 2]
        )
        downstream_segment = branch_segment_ids[index - 1]
        fittings.append(
            DraftFitting(
                f"{source.fixture_id}_wye_45",
                "wye_45",
                junction,
                max(value for _, value in resolved[:index]),
                (upstream_segment, downstream_segment, connection_ids[-1]),
            )
        )
        floor_fixtures.append(
            FloorFixtureDraft(
                fixture_id=source.fixture_id,
                kind=source.kind,
                room_label=source.room_label,
                dn_mm=dn,
                trap_mode=mode,
                fixture_outlet_port_id=fixture_outlet_id,
                junction_port_id=junction_id,
                connection_segment_ids=tuple(connection_ids),
                trap_inlet_port_id=trap_inlet_id,
                trap_outlet_port_id=trap_outlet_id,
            )
        )

    fittings.extend(
        (
            DraftFitting(
                "cleanout_cap_fitting",
                "cap",
                DraftPoint(cap_x, cap_y),
                resolved[0][1],
                ("cleanout_access",),
            ),
            DraftFitting(
                "riser_branch_wye",
                "wye_45",
                DraftPoint(riser_x, riser_y),
                max(100, outlet_dn),
                ("collector_to_riser", "riser_upper", "riser_lower"),
            ),
        )
    )

    assembly = WastewaterFloorAssembly(
        assembly_id=assembly_id,
        system=system,
        floor_no=floor_no,
        floor_elevation_m=floor_elevation_m,
        riser_id=riser_id,
        fixtures=tuple(floor_fixtures),
        ports=tuple(ports),
        segments=tuple(segments),
        fittings=tuple(fittings),
        branch_segment_ids=tuple(branch_segment_ids),
        riser_segment_ids=("riser_upper", "riser_lower"),
        service_path=DraftServicePath(
            "floor_cleanout_cable",
            "cleanout_cap",
            f"{floor_fixtures[0].fixture_id}_wye_45",
            ("cleanout_cap", *junction_ids, "riser_join"),
            tuple(branch_segment_ids),
        ),
        slope_by_dn=((50, slope_dn50), (100, slope_dn100)),
    )
    errors = assembly.validate()
    if errors:
        raise ValueError("invalid typical floor assembly: " + "; ".join(errors))
    return assembly


def _system_mark(system: str) -> str:
    return {"K1": "К1", "K2": "К2", "K3": "К3"}.get(system, system)


def _tick_svg(
    point: DraftPoint,
    toward: DraftPoint,
    *,
    xy,
    offset_mm: float = 5.5,
    half_length_px: float = 5.0,
) -> str:
    dx, dy = point.vector_to(toward)
    length = hypot(dx, dy)
    if length <= 1e-9:
        return ""
    ux, uy = dx / length, dy / length
    center = DraftPoint(point.x_mm + ux * offset_mm, point.y_mm + uy * offset_mm)
    cx, cy = xy(center)
    px, py = -uy, ux
    return (
        f'<line x1="{cx-px*half_length_px:.1f}" '
        f'y1="{cy-py*half_length_px:.1f}" '
        f'x2="{cx+px*half_length_px:.1f}" '
        f'y2="{cy+py*half_length_px:.1f}" stroke="{BLACK}" '
        'stroke-width="1.8"/>'
    )


def render_typical_floor_assembly_svg(
    assembly: WastewaterFloorAssembly,
    *,
    diagnostics: bool = False,
    x: float = 0.0,
    y: float = 0.0,
    scale: float = 2.2,
) -> str:
    """Render the connected floor graph using the canonical UGO catalogue."""
    errors = assembly.validate()
    if errors:
        raise ValueError("cannot render invalid floor assembly: " + "; ".join(errors))

    def xy(value: str | DraftPoint) -> tuple[float, float]:
        point = assembly.port(value).point if isinstance(value, str) else value
        return x + point.x_mm * scale, y + point.y_mm * scale

    body: list[str] = [
        f'<g data-floor-assembly="{escape(assembly.assembly_id)}" '
        f'data-floor="{assembly.floor_no}" data-system="{assembly.system}">'
    ]

    # Architectural context is intentionally restrained: room boundaries,
    # floor slab and shaft.  It follows the hierarchy of the GOST appendix
    # example without pretending to be a plan-derived layout.
    first_x = assembly.port("cleanout_cap").point.x_mm - 18.0
    riser_x = assembly.port("riser_join").point.x_mm
    slab_y = 228.0
    room_split = (
        assembly.port(assembly.fixtures[0].junction_port_id).point.x_mm
        + assembly.port(assembly.fixtures[1].junction_port_id).point.x_mm
    ) / 2
    shaft_left = riser_x - 30.0
    sx1, sy1 = xy(DraftPoint(first_x, slab_y))
    sx2, _ = xy(DraftPoint(riser_x + 22.0, slab_y))
    body.extend(
        (
            f'<line data-architecture="floor" x1="{sx1:.1f}" y1="{sy1:.1f}" '
            f'x2="{sx2:.1f}" y2="{sy1:.1f}" stroke="#777" stroke-width="1"/>',
            f'<line data-architecture="wall" x1="{xy(DraftPoint(room_split, 20))[0]:.1f}" '
            f'y1="{xy(DraftPoint(room_split, 20))[1]:.1f}" '
            f'x2="{xy(DraftPoint(room_split, slab_y))[0]:.1f}" '
            f'y2="{sy1:.1f}" stroke="#777" stroke-width="1"/>',
            f'<line data-architecture="shaft" x1="{xy(DraftPoint(shaft_left, 20))[0]:.1f}" '
            f'y1="{xy(DraftPoint(shaft_left, 20))[1]:.1f}" '
            f'x2="{xy(DraftPoint(shaft_left, slab_y))[0]:.1f}" '
            f'y2="{sy1:.1f}" stroke="#777" stroke-width="1"/>',
            f'<text x="{xy(DraftPoint(first_x+20, 16))[0]:.1f}" '
            f'y="{xy(DraftPoint(first_x+20, 16))[1]:.1f}" font-family="{FONT}" '
            'font-size="12" fill="#555">Кухня</text>',
            f'<text x="{xy(DraftPoint(room_split+10, 16))[0]:.1f}" '
            f'y="{xy(DraftPoint(room_split+10, 16))[1]:.1f}" font-family="{FONT}" '
            'font-size="12" fill="#555">Санузел</text>',
            f'<text x="{xy(DraftPoint(shaft_left+4, 30))[0]:.1f}" '
            f'y="{xy(DraftPoint(shaft_left+4, 30))[1]:.1f}" font-family="{FONT}" '
            'font-size="9.5" fill="#555">шахта</text>',
        )
    )

    for segment in assembly.segments:
        x1, y1 = xy(segment.start_port_id)
        x2, y2 = xy(segment.end_port_id)
        body.append(
            f'<line data-floor-segment="{escape(segment.segment_id)}" '
            f'data-role="{escape(segment.role)}" data-dn="{segment.dn_mm}" '
            f'data-carries-flow="{str(segment.carries_flow).lower()}" '
            f'x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{BLACK}" stroke-width="3" fill="none"/>'
        )

    # UGO symbols are anchored at their actual outlet points.  External traps
    # are anchored at both graph ports, so there is no visual gap.
    for fixture in assembly.fixtures:
        outlet = xy(fixture.fixture_outlet_port_id)
        ax, ay = get_ugo_connection_anchor(fixture.kind)
        fixture_scale = _FIXTURE_SYMBOL_RATIO * scale
        origin_x = outlet[0] - ax * fixture_scale
        origin_y = outlet[1] - ay * fixture_scale
        body.append(
            f'<g data-floor-fixture="{escape(fixture.fixture_id)}" '
            f'data-kind="{fixture.kind}" data-trap-mode="{fixture.trap_mode}">'
            + render_ugo(
                fixture.kind,
                origin_x,
                origin_y,
                scale=fixture_scale,
            )
        )
        if fixture.trap_mode == "external":
            trap_in = xy(fixture.trap_inlet_port_id)
            trap_scale = _TRAP_SYMBOL_RATIO * scale
            body.append(
                render_ugo(
                    "trap",
                    trap_in[0] + 14.0 * trap_scale,
                    trap_in[1] + 20.0 * trap_scale,
                    scale=trap_scale,
                )
            )
        body.append("</g>")

        fx, fy = outlet
        body.extend(
            (
                f'<text x="{fx:.1f}" y="{fy-68:.1f}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="9.5" font-weight="bold">'
                f'{escape(fixture.fixture_id)}</text>',
                f'<text x="{fx:.1f}" y="{fy-54:.1f}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="8.5">'
                f'{escape(_FIXTURE_LABEL[fixture.kind])}; DN{fixture.dn_mm}</text>',
            )
        )

    # Manufactured fitting boundaries: three ports of every wye and both
    # sides of each 45-degree elbow.  These ticks prevent a connected line
    # from being mistaken for an undefined freehand branch.
    for fixture in assembly.fixtures:
        joint = assembly.port(fixture.junction_port_id).point
        connection = assembly.segment(fixture.connection_segment_ids[-1])
        diagonal = assembly.port(connection.start_port_id).point
        index = assembly.fixtures.index(fixture)
        upstream_id = "cleanout_cap" if index == 0 else assembly.fixtures[index - 1].junction_port_id
        downstream_id = (
            assembly.fixtures[index + 1].junction_port_id
            if index + 1 < len(assembly.fixtures)
            else "riser_join"
        )
        body.append(f'<g data-floor-fitting="{escape(fixture.fixture_id)}_wye_45">')
        for toward_id in (upstream_id, downstream_id):
            body.append(_tick_svg(joint, assembly.port(toward_id).point, xy=xy))
        body.append(_tick_svg(joint, diagonal, xy=xy))
        body.append("</g>")

        elbow = assembly.port(connection.start_port_id).point
        vertical = assembly.port(connection.start_port_id).point
        previous_segment = assembly.segment(fixture.connection_segment_ids[-2])
        vertical_start = assembly.port(previous_segment.start_port_id).point
        body.append(f'<g data-floor-fitting="{escape(fixture.fixture_id)}_elbow_45">')
        body.append(_tick_svg(elbow, vertical_start, xy=xy, offset_mm=4.0))
        body.append(_tick_svg(elbow, joint, xy=xy, offset_mm=4.0))
        body.append("</g>")

    cap = assembly.port("cleanout_cap").point
    first_joint = assembly.port(assembly.fixtures[0].junction_port_id).point
    dx, dy = cap.vector_to(first_joint)
    length = hypot(dx, dy)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    cap_x, cap_y = xy(cap)
    for offset in (-1.6, 1.6):
        cx = cap_x + ux * offset * scale
        cy = cap_y + uy * offset * scale
        body.append(
            f'<line data-floor-fitting="cleanout_cap_fitting" '
            f'x1="{cx-px*8:.1f}" y1="{cy-py*8:.1f}" '
            f'x2="{cx+px*8:.1f}" y2="{cy+py*8:.1f}" '
            f'stroke="{BLACK}" stroke-width="2"/>'
        )

    # Cleanout callout and system labels.
    body.extend(
        (
            f'<path d="M{cap_x:.1f},{cap_y:.1f} L{cap_x-30:.1f},{cap_y-34:.1f} '
            f'H{cap_x-112:.1f}" fill="none" stroke="{BLACK}" stroke-width="1.2"/>',
            f'<text x="{cap_x-108:.1f}" y="{cap_y-42:.1f}" text-anchor="start" '
            f'font-family="{FONT}" font-size="11" font-weight="bold">Прочистка</text>',
            f'<text x="{cap_x-108:.1f}" y="{cap_y-27:.1f}" text-anchor="start" '
            f'font-family="{FONT}" font-size="9">DN{assembly.fixtures[0].dn_mm}</text>',
        )
    )

    branch = [assembly.segment(row) for row in assembly.branch_segment_ids]
    label_groups: list[tuple[int, DraftPipeSegment]] = []
    for row in branch:
        if not label_groups or label_groups[-1][0] != row.dn_mm:
            label_groups.append((row.dn_mm, row))
    for group_index, (dn, segment) in enumerate(label_groups, start=1):
        start = assembly.port(segment.start_port_id).point
        end = assembly.port(segment.end_port_id).point
        mx, my = xy(DraftPoint((start.x_mm + end.x_mm) / 2, (start.y_mm + end.y_mm) / 2))
        slope = assembly.slope(100 if dn >= 100 else 50)
        body.append(
            f'<text data-branch-label="DN{dn}" x="{mx:.1f}" y="{my+22:.1f}" '
            f'text-anchor="middle" font-family="{FONT}" font-size="9.5">'
            f'{_system_mark(assembly.system)}-М{group_index} DN{dn}; '
            f'i={slope:.3f}</text>'.replace(".", ",")
        )

    riser_join_x, riser_join_y = xy("riser_join")
    body.extend(
        (
            f'<text x="{riser_join_x+12:.1f}" y="{riser_join_y-52:.1f}" '
            f'font-family="{FONT}" font-size="10.5" font-weight="bold">'
            f'{escape(assembly.riser_id)} DN{assembly.segment("riser_lower").dn_mm}</text>',
            f'<path data-flow-direction="collector" '
            f'd="M{riser_join_x-54:.1f},{riser_join_y-6:.1f} '
            f'L{riser_join_x-42:.1f},{riser_join_y:.1f} '
            f'L{riser_join_x-54:.1f},{riser_join_y+6:.1f} Z" fill="{BLACK}"/>',
            f'<path data-flow-direction="riser" '
            f'd="M{riser_join_x-6:.1f},{riser_join_y+42:.1f} '
            f'L{riser_join_x:.1f},{riser_join_y+54:.1f} '
            f'L{riser_join_x+6:.1f},{riser_join_y+42:.1f} Z" fill="{BLACK}"/>',
        )
    )

    if diagnostics:
        points = [xy(port_id) for port_id in assembly.service_path.point_ids]
        d = " ".join(
            ("M" if index == 0 else "L") + f"{px:.1f},{py:.1f}"
            for index, (px, py) in enumerate(points)
        )
        body.extend(
            (
                f'<path data-service-path="{assembly.service_path.path_id}" d="{d}" '
                f'fill="none" stroke="{SERVICE}" stroke-width="5" '
                'stroke-dasharray="12 8" opacity="0.8"/>',
                f'<text x="{cap_x:.1f}" y="{cap_y+52:.1f}" font-family="{FONT}" '
                f'font-size="10" fill="{SERVICE}">контрольный путь троса до стояка</text>',
            )
        )
    body.append("</g>")
    return "".join(body)


def build_typical_floor_control_sheet_svg(
    assembly: WastewaterFloorAssembly,
) -> str:
    """A4 landscape approval sheet for one repeatable K1 floor module."""
    width, height = 1123, 794
    margin = 34
    diagram_x = 112.0
    diagram_y = 106.0
    diagram_scale = 2.15
    panel_x = 870.0
    system = _system_mark(assembly.system)
    elevation = f"{assembly.floor_elevation_m:+.3f}".replace(".", ",")
    body = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="1122.519685" height="793.700787" viewBox="0 0 1123 794">',
        '<rect width="1123" height="794" fill="white"/>',
        f'<rect x="{margin}" y="{margin}" width="{width-2*margin}" '
        f'height="{height-2*margin}" fill="none" stroke="{BLACK}" stroke-width="2"/>',
        f'<text x="{margin+24}" y="{margin+36}" font-family="{FONT}" '
        'font-size="21" font-weight="bold">Контрольный модуль 02. Типовой этаж системы К1</text>',
        f'<text x="{margin+24}" y="{margin+59}" font-family="{FONT}" '
        f'font-size="11.5" fill="{GRAY}">Параметрическая сборка: приборы - '
        'гидрозатворы - общая ветвь - прочистка - стояк</text>',
        f'<text x="{margin+24}" y="{diagram_y+24}" font-family="{FONT}" '
        f'font-size="13" font-weight="bold">{assembly.floor_no} этаж</text>',
        f'<text x="{margin+24}" y="{diagram_y+43}" font-family="{FONT}" '
        f'font-size="10">отм. {elevation}</text>',
        render_typical_floor_assembly_svg(
            assembly,
            diagnostics=False,
            x=diagram_x,
            y=diagram_y,
            scale=diagram_scale,
        ),
        f'<line x1="{panel_x}" y1="{margin+86}" x2="{panel_x}" '
        f'y2="{height-margin-26}" stroke="#777" stroke-width="1"/>',
        f'<text x="{panel_x+18}" y="{margin+111}" font-family="{FONT}" '
        'font-size="13" font-weight="bold">Проверки модуля</text>',
    ]
    checks = (
        "Все трубы начинаются от приборов",
        "Мойка, ванна и умывальник - с сифонами",
        "Унитаз - DN100 и последний перед стояком",
        "Ветви объединены в один самотечный коллектор",
        "Прочистка - заглушённый конец первого тройника",
        "Трос проходит по оси ветви до стояка",
    )
    cy = margin + 140
    for index, value in enumerate(checks, start=1):
        body.extend(
            (
                f'<circle cx="{panel_x+25}" cy="{cy-4}" r="8" fill="none" '
                f'stroke="{BLACK}" stroke-width="1.3"/>',
                f'<text x="{panel_x+25}" y="{cy}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="8.5" font-weight="bold">{index}</text>',
                f'<text x="{panel_x+42}" y="{cy}" font-family="{FONT}" '
                f'font-size="8.7">{escape(value[:35])}</text>',
            )
        )
        if len(value) > 35:
            split = value.rfind(" ", 0, 35)
            if split <= 0:
                split = 35
            body[-1] = (
                f'<text x="{panel_x+42}" y="{cy-5}" font-family="{FONT}" '
                f'font-size="8.7">{escape(value[:split])}</text>'
            )
            body.append(
                f'<text x="{panel_x+42}" y="{cy+8}" font-family="{FONT}" '
                f'font-size="8.7">{escape(value[split+1:])}</text>'
            )
        cy += 48

    body.extend(
        (
            f'<line x1="{panel_x+18}" y1="{cy+2}" x2="{width-margin-18}" '
            f'y2="{cy+2}" stroke="#777" stroke-width="0.8"/>',
            f'<text x="{panel_x+18}" y="{cy+27}" font-family="{FONT}" '
            f'font-size="10" font-weight="bold">Нормативная трассировка</text>',
            f'<text x="{panel_x+18}" y="{cy+47}" font-family="{FONT}" '
            'font-size="8.5">СП 30.13330.2020:</text>',
            f'<text x="{panel_x+18}" y="{cy+62}" font-family="{FONT}" '
            'font-size="8.5">17.2 - гидрозатворы;</text>',
            f'<text x="{panel_x+18}" y="{cy+77}" font-family="{FONT}" '
            'font-size="8.5">17.3, 19.1 - уклоны;</text>',
            f'<text x="{panel_x+18}" y="{cy+92}" font-family="{FONT}" '
            'font-size="8.5">18.26 - прочистка в начале;</text>',
            f'<text x="{panel_x+18}" y="{cy+107}" font-family="{FONT}" '
            'font-size="8.5">19.12 - минимальные диаметры.</text>',
            f'<text x="{panel_x+18}" y="{height-margin-62}" font-family="{FONT}" '
            f'font-size="8" fill="{GRAY}">Уклоны являются входами модуля;</text>',
            f'<text x="{panel_x+18}" y="{height-margin-48}" font-family="{FONT}" '
            f'font-size="8" fill="{GRAY}">гидравлическая проверка выполняется</text>',
            f'<text x="{panel_x+18}" y="{height-margin-34}" font-family="{FONT}" '
            f'font-size="8" fill="{GRAY}">отдельным расчётным слоем.</text>',
            f'<text x="{margin+18}" y="{height-margin-16}" font-family="{FONT}" '
            f'font-size="9" fill="{GRAY}">Графический язык - приложение В '
            f'ГОСТ Р 21.620-2023. Система: {system}. Контрольный лист не входит в комплект ПД.</text>',
            '</svg>',
        )
    )
    return "".join(body)


def generate_typical_floor_control_pdf(
    output_path: str,
    *,
    fixtures: Iterable[FloorFixtureInput] | None = None,
    floor_no: int = 2,
    floor_elevation_m: float = 3.0,
    riser_id: str = "К1-Ст1",
) -> str:
    """Write the isolated floor approval sheet as a vector A4 PDF."""
    import cairosvg

    assembly = build_typical_floor_assembly(
        fixtures=fixtures,
        floor_no=floor_no,
        floor_elevation_m=floor_elevation_m,
        riser_id=riser_id,
    )
    svg = build_typical_floor_control_sheet_svg(assembly)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=str(path))
    return str(path)
