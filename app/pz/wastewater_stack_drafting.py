"""Multi-storey composer for the accepted parametric K1 floor module.

Every floor is built as its own :class:`WastewaterFloorAssembly`; repeated
storeys are never collapsed into an ellipsis.  The gravity riser is continued
through the accepted basement turn and building outlet.  A force main
downstream of a sewage pumping unit is a different hydraulic regime and is
intentionally not represented as a calculated part of this assembly.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Iterable, Mapping

from app.pz.wastewater_basement_drafting import (
    WastewaterBasementAssembly,
    build_wastewater_basement_assembly,
    build_wastewater_basement_control_svg,
)
from app.pz.wastewater_drafting import BLACK, FONT, GRAY
from app.pz.wastewater_floor_drafting import (
    FloorFixtureInput,
    WastewaterFloorAssembly,
    build_typical_floor_assembly,
    default_typical_floor_fixtures,
    render_typical_floor_assembly_svg,
)
from app.pz.wastewater_ugo import render_ugo


_ROOF_VENT_HEIGHT_M = {
    "flat_non_accessible": 0.2,
    "pitched": 0.2,
    "collecting_vent_shaft": 0.1,
    "flat_accessible": 3.0,
}
_ROOF_LABELS = {
    "flat_non_accessible": "плоская неэксплуатируемая кровля",
    "pitched": "скатная кровля",
    "collecting_vent_shaft": "обрез сборной вентиляционной шахты",
    "flat_accessible": "плоская эксплуатируемая кровля",
}


@dataclass(frozen=True)
class StackRevisionDraft:
    floor_no: int
    height_above_floor_m: float = 1.0
    basis: str = "СП 30.13330.2020, 18.26"


@dataclass(frozen=True)
class WastewaterStackPage:
    page_no: int
    floor_numbers: tuple[int, ...]
    show_roof: bool
    continues_above: bool
    continues_below: bool


@dataclass(frozen=True)
class StackBasementConnectionDraft:
    """Semantic page-break connection between floor 1 and the basement."""

    floor_no: int
    floor_port_id: str
    basement_port_id: str
    dn_mm: int
    shared_revision_fitting_id: str


@dataclass(frozen=True)
class WastewaterStackAssembly:
    assembly_id: str
    system: str
    flow_regime: str
    floors_above: int
    floor_height_m: float
    riser_id: str
    riser_dn_mm: int
    roof_kind: str
    vent_height_above_roof_m: float
    floors: tuple[WastewaterFloorAssembly, ...]
    revisions: tuple[StackRevisionDraft, ...]
    pages: tuple[WastewaterStackPage, ...]
    basement: WastewaterBasementAssembly
    basement_connection: StackBasementConnectionDraft

    def floor(self, floor_no: int) -> WastewaterFloorAssembly:
        try:
            return next(row for row in self.floors if row.floor_no == floor_no)
        except StopIteration as exc:
            raise KeyError(f"unknown stack floor: {floor_no}") from exc

    @property
    def revision_floors(self) -> tuple[int, ...]:
        return tuple(row.floor_no for row in self.revisions)

    @property
    def basement_page_no(self) -> int:
        return len(self.pages) + 1

    @property
    def total_sheet_count(self) -> int:
        return self.basement_page_no

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.system != "K1":
            errors.append("stack composer currently supports K1 only")
        if self.flow_regime != "gravity":
            errors.append("stack assembly must not masquerade as a force main")
        if self.floors_above < 1:
            errors.append("stack must contain at least one floor")
        if self.floor_height_m <= 0:
            errors.append("floor height must be positive")
        expected_floors = set(range(1, self.floors_above + 1))
        actual_floors = {row.floor_no for row in self.floors}
        if actual_floors != expected_floors:
            errors.append("every above-ground floor must have one assembly")
        if len(self.floors) != len(actual_floors):
            errors.append("floor assemblies contain duplicate floor numbers")
        for floor in self.floors:
            if floor.riser_id != self.riser_id:
                errors.append(f"floor {floor.floor_no}: inconsistent riser ID")
            if floor.system != self.system:
                errors.append(f"floor {floor.floor_no}: inconsistent system")
            for error in floor.validate():
                errors.append(f"floor {floor.floor_no}: {error}")
        expected_revisions = set(_revision_floors(self.floors_above))
        actual_revisions = {row.floor_no for row in self.revisions}
        if actual_revisions != expected_revisions:
            errors.append("revision floors do not satisfy SP 30 spacing")
        if any(row.height_above_floor_m <= 0 for row in self.revisions):
            errors.append("revision height above floor must be positive")
        page_floors = [floor for page in self.pages for floor in page.floor_numbers]
        if page_floors != list(range(self.floors_above, 0, -1)):
            errors.append("pages must show every floor once, from top to bottom")
        if not self.pages or not self.pages[0].show_roof:
            errors.append("the first page must contain the roof and vent extension")
        if any(page.show_roof for page in self.pages[1:]):
            errors.append("the roof must not be duplicated on continuation pages")
        if not self.pages or not self.pages[-1].continues_below:
            errors.append("the last floor page must continue to the basement page")
        connection = self.basement_connection
        try:
            floor_port = self.floor(connection.floor_no).port(connection.floor_port_id)
            basement_port = self.basement.draft.port(connection.basement_port_id)
            shared_revision = self.basement.draft.fitting(
                connection.shared_revision_fitting_id
            )
        except KeyError as exc:
            errors.append(str(exc))
        else:
            if connection.floor_no != 1:
                errors.append("basement connection must originate on floor 1")
            if floor_port.role != "riser_to_below":
                errors.append("floor connection must use the downward riser port")
            if basement_port.role != "hydraulic_inlet":
                errors.append("basement connection must enter its hydraulic inlet")
            if connection.dn_mm != self.riser_dn_mm:
                errors.append("basement connection DN differs from the stack DN")
            if shared_revision.kind != "revision":
                errors.append("first-floor overlap must reference the revision")
        for error in self.basement.validate():
            errors.append(f"basement: {error}")
        if self.basement.riser_id != self.riser_id:
            errors.append("basement riser ID differs from the stack")
        if self.basement.dn_mm != self.riser_dn_mm:
            errors.append("basement DN differs from the stack")
        expected_vent = _ROOF_VENT_HEIGHT_M.get(self.roof_kind)
        if expected_vent is None:
            errors.append("unsupported roof kind")
        elif abs(self.vent_height_above_roof_m - expected_vent) > 1e-9:
            errors.append("vent height does not match the selected roof kind")
        return errors


def _revision_floors(floors_above: int) -> tuple[int, ...]:
    """Lower, upper and no more than three storeys between revisions."""
    floors = {1, floors_above}
    if floors_above >= 5:
        floors.update(range(1, floors_above + 1, 3))
    return tuple(sorted(floors))


def build_wastewater_stack_assembly(
    *,
    floors_above: int,
    floor_height_m: float = 3.0,
    riser_id: str = "К1-Ст1",
    riser_dn_mm: int = 100,
    roof_kind: str = "flat_non_accessible",
    fixtures_by_floor: Mapping[int, Iterable[FloorFixtureInput]] | None = None,
    max_floors_per_sheet: int = 5,
    assembly_id: str = "К1-Стояк-01",
    basement_floor_elevation_m: float | None = None,
    outlet_invert_elevation_m: float | None = None,
    basement_collector_slope_per_mille: float | None = None,
    outlet_id: str = "К1-1",
) -> WastewaterStackAssembly:
    """Build one gravity riser while preserving every individual floor."""
    if floors_above < 1:
        raise ValueError("floors_above must be positive")
    if floor_height_m <= 0:
        raise ValueError("floor_height_m must be positive")
    if riser_dn_mm < 100:
        raise ValueError("K1 riser serving toilets must be at least DN100")
    if roof_kind not in _ROOF_VENT_HEIGHT_M:
        raise ValueError("unsupported roof_kind")
    if max_floors_per_sheet < 1:
        raise ValueError("max_floors_per_sheet must be positive")

    fixture_map = dict(fixtures_by_floor or {})
    unknown_floors = set(fixture_map) - set(range(1, floors_above + 1))
    if unknown_floors:
        raise ValueError(
            "fixtures specified for unknown floors: "
            + ", ".join(map(str, sorted(unknown_floors)))
        )
    floor_assemblies = tuple(
        build_typical_floor_assembly(
            fixtures=fixture_map.get(floor_no, default_typical_floor_fixtures()),
            assembly_id=f"К1-Этаж-{floor_no:02d}",
            floor_no=floor_no,
            floor_elevation_m=(floor_no - 1) * floor_height_m,
            riser_id=riser_id,
            junction_spacing_mm=180.0,
        )
        for floor_no in range(1, floors_above + 1)
    )
    descending = list(range(floors_above, 0, -1))
    chunks = tuple(
        tuple(descending[index : index + max_floors_per_sheet])
        for index in range(0, len(descending), max_floors_per_sheet)
    )
    pages = tuple(
        WastewaterStackPage(
            page_no=index + 1,
            floor_numbers=chunk,
            show_roof=index == 0,
            continues_above=index > 0,
            # Every floor page continues either to another floor page or to
            # the dedicated basement sheet.
            continues_below=True,
        )
        for index, chunk in enumerate(chunks)
    )
    basement = build_wastewater_basement_assembly(
        assembly_id=f"{assembly_id}-Подвал",
        riser_id=riser_id,
        dn_mm=riser_dn_mm,
        first_floor_elevation_m=0.0,
        basement_floor_elevation_m=basement_floor_elevation_m,
        outlet_invert_elevation_m=outlet_invert_elevation_m,
        collector_slope_per_mille=basement_collector_slope_per_mille,
        outlet_id=outlet_id,
    )
    stack = WastewaterStackAssembly(
        assembly_id=assembly_id,
        system="K1",
        flow_regime="gravity",
        floors_above=floors_above,
        floor_height_m=floor_height_m,
        riser_id=riser_id,
        riser_dn_mm=riser_dn_mm,
        roof_kind=roof_kind,
        vent_height_above_roof_m=_ROOF_VENT_HEIGHT_M[roof_kind],
        floors=floor_assemblies,
        revisions=tuple(
            StackRevisionDraft(floor_no=row) for row in _revision_floors(floors_above)
        ),
        pages=pages,
        basement=basement,
        basement_connection=StackBasementConnectionDraft(
            floor_no=1,
            floor_port_id="riser_bottom",
            basement_port_id="first_floor_connection",
            dn_mm=riser_dn_mm,
            shared_revision_fitting_id="first_floor_revision",
        ),
    )
    errors = stack.validate()
    if errors:
        raise ValueError("invalid wastewater stack: " + "; ".join(errors))
    return stack


def _page_floor_origins(
    page: WastewaterStackPage,
    *,
    start_y: float,
    floor_scale: float,
) -> dict[int, float]:
    band = (252.0 - 5.0) * floor_scale
    return {
        floor_no: start_y + index * band
        for index, floor_no in enumerate(page.floor_numbers)
    }


def _revision_svg(
    stack: WastewaterStackAssembly,
    floor: WastewaterFloorAssembly,
    *,
    origin_x: float,
    origin_y: float,
    scale: float,
    show_dimension: bool,
) -> str:
    riser_local_x = floor.port("riser_join").point.x_mm
    riser_x = origin_x + riser_local_x * scale
    slab_y = origin_y + 228.0 * scale
    band_height = (252.0 - 5.0) * scale
    revision_y = slab_y - band_height / stack.floor_height_m
    body = [
        f'<g data-stack-revision-floor="{floor.floor_no}">',
        render_ugo("revision", riser_x, revision_y, scale=0.68, rotation=90.0),
        f'<text x="{riser_x+24:.1f}" y="{revision_y-10:.1f}" '
        f'font-family="{FONT}" font-size="10" font-weight="bold">Р</text>',
    ]
    if show_dimension:
        dim_x = riser_x + 54.0
        body.extend(
            (
                f'<line x1="{dim_x:.1f}" y1="{revision_y:.1f}" '
                f'x2="{dim_x:.1f}" y2="{slab_y:.1f}" stroke="{BLACK}" '
                'stroke-width="1"/>',
                f'<line x1="{dim_x-8:.1f}" y1="{revision_y:.1f}" '
                f'x2="{dim_x+8:.1f}" y2="{revision_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="1"/>',
                f'<line x1="{dim_x-8:.1f}" y1="{slab_y:.1f}" '
                f'x2="{dim_x+8:.1f}" y2="{slab_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="1"/>',
                f'<text x="{dim_x+10:.1f}" y="{(revision_y+slab_y)/2:.1f}" '
                f'font-family="{FONT}" font-size="9">1000</text>',
            )
        )
    body.append("</g>")
    return "".join(body)


def build_wastewater_stack_page_svg(
    stack: WastewaterStackAssembly,
    page: WastewaterStackPage,
) -> str:
    """Render one A1 landscape page of the multi-storey stack."""
    errors = stack.validate()
    if errors:
        raise ValueError("cannot render invalid wastewater stack: " + "; ".join(errors))
    if page not in stack.pages:
        raise ValueError("page does not belong to the stack assembly")

    width, height = 2800, 1980
    margin = 50
    origin_x = 390.0
    floor_scale = 1.25
    start_y = 245.0
    origins = _page_floor_origins(page, start_y=start_y, floor_scale=floor_scale)
    panel_x = 1550.0
    total_pages = stack.total_sheet_count
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        'viewBox="0 0 2800 1980">',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{margin}" y="{margin}" width="{width-2*margin}" '
        f'height="{height-2*margin}" fill="none" stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+38}" y="{margin+48}" font-family="{FONT}" '
        'font-size="30" font-weight="bold">Параметрический стояк К1. Каждый этаж показан отдельно</text>',
        f'<text x="{margin+38}" y="{margin+82}" font-family="{FONT}" '
        f'font-size="16" fill="{GRAY}">{escape(stack.riser_id)} DN{stack.riser_dn_mm}; '
        f'лист {page.page_no} из {total_pages}; режим - самотечный</text>',
        f'<line x1="{panel_x}" y1="{margin+115}" x2="{panel_x}" '
        f'y2="{height-margin-85}" stroke="#777" stroke-width="1.5"/>',
    ]

    for floor_no in page.floor_numbers:
        floor = stack.floor(floor_no)
        origin_y = origins[floor_no]
        body.append(
            render_typical_floor_assembly_svg(
                floor,
                diagnostics=False,
                x=origin_x,
                y=origin_y,
                scale=floor_scale,
            )
        )
        elevation = f"{floor.floor_elevation_m:+.3f}".replace(".", ",")
        floor_line_y = origin_y + 228.0 * floor_scale
        body.extend(
            (
                f'<text data-stack-floor-label="{floor_no}" x="{margin+55}" '
                f'y="{floor_line_y-20:.1f}" font-family="{FONT}" '
                f'font-size="19" font-weight="bold">{floor_no} этаж</text>',
                f'<text x="{margin+55}" y="{floor_line_y+4:.1f}" '
                f'font-family="{FONT}" font-size="13">отм. {elevation}</text>',
            )
        )
        if floor_no in stack.revision_floors:
            body.append(
                _revision_svg(
                    stack,
                    floor,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    scale=floor_scale,
                    show_dimension=floor_no == 1,
                )
            )

    top_floor = stack.floor(page.floor_numbers[0])
    riser_x = origin_x + top_floor.port("riser_join").point.x_mm * floor_scale
    top_y = origins[page.floor_numbers[0]] + 5.0 * floor_scale
    bottom_floor = stack.floor(page.floor_numbers[-1])
    bottom_y = origins[page.floor_numbers[-1]] + 252.0 * floor_scale
    roof_elevation = (
        f"{stack.floors_above * stack.floor_height_m:+.3f}".replace(".", ",")
    )
    floor_height_label = f"{stack.floor_height_m:.2f}".replace(".", ",")

    if page.show_roof:
        roof_y = top_y - 58.0
        vent_top_y = roof_y - (100.0 if stack.vent_height_above_roof_m >= 3.0 else 58.0)
        body.extend(
            (
                f'<line data-roof="{stack.roof_kind}" x1="{origin_x-60:.1f}" '
                f'y1="{roof_y:.1f}" x2="{riser_x+180:.1f}" y2="{roof_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="2"/>',
                f'<line data-vent-extension="true" x1="{riser_x:.1f}" '
                f'y1="{top_y:.1f}" x2="{riser_x:.1f}" y2="{vent_top_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="4"/>',
                f'<line x1="{riser_x-8:.1f}" y1="{vent_top_y:.1f}" '
                f'x2="{riser_x+8:.1f}" y2="{vent_top_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="2"/>',
                f'<text x="{origin_x-42:.1f}" y="{roof_y-16:.1f}" '
                f'font-family="{FONT}" font-size="16" font-weight="bold">Кровля</text>',
                f'<text x="{origin_x-42:.1f}" y="{roof_y+23:.1f}" '
                f'font-family="{FONT}" font-size="12">отм. '
                f'{roof_elevation}</text>',
                f'<text x="{riser_x+24:.1f}" y="{vent_top_y+5:.1f}" '
                f'font-family="{FONT}" font-size="13">'
                f'{int(stack.vent_height_above_roof_m*1000)} мм над кровлей</text>',
            )
        )
    elif page.continues_above:
        body.extend(
            (
                f'<path d="M{riser_x-10:.1f},{top_y+22:.1f} '
                f'L{riser_x:.1f},{top_y:.1f} L{riser_x+10:.1f},{top_y+22:.1f} Z" '
                f'fill="{BLACK}"/>',
                f'<text x="{riser_x+24:.1f}" y="{top_y+12:.1f}" '
                f'font-family="{FONT}" font-size="12">продолжение с листа '
                f'{page.page_no-1}</text>',
            )
        )
    if page.continues_below:
        body.extend(
            (
                f'<path d="M{riser_x-10:.1f},{bottom_y-22:.1f} '
                f'L{riser_x:.1f},{bottom_y:.1f} L{riser_x+10:.1f},{bottom_y-22:.1f} Z" '
                f'fill="{BLACK}"/>',
                f'<text x="{riser_x+24:.1f}" y="{bottom_y-8:.1f}" '
                f'font-family="{FONT}" font-size="12">продолжение на листе '
                f'{page.page_no+1}</text>',
            )
        )

    body.extend(
        (
            f'<text x="{panel_x+35}" y="{margin+160}" font-family="{FONT}" '
            'font-size="22" font-weight="bold">Параметры стояка</text>',
            f'<text x="{panel_x+35}" y="{margin+205}" font-family="{FONT}" '
            f'font-size="15">Этажей: {stack.floors_above}</text>',
            f'<text x="{panel_x+35}" y="{margin+235}" font-family="{FONT}" '
            f'font-size="15">Высота этажа: {floor_height_label} м</text>',
            f'<text x="{panel_x+35}" y="{margin+265}" font-family="{FONT}" '
            f'font-size="15">Стояк: {escape(stack.riser_id)} DN{stack.riser_dn_mm}</text>',
            f'<text x="{panel_x+35}" y="{margin+295}" font-family="{FONT}" '
            f'font-size="15">Кровля: {escape(_ROOF_LABELS[stack.roof_kind])}</text>',
            f'<text x="{panel_x+35}" y="{margin+340}" font-family="{FONT}" '
            'font-size="18" font-weight="bold">Ревизии</text>',
            f'<text x="{panel_x+35}" y="{margin+374}" font-family="{FONT}" '
            f'font-size="15">Этажи: {", ".join(map(str, stack.revision_floors))}</text>',
            f'<text x="{panel_x+35}" y="{margin+405}" font-family="{FONT}" '
            'font-size="13">Нижний и верхний этажи;</text>',
            f'<text x="{panel_x+35}" y="{margin+430}" font-family="{FONT}" '
            'font-size="13">при 5 этажах и более - не реже</text>',
            f'<text x="{panel_x+35}" y="{margin+455}" font-family="{FONT}" '
            'font-size="13">чем через три этажа.</text>',
            f'<text x="{panel_x+35}" y="{margin+500}" font-family="{FONT}" '
            'font-size="18" font-weight="bold">Нормативная трассировка</text>',
            f'<text x="{panel_x+35}" y="{margin+534}" font-family="{FONT}" '
            'font-size="13">СП 30.13330.2020:</text>',
            f'<text x="{panel_x+35}" y="{margin+559}" font-family="{FONT}" '
            'font-size="13">18.18 - вытяжная часть над кровлей;</text>',
            f'<text x="{panel_x+35}" y="{margin+584}" font-family="{FONT}" '
            'font-size="13">18.19 - DN вытяжной части;</text>',
            f'<text x="{panel_x+35}" y="{margin+609}" font-family="{FONT}" '
            'font-size="13">18.26 - ревизии и прочистки.</text>',
            f'<line x1="{panel_x+35}" y1="{margin+655}" '
            f'x2="{width-margin-35}" y2="{margin+655}" stroke="#777"/>',
            f'<text x="{panel_x+35}" y="{margin+695}" font-family="{FONT}" '
            'font-size="18" font-weight="bold">Граница расчёта</text>',
            f'<text x="{panel_x+35}" y="{margin+730}" font-family="{FONT}" '
            'font-size="13">Этот лист: самотечная К1 и вентиляция.</text>',
            f'<text x="{panel_x+35}" y="{margin+755}" font-family="{FONT}" '
            'font-size="13">Напорная линия после КНС сюда не входит.</text>',
            f'<text x="{panel_x+35}" y="{margin+780}" font-family="{FONT}" '
            'font-size="13">Q/H КНС без расчёта не подтверждаются.</text>',
            f'<text x="{margin+28}" y="{height-margin-27}" font-family="{FONT}" '
            f'font-size="12" fill="{GRAY}">Контрольный лист генератора; '
            'графический язык - приложение В ГОСТ Р 21.620-2023. Не входит в комплект ПД.</text>',
            '</svg>',
        )
    )
    return "".join(body)


def build_wastewater_stack_control_svgs(
    stack: WastewaterStackAssembly,
) -> tuple[str, ...]:
    floor_pages = tuple(
        build_wastewater_stack_page_svg(stack, page) for page in stack.pages
    )
    return floor_pages + (build_wastewater_stack_basement_page_svg(stack),)


def build_wastewater_stack_basement_page_svg(
    stack: WastewaterStackAssembly,
) -> str:
    """Render the accepted basement module as the final A1 stack sheet."""
    errors = stack.validate()
    if errors:
        raise ValueError("cannot render invalid wastewater stack: " + "; ".join(errors))
    return build_wastewater_basement_control_svg(
        stack.basement,
        page_width_mm=841,
        page_height_mm=594,
        sheet_title="Параметрический стояк К1. Подвал и выпуск",
        sheet_subtitle=(
            f"{stack.riser_id} DN{stack.riser_dn_mm}; лист "
            f"{stack.basement_page_no} из {stack.total_sheet_count}; "
            "продолжение самотечной системы"
        ),
        continuation_from_sheet=stack.basement_page_no - 1,
        # Both pages are A1, but the accepted basement scene retains its A3
        # coordinate grid.  Scale only the header typography so its printed
        # size matches the other stack sheets.
        title_font_size=19.3,
        subtitle_font_size=10.3,
    )


def generate_wastewater_stack_control_pdf(
    output_path: str,
    *,
    floors_above: int = 9,
    floor_height_m: float = 3.0,
    riser_id: str = "К1-Ст1",
    riser_dn_mm: int = 100,
    roof_kind: str = "flat_non_accessible",
    fixtures_by_floor: Mapping[int, Iterable[FloorFixtureInput]] | None = None,
    max_floors_per_sheet: int = 5,
    basement_floor_elevation_m: float | None = None,
    outlet_invert_elevation_m: float | None = None,
    basement_collector_slope_per_mille: float | None = None,
    outlet_id: str = "К1-1",
) -> str:
    """Write all A1 pages to one vector PDF."""
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    stack = build_wastewater_stack_assembly(
        floors_above=floors_above,
        floor_height_m=floor_height_m,
        riser_id=riser_id,
        riser_dn_mm=riser_dn_mm,
        roof_kind=roof_kind,
        fixtures_by_floor=fixtures_by_floor,
        max_floors_per_sheet=max_floors_per_sheet,
        basement_floor_elevation_m=basement_floor_elevation_m,
        outlet_invert_elevation_m=outlet_invert_elevation_m,
        basement_collector_slope_per_mille=basement_collector_slope_per_mille,
        outlet_id=outlet_id,
    )
    writer = PdfWriter()
    for svg in build_wastewater_stack_control_svgs(stack):
        page_pdf = BytesIO()
        cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=page_pdf)
        page_pdf.seek(0)
        writer.append(PdfReader(page_pdf))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer.write(stream)
    return str(path)
