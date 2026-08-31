"""Parametric basement module for the internal gravity K1 generator.

The module joins the accepted lower-riser turn to the building outlet.  It
stops immediately outside the foundation wall: an external manhole or an
external sewer network is not silently invented.  Project elevations remain
blank until they are supplied explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from xml.etree import ElementTree

from app.pz.wastewater_drafting import (
    BLACK,
    FONT,
    GRAY,
    DraftFitting,
    DraftPipeSegment,
    DraftPoint,
    DraftPort,
    DraftServicePath,
    WastewaterDraftAssembly,
    build_lower_turn_cleanout_assembly,
    render_inline_pipe_label,
    render_lower_turn_assembly_svg,
)
from app.pz.wastewater_revision_placement import (
    REVISION_PLACEMENT_RULE_ID,
    REVISION_PREFERRED_HEIGHT_ABOVE_FLOOR_M,
    resolve_riser_revision_placement,
)
from app.pz.wastewater_ugo import render_ugo


@dataclass(frozen=True)
class WastewaterBasementAssembly:
    """One connected internal path from the first floor to the outlet."""

    assembly_id: str
    system: str
    riser_id: str
    dn_mm: int
    outlet_dn_mm: int
    revision_height_above_floor_m: float
    first_floor_elevation_m: float
    basement_floor_elevation_m: float | None
    outlet_invert_elevation_m: float | None
    collector_slope_per_mille: float | None
    outlet_id: str
    wall_inner_x_mm: float
    wall_outer_x_mm: float
    lower_turn: WastewaterDraftAssembly
    draft: WastewaterDraftAssembly

    @property
    def missing_project_inputs(self) -> tuple[str, ...]:
        """Inputs that cannot be inferred safely from the schematic."""
        missing: list[str] = []
        if self.basement_floor_elevation_m is None:
            missing.append("basement_floor_elevation_m")
        if self.outlet_invert_elevation_m is None:
            missing.append("outlet_invert_elevation_m")
        if self.collector_slope_per_mille is None:
            missing.append("collector_slope_per_mille")
        if not self.outlet_id.strip():
            missing.append("outlet_id")
        return tuple(missing)

    @property
    def project_inputs_complete(self) -> bool:
        return not self.missing_project_inputs

    def validate(self) -> list[str]:
        errors = list(self.draft.validate())
        if self.system != "K1":
            errors.append("basement control module currently supports K1 only")
        if self.dn_mm < 100:
            errors.append("K1 basement outlet serving toilets must be at least DN100")
        if self.outlet_dn_mm < self.dn_mm:
            errors.append("outlet DN must not decrease in the direction of flow")
        try:
            resolve_riser_revision_placement(
                floor_height_m=(
                    self.first_floor_elevation_m - self.basement_floor_elevation_m
                    if self.basement_floor_elevation_m is not None
                    else 3.0
                ),
                requested_height_m=self.revision_height_above_floor_m,
            )
        except ValueError as exc:
            errors.append(f"invalid revision placement ({exc})")
        if (
            self.collector_slope_per_mille is not None
            and self.collector_slope_per_mille <= 0
        ):
            errors.append("collector slope must be positive")
        if self.wall_outer_x_mm <= self.wall_inner_x_mm:
            errors.append("foundation wall faces are reversed")
        if (
            self.basement_floor_elevation_m is not None
            and self.basement_floor_elevation_m >= self.first_floor_elevation_m
        ):
            errors.append("basement floor must be below the first floor")

        expected_flow = (
            "riser_above_revision",
            "riser_to_lower_turn",
            "riser",
            "diagonal",
            "main",
            "collector_main",
            "collector_to_sleeve",
            "sleeve_segment",
            "outlet_segment",
        )
        if self.draft.flow_segment_ids != expected_flow:
            errors.append("basement flow path is incomplete")
        try:
            sleeve_in = self.draft.port("sleeve_in").point
            sleeve_out = self.draft.port("sleeve_out").point
            outlet = self.draft.port("outlet_end").point
        except KeyError as exc:
            errors.append(str(exc))
        else:
            if abs(sleeve_in.x_mm - self.wall_inner_x_mm) > 1e-9:
                errors.append("sleeve does not begin at the inner wall face")
            if abs(sleeve_out.x_mm - self.wall_outer_x_mm) > 1e-9:
                errors.append("sleeve does not end at the outer wall face")
            if outlet.x_mm <= self.wall_outer_x_mm:
                errors.append("building outlet must extend beyond the outer wall face")

        if any(
            row.role in {"external_network", "external_manhole"}
            for row in self.draft.segments
        ):
            errors.append("external sewer elements are outside this module")
        if self.lower_turn.fitting("service_wye_45").replaces_kind != "elbow_45":
            errors.append("lower turn lost its accepted cleanout wye")
        return errors


def build_wastewater_basement_assembly(
    *,
    assembly_id: str = "К1-Подвал-01",
    riser_id: str = "К1-Ст1",
    dn_mm: int = 100,
    first_floor_elevation_m: float = 0.0,
    basement_floor_elevation_m: float | None = None,
    outlet_invert_elevation_m: float | None = None,
    collector_slope_per_mille: float | None = None,
    outlet_id: str = "К1-1",
    outlet_dn_mm: int | None = None,
    revision_height_above_floor_m: float = REVISION_PREFERRED_HEIGHT_ABOVE_FLOOR_M,
) -> WastewaterBasementAssembly:
    """Build the basement path without manufacturing project elevations."""
    if dn_mm < 100:
        raise ValueError("K1 basement outlet serving toilets must be at least DN100")
    if (
        basement_floor_elevation_m is not None
        and basement_floor_elevation_m >= first_floor_elevation_m
    ):
        raise ValueError("basement floor must be below the first floor")
    resolve_riser_revision_placement(
        floor_height_m=(
            first_floor_elevation_m - basement_floor_elevation_m
            if basement_floor_elevation_m is not None
            else 3.0
        ),
        requested_height_m=revision_height_above_floor_m,
    )
    if collector_slope_per_mille is not None and collector_slope_per_mille <= 0:
        raise ValueError("collector_slope_per_mille must be positive")
    resolved_outlet_dn_mm = dn_mm if outlet_dn_mm is None else outlet_dn_mm
    if resolved_outlet_dn_mm < dn_mm:
        raise ValueError("outlet DN must not decrease in the direction of flow")
    lower_turn = build_lower_turn_cleanout_assembly(
        assembly_id=f"{assembly_id}-НП",
        system="K1",
        dn_mm=dn_mm,
    )
    wall_inner_x_mm = 235.0
    wall_outer_x_mm = 265.0
    ports = (
        DraftPort("first_floor_connection", DraftPoint(0.0, -48.0), "hydraulic_inlet"),
        DraftPort("revision_point", DraftPoint(0.0, -30.0), "service_joint", accessible=True),
        *lower_turn.ports,
        DraftPort("collector_mid", DraftPoint(185.0, 80.0), "gravity_collector"),
        DraftPort("sleeve_in", DraftPoint(wall_inner_x_mm, 82.0), "wall_penetration_in"),
        DraftPort("sleeve_out", DraftPoint(wall_outer_x_mm, 83.5), "wall_penetration_out"),
        DraftPort("outlet_end", DraftPoint(340.0, 87.0), "internal_scope_outlet"),
    )
    segments = (
        DraftPipeSegment(
            "riser_above_revision",
            "first_floor_connection",
            "revision_point",
            dn_mm,
            "riser",
        ),
        DraftPipeSegment(
            "riser_to_lower_turn",
            "revision_point",
            "riser_in",
            dn_mm,
            "riser",
        ),
        *lower_turn.segments,
        DraftPipeSegment(
            "collector_main",
            "main_out",
            "collector_mid",
            dn_mm,
            "basement_collector",
        ),
        DraftPipeSegment(
            "collector_to_sleeve",
            "collector_mid",
            "sleeve_in",
            resolved_outlet_dn_mm,
            "basement_collector",
        ),
        DraftPipeSegment(
            "sleeve_segment",
            "sleeve_in",
            "sleeve_out",
            resolved_outlet_dn_mm,
            "wall_sleeve_crossing",
        ),
        DraftPipeSegment(
            "outlet_segment",
            "sleeve_out",
            "outlet_end",
            resolved_outlet_dn_mm,
            "building_outlet",
        ),
    )
    transition_fittings = (
        (
            DraftFitting(
                "outlet_diameter_transition",
                "diameter_transition",
                DraftPoint(185.0, 80.0),
                resolved_outlet_dn_mm,
                ("collector_main", "collector_to_sleeve"),
            ),
        )
        if resolved_outlet_dn_mm != dn_mm
        else ()
    )
    fittings = (
        DraftFitting(
            "first_floor_revision",
            "revision",
            DraftPoint(0.0, -30.0),
            dn_mm,
            ("riser_above_revision", "riser_to_lower_turn"),
        ),
        *lower_turn.fittings,
        *transition_fittings,
    )
    flow_segment_ids = (
        "riser_above_revision",
        "riser_to_lower_turn",
        *lower_turn.flow_segment_ids,
        "collector_main",
        "collector_to_sleeve",
        "sleeve_segment",
        "outlet_segment",
    )
    draft = WastewaterDraftAssembly(
        assembly_id=assembly_id,
        system="K1",
        ports=ports,
        segments=segments,
        fittings=fittings,
        flow_segment_ids=flow_segment_ids,
        service_path=DraftServicePath(
            "basement_cleanout_cable",
            "cleanout_cap",
            "service_wye_45",
            (
                "cleanout_cap",
                "wye_45",
                "main_out",
                "collector_mid",
                "sleeve_in",
                "sleeve_out",
                "outlet_end",
            ),
            (
                "main",
                "collector_main",
                "collector_to_sleeve",
                "sleeve_segment",
                "outlet_segment",
            ),
        ),
    )
    basement = WastewaterBasementAssembly(
        assembly_id=assembly_id,
        system="K1",
        riser_id=riser_id,
        dn_mm=dn_mm,
        outlet_dn_mm=resolved_outlet_dn_mm,
        revision_height_above_floor_m=revision_height_above_floor_m,
        first_floor_elevation_m=first_floor_elevation_m,
        basement_floor_elevation_m=basement_floor_elevation_m,
        outlet_invert_elevation_m=outlet_invert_elevation_m,
        collector_slope_per_mille=collector_slope_per_mille,
        outlet_id=outlet_id.strip(),
        wall_inner_x_mm=wall_inner_x_mm,
        wall_outer_x_mm=wall_outer_x_mm,
        lower_turn=lower_turn,
        draft=draft,
    )
    errors = basement.validate()
    if errors:
        raise ValueError("invalid wastewater basement assembly: " + "; ".join(errors))
    return basement


def _elevation(value: float | None) -> str:
    return "________" if value is None else f"{value:+.3f}".replace(".", ",")


def _slope_value(per_mille: float | None) -> str:
    if per_mille is None:
        return "уклон не задан"
    return f"{per_mille / 1000.0:.3f}".replace(".", ",")


def _outlet_id(value: str) -> str:
    return value if value else "________"


def _diameter_transition_svg(
    x: float,
    y: float,
    *,
    upstream_dn_mm: int,
    downstream_dn_mm: int,
) -> str:
    """Unfilled triangle at the exact point where the diameter increases."""
    return (
        f'<g data-basement-diameter-transition="true" '
        f'data-upstream-dn="{upstream_dn_mm}" '
        f'data-downstream-dn="{downstream_dn_mm}">'
        f'<path d="M{x:.1f},{y:.1f} L{x+18:.1f},{y-9:.1f} '
        f'L{x+18:.1f},{y+9:.1f} Z" fill="white" stroke="{BLACK}" '
        'stroke-width="1.5"/></g>'
    )


def audit_basement_pipe_labels(
    basement: WastewaterBasementAssembly,
    svg: str,
) -> tuple[str, ...]:
    """Require one system/DN mark on every independent basement pipe line."""
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        return (f"invalid basement SVG: {exc}",)
    system_mark = basement.system.replace("K", "К")
    expected = {
        "basement-riser": f"{system_mark} ⌀{basement.dn_mm}",
        "basement-collector-before-transition": (
            f"{system_mark} ⌀{basement.dn_mm}"
        ),
        "basement-collector-after-transition": (
            f"{system_mark} ⌀{basement.outlet_dn_mm}"
        ),
        "building-outlet": f"{system_mark} ⌀{basement.outlet_dn_mm}",
    }
    actual = {
        row.get("data-pipe-line-id"): row.get("data-inline-pipe-label")
        for row in root.iter()
        if row.get("data-pipe-line-id")
    }
    errors: list[str] = []
    for line_id, expected_label in expected.items():
        actual_label = actual.get(line_id)
        if actual_label is None:
            errors.append(f"{line_id}: missing pipe label {expected_label}")
        elif actual_label != expected_label:
            errors.append(
                f"{line_id}: expected {expected_label}, got {actual_label}"
            )
    return tuple(errors)


def build_wastewater_basement_control_svg(
    basement: WastewaterBasementAssembly,
    *,
    page_width_mm: int = 420,
    page_height_mm: int = 297,
    sheet_title: str = "Контрольный модуль подвала К1",
    sheet_subtitle: str | None = None,
    continuation_from_sheet: int | None = None,
    title_font_size: float = 30.0,
    subtitle_font_size: float = 16.0,
) -> str:
    """Render an isolated A3 basement control sheet for topology approval."""
    errors = basement.validate()
    if errors:
        raise ValueError("cannot render invalid wastewater basement: " + "; ".join(errors))

    width, height = 1800, 1273
    margin = 45
    origin_x, origin_y, scale = 580.0, 370.0, 3.4

    def xy(port_id: str) -> tuple[float, float]:
        point = basement.draft.port(port_id).point
        return origin_x + point.x_mm * scale, origin_y + point.y_mm * scale

    def segment_svg(segment_id: str) -> str:
        segment = basement.draft.segment(segment_id)
        x1, y1 = xy(segment.start_port_id)
        x2, y2 = xy(segment.end_port_id)
        return (
            f'<line data-basement-segment="{escape(segment_id)}" '
            f'data-role="{escape(segment.role)}" x1="{x1:.1f}" y1="{y1:.1f}" '
            f'x2="{x2:.1f}" y2="{y2:.1f}" stroke="{BLACK}" '
            'stroke-width="3" fill="none"/>'
        )

    first_floor_y = 300.0
    basement_floor_y = 805.0
    wall_inner_x = origin_x + basement.wall_inner_x_mm * scale
    wall_outer_x = origin_x + basement.wall_outer_x_mm * scale
    revision_x, revision_y = xy("revision_point")
    outlet_x, outlet_y = xy("outlet_end")
    sleeve_in_x, sleeve_in_y = xy("sleeve_in")
    sleeve_out_x, sleeve_out_y = xy("sleeve_out")
    slope_start_x, slope_start_y = xy("main_out")
    slope_end_x, slope_end_y = xy("sleeve_in")
    transition_x, transition_y = xy("collector_mid")
    system_mark = basement.system.replace("K", "К")
    slope_centre_x = (slope_start_x + slope_end_x) / 2
    slope_sign_y = min(slope_start_y, slope_end_y) - 38.0
    slope_apex_x = slope_centre_x + 18.0
    slope_arm_x = slope_apex_x - 10.0
    slope_status = (
        "confirmed"
        if basement.collector_slope_per_mille is not None
        else "required"
    )
    subtitle = sheet_subtitle or (
        f"{basement.riser_id} DN{basement.dn_mm}; "
        "самотечный путь до границы внутренней системы"
    )
    body: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{page_width_mm}mm" height="{page_height_mm}mm" '
        f'viewBox="0 0 {width} {height}">',
        '<defs><pattern id="basement-hatch" width="18" height="18" '
        'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="18" stroke="#777" stroke-width="2"/>'
        '</pattern></defs>',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<rect x="{margin}" y="{margin}" width="{width-2*margin}" '
        f'height="{height-2*margin}" fill="none" stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+34}" y="{margin+48}" font-family="{FONT}" '
        f'font-size="{title_font_size:g}" font-weight="bold">{escape(sheet_title)}</text>',
        f'<text x="{margin+34}" y="{margin+82}" font-family="{FONT}" '
        f'font-size="{subtitle_font_size:g}" fill="{GRAY}">{escape(subtitle)}</text>',
        # First-floor slab and basement slab are architectural context only.
        f'<line data-level="first-floor" x1="{margin+55}" y1="{first_floor_y:.1f}" '
        f'x2="{wall_inner_x:.1f}" y2="{first_floor_y:.1f}" stroke="{BLACK}" stroke-width="2"/>',
        f'<line x1="{margin+55}" y1="{first_floor_y+9:.1f}" '
        f'x2="{wall_inner_x:.1f}" y2="{first_floor_y+9:.1f}" stroke="{BLACK}" stroke-width="1"/>',
        f'<rect data-basement-slab="hatched" x="{margin+55}" y="{basement_floor_y:.1f}" '
        f'width="{wall_outer_x-margin-55:.1f}" height="52" fill="url(#basement-hatch)" '
        f'stroke="{BLACK}" stroke-width="2"/>',
        # Foundation wall and the sleeve crossing it.
        f'<rect data-foundation-wall="true" x="{wall_inner_x:.1f}" y="{first_floor_y:.1f}" '
        f'width="{wall_outer_x-wall_inner_x:.1f}" height="{basement_floor_y-first_floor_y+52:.1f}" '
        'fill="url(#basement-hatch)" stroke="black" stroke-width="2"/>',
        f'<rect data-wall-sleeve="true" x="{sleeve_in_x-8:.1f}" y="{sleeve_in_y-14:.1f}" '
        f'width="{sleeve_out_x-sleeve_in_x+16:.1f}" height="{sleeve_out_y-sleeve_in_y+28:.1f}" '
        'fill="white" stroke="black" stroke-width="2"/>',
        f'<text x="{margin+62}" y="{first_floor_y-18:.1f}" font-family="{FONT}" '
        'font-size="18" font-weight="bold">1 этаж</text>',
        f'<text x="{margin+62}" y="{first_floor_y+34:.1f}" font-family="{FONT}" '
        f'font-size="14">отм. { _elevation(basement.first_floor_elevation_m) }</text>',
        f'<text x="{margin+62}" y="{basement_floor_y-24:.1f}" font-family="{FONT}" '
        'font-size="18" font-weight="bold">Подвал / техподполье</text>',
        f'<text x="{margin+62}" y="{basement_floor_y+82:.1f}" font-family="{FONT}" '
        f'font-size="14">отм. пола { _elevation(basement.basement_floor_elevation_m) }</text>',
        segment_svg("riser_above_revision"),
        segment_svg("riser_to_lower_turn"),
        render_lower_turn_assembly_svg(
            basement.lower_turn,
            diagnostics=False,
            pipe_labels=False,
            x=origin_x,
            y=origin_y,
            scale=scale,
        ),
        segment_svg("collector_main"),
        segment_svg("collector_to_sleeve"),
        segment_svg("sleeve_segment"),
        segment_svg("outlet_segment"),
        render_inline_pipe_label(
            line_id="basement-riser",
            label=f"{system_mark} ⌀{basement.dn_mm}",
            start=xy("revision_point"),
            end=xy("riser_in"),
            position=0.52,
            font_size=12.5,
        ),
        render_inline_pipe_label(
            line_id="basement-collector-before-transition",
            label=f"{system_mark} ⌀{basement.dn_mm}",
            start=xy("main_out"),
            end=xy("collector_mid"),
            position=0.58,
            font_size=12.5,
        ),
        render_inline_pipe_label(
            line_id="basement-collector-after-transition",
            label=f"{system_mark} ⌀{basement.outlet_dn_mm}",
            start=xy("collector_mid"),
            end=xy("sleeve_in"),
            position=0.52,
            font_size=12.5,
        ),
        render_inline_pipe_label(
            line_id="building-outlet",
            label=f"{system_mark} ⌀{basement.outlet_dn_mm}",
            start=(sleeve_out_x, sleeve_out_y),
            end=(outlet_x, outlet_y),
            position=0.54,
            font_size=14.0,
        ),
        f'<g data-basement-slope="collector" data-placement="above" '
        f'data-slope-status="{slope_status}" data-label-underline="false">'
        f'<path data-slope-angle="true" d="M{slope_arm_x:.1f},{slope_sign_y-6:.1f} '
        f'L{slope_apex_x:.1f},{slope_sign_y:.1f} '
        f'L{slope_arm_x:.1f},{slope_sign_y+6:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="1.3"/>'
        f'<text x="{slope_arm_x-5:.1f}" y="{slope_sign_y+3.5:.1f}" '
        f'text-anchor="end" font-family="{FONT}" font-size="12">'
        f'{escape(_slope_value(basement.collector_slope_per_mille))}</text></g>',
        f'<g data-basement-revision="first-floor" '
        f'data-floor-reference="clean-floor" '
        f'data-height-above-floor-mm="{int(round(basement.revision_height_above_floor_m*1000))}" '
        f'data-height-rule="{REVISION_PLACEMENT_RULE_ID}">'
        f'{render_ugo("revision", revision_x, revision_y, scale=0.9, rotation=90.0)}'
        '</g>',
        f'<text x="{revision_x+36:.1f}" y="{revision_y-14:.1f}" '
        f'font-family="{FONT}" font-size="15" font-weight="bold">Ревизия DN{basement.dn_mm}</text>',
    ]

    if basement.outlet_dn_mm != basement.dn_mm:
        body.extend(
            (
                _diameter_transition_svg(
                    transition_x,
                    transition_y,
                    upstream_dn_mm=basement.dn_mm,
                    downstream_dn_mm=basement.outlet_dn_mm,
                ),
                f'<text x="{transition_x:.1f}" y="{transition_y+38:.1f}" '
                f'font-family="{FONT}" font-size="13">Переход '
                f'DN{basement.dn_mm}x{basement.outlet_dn_mm}</text>',
            )
        )

    if continuation_from_sheet is not None:
        connection_x, connection_y = xy("first_floor_connection")
        body.extend(
            (
                f'<g data-stack-basement-continuation="from-sheet-{continuation_from_sheet}">',
                f'<path d="M{connection_x-10:.1f},{connection_y-24:.1f} '
                f'L{connection_x:.1f},{connection_y-46:.1f} '
                f'L{connection_x+10:.1f},{connection_y-24:.1f} Z" fill="{BLACK}"/>',
                f'<line x1="{connection_x:.1f}" y1="{connection_y-24:.1f}" '
                f'x2="{connection_x:.1f}" y2="{connection_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="3"/>',
                f'<text x="{connection_x+24:.1f}" y="{connection_y-34:.1f}" '
                f'font-family="{FONT}" font-size="13">продолжение с листа '
                f'{continuation_from_sheet}</text>',
                '</g>',
            )
        )

    # Dimension the first-floor revision exactly as a requirement, without
    # pretending that the schematic vertical scale is a construction scale.
    dim_x = revision_x + 95.0
    body.extend(
        (
            f'<line data-revision-dimension="true" x1="{dim_x:.1f}" y1="{revision_y:.1f}" '
            f'x2="{dim_x:.1f}" y2="{first_floor_y:.1f}" stroke="{BLACK}" stroke-width="1.2"/>',
            f'<line x1="{dim_x-10:.1f}" y1="{revision_y:.1f}" '
            f'x2="{dim_x+10:.1f}" y2="{revision_y:.1f}" stroke="{BLACK}" stroke-width="1.2"/>',
            f'<line x1="{dim_x-10:.1f}" y1="{first_floor_y:.1f}" '
            f'x2="{dim_x+10:.1f}" y2="{first_floor_y:.1f}" stroke="{BLACK}" stroke-width="1.2"/>',
            f'<text x="{dim_x+14:.1f}" y="{(revision_y+first_floor_y)/2+5:.1f}" '
            f'font-family="{FONT}" font-size="13">{int(basement.revision_height_above_floor_m*1000)}</text>',
        )
    )

    # Sleeve and outlet annotations.  The outlet arrow is beyond the wall;
    # nothing is drawn after it as an unverified external sewer network.
    body.extend(
        (
            f'<path data-outlet-direction="true" d="M{outlet_x-22:.1f},{outlet_y-12:.1f} '
            f'L{outlet_x:.1f},{outlet_y:.1f} L{outlet_x-22:.1f},{outlet_y+12:.1f} Z" fill="{BLACK}"/>',
            f'<path d="M{(sleeve_in_x+sleeve_out_x)/2:.1f},{sleeve_in_y-18:.1f} '
            f'L{(sleeve_in_x+sleeve_out_x)/2:.1f},{sleeve_in_y-72:.1f} '
            f'H{wall_inner_x-145:.1f}" fill="none" stroke="{BLACK}" stroke-width="1.2"/>',
            f'<text x="{wall_inner_x-155:.1f}" y="{sleeve_in_y-78:.1f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="14">Гильза в фундаментной стене</text>',
            f'<text x="{outlet_x-12:.1f}" y="{outlet_y-30:.1f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="17" font-weight="bold">Выпуск '
            f'{escape(_outlet_id(basement.outlet_id))} DN{basement.outlet_dn_mm}</text>',
            f'<text x="{outlet_x-12:.1f}" y="{outlet_y+38:.1f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="14">отм. лотка { _elevation(basement.outlet_invert_elevation_m) }</text>',
            f'<text x="{wall_outer_x+18:.1f}" y="{first_floor_y-18:.1f}" '
            f'font-family="{FONT}" font-size="14">за пределами здания</text>',
        )
    )

    notes_y = 970.0
    body.extend(
        (
            f'<line x1="{margin+35}" y1="{notes_y-35:.1f}" x2="{width-margin-35}" '
            f'y2="{notes_y-35:.1f}" stroke="{BLACK}" stroke-width="1.4"/>',
            f'<text x="{margin+35}" y="{notes_y:.1f}" font-family="{FONT}" '
            'font-size="18" font-weight="bold">Что проверяет модуль</text>',
            f'<text x="{margin+35}" y="{notes_y+34:.1f}" font-family="{FONT}" font-size="14">'
            '1. Непрерывный самотечный путь: стояк - нижний поворот - лежак - гильза - выпуск.</text>',
            f'<text x="{margin+35}" y="{notes_y+64:.1f}" font-family="{FONT}" font-size="14">'
            '2. Нижний поворот использует отвод 45° и косой тройник 45° с доступным заглушённым концом.</text>',
            f'<text x="{margin+35}" y="{notes_y+94:.1f}" font-family="{FONT}" font-size="14">'
            '3. Выпуск проходит сквозь гильзу и заканчивается снаружи; колодец и наружная сеть не выдуманы.</text>',
            f'<text x="{margin+35}" y="{notes_y+124:.1f}" font-family="{FONT}" font-size="14">'
            '4. Пустые отметки и уклон должны быть заполнены исходными данными проекта до включения листа в ПД.</text>',
            f'<text x="{margin+35}" y="{height-margin-24:.1f}" font-family="{FONT}" '
            f'font-size="12" fill="{GRAY}">Контрольный лист генератора; графический язык - приложение В '
            'ГОСТ Р 21.620-2023. Не входит в комплект ПД.</text>',
            '</svg>',
        )
    )
    svg = "".join(body)
    label_errors = audit_basement_pipe_labels(basement, svg)
    if label_errors:
        raise ValueError(
            "invalid basement pipe labeling: " + "; ".join(label_errors)
        )
    return svg


def generate_wastewater_basement_control_pdf(
    output_path: str,
    *,
    riser_id: str = "К1-Ст1",
    dn_mm: int = 100,
    first_floor_elevation_m: float = 0.0,
    basement_floor_elevation_m: float | None = None,
    outlet_invert_elevation_m: float | None = None,
    collector_slope_per_mille: float | None = None,
    outlet_id: str = "К1-1",
    outlet_dn_mm: int | None = None,
) -> str:
    """Write the isolated vector A3 basement approval sheet."""
    import cairosvg

    basement = build_wastewater_basement_assembly(
        riser_id=riser_id,
        dn_mm=dn_mm,
        first_floor_elevation_m=first_floor_elevation_m,
        basement_floor_elevation_m=basement_floor_elevation_m,
        outlet_invert_elevation_m=outlet_invert_elevation_m,
        collector_slope_per_mille=collector_slope_per_mille,
        outlet_id=outlet_id,
        outlet_dn_mm=outlet_dn_mm,
    )
    svg = build_wastewater_basement_control_svg(basement)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=str(path))
    return str(path)
