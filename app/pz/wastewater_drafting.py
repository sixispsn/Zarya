"""Reusable drafting primitives for the parametric wastewater generator.

The calculation topology answers where sewage flows.  This module adds a
separate installation graph: real pipe segments, fitting ports and service
paths that can later be laid out on a GOST drawing.  The first supported
assembly is the lower riser turn discussed in ``логика1.pdf`` and reconciled
with SP 30.13330.2020, 18.4: two 45-degree elbows form the turn, followed by a
45-degree wye whose unused branch is capped as the cleanout access.

No project element registry is reconstructed here.  The builder produces a
deterministic *proposed assembly* from explicit parameters.  A project may
accept it, replace it with a revision-only solution or keep it pending.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import acos, atan2, ceil, degrees, hypot
from pathlib import Path
BLACK = "#000"
GRAY = "#555"
SERVICE = "#7650b8"
FONT = "osifont"


def render_inline_pipe_label(
    *,
    line_id: str,
    label: str,
    start: tuple[float, float],
    end: tuple[float, float],
    position: float = 0.5,
    font_size: float = 10.0,
    padding: float = 4.0,
) -> str:
    """Mask a pipe centreline and place its system/DN mark in the gap.

    The text follows the pipe axis and stays readable from the bottom or the
    right.  This is the reusable graphic primitive used for GOST-style marks
    such as ``К1 ⌀100`` and ``К2 ⌀150``.
    """
    if not 0.0 < position < 1.0:
        raise ValueError("inline pipe label position must be between 0 and 1")
    x1, y1 = start
    x2, y2 = end
    if hypot(x2 - x1, y2 - y1) <= 1e-9:
        raise ValueError("inline pipe label needs a non-zero pipe line")
    centre_x = x1 + (x2 - x1) * position
    centre_y = y1 + (y2 - y1) * position
    angle = degrees(atan2(y2 - y1, x2 - x1))
    if angle > 90.0:
        angle -= 180.0
    elif angle <= -90.0:
        angle += 180.0
    text_width = max(font_size * 2.6, len(label) * font_size * 0.56)
    mask_width = text_width + 2.0 * padding
    mask_height = font_size * 1.55
    label_parts = label.split("⌀", 1)
    if len(label_parts) == 2:
        # ``osifont`` embedded by CairoSVG does not contain U+2300.  A text
        # fallback therefore turns the diameter mark into an empty square in
        # macOS Preview.  Draw the sign as vector geometry so it remains
        # identical in SVG, browser preview and the exported PDF.
        prefix = label_parts[0].rstrip()
        suffix = label_parts[1].lstrip()
        prefix_width = len(prefix) * font_size * 0.56
        suffix_width = len(suffix) * font_size * 0.56
        sign_width = font_size * 0.82
        gap = font_size * 0.16
        content_width = prefix_width + suffix_width + sign_width + 2.0 * gap
        cursor = -content_width / 2.0
        baseline = font_size * 0.34
        sign_cx = cursor + prefix_width + gap + sign_width / 2.0
        sign_cy = -font_size * 0.08
        sign_radius = font_size * 0.29
        sign_slash = font_size * 0.39
        visible_label = "".join((
            f'<text x="{cursor:.2f}" y="{baseline:.1f}" text-anchor="start" '
            f'font-family="{FONT}" font-size="{font_size:g}">{escape(prefix)}</text>',
            f'<g data-vector-diameter-sign="true" aria-label="diameter">'
            f'<circle cx="{sign_cx:.2f}" cy="{sign_cy:.2f}" r="{sign_radius:.2f}" '
            f'fill="none" stroke="{BLACK}" stroke-width="{font_size*0.085:.2f}"/>'
            f'<line x1="{sign_cx-sign_slash:.2f}" y1="{sign_cy+sign_slash:.2f}" '
            f'x2="{sign_cx+sign_slash:.2f}" y2="{sign_cy-sign_slash:.2f}" '
            f'stroke="{BLACK}" stroke-width="{font_size*0.085:.2f}"/></g>',
            f'<text x="{sign_cx+sign_width/2.0+gap:.2f}" y="{baseline:.1f}" '
            f'text-anchor="start" font-family="{FONT}" font-size="{font_size:g}">'
            f'{escape(suffix)}</text>',
        ))
    else:
        visible_label = (
            f'<text x="0" y="{font_size*0.34:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="{font_size:g}">'
            f'{escape(label)}</text>'
        )
    return "".join(
        (
            f'<g data-inline-pipe-label="{escape(label)}" '
            f'data-pipe-line-id="{escape(line_id)}" '
            f'transform="translate({centre_x:.1f} {centre_y:.1f}) '
            f'rotate({angle:.2f})">',
            f'<rect data-pipe-label-mask="{escape(line_id)}" '
            f'x="{-mask_width/2:.1f}" y="{-mask_height/2:.1f}" '
            f'width="{mask_width:.1f}" height="{mask_height:.1f}" '
            'fill="white"/>',
            visible_label,
            '</g>',
        )
    )


def plan_repeated_inline_pipe_label_positions(
    *,
    label: str,
    start: tuple[float, float],
    end: tuple[float, float],
    max_spacing: float = 240.0,
    font_size: float = 10.0,
    padding: float = 4.0,
    end_clearance: float = 10.0,
    fitting_points: tuple[tuple[float, float], ...] = (),
    fitting_clearance: float = 14.0,
) -> tuple[float, ...]:
    """Plan repeated system/DN marks on clear portions of one pipe line.

    Positions are returned as fractions of the line length.  The text mask is
    kept clear of both line ends and every supplied fitting point.  A fitting
    may be a tee, cross, wye, transition, cleanout or any other node that must
    remain graphically continuous.  Long clear intervals receive several
    marks so that adjacent centres are no farther apart than ``max_spacing``.
    """
    if max_spacing <= 0:
        raise ValueError("inline pipe label spacing must be positive")
    if min(font_size, padding, end_clearance, fitting_clearance) < 0:
        raise ValueError("inline pipe label dimensions cannot be negative")
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = hypot(dx, dy)
    if length <= 1e-9:
        raise ValueError("inline pipe label needs a non-zero pipe line")

    text_width = max(font_size * 2.6, len(label) * font_size * 0.56)
    half_mask = (text_width + 2.0 * padding) / 2.0
    edge = half_mask + end_clearance
    if length <= 2.0 * edge:
        return ()

    # Intervals contain admissible distances of label centres from ``start``.
    free: list[tuple[float, float]] = [(edge, length - edge)]
    ux, uy = dx / length, dy / length
    fitting_zone = half_mask + fitting_clearance
    for point_x, point_y in fitting_points:
        offset_x, offset_y = point_x - x1, point_y - y1
        along = offset_x * ux + offset_y * uy
        perpendicular = abs(offset_x * uy - offset_y * ux)
        if not 0.0 < along < length or perpendicular > fitting_clearance:
            continue
        blocked_start = along - fitting_zone
        blocked_end = along + fitting_zone
        next_free: list[tuple[float, float]] = []
        for interval_start, interval_end in free:
            if blocked_end <= interval_start or blocked_start >= interval_end:
                next_free.append((interval_start, interval_end))
                continue
            if blocked_start > interval_start:
                next_free.append((interval_start, blocked_start))
            if blocked_end < interval_end:
                next_free.append((blocked_end, interval_end))
        free = next_free

    clear_span = length - 2.0 * edge
    desired_count = max(1, ceil(clear_span / max_spacing))
    target_step = clear_span / desired_count
    targets = (
        edge + (index + 0.5) * target_step
        for index in range(desired_count)
    )
    distances: list[float] = []
    minimum_separation = 2.0 * half_mask + 2.0
    for target in targets:
        choices = [
            max(interval_start, min(target, interval_end))
            for interval_start, interval_end in free
            if interval_end >= interval_start
        ]
        choices.sort(key=lambda candidate: abs(candidate - target))
        selected = next(
            (
                candidate for candidate in choices
                if all(
                    abs(candidate - previous) >= minimum_separation
                    for previous in distances
                )
            ),
            None,
        )
        if selected is not None:
            distances.append(selected)
    distances.sort()
    return tuple(distance / length for distance in distances)


def render_repeated_inline_pipe_labels(
    *,
    line_id: str,
    label: str,
    start: tuple[float, float],
    end: tuple[float, float],
    max_spacing: float = 240.0,
    font_size: float = 10.0,
    padding: float = 4.0,
    end_clearance: float = 10.0,
    fitting_points: tuple[tuple[float, float], ...] = (),
    fitting_clearance: float = 14.0,
) -> str:
    """Break a clear pipe line periodically and repeat its system/DN mark."""
    positions = plan_repeated_inline_pipe_label_positions(
        label=label,
        start=start,
        end=end,
        max_spacing=max_spacing,
        font_size=font_size,
        padding=padding,
        end_clearance=end_clearance,
        fitting_points=fitting_points,
        fitting_clearance=fitting_clearance,
    )
    if not positions:
        return ""
    return "".join((
        f'<g data-repeated-pipe-labels="{escape(line_id)}" '
        f'data-label-count="{len(positions)}" '
        f'data-label-max-spacing="{max_spacing:g}">',
        *(render_inline_pipe_label(
            line_id=line_id,
            label=label,
            start=start,
            end=end,
            position=position,
            font_size=font_size,
            padding=padding,
        ) for position in positions),
        '</g>',
    ))


@dataclass(frozen=True)
class DraftPoint:
    """Point in millimetres in a local drafting coordinate system."""

    x_mm: float
    y_mm: float

    def vector_to(self, other: "DraftPoint") -> tuple[float, float]:
        return other.x_mm - self.x_mm, other.y_mm - self.y_mm

    def distance_to(self, other: "DraftPoint") -> float:
        dx, dy = self.vector_to(other)
        return hypot(dx, dy)


@dataclass(frozen=True)
class DraftPort:
    port_id: str
    point: DraftPoint
    role: str
    accessible: bool = False


@dataclass(frozen=True)
class DraftPipeSegment:
    segment_id: str
    start_port_id: str
    end_port_id: str
    dn_mm: int
    role: str
    carries_flow: bool = True


@dataclass(frozen=True)
class DraftFitting:
    fitting_id: str
    kind: str
    point: DraftPoint
    dn_mm: int
    connected_segment_ids: tuple[str, ...]
    replaces_kind: str = ""


@dataclass(frozen=True)
class DraftServicePath:
    path_id: str
    access_port_id: str
    target_fitting_id: str
    point_ids: tuple[str, ...]
    serviced_segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class WastewaterDraftAssembly:
    assembly_id: str
    system: str
    ports: tuple[DraftPort, ...]
    segments: tuple[DraftPipeSegment, ...]
    fittings: tuple[DraftFitting, ...]
    flow_segment_ids: tuple[str, ...]
    service_path: DraftServicePath

    def port(self, port_id: str) -> DraftPort:
        try:
            return next(row for row in self.ports if row.port_id == port_id)
        except StopIteration as exc:
            raise KeyError(f"unknown draft port: {port_id}") from exc

    def segment(self, segment_id: str) -> DraftPipeSegment:
        try:
            return next(row for row in self.segments if row.segment_id == segment_id)
        except StopIteration as exc:
            raise KeyError(f"unknown draft segment: {segment_id}") from exc

    def fitting(self, fitting_id: str) -> DraftFitting:
        try:
            return next(row for row in self.fittings if row.fitting_id == fitting_id)
        except StopIteration as exc:
            raise KeyError(f"unknown draft fitting: {fitting_id}") from exc

    def validate(self) -> list[str]:
        """Validate hydraulic continuity and the physical cleanout route."""
        errors: list[str] = []
        port_ids = [row.port_id for row in self.ports]
        segment_ids = [row.segment_id for row in self.segments]
        fitting_ids = [row.fitting_id for row in self.fittings]
        for label, values in (
            ("port", port_ids),
            ("segment", segment_ids),
            ("fitting", fitting_ids),
        ):
            duplicates = sorted({value for value in values if values.count(value) > 1})
            if duplicates:
                errors.append(f"duplicate {label} IDs: {', '.join(duplicates)}")

        known_ports = set(port_ids)
        for segment in self.segments:
            for port_id in (segment.start_port_id, segment.end_port_id):
                if port_id not in known_ports:
                    errors.append(
                        f"{segment.segment_id}: unknown endpoint port {port_id}"
                    )
            if segment.dn_mm <= 0:
                errors.append(f"{segment.segment_id}: DN must be positive")

        known_segments = set(segment_ids)
        for fitting in self.fittings:
            missing = set(fitting.connected_segment_ids) - known_segments
            if missing:
                errors.append(
                    f"{fitting.fitting_id}: unknown segments {', '.join(sorted(missing))}"
                )

        try:
            flow = [self.segment(row) for row in self.flow_segment_ids]
        except KeyError as exc:
            errors.append(str(exc))
            flow = []
        for upstream, downstream in zip(flow, flow[1:]):
            if upstream.end_port_id != downstream.start_port_id:
                errors.append(
                    f"flow discontinuity: {upstream.segment_id} -> "
                    f"{downstream.segment_id}"
                )
        for segment in flow:
            if not segment.carries_flow:
                errors.append(f"{segment.segment_id}: service segment is in flow path")
            if (
                segment.start_port_id in known_ports
                and segment.end_port_id in known_ports
                and self.port(segment.end_port_id).point.y_mm
                < self.port(segment.start_port_id).point.y_mm - 1e-9
            ):
                errors.append(f"{segment.segment_id}: gravity path rises")

        path = self.service_path
        try:
            access = self.port(path.access_port_id)
            target = self.fitting(path.target_fitting_id)
        except KeyError as exc:
            errors.append(str(exc))
        else:
            if not access.accessible:
                errors.append(f"{path.access_port_id}: cleanout access is not accessible")
            if not path.point_ids or path.point_ids[0] != path.access_port_id:
                errors.append(f"{path.path_id}: cable path must start at cleanout cap")
            if target.point not in [
                self.port(port_id).point
                for port_id in path.point_ids
                if port_id in known_ports
            ]:
                errors.append(f"{path.path_id}: cable path misses target fitting")
            missing = set(path.serviced_segment_ids) - known_segments
            if missing:
                errors.append(
                    f"{path.path_id}: unknown serviced segments "
                    f"{', '.join(sorted(missing))}"
                )

        # The capped branch of the service wye must enter the downstream main
        # at no more than 45 degrees.  The wye is installed after the two
        # mandatory 45-degree elbows of the lower riser turn (SP 30, 18.4),
        # so it no longer substitutes either elbow.
        try:
            access_segment = next(
                row for row in self.segments if row.role == "cleanout_access"
            )
            downstream = next(row for row in self.segments if row.role == "main")
            access_start = self.port(access_segment.start_port_id).point
            access_end = self.port(access_segment.end_port_id).point
            downstream_start = self.port(downstream.start_port_id).point
            downstream_end = self.port(downstream.end_port_id).point
            ax, ay = access_start.vector_to(access_end)
            dx, dy = downstream_start.vector_to(downstream_end)
            length = hypot(ax, ay) * hypot(dx, dy)
            cosine = (ax * dx + ay * dy) / length if length > 1e-12 else -1.0
            approach_angle = degrees(acos(max(-1.0, min(1.0, cosine))))
            if approach_angle > 45.0 + 1e-6:
                errors.append(
                    "cleanout approach angle to downstream main exceeds 45 degrees"
                )
        except StopIteration:
            errors.append("assembly needs one cleanout access and one main segment")

        return errors


def _angle_degrees(a: DraftPoint, vertex: DraftPoint, b: DraftPoint) -> float:
    vx1, vy1 = vertex.vector_to(a)
    vx2, vy2 = vertex.vector_to(b)
    length = hypot(vx1, vy1) * hypot(vx2, vy2)
    if length <= 1e-12:
        return 0.0
    cosine = max(-1.0, min(1.0, (vx1 * vx2 + vy1 * vy2) / length))
    return degrees(acos(cosine))


def build_lower_turn_cleanout_assembly(
    *,
    assembly_id: str = "К1-Узел-НП1",
    system: str = "K1",
    dn_mm: int = 100,
) -> WastewaterDraftAssembly:
    """Build the first parametric installation node of the sewer generator.

    Flow moves from the vertical riser through two 45-degree elbows into a
    horizontal leg, as required by SP 30.13330.2020, 18.4.  A separate
    45-degree wye then adds an accessible capped branch for cleaning the
    downstream main without substituting either elbow.
    """
    if system not in {"K1", "K2", "K3"}:
        raise ValueError("system must be K1, K2 or K3")
    if dn_mm <= 0:
        raise ValueError("dn_mm must be positive")

    inlet = DraftPoint(0.0, 0.0)
    elbow = DraftPoint(0.0, 38.0)
    second_elbow = DraftPoint(38.0, 76.0)
    wye = DraftPoint(70.0, 76.0)
    outlet = DraftPoint(144.0, 76.0)
    cleanout_cap = DraftPoint(48.0, 54.0)
    ports = (
        DraftPort("riser_in", inlet, "hydraulic_inlet"),
        DraftPort("elbow_45", elbow, "flow_joint"),
        DraftPort("elbow_45_2", second_elbow, "flow_joint"),
        DraftPort("wye_45", wye, "flow_and_service_joint"),
        DraftPort("main_out", outlet, "hydraulic_outlet"),
        DraftPort("cleanout_cap", cleanout_cap, "service_access", accessible=True),
    )
    segments = (
        DraftPipeSegment("riser", "riser_in", "elbow_45", dn_mm, "riser"),
        DraftPipeSegment(
            "diagonal", "elbow_45", "elbow_45_2", dn_mm, "diagonal"
        ),
        DraftPipeSegment(
            "turn_out", "elbow_45_2", "wye_45", dn_mm, "horizontal_turn_out"
        ),
        DraftPipeSegment("main", "wye_45", "main_out", dn_mm, "main"),
        DraftPipeSegment(
            "cleanout_access",
            "cleanout_cap",
            "wye_45",
            dn_mm,
            "cleanout_access",
            carries_flow=False,
        ),
    )
    fittings = (
        DraftFitting(
            "lower_elbow_45_1",
            "elbow_45",
            elbow,
            dn_mm,
            ("riser", "diagonal"),
        ),
        DraftFitting(
            "lower_elbow_45_2",
            "elbow_45",
            second_elbow,
            dn_mm,
            ("diagonal", "turn_out"),
        ),
        DraftFitting(
            "service_wye_45",
            "wye_45_cleanout",
            wye,
            dn_mm,
            ("turn_out", "main", "cleanout_access"),
        ),
        DraftFitting(
            "cleanout_cap_fitting",
            "cap",
            cleanout_cap,
            dn_mm,
            ("cleanout_access",),
        ),
    )
    assembly = WastewaterDraftAssembly(
        assembly_id=assembly_id,
        system=system,
        ports=ports,
        segments=segments,
        fittings=fittings,
        flow_segment_ids=("riser", "diagonal", "turn_out", "main"),
        service_path=DraftServicePath(
            "cleanout_cable",
            "cleanout_cap",
            "service_wye_45",
            ("cleanout_cap", "wye_45", "main_out"),
            ("main",),
        ),
    )
    errors = assembly.validate()
    if errors:
        raise ValueError("invalid lower turn assembly: " + "; ".join(errors))

    # Explicit geometry guard: both changes of direction are 45 degrees.
    first_change = 180.0 - _angle_degrees(inlet, elbow, second_elbow)
    second_change = 180.0 - _angle_degrees(elbow, second_elbow, wye)
    if abs(first_change - 45.0) > 1e-6 or abs(second_change - 45.0) > 1e-6:
        raise ValueError("lower turn geometry must contain two 45-degree changes")
    return assembly


def _system_mark(system: str) -> str:
    return {"K1": "К1", "K2": "К2", "K3": "К3"}.get(system, system)


def render_lower_turn_assembly_svg(
    assembly: WastewaterDraftAssembly,
    *,
    diagnostics: bool = False,
    pipe_labels: bool = True,
    annotations: bool = True,
    flow_direction: bool = True,
    visible_segment_ids: tuple[str, ...] | None = None,
    x: float = 0.0,
    y: float = 0.0,
    scale: float = 5.0,
    pipe_width: float = 3.0,
) -> str:
    """Render one semantic assembly without inventing extra pipework."""
    errors = assembly.validate()
    if errors:
        raise ValueError("cannot render invalid assembly: " + "; ".join(errors))

    def xy(port_id: str) -> tuple[float, float]:
        point = assembly.port(port_id).point
        return x + point.x_mm * scale, y + point.y_mm * scale

    def line(a: str, b: str, width: float = 3.0, color: str = BLACK, dash: str = "") -> str:
        x1, y1 = xy(a)
        x2, y2 = xy(b)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        return (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
            f'y2="{y2:.1f}" fill="none" stroke="{color}" '
            f'stroke-width="{width:g}"{dash_attr}/>'
        )

    body: list[str] = [
        f'<g data-draft-assembly="{escape(assembly.assembly_id)}" '
        f'data-system="{escape(assembly.system)}" '
        'data-lower-connection="elbow-wye-cleanout" '
        'data-accessible-capped-end="true">'
    ]
    for segment in assembly.segments:
        if visible_segment_ids is not None and segment.segment_id not in visible_segment_ids:
            continue
        body.append(
            f'<g data-draft-segment="{escape(segment.segment_id)}" '
            f'data-role="{escape(segment.role)}" '
            f'data-dn="{segment.dn_mm}" '
            f'data-carries-flow="{str(segment.carries_flow).lower()}">'
            f'{line(segment.start_port_id, segment.end_port_id, pipe_width)}</g>'
        )

    # Fitting limits: small perpendicular strokes at the physical ends of each
    # manufactured fitting.  They are deliberately short to avoid the false
    # large X that appeared in the former full-sheet renderer.
    elbow_x, elbow_y = xy("elbow_45")
    elbow_2_x, elbow_2_y = xy("elbow_45_2")
    wye_x, wye_y = xy("wye_45")
    cap_x, cap_y = xy("cleanout_cap")
    tick = 6.0
    diagonal_offset = 11.0
    body.extend((
        f'<path data-fitting="lower_elbow_45_1" '
        f'd="M{elbow_x-tick:.1f},{elbow_y-10:.1f} '
        f'H{elbow_x+tick:.1f} '
        f'M{elbow_x+diagonal_offset-tick:.1f},'
        f'{elbow_y+diagonal_offset+tick:.1f} '
        f'L{elbow_x+diagonal_offset+tick:.1f},'
        f'{elbow_y+diagonal_offset-tick:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="2.2"/>',
        f'<path data-fitting="lower_elbow_45_2" '
        f'd="M{elbow_2_x-diagonal_offset-tick:.1f},'
        f'{elbow_2_y-diagonal_offset+tick:.1f} '
        f'L{elbow_2_x-diagonal_offset+tick:.1f},'
        f'{elbow_2_y-diagonal_offset-tick:.1f} '
        f'M{elbow_2_x+10:.1f},{elbow_2_y-tick:.1f} '
        f'V{elbow_2_y+tick:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="2.2"/>',
        f'<path data-fitting="service_wye_45" '
        f'd="M{wye_x-diagonal_offset-tick:.1f},'
        f'{wye_y-diagonal_offset+tick:.1f} '
        f'L{wye_x-diagonal_offset+tick:.1f},'
        f'{wye_y-diagonal_offset-tick:.1f} '
        f'M{wye_x+10:.1f},{wye_y-tick:.1f} '
        f'V{wye_y+tick:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="2.2"/>',
        f'<path data-fitting="cleanout_cap_fitting" '
        f'd="M{cap_x-tick:.1f},{cap_y+tick:.1f} '
        f'L{cap_x+tick:.1f},{cap_y-tick:.1f} '
        f'M{cap_x-tick+3.2:.1f},{cap_y+tick+3.2:.1f} '
        f'L{cap_x+tick+3.2:.1f},{cap_y-tick+3.2:.1f}" '
        f'fill="none" stroke="{BLACK}" stroke-width="2.4"/>',
    ))

    # Flow direction is a filled triangle in the pipe, per the adopted UGO.
    if flow_direction:
        flow_x = (wye_x + xy("main_out")[0]) / 2
        body.append(
            f'<path data-flow-direction="downstream" '
            f'd="M{flow_x-10:.1f},{wye_y-7:.1f} '
            f'L{flow_x+2:.1f},{wye_y:.1f} L{flow_x-10:.1f},{wye_y+7:.1f} Z" '
            f'fill="{BLACK}"/>'
        )
    if diagnostics:
        service_points = [xy(port_id) for port_id in assembly.service_path.point_ids]
        path_d = " ".join(
            ("M" if index == 0 else "L") + f"{px:.1f},{py:.1f}"
            for index, (px, py) in enumerate(service_points)
        )
        body.append(
            f'<path data-service-path="{escape(assembly.service_path.path_id)}" '
            f'd="{path_d}" fill="none" stroke="{SERVICE}" stroke-width="5" '
            f'stroke-dasharray="12 8" opacity="0.82"/>'
        )

    system = _system_mark(assembly.system)
    dn = assembly.segment("main").dn_mm
    riser_start = xy("riser_in")
    riser_end = xy("elbow_45")
    main_start = xy("wye_45")
    main_end = xy("main_out")
    body.extend((
        *(
            (
                render_inline_pipe_label(
                    line_id=f"{assembly.assembly_id}:riser",
                    label=f"{system} ⌀{dn}",
                    start=riser_start,
                    end=riser_end,
                    position=0.42,
                    font_size=11.5,
                ),
                render_inline_pipe_label(
                    line_id=f"{assembly.assembly_id}:main",
                    label=f"{system} ⌀{dn}",
                    start=main_start,
                    end=main_end,
                    position=0.72,
                    font_size=11.5,
                ),
            )
            if pipe_labels
            else ()
        ),
        *(
            (
                f'<text x="{(elbow_x+elbow_2_x)/2:.1f}" y="{wye_y+72:.1f}" text-anchor="middle" '
                f'font-family="{FONT}" font-size="14">2 отвода 45° DN{dn}</text>',
                f'<text x="{wye_x+45:.1f}" y="{wye_y-38:.1f}" text-anchor="start" '
                f'font-family="{FONT}" font-size="14">Косой тройник 45° DN{dn}</text>',
                f'<path d="M{cap_x:.1f},{cap_y:.1f} L{cap_x+42:.1f},{cap_y-48:.1f} '
                f'H{cap_x+180:.1f}" fill="none" stroke="{BLACK}" stroke-width="1.3"/>',
                f'<text x="{cap_x+50:.1f}" y="{cap_y-56:.1f}" text-anchor="start" '
                f'font-family="{FONT}" font-size="15" font-weight="bold">Прочистка</text>',
                f'<text x="{cap_x+50:.1f}" y="{cap_y-34:.1f}" text-anchor="start" '
                f'font-family="{FONT}" font-size="11.5">заглушённый конец; DN{dn}</text>',
            )
            if annotations
            else ()
        ),
    ))
    if diagnostics:
        body.extend((
            f'<text x="{wye_x+40:.1f}" y="{wye_y+42:.1f}" text-anchor="start" '
            f'font-family="{FONT}" font-size="11.5" fill="{SERVICE}">'
            'маршрут троса:</text>',
            f'<text x="{wye_x+40:.1f}" y="{wye_y+59:.1f}" text-anchor="start" '
            f'font-family="{FONT}" font-size="11.5" fill="{SERVICE}">'
            'доступ - тройник - магистраль</text>',
        ))
    body.append("</g>")
    return "".join(body)


def build_lower_turn_control_sheet_svg(
    assembly: WastewaterDraftAssembly,
) -> str:
    """A4 landscape approval sheet for the first generator component."""
    width, height = 1123, 794
    margin = 34
    body = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="1122.519685" height="793.700787" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<rect x="{margin}" y="{margin}" width="{width-2*margin}" '
        f'height="{height-2*margin}" fill="none" stroke="{BLACK}" stroke-width="2"/>',
        f'<text x="{margin+24}" y="{margin+38}" font-family="{FONT}" '
        'font-size="22" font-weight="bold">Контрольный узел 01. Нижний поворот стояка с прочисткой</text>',
        f'<text x="{margin+24}" y="{margin+62}" font-family="{FONT}" '
        f'font-size="12" fill="{GRAY}">Монтажная логика: логика1.pdf; оформление - '
        'по графическому языку приложения В ГОСТ Р 21.620-2023</text>',
        f'<line x1="{width/2:.1f}" y1="{margin+88}" x2="{width/2:.1f}" '
        f'y2="{height-margin-86}" stroke="{GRAY}" stroke-width="1"/>',
        f'<text x="{margin+24}" y="{margin+104}" font-family="{FONT}" '
        'font-size="16" font-weight="bold">Монтажная геометрия</text>',
        f'<text x="{width/2+24:.1f}" y="{margin+104}" font-family="{FONT}" '
        'font-size="16" font-weight="bold">Контроль достижимости</text>',
        render_lower_turn_assembly_svg(
            assembly,
            diagnostics=False,
            pipe_labels=False,
            x=150,
            y=170,
            scale=1.9,
        ),
        render_lower_turn_assembly_svg(
            assembly,
            diagnostics=True,
            pipe_labels=False,
            x=670,
            y=170,
            scale=1.9,
        ),
    ]
    notes_y = height - margin - 70
    body.extend((
        f'<line x1="{margin}" y1="{notes_y-28}" x2="{width-margin}" '
        f'y2="{notes_y-28}" stroke="{BLACK}" stroke-width="1.2"/>',
        f'<text x="{margin+16}" y="{notes_y}" font-family="{FONT}" '
        'font-size="12">1. Нижний поворот выполнен двумя отводами 45°; '
        'косой тройник с заглушкой установлен далее отдельным узлом.</text>',
        f'<text x="{margin+16}" y="{notes_y+20}" font-family="{FONT}" '
        'font-size="12">2. Доступ присоединён косым тройником под 45°; '
        'трос входит в магистраль по направлению стока.</text>',
        f'<text x="{margin+16}" y="{notes_y+40}" font-family="{FONT}" '
        f'font-size="12">3. Фиолетовый маршрут является диагностическим слоем '
        'и не выводится на нормативный лист.</text>',
        "</svg>",
    ))
    return "".join(body)


def generate_lower_turn_control_pdf(
    output_path: str,
    *,
    system: str = "K1",
    dn_mm: int = 100,
) -> str:
    """Write the approval sheet as a vector A4 landscape PDF."""
    import cairosvg

    assembly = build_lower_turn_cleanout_assembly(system=system, dn_mm=dn_mm)
    svg = build_lower_turn_control_sheet_svg(assembly)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(
        bytestring=svg.encode("utf-8"),
        write_to=str(path),
    )
    return str(path)
