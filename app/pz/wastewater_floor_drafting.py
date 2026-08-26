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
from xml.etree import ElementTree

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
    render_inline_pipe_label,
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
_FIXTURE_OUTLET_Y_MM = {
    "sink": 130.0,
    "washbasin": 130.0,
    "bath": 138.0,
    "shower": 138.0,
    "floor_drain": 158.0,
    "toilet": 158.0,
}


@dataclass(frozen=True)
class FloorFixtureInput:
    fixture_id: str
    kind: str
    room_label: str
    dn_mm: int | None = None
    quantity: int = 1


@dataclass(frozen=True)
class FloorFixtureDraft:
    fixture_id: str
    kind: str
    room_label: str
    dn_mm: int
    quantity: int
    trap_mode: str
    fixture_outlet_port_id: str
    junction_port_id: str
    connection_segment_ids: tuple[str, ...]
    connection_joint_id: str
    trap_inlet_port_id: str = ""
    trap_outlet_port_id: str = ""


@dataclass(frozen=True)
class DirectFittingJointDraft:
    """A socketed fitting-to-fitting joint with no intervening pipe piece."""

    joint_id: str
    start_fitting_id: str
    end_fitting_id: str
    start_port_id: str
    end_port_id: str
    dn_mm: int


@dataclass(frozen=True)
class SimplificationFinding:
    """A deterministic indication that drawn pipe can be removed."""

    code: str
    element_id: str
    message: str


@dataclass(frozen=True)
class FloorSlopeAnnotationDraft:
    annotation_id: str
    first_segment_id: str
    last_segment_id: str
    dn_mm: int
    slope: float


@dataclass(frozen=True)
class FloorDiameterTransitionDraft:
    transition_id: str
    port_id: str
    upstream_segment_id: str
    downstream_segment_id: str
    upstream_dn_mm: int
    downstream_dn_mm: int


