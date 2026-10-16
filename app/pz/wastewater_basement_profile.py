"""Elevation-aware draft view of the existing K1 basement installation node.

This is an explicit opt-in preview, not a release adapter: a proposed outlet
elevation and schematic DN never become confirmed pipes, lengths or flows.
The lower fitting/service topology comes from wastewater_basement_drafting.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import isfinite
from pathlib import Path
import os
import tempfile
from xml.etree import ElementTree

from app.intake.request_dto import IOS2Request
from app.pz.drafting_font import DRAFTING_FONT_FAMILY, ensure_drafting_font_registered
from app.pz.drawing_sheet_style import DrawingSheetStyle, FittingGraphicSize
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderRequest
from app.pz.wastewater_basement_drafting import build_wastewater_basement_assembly
from app.pz.wastewater_drafting import render_inline_pipe_label, render_lower_turn_assembly_svg
from app.pz.wastewater_ugo import REVISION_CENTRE_ANCHOR, render_ugo


STYLE = DrawingSheetStyle(units_per_mm=1)


@dataclass(frozen=True)
class BasementProfileInput:
    first_floor_m: float
    basement_floor_m: float
    clear_height_m: float
    ground_m: float
    frost_depth_m: float
    manhole_cover_m: float | None
    proposed_invert_m: float
    proposed_invert_basis: str
    preview_dn_mm: int

    @property
    def ceiling_m(self) -> float:
        return self.basement_floor_m + self.clear_height_m

    @property
    def frost_level_m(self) -> float:
        return self.ground_m - self.frost_depth_m

    @property
    def release_ready(self) -> bool:
        # There is no supported path from this proposal into a sealed release.
        return False

    def validate(self) -> None:
        values = (self.first_floor_m, self.basement_floor_m, self.clear_height_m,
                  self.ground_m, self.frost_depth_m, self.proposed_invert_m)
        if not all(isfinite(value) for value in values):
            raise ValueError("profile elevations and dimensions must be finite")
        if self.manhole_cover_m is not None and not isfinite(self.manhole_cover_m):
            raise ValueError("manhole cover must be finite")
        if self.clear_height_m <= 0 or self.frost_depth_m < 0:
            raise ValueError("clear height must be positive; frost depth cannot be negative")
        if not self.basement_floor_m < self.ceiling_m <= self.first_floor_m:
            raise ValueError("basement clear height conflicts with floor elevations")
        if not self.basement_floor_m < self.proposed_invert_m < min(self.ceiling_m, self.ground_m):
            raise ValueError("this preview supports only an exposed basement outlet below ground")
        if (isinstance(self.preview_dn_mm, bool) or not isinstance(self.preview_dn_mm, int)
                or self.preview_dn_mm < 100 or not self.proposed_invert_basis.strip()):
            raise ValueError("explicit schematic DN100+ and proposal basis are required")


def basement_profile_from_request(
    req: IOS2Request, *, proposed_invert_m: float,
    proposed_invert_basis: str, preview_dn_mm: int,
) -> BasementProfileInput:
    """Read only confirmed architectural inputs; do not bypass release validation."""
    needed = {
        "first_floor_m": req.floor_elevations_m.get(1),
        "basement_floor_m": req.wastewater_basement_floor_elevation_m,
        "clear_height_m": req.basement_clear_height_m,
        "ground_m": req.wastewater_ground_relative_elevation_m,
        "frost_depth_m": req.wastewater_frost_depth_m,
    }
    missing = [key for key, value in needed.items() if value is None]
    if missing:
        raise ValueError("missing profile inputs: " + ", ".join(missing))
    if (-1 in req.floor_elevations_m
            and req.floor_elevations_m[-1] != req.wastewater_basement_floor_elevation_m):
        raise ValueError("basement floor elevations disagree")
    result = BasementProfileInput(
        **{key: float(value) for key, value in needed.items() if value is not None},
        manhole_cover_m=req.wastewater_first_manhole_cover_relative_elevation_m,
        proposed_invert_m=proposed_invert_m,
        proposed_invert_basis=proposed_invert_basis,
        preview_dn_mm=preview_dn_mm,
    )
    result.validate()
    return result


def _text(x: float, y: float, value: str, *, height: float = 3.5,
          anchor: str = "start", color: str = "#000", marker: str = "") -> str:
    return (f'<text x="{x:.3f}" y="{y:.3f}" text-anchor="{anchor}" '
            f'font-family="{DRAFTING_FONT_FAMILY}" font-size="{STYLE.font_size(height, 1):.4f}" '
            f'fill="{color}" data-paper-text-height-mm="{height:g}" {marker}>'
            f'{escape(value)}</text>')


def _line(x1: float, y1: float, x2: float, y2: float, *, width: float = .25,
          marker: str = "", dash: str = "", color: str = "#000") -> str:
    return (f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" '
            f'stroke="{color}" stroke-width="{width:g}" '
            f'stroke-dasharray="{dash}" {marker}/>')


def _elev(value: float) -> str:
    return f"{value:+.2f}".replace(".", ",")


_PROFILE_NOTICE = "Предварительный вариант. Не проектная документация. Не для выпуска."


def _profile_notes(data: BasementProfileInput) -> tuple[str, ...]:
    return (
        "Показан начальный тупиковый узел, не присоединение к проходной магистрали.",
        f"Положение трубы дано по лотку; DN{data.preview_dn_mm} - компоновочный вариант, не подбор диаметра.",
        "Протяжённость, уклон, наружная труба и присоединение к колодцу не определены.",
        "Заглубление предварительное; минимум 0,7 м до верха трубы подлежит проверке.",
        data.proposed_invert_basis,
        "ГОСТ Р 21.620-2023: п. 5.2.2.4, приложение В - ориентир оформления фрагмента.",
        "Не является полным листом ПД или монтажным чертежом. Наружная сеть не проектируется.",
    )


def _profile_notes_svg(notes, *, width=384, y=236, bottom=276):
    """Wrap complete notes at the existing paper text height, or fail safely."""
    from app.pz.leader_layout import _text_width

    size = STYLE.font_size(2.5, 1)
    body = ['<g data-profile-notes="true">', _text(25, 230, "Границы этого шага", height=3.5)]
    for note in notes:
        remaining = " ".join(note.split())
        while remaining:
            end = 0
            for index in range(1, len(remaining) + 1):
                if _text_width(remaining[:index], size) > width:
                    break
                end = index
            if not end or y > bottom:
                raise ValueError("Пояснения профиля не помещаются; PDF не изменён")
            if end < len(remaining):
                space = remaining.rfind(" ", 0, end + 1)
                if space > 0:
                    end = space
            body.append(_text(25, y, remaining[:end], height=2.5))
            remaining = remaining[end:].lstrip()
            y += 5.5
    body.append('</g>')
    return "".join(body)


def _validate_profile_layout(svg):
    """Printable text bounds only; not a generic engineering collision check."""
    from app.pz.leader_layout import _text_width

    root = ElementTree.fromstring(svg)
    if root.get("data-release-ready") != "false":
        raise ValueError("Профиль подвала не является проектным выпуском")

    def visit(element, transformed=False):
        transformed = transformed or bool(element.get("transform"))
        if element.tag.endswith("text") and not transformed:
            size = float(element.get("font-size"))
            width = _text_width("".join(element.itertext()), size)
            x, y = float(element.get("x")), float(element.get("y"))
            anchor = element.get("text-anchor", "start")
            left = x - (width if anchor == "end" else width / 2 if anchor == "middle" else 0)
            if left < 20 or left + width > 410 or y - size < 5 or y > 292:
                raise ValueError("Подпись профиля выходит за поле; PDF не изменён")
        for child in element:
            visit(child, transformed)
    visit(root)


def build_basement_profile_svg(data: BasementProfileInput) -> str:
    """A3 draft; real vertical scale, explicit unscaled horizontal arrangement."""
    data.validate()
    ceiling = data.ceiling_m
    highest = data.first_floor_m + 1.15
    lowest = min(data.basement_floor_m - .15, data.frost_level_m - .25)
    denominator = next((n for n in (25, 50, 100, 200)
                        if (highest - lowest) * 1000 / n <= 180), None)
    if denominator is None:
        raise ValueError("profile does not fit the supported A3 vertical scales")
    vertical_scale = 1000 / denominator

    def y(elevation: float) -> float:
        return 34 + (highest - elevation) * vertical_scale

    # The single line is explicitly the invert on this profile, not a measured
    # outside pipe envelope. Exact exterior pipe OD and crown cover are pending.
    pipe_y = y(data.proposed_invert_m)
    first_y, ceiling_y, floor_y = y(data.first_floor_m), y(ceiling), y(data.basement_floor_m)
    wall_in, wall_out, stack_x, outlet_x = 266., 274., 128., 312.
    turn_scale = .22
    turn_y = pipe_y - 76 * turn_scale
    revision_y = y(data.first_floor_m + 1)
    basement = build_wastewater_basement_assembly(
        dn_mm=data.preview_dn_mm, first_floor_elevation_m=data.first_floor_m,
        basement_floor_elevation_m=data.basement_floor_m,
        # Intentionally not forwarded: the approved-domain assembly still has
        # no confirmed invert or slope, despite the visible graphical proposal.
        outlet_id="К1-выпуск (вариант)",
    )
    lower = basement.lower_turn
    lower.validate()
    # The shared fitting renderer serializes segment coordinates to 0.1 mm.
    # Match that endpoint, so a butt-ended continuation cannot leave a seam.
    main_x = round(stack_x + lower.port("main_out").point.x_mm * turn_scale, 1)
    cap_x = stack_x + lower.port("cleanout_cap").point.x_mm * turn_scale
    leaders = LeaderLayoutEngine(bounds=LeaderBounds(25, 30, 409, 220), units_per_mm=1)
    body = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
        f'viewBox="0 0 420 297" data-basement-profile="true" data-release-ready="false" '
        f'data-vertical-scale-denominator="{denominator}" data-horizontal-scale="schematic">',
        '<defs><pattern id="profile-hatch" width="3" height="3" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="3" '
        'stroke="#777" stroke-width="0.25"/></pattern></defs>',
        '<rect width="420" height="297" fill="white"/>',
        _text(25, 16, "К1. Узел подвального выпуска", height=5),
        _text(25, 25, f"Фрагмент для согласования. По высоте М 1:{denominator}; по горизонтали без масштаба", height=2.5),
        _text(25, 31, _PROFILE_NOTICE, height=2.5),
        f'<rect data-profile-slab="first-floor" x="71" y="{first_y:.3f}" '
        f'width="{wall_out-71:g}" height="{ceiling_y-first_y:.3f}" '
        'fill="url(#profile-hatch)" stroke="black" stroke-width="0.25"/>',
        f'<rect data-profile-wall="schematic" x="{wall_in:g}" y="{first_y:.3f}" '
        f'width="{wall_out-wall_in:g}" height="{floor_y-first_y+5:.3f}" '
        'fill="url(#profile-hatch)" stroke="black" stroke-width="0.25"/>',
        f'<rect data-profile-slab="basement" x="71" y="{floor_y:.3f}" '
        f'width="{wall_out-71:g}" height="5" fill="url(#profile-hatch)" '
        'stroke="black" stroke-width="0.25"/>',
        _text(175, ceiling_y + 12, "Подвал", height=5),
        _text(175, ceiling_y + 19, "Экспликация помещений не задана", height=2.5, color="#555"),
    ]
    # Floor/elevation markers, anchored to the exact same transformed levels.
    for level_id, elevation, label in (
        ("first-floor", data.first_floor_m, "1 этаж"),
        ("ceiling", ceiling, "Низ перекрытия"),
        ("basement-floor", data.basement_floor_m, "Пол подвала"),
    ):
        yy = y(elevation)
        body.extend((
            f'<g data-profile-level="{level_id}" data-elevation-m="{elevation:g}">',
            _line(29, yy-4, 67, yy-4),
            _line(67, yy-4, 67, yy),
            _line(63, yy, 71, yy),
            f'<path d="M65,{yy-2:.3f} L67,{yy:.3f} L69,{yy-2:.3f}" '
            'fill="none" stroke="black" stroke-width="0.25"/>',
            _text(29, yy-6, _elev(elevation)),
            _text(29, yy-.5, label, height=2.5), '</g>',
        ))
    # Clear-height dimension is NOT the floor-to-floor dimension.
    dim_x = 91.
    body.extend((_line(dim_x, ceiling_y, dim_x, floor_y, marker='data-clear-height-dimension="true"'),))
    for yy in (ceiling_y, floor_y):
        body.extend((_line(dim_x-3, yy, dim_x+3, yy), _line(dim_x-1.5, yy+1.5, dim_x+1.5, yy-1.5)))
    body.append(_text(dim_x-3, (ceiling_y+floor_y)/2, f"{data.clear_height_m*1000:g}", anchor="end"))

    # Known boundary levels only: no invented manhole shaft, invert or network.
    for level_id, level, label, dash in (
        ("ground", data.ground_m, "Земля", ""),
        ("frost", data.frost_level_m, "Граница промерзания", "3 1.5"),
    ):
        yy = y(level)
        body.extend((
            _line(wall_out, yy, 409, yy, marker=f'data-profile-level="{level_id}" data-elevation-m="{level:g}"', dash=dash, color="#555"),
            _text(281, yy-3 if level_id == "ground" else yy+6,
                  f"{label} {_elev(level)}", height=3.5, color="#555"),
        ))
    if data.manhole_cover_m is not None:
        body.append(_text(281, y(data.ground_m)+7,
                          f"Крышка первого колодца {_elev(data.manhole_cover_m)}", height=2.5))

    # Same lower-turn assembly and cap as the accepted drafting engine.
    body.extend((
        _line(stack_x, revision_y-5, stack_x, turn_y, width=.6, marker='data-profile-pipe="riser"'),
        render_lower_turn_assembly_svg(
            lower, x=stack_x, y=turn_y, scale=turn_scale, pipe_width=.6,
            graphic_size=FittingGraphicSize(data.preview_dn_mm, data.preview_dn_mm, 1),
            annotations=False, pipe_labels=False, flow_direction=False,
        ),
        f'<rect data-profile-sleeve="schematic" x="{wall_in-1:g}" y="{pipe_y-2:.3f}" '
        f'width="{wall_out-wall_in+2:g}" height="4" fill="white" stroke="black" stroke-width="0.25"/>',
        _line(main_x, pipe_y, outlet_x, pipe_y, width=.6,
              marker='data-profile-pipe="outlet" data-invert-status="proposed"'),
        f'<path data-flow-direction="downstream" d="M248,{pipe_y-1.2:.3f} '
        f'L251,{pipe_y:.3f} L248,{pipe_y+1.2:.3f} Z" fill="black"/>',
        render_inline_pipe_label(line_id="profile-collector", label=f"К1 ⌀{data.preview_dn_mm}",
                                 start=(main_x, pipe_y), end=(wall_in-1, pipe_y), font_size=STYLE.font_size(3.5,1), padding=1.2),
        render_inline_pipe_label(line_id="profile-riser", label=f"К1 ⌀{data.preview_dn_mm}",
                                 start=(stack_x, ceiling_y+7), end=(stack_x, turn_y-2), font_size=STYLE.font_size(3.5,1), padding=1.2),
        f'<g data-profile-revision="true" data-height-above-floor-mm="1000">'
        f'{render_ugo("revision", stack_x + .14 * REVISION_CENTRE_ANCHOR[1], revision_y - .14 * REVISION_CENTRE_ANCHOR[0], scale=.14, rotation=90)}</g>',
        _text(stack_x+6, revision_y-3, "Ревизия", height=3.5,
              marker='data-profile-revision-caption="true"'),
    ))
    # Dimension to the centre of the revision; not an unrelated ceiling mark.
    dim_x = stack_x + 38
    body.extend((_line(dim_x, revision_y, dim_x, first_y, marker='data-revision-dimension="1000"'),))
    for yy in (revision_y, first_y):
        body.extend((_line(stack_x+2, yy, dim_x+2, yy), _line(dim_x-1, yy+1, dim_x+1, yy-1)))
    body.append(_text(dim_x+2, (revision_y+first_y)/2, "1000"))
    for request in (
        LeaderRequest("profile-cleanout", "cleanout_cap", (cap_x, pipe_y), "Прочистка", f"DN{data.preview_dn_mm}", preferred_side=-1, preferred_vertical=1),
        LeaderRequest("profile-outlet", "outlet_end", (outlet_x, pipe_y), "Выпуск К1 (вариант)", f"Лоток {_elev(data.proposed_invert_m)}", preferred_side=1, preferred_vertical=-1),
    ):
        body.append(leaders.place_and_render(request))
    body.append(_text(187, pipe_y-7, "Уклон: требуется расчёт", height=2.5))
    body.extend((
        _profile_notes_svg(_profile_notes(data)),
        _text(25, 288, "ЗАРЯ  |  Согласование узла", height=3.5),
        _text(325, 288, "Подвал и выпуск К1", height=3.5),
        _text(409, 288, "Лист 1 из 1", height=3.5, anchor="end"), '</svg>',
    ))
    svg = "".join(body)
    _validate_profile_layout(svg)
    return svg


def generate_basement_profile_pdf(output_path: str, data: BasementProfileInput) -> str:
    ensure_drafting_font_registered()
    import cairosvg  # type: ignore[import-untyped]

    svg = build_basement_profile_svg(data)
    _validate_profile_layout(svg)
    pdf = cairosvg.svg2pdf(bytestring=svg.encode())
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".basement-profile-",
                                         suffix=".pdf", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(pdf)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(path)