@dataclass(frozen=True)
class DraftingConventionFinding:
    code: str
    element_id: str
    message: str


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
    direct_fitting_joints: tuple[DirectFittingJointDraft, ...]
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

    def direct_fitting_joint(self, joint_id: str) -> DirectFittingJointDraft:
        try:
            return next(
                row for row in self.direct_fitting_joints if row.joint_id == joint_id
            )
        except StopIteration as exc:
            raise KeyError(f"unknown direct fitting joint: {joint_id}") from exc

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
        joint_ids = [row.joint_id for row in self.direct_fitting_joints]
        fixture_ids = [row.fixture_id for row in self.fixtures]
        for label, values in (
            ("port", port_ids),
            ("segment", segment_ids),
            ("fitting", fitting_ids),
            ("direct fitting joint", joint_ids),
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

        known_fittings = set(fitting_ids)
        for joint in self.direct_fitting_joints:
            for fitting_id in (joint.start_fitting_id, joint.end_fitting_id):
                if fitting_id not in known_fittings:
                    errors.append(
                        f"{joint.joint_id}: unknown fitting {fitting_id}"
                    )
            for port_id in (joint.start_port_id, joint.end_port_id):
                if port_id not in known_ports:
                    errors.append(f"{joint.joint_id}: unknown port {port_id}")
            if joint.dn_mm <= 0:
                errors.append(f"{joint.joint_id}: DN must be positive")
            if joint.start_port_id in known_ports and joint.end_port_id in known_ports:
                start = self.port(joint.start_port_id).point
                end = self.port(joint.end_port_id).point
                if start.distance_to(end) <= 1e-9:
                    errors.append(f"{joint.joint_id}: fitting bodies overlap")
                if end.y_mm < start.y_mm - 1e-9:
                    errors.append(f"{joint.joint_id}: gravity path rises")

        toilets = [row for row in self.fixtures if row.kind == "toilet"]
        if len(toilets) != 1:
            errors.append("floor module must contain exactly one toilet")
        elif self.fixtures[-1].fixture_id != toilets[0].fixture_id:
            errors.append("toilet must be the last fixture before the riser")
        if any(row.kind not in _FIXTURE_DEFAULT_DN for row in self.fixtures):
            errors.append("floor module contains an unsupported fixture UGO")

        for fixture in self.fixtures:
            if fixture.quantity < 1:
                errors.append(f"{fixture.fixture_id}: quantity must be positive")
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
                try:
                    direct_joint = self.direct_fitting_joint(
                        fixture.connection_joint_id
                    )
                except KeyError as exc:
                    errors.append(str(exc))
                else:
                    if connection[-1].end_port_id != direct_joint.start_port_id:
                        errors.append(
                            f"{fixture.fixture_id}: pipe misses connection elbow"
                        )
                    if direct_joint.end_port_id != fixture.junction_port_id:
                        errors.append(
                            f"{fixture.fixture_id}: direct fitting joint misses "
                            "common branch"
                        )
            if fixture.kind == "toilet":
                try:
                    wye = self.fitting(f"{fixture.fixture_id}_wye_45")
                    main_run = [
                        self.segment(row) for row in wye.connected_segment_ids[:2]
                    ]
                except KeyError as exc:
                    errors.append(str(exc))
                else:
                    if any(row.dn_mm < fixture.dn_mm for row in main_run):
                        errors.append(
                            f"{fixture.fixture_id}: collector must increase to "
                            f"DN{fixture.dn_mm} before the toilet connection"
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
        errors.extend(
            f"{row.element_id}: {row.message}"
            for row in audit_floor_simplification(self)
        )
        return errors


def audit_floor_simplification(
    assembly: WastewaterFloorAssembly,
    *,
    maximum_graphic_spool_mm: float = 30.0,
) -> tuple[SimplificationFinding, ...]:
    """Reject short graphic-only spools between an elbow and an oblique wye.

    A real measured straight piece can be longer and may be required by the
    project layout.  The small 45-degree links produced solely to separate
    adjacent fitting symbols are not pipework and must instead be represented
    by :class:`DirectFittingJointDraft`.
    """
    if maximum_graphic_spool_mm <= 0:
        raise ValueError("maximum_graphic_spool_mm must be positive")

    fittings_by_point: dict[tuple[float, float], list[DraftFitting]] = {}
    for fitting in assembly.fittings:
        key = (fitting.point.x_mm, fitting.point.y_mm)
        fittings_by_point.setdefault(key, []).append(fitting)

    findings: list[SimplificationFinding] = []
    for segment in assembly.segments:
        try:
            start = assembly.port(segment.start_port_id).point
            end = assembly.port(segment.end_port_id).point
        except KeyError:
            continue
        if start.distance_to(end) > maximum_graphic_spool_mm:
            continue
        dx, dy = start.vector_to(end)
        if abs(abs(dx) - abs(dy)) > 1e-6 or abs(dx) <= 1e-9:
            continue
        start_kinds = {
            row.kind for row in fittings_by_point.get((start.x_mm, start.y_mm), ())
        }
        end_kinds = {
            row.kind for row in fittings_by_point.get((end.x_mm, end.y_mm), ())
        }
        if not (
            ("elbow_45" in start_kinds and "wye_45" in end_kinds)
            or ("wye_45" in start_kinds and "elbow_45" in end_kinds)
        ):
            continue
        findings.append(
            SimplificationFinding(
                "avoidable_elbow_wye_spool",
                segment.segment_id,
                "короткий графический отрезок между полуотводом и косым "
                "тройником следует заменить прямым стыком фасонных частей",
            )
        )
    return tuple(findings)


def build_floor_graphic_annotations(
    assembly: WastewaterFloorAssembly,
) -> tuple[
    tuple[FloorSlopeAnnotationDraft, ...],
    tuple[FloorDiameterTransitionDraft, ...],
]:
    """Derive slope signs and diameter transitions from the pipe topology."""
    branch = [assembly.segment(row) for row in assembly.branch_segment_ids]
    slope_rows: list[FloorSlopeAnnotationDraft] = []
    if branch:
        group: list[DraftPipeSegment] = [branch[0]]
        for segment in branch[1:]:
            if segment.dn_mm == group[-1].dn_mm:
                group.append(segment)
                continue
            slope_rows.append(
                FloorSlopeAnnotationDraft(
                    f"slope_{len(slope_rows) + 1}",
                    group[0].segment_id,
                    group[-1].segment_id,
                    group[-1].dn_mm,
                    assembly.slope(100 if group[-1].dn_mm >= 100 else 50),
                )
            )
            group = [segment]
        slope_rows.append(
            FloorSlopeAnnotationDraft(
                f"slope_{len(slope_rows) + 1}",
                group[0].segment_id,
                group[-1].segment_id,
                group[-1].dn_mm,
                assembly.slope(100 if group[-1].dn_mm >= 100 else 50),
            )
        )

    transitions = tuple(
        FloorDiameterTransitionDraft(
            f"transition_{index}",
            upstream.end_port_id,
            upstream.segment_id,
            downstream.segment_id,
            upstream.dn_mm,
            downstream.dn_mm,
        )
        for index, (upstream, downstream) in enumerate(
            zip(branch, branch[1:]), start=1
        )
        if upstream.dn_mm != downstream.dn_mm
    )
    return tuple(slope_rows), transitions


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
    junction_spacing_mm: float = 60.0,
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
    if junction_spacing_mm < 45.0:
        raise ValueError("junction_spacing_mm must be at least 45 mm")

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
        if row.quantity < 1:
            raise ValueError(f"{row.fixture_id}: fixture quantity must be positive")
        dn = row.dn_mm or _FIXTURE_DEFAULT_DN[row.kind]
        if dn < 50:
            raise ValueError(f"{row.fixture_id}: fixture connection must be at least DN50")
        if row.kind == "toilet" and dn < 100:
            raise ValueError(f"{row.fixture_id}: toilet connection must be DN100")
        resolved.append((row, dn))

    ports: list[DraftPort] = []
    segments: list[DraftPipeSegment] = []
    fittings: list[DraftFitting] = []
    direct_fitting_joints: list[DirectFittingJointDraft] = []
    floor_fixtures: list[FloorFixtureDraft] = []

    junction_x = [
        70.0 + index * junction_spacing_mm for index in range(len(resolved))
    ]
    # The collector is drawn close to the fixture outlets, as it is installed
    # in the floor/ceiling zone in reality.  The former 205/62 coordinates
    # exaggerated every fixture connection into a full-height vertical drop.
    junction_y = [185.0]
    joined_dn = resolved[0][1]
    interval_data: list[tuple[int, int, str, DraftPoint | None]] = []
    for index in range(len(resolved) - 1):
        upstream_dn = joined_dn
        downstream_dn = max(upstream_dn, resolved[index + 1][1])
        dx = junction_x[index + 1] - junction_x[index]
        transition_port_id = ""
        transition_point: DraftPoint | None = None
        if downstream_dn > upstream_dn:
            # Increase the collector diameter before the larger fixture joins
            # it.  In particular, a DN100 toilet must enter an already-DN100
            # main, never a DN50 run enlarged only after the toilet wye.
            # Leave enough visible DN100 run before a toilet wye for the
            # required inline system/DN mark.  The transition remains before
            # the toilet and no extra fitting or pipe branch is invented.
            setback = min(60.0, dx * 0.4)
            transition_x = junction_x[index + 1] - setback
            upstream_slope = slope_dn100 if upstream_dn >= 100 else slope_dn50
            downstream_slope = (
                slope_dn100 if downstream_dn >= 100 else slope_dn50
            )
            transition_y = junction_y[-1] + (
                transition_x - junction_x[index]
            ) * upstream_slope
            next_y = transition_y + setback * downstream_slope
            transition_port_id = f"transition_before_junction_{index + 2}"
            transition_point = DraftPoint(transition_x, transition_y)
        else:
            slope = slope_dn100 if upstream_dn >= 100 else slope_dn50
            next_y = junction_y[-1] + dx * slope
        interval_data.append(
            (upstream_dn, downstream_dn, transition_port_id, transition_point)
        )
        junction_y.append(next_y)
        joined_dn = downstream_dn
    outlet_dn = joined_dn

    junction_ids: list[str] = []
    for index, (x_mm, y_mm) in enumerate(zip(junction_x, junction_y), start=1):
        port_id = f"junction_{index}"
        junction_ids.append(port_id)
        ports.append(DraftPort(port_id, DraftPoint(x_mm, y_mm), "fixture_wye"))
    for upstream_dn, downstream_dn, port_id, point in interval_data:
        if point is not None:
            ports.append(DraftPort(port_id, point, "diameter_transition"))

    outlet_slope = slope_dn100 if outlet_dn >= 100 else slope_dn50
    riser_elbow_x = junction_x[-1] + 30.0
    riser_elbow_y = junction_y[-1] + 30.0 * outlet_slope
    # One-sided floor branch: a 45-degree elbow turns the shallow collector
    # into the branch of an oblique 45-degree tee on the vertical riser.
    # The hubs are adjacent in the drawing: this is a direct socketed joint,
    # not a separately measured pipe segment between the two fittings.
    riser_x = riser_elbow_x + 8.0
    riser_y = riser_elbow_y + 8.0
    ports.extend(
        (
            DraftPort(
                "riser_branch_elbow",
                DraftPoint(riser_elbow_x, riser_elbow_y),
                "riser_connection_elbow_45",
            ),
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
    junction_upstream_segment: dict[str, str] = {
        junction_ids[0]: "cleanout_access"
    }
    junction_downstream_segment: dict[str, str] = {}
    for index, (upstream_dn, downstream_dn, transition_id, transition_point) in enumerate(
        interval_data
    ):
        start_id = junction_ids[index]
        end_id = junction_ids[index + 1]
        if transition_point is None:
            segment_id = f"collector_{index + 1}"
            branch_segment_ids.append(segment_id)
            segments.append(
                DraftPipeSegment(
                    segment_id,
                    start_id,
                    end_id,
                    upstream_dn,
                    "common_floor_branch",
                )
            )
            junction_downstream_segment[start_id] = segment_id
            junction_upstream_segment[end_id] = segment_id
            continue

        before_id = f"collector_{index + 1}_before_transition"
        after_id = f"collector_{index + 1}_after_transition"
        branch_segment_ids.extend((before_id, after_id))
        segments.extend(
            (
                DraftPipeSegment(
                    before_id,
                    start_id,
                    transition_id,
                    upstream_dn,
                    "common_floor_branch",
                ),
                DraftPipeSegment(
                    after_id,
                    transition_id,
                    end_id,
                    downstream_dn,
                    "common_floor_branch",
                ),
            )
        )
        fittings.append(
            DraftFitting(
                f"diameter_transition_{index + 1}",
                "diameter_transition",
                transition_point,
                downstream_dn,
                (before_id, after_id),
            )
        )
        junction_downstream_segment[start_id] = before_id
        junction_upstream_segment[end_id] = after_id
    branch_segment_ids.append("collector_to_riser")
    segments.append(
        DraftPipeSegment(
            "collector_to_riser",
            junction_ids[-1],
            "riser_branch_elbow",
            outlet_dn,
            "common_floor_branch",
        )
    )
    junction_downstream_segment[junction_ids[-1]] = "collector_to_riser"
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
        # The 45-degree elbow is socketed directly into the oblique wye.  The
        # eight-millimetre centreline represents the adjacent fitting bodies,
        # not a separately measured or specified pipe spool.
        elbow = DraftPoint(junction.x_mm - 8.0, junction.y_mm - 8.0)
        ports.append(DraftPort(elbow_id, elbow, "connection_elbow_45"))
        mode = fixture_trap_mode(source.kind)
        fixture_outlet_id = f"{source.fixture_id}_outlet"
        connection_ids: list[str] = []
        trap_inlet_id = ""
        trap_outlet_id = ""
        fixture_outlet_y = _FIXTURE_OUTLET_Y_MM[source.kind]
        if mode == "external":
            trap_inlet_id = f"{source.fixture_id}_trap_in"
            trap_outlet_id = f"{source.fixture_id}_trap_out"
            trap_in_y = fixture_outlet_y + 12.0
            trap_in = DraftPoint(elbow.x_mm - _TRAP_DX, trap_in_y)
            trap_out = DraftPoint(elbow.x_mm, trap_in_y + _TRAP_DY)
            fixture_outlet = DraftPoint(trap_in.x_mm, fixture_outlet_y)
            ports.extend(
                (
                    DraftPort(fixture_outlet_id, fixture_outlet, "fixture_outlet"),
                    DraftPort(trap_inlet_id, trap_in, "trap_inlet"),
                    DraftPort(trap_outlet_id, trap_out, "trap_outlet"),
                )
            )
            before_id = f"{source.fixture_id}_to_trap"
            vertical_id = f"{source.fixture_id}_vertical"
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
                )
            )
            connection_ids.extend((before_id, vertical_id))
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
            fixture_outlet = DraftPoint(elbow.x_mm, fixture_outlet_y)
            ports.append(
                DraftPort(fixture_outlet_id, fixture_outlet, "fixture_outlet")
            )
            vertical_id = f"{source.fixture_id}_vertical"
            segments.append(
                DraftPipeSegment(
                    vertical_id,
                    fixture_outlet_id,
                    elbow_id,
                    dn,
                    "fixture_connection",
                )
            )
            connection_ids.append(vertical_id)

        elbow_fitting_id = f"{source.fixture_id}_elbow_45"
        fittings.append(
            DraftFitting(
                elbow_fitting_id,
                "elbow_45",
                elbow,
                dn,
                (connection_ids[-1],),
            )
        )
        upstream_segment = junction_upstream_segment[junction_id]
        downstream_segment = junction_downstream_segment[junction_id]
        wye_fitting_id = f"{source.fixture_id}_wye_45"
        fittings.append(
            DraftFitting(
                wye_fitting_id,
                "wye_45",
                junction,
                max(value for _, value in resolved[:index]),
                (upstream_segment, downstream_segment),
            )
        )
        connection_joint_id = f"{source.fixture_id}_elbow_to_wye"
        direct_fitting_joints.append(
            DirectFittingJointDraft(
                connection_joint_id,
                elbow_fitting_id,
                wye_fitting_id,
                elbow_id,
                junction_id,
                dn,
            )
        )
        floor_fixtures.append(
            FloorFixtureDraft(
                fixture_id=source.fixture_id,
                kind=source.kind,
                room_label=source.room_label,
                dn_mm=dn,
                quantity=source.quantity,
                trap_mode=mode,
                fixture_outlet_port_id=fixture_outlet_id,
                junction_port_id=junction_id,
                connection_segment_ids=tuple(connection_ids),
                connection_joint_id=connection_joint_id,
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
                "riser_branch_elbow_45",
                "elbow_45",
                DraftPoint(riser_elbow_x, riser_elbow_y),
                max(100, outlet_dn),
                ("collector_to_riser",),
            ),
            DraftFitting(
                "riser_branch_wye",
                "wye_45",
                DraftPoint(riser_x, riser_y),
                max(100, outlet_dn),
                ("riser_upper", "riser_lower"),
            ),
        )
    )

    direct_fitting_joints.append(
        DirectFittingJointDraft(
            "riser_elbow_to_wye",
            "riser_branch_elbow_45",
            "riser_branch_wye",
            "riser_branch_elbow",
            "riser_join",
            max(100, outlet_dn),
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
        direct_fitting_joints=tuple(direct_fitting_joints),
        branch_segment_ids=tuple(branch_segment_ids),
        riser_segment_ids=("riser_upper", "riser_lower"),
        service_path=DraftServicePath(
            "floor_cleanout_cable",
            "cleanout_cap",
            f"{floor_fixtures[0].fixture_id}_wye_45",
            (
                "cleanout_cap",
                *junction_ids,
                "riser_branch_elbow",
                "riser_join",
            ),
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
    marker_id: str = "",
) -> str:
    dx, dy = point.vector_to(toward)
    length = hypot(dx, dy)
    if length <= 1e-9:
        return ""
    ux, uy = dx / length, dy / length
    center = DraftPoint(point.x_mm + ux * offset_mm, point.y_mm + uy * offset_mm)
    cx, cy = xy(center)
    px, py = -uy, ux
    marker_attr = (
        f' data-fitting-boundary="{escape(marker_id)}"' if marker_id else ""
    )
    return (
        f'<line{marker_attr} x1="{cx-px*half_length_px:.1f}" '
        f'y1="{cy-py*half_length_px:.1f}" '
        f'x2="{cx+px*half_length_px:.1f}" '
        f'y2="{cy+py*half_length_px:.1f}" stroke="{BLACK}" '
        'stroke-width="1.8"/>'
    )


def _slope_sign_svg(
    annotation: FloorSlopeAnnotationDraft,
    start: DraftPoint,
    end: DraftPoint,
    *,
    xy,
) -> str:
    """Render an open angle pointing towards the downstream end.

    The numeric value is placed beside the angle.  No line is allowed below
    the value: a horizontal baseline would turn the sign into an underlined
    caption instead of the compact direction mark used by the reference.
    """
    x1, y1 = xy(start)
    x2, y2 = xy(end)
    centre_x = (x1 + x2) / 2
    sign_y = min(y1, y2) - 17.0
    direction = 1.0 if x2 >= x1 else -1.0
    apex_x = centre_x + direction * 18.0
    arm_x = apex_x - direction * 10.0
    text_x = arm_x - direction * 5.0
    text_anchor = "end" if direction > 0 else "start"
    direction_label = "right" if direction > 0 else "left"
    value = f"{annotation.slope:.3f}".replace(".", ",")
    return (
        f'<g data-slope-marker="{escape(annotation.annotation_id)}" '
        f'data-first-segment="{escape(annotation.first_segment_id)}" '
        f'data-last-segment="{escape(annotation.last_segment_id)}" '
        f'data-placement="above" data-slope-value="{value}" '
        f'data-sign-shape="open-angle" data-slope-direction="{direction_label}" '
        'data-label-underline="false">'
        f'<path data-slope-angle="true" '
        f'd="M{arm_x:.1f},{sign_y-6.0:.1f} '
        f'L{apex_x:.1f},{sign_y:.1f} '
        f'L{arm_x:.1f},{sign_y+6.0:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="1.3"/>'
        f'<text x="{text_x:.1f}" y="{sign_y+3.5:.1f}" '
        f'text-anchor="{text_anchor}" font-family="{FONT}" font-size="9.5">'
        f'{value}</text></g>'
    )


def _diameter_transition_svg(
    transition: FloorDiameterTransitionDraft,
    point: DraftPoint,
    toward: DraftPoint,
    *,
    xy,
) -> str:
    """Render an unfilled triangle at a pipe diameter change."""
    apex_x, apex_y = xy(point)
    toward_x, toward_y = xy(toward)
    dx, dy = toward_x - apex_x, toward_y - apex_y
    length = hypot(dx, dy)
    if length <= 1e-9:
        return ""
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    base_x = apex_x + ux * 11.0
    base_y = apex_y + uy * 11.0
    half_width = 5.5
    triangle_d = (
        f"M{apex_x:.1f},{apex_y:.1f} "
        f"L{base_x+px*half_width:.1f},{base_y+py*half_width:.1f} "
        f"L{base_x-px*half_width:.1f},{base_y-py*half_width:.1f} Z"
    )
    return (
        f'<g data-diameter-transition-group="{escape(transition.transition_id)}">'
        f'<path data-diameter-transition-mask="{escape(transition.transition_id)}" '
        f'd="{triangle_d}" fill="white" stroke="white" stroke-width="3"/>'
        f'<path data-diameter-transition="{escape(transition.transition_id)}" '
        f'data-transition-port="{escape(transition.port_id)}" '
        f'data-upstream-dn="{transition.upstream_dn_mm}" '
        f'data-downstream-dn="{transition.downstream_dn_mm}" '
        f'd="{triangle_d}" fill="none" stroke="{BLACK}" '
        f'stroke-width="1.5"/></g>'
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

    slope_annotations, diameter_transitions = build_floor_graphic_annotations(
        assembly
    )
    diameter_transition_ports = {row.port_id for row in diameter_transitions}

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

    # Directly socketed fitting bodies have a centreline for flow continuity,
    # but are deliberately not emitted as a pipe segment or bounded by two
    # pipe-end ticks.  This prevents the joint from looking like a cut piece
    # of pipe between the elbow and the oblique tee.
    for joint in assembly.direct_fitting_joints:
        x1, y1 = xy(joint.start_port_id)
        x2, y2 = xy(joint.end_port_id)
        body.append(
            f'<line data-direct-fitting-joint="{escape(joint.joint_id)}" '
            f'data-start-fitting="{escape(joint.start_fitting_id)}" '
            f'data-end-fitting="{escape(joint.end_fitting_id)}" '
            f'data-dn="{joint.dn_mm}" x1="{x1:.1f}" y1="{y1:.1f}" '
            f'x2="{x2:.1f}" y2="{y2:.1f}" stroke="{BLACK}" '
            f'stroke-width="3" fill="none"/>'
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
        quantity_label = f"; {fixture.quantity} шт." if fixture.quantity > 1 else ""
        body.extend(
            (
                f'<text x="{fx:.1f}" y="{fy-68:.1f}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="9.5" font-weight="bold">'
                f'{escape(fixture.fixture_id)}</text>',
                f'<text x="{fx:.1f}" y="{fy-54:.1f}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="8.5">'
                f'{escape(_FIXTURE_LABEL[fixture.kind])}; '
                f'{_system_mark(assembly.system)} ⌀{fixture.dn_mm}'
                f'{quantity_label}</text>',
            )
        )

    # Every fixture elbow is socketed directly into its oblique wye.  The
    # collector boundaries are shifted outside the short fitting bodies, and
    # only the elbow receives a boundary on the 45-degree joint.  Therefore a
    # direct fitting connection cannot be mistaken for a straight pipe spool.
    for fixture in assembly.fixtures:
        joint = assembly.port(fixture.junction_port_id).point
        direct_joint = assembly.direct_fitting_joint(fixture.connection_joint_id)
        elbow = assembly.port(direct_joint.start_port_id).point
        connection = assembly.segment(fixture.connection_segment_ids[-1])
        vertical_start = assembly.port(connection.start_port_id).point
        wye = assembly.fitting(f"{fixture.fixture_id}_wye_45")
        upstream_segment = assembly.segment(wye.connected_segment_ids[0])
        downstream_segment = assembly.segment(wye.connected_segment_ids[1])
        upstream_id = (
            upstream_segment.start_port_id
            if upstream_segment.end_port_id == fixture.junction_port_id
            else upstream_segment.end_port_id
        )
        downstream_id = (
            downstream_segment.end_port_id
            if downstream_segment.start_port_id == fixture.junction_port_id
            else downstream_segment.start_port_id
        )
        body.append(f'<g data-floor-fitting="{escape(fixture.fixture_id)}_wye_45">')
        body.append(
            _tick_svg(
                joint,
                assembly.port(upstream_id).point,
                xy=xy,
                offset_mm=10.0,
                marker_id=f"{fixture.fixture_id}_wye_upstream",
            )
        )
        if fixture.junction_port_id not in diameter_transition_ports:
            body.append(
                _tick_svg(
                    joint,
                    assembly.port(downstream_id).point,
                    xy=xy,
                    marker_id=f"{fixture.fixture_id}_wye_downstream",
                )
            )
        body.append("</g>")

        body.append(f'<g data-floor-fitting="{escape(fixture.fixture_id)}_elbow_45">')
        body.append(
            _tick_svg(
                elbow,
                vertical_start,
                xy=xy,
                offset_mm=4.0,
                marker_id=f"{fixture.fixture_id}_elbow_inlet",
            )
        )
        body.append(
            _tick_svg(
                elbow,
                joint,
                xy=xy,
                offset_mm=2.8,
                half_length_px=4.0,
                marker_id=f"{fixture.fixture_id}_elbow_outlet_45",
            )
        )
        body.append("</g>")

    # The floor collector does not terminate in an undefined T intersection.
    # It turns through a 45-degree elbow and enters the branch of an oblique
    # 45-degree tee on the vertical riser.  The elbow keeps boundaries on both
    # legs.  The upper tee boundary is shifted beyond the direct 45-degree
    # fitting joint so its horizontal tick cannot cross the diagonal line.
    riser_elbow = assembly.port("riser_branch_elbow").point
    last_joint = assembly.port(assembly.fixtures[-1].junction_port_id).point
    riser_join = assembly.port("riser_join").point
    riser_top = assembly.port("riser_top").point
    riser_bottom = assembly.port("riser_bottom").point
    body.append('<g data-floor-fitting="riser_branch_elbow_45">')
    body.append(
        _tick_svg(
            riser_elbow,
            last_joint,
            xy=xy,
            offset_mm=4.0,
            marker_id="riser_elbow_inlet",
        )
    )
    body.append(
        _tick_svg(
            riser_elbow,
            riser_join,
            xy=xy,
            offset_mm=2.8,
            half_length_px=4.0,
            marker_id="riser_elbow_outlet_45",
        )
    )
    body.append("</g>")
    body.append('<g data-floor-fitting="riser_branch_wye_45">')
    body.append(
        _tick_svg(
            riser_join,
            riser_top,
            xy=xy,
            offset_mm=10.0,
            marker_id="riser_wye_upper",
        )
    )
    body.append(
        _tick_svg(
            riser_join,
            riser_bottom,
            xy=xy,
            offset_mm=6.0,
            marker_id="riser_wye_lower",
        )
    )
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
            f'font-family="{FONT}" font-size="9">'
            f'{_system_mark(assembly.system)} ⌀{assembly.fixtures[0].dn_mm}</text>',
        )
    )

    for group_index, annotation in enumerate(slope_annotations, start=1):
        first = assembly.segment(annotation.first_segment_id)
        last = assembly.segment(annotation.last_segment_id)
        start = assembly.port(first.start_port_id).point
        end = assembly.port(last.end_port_id).point
        body.append(
            render_inline_pipe_label(
                line_id=f"floor-branch-{group_index}",
                label=(
                    f"{_system_mark(assembly.system)} ⌀{annotation.dn_mm}"
                ),
                start=xy(start),
                end=xy(end),
                position=0.35 if annotation.dn_mm >= 100 else 0.56,
                font_size=9.5,
            )
        )
        body.append(
            _slope_sign_svg(annotation, start, end, xy=xy)
        )

    for transition in diameter_transitions:
        downstream = assembly.segment(transition.downstream_segment_id)
        body.append(
            _diameter_transition_svg(
                transition,
                assembly.port(transition.port_id).point,
                assembly.port(downstream.end_port_id).point,
                xy=xy,
            )
        )

    riser_join_x, riser_join_y = xy("riser_join")
    body.append(
        render_inline_pipe_label(
            line_id="floor-riser",
            label=(
                f"{_system_mark(assembly.system)} "
                f"⌀{assembly.segment('riser_upper').dn_mm}"
            ),
            start=xy("riser_top"),
            end=xy("riser_join"),
            position=0.48,
            font_size=9.5,
        )
    )
    collector_to_riser = assembly.segment("collector_to_riser")
    collector_start = assembly.port(collector_to_riser.start_port_id).point
    collector_end = assembly.port(collector_to_riser.end_port_id).point
    flow_x, flow_y = xy(
        DraftPoint(
            collector_start.x_mm
            + (collector_end.x_mm - collector_start.x_mm) * 0.78,
            collector_start.y_mm
            + (collector_end.y_mm - collector_start.y_mm) * 0.78,
        )
    )
    body.extend(
        (
            f'<path data-flow-direction="collector" '
            f'd="M{flow_x-8:.1f},{flow_y-5:.1f} '
            f'L{flow_x+3:.1f},{flow_y:.1f} '
            f'L{flow_x-8:.1f},{flow_y+5:.1f} Z" fill="{BLACK}"/>',
            f'<path data-flow-direction="riser" '
            f'd="M{riser_join_x-6:.1f},{riser_join_y+42:.1f} '
            f'L{riser_join_x:.1f},{riser_join_y+54:.1f} '
            f'L{riser_join_x+6:.1f},{riser_join_y+42:.1f} Z" fill="{BLACK}"/>',
            f'<text data-fitting-label="riser_branch_wye_45" '
            f'x="{riser_join_x+17:.1f}" y="{riser_join_y-14:.1f}" '
            f'font-family="{FONT}" font-size="8.5">Тр. 45°</text>',
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
    svg = "".join(body)
    convention_errors = audit_floor_rendering_conventions(assembly, svg)
    if convention_errors:
        raise ValueError(
            "invalid floor graphic conventions: "
            + "; ".join(row.message for row in convention_errors)
        )
    return svg


def audit_floor_rendering_conventions(
    assembly: WastewaterFloorAssembly,
    svg: str,
) -> tuple[DraftingConventionFinding, ...]:
    """Check GOST-style slope and diameter-change annotations in an SVG."""
    findings: list[DraftingConventionFinding] = []
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        return (
            DraftingConventionFinding(
                "invalid_svg",
                assembly.assembly_id,
                f"SVG не разобран: {exc}",
            ),
        )

    visible_text = " ".join(root.itertext())
    if "i=" in visible_text or "i =" in visible_text:
        findings.append(
            DraftingConventionFinding(
                "legacy_slope_notation",
                assembly.assembly_id,
                "уклон нельзя подписывать под трубой в виде i=; требуется "
                "знак уклона над трубопроводом",
            )
        )

    expected_slopes, expected_transitions = build_floor_graphic_annotations(
        assembly
    )
    slope_elements = {
        row.get("data-slope-marker"): row
        for row in root.iter()
        if row.get("data-slope-marker")
    }
    for expected in expected_slopes:
        element = slope_elements.get(expected.annotation_id)
        if element is None:
            findings.append(
                DraftingConventionFinding(
                    "missing_slope_sign",
                    expected.annotation_id,
                    "отсутствует нормативный знак уклона",
                )
            )
        elif element.get("data-placement") != "above":
            findings.append(
                DraftingConventionFinding(
                    "slope_not_above_pipe",
                    expected.annotation_id,
                    "знак уклона должен находиться над трубопроводом",
                )
            )
        elif (
            element.get("data-sign-shape") != "open-angle"
            or element.get("data-label-underline") != "false"
        ):
            findings.append(
                DraftingConventionFinding(
                    "invalid_slope_sign_geometry",
                    expected.annotation_id,
                    "уклон должен быть показан открытым углом без линии под текстом",
                )
            )

    transition_elements = {
        row.get("data-diameter-transition"): row
        for row in root.iter()
        if row.get("data-diameter-transition")
    }
    for expected in expected_transitions:
        element = transition_elements.get(expected.transition_id)
        if element is None:
            findings.append(
                DraftingConventionFinding(
                    "missing_diameter_transition",
                    expected.transition_id,
                    f"не показан переход DN{expected.upstream_dn_mm} -> "
                    f"DN{expected.downstream_dn_mm}",
                )
            )
        elif element.get("fill") != "none":
            findings.append(
                DraftingConventionFinding(
                    "filled_diameter_transition",
                    expected.transition_id,
                    "знак перехода диаметра должен быть незалитым треугольником",
                )
            )

    pipe_labels = {
        row.get("data-pipe-line-id"): row.get("data-inline-pipe-label")
        for row in root.iter()
        if row.get("data-pipe-line-id")
    }
    expected_pipe_labels = {
        **{
            f"floor-branch-{index}": (
                f"{_system_mark(assembly.system)} ⌀{row.dn_mm}"
            )
            for index, row in enumerate(expected_slopes, start=1)
        },
        "floor-riser": (
            f"{_system_mark(assembly.system)} "
            f"⌀{assembly.segment('riser_upper').dn_mm}"
        ),
    }
    for line_id, expected_label in expected_pipe_labels.items():
        actual_label = pipe_labels.get(line_id)
        if actual_label is None:
            findings.append(
                DraftingConventionFinding(
                    "missing_pipe_line_label",
                    line_id,
                    f"линия не обозначена как {expected_label}",
                )
            )
        elif actual_label != expected_label:
            findings.append(
                DraftingConventionFinding(
                    "incorrect_pipe_line_label",
                    line_id,
                    f"ожидалось обозначение {expected_label}, получено {actual_label}",
                )
            )
    return tuple(findings)


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
