"""Plan-to-Section engine for a GOST-style architectural schematic frame.

The engine accepts an explicit room register extracted from architectural
plans and a confirmed straight section cut.  It intersects that cut with the
real room rectangles, preserves room numbers/names and produces a vertical
schematic section.  It never creates rooms, shafts, barriers or elevations
from the building type or storey count.

The resulting section is independent of K1/K2.  Wastewater systems can be
overlaid only after this architectural model has passed its own audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from math import hypot, isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.pz.wastewater_drafting import BLACK, FONT, GRAY
from app.pz.wastewater_layout import (
    RectMm,
    WastewaterFloorGroup,
    WastewaterLayoutMode,
    WastewaterSchemeLayout,
    WastewaterSlab,
    WastewaterSpace,
)


@dataclass(frozen=True)
class PlanPoint:
    x_m: float
    y_m: float


@dataclass(frozen=True)
class PlanRect:
    x_m: float
    y_m: float
    width_m: float
    height_m: float

    @property
    def x2_m(self) -> float:
        return self.x_m + self.width_m

    @property
    def y2_m(self) -> float:
        return self.y_m + self.height_m


@dataclass(frozen=True)
class ArchitectureRoomPlan:
    room_id: str
    number: str
    name: str
    kind: str
    bounds: PlanRect
    source_ref: str


@dataclass(frozen=True)
class ArchitectureBarrierPlan:
    barrier_id: str
    kind: str
    start: PlanPoint
    end: PlanPoint
    source_ref: str


@dataclass(frozen=True)
class ArchitectureFloorPlan:
    floor: int
    elevation_m: float
    clear_height_m: float
    rooms: tuple[ArchitectureRoomPlan, ...]
    barriers: tuple[ArchitectureBarrierPlan, ...] = ()
    source_ref: str = ""


@dataclass(frozen=True)
class ArchitectureSectionCut:
    cut_id: str
    start: PlanPoint
    end: PlanPoint
    source_ref: str

    @property
    def length_m(self) -> float:
        return hypot(self.end.x_m - self.start.x_m, self.end.y_m - self.start.y_m)


@dataclass(frozen=True)
class ArchitecturePlanRegistry:
    plan_id: str
    cut: ArchitectureSectionCut
    floors: tuple[ArchitectureFloorPlan, ...]
    source_ref: str


@dataclass(frozen=True)
class SectionRoomCell:
    floor: int
    room_id: str
    number: str
    name: str
    kind: str
    start_m: float
    end_m: float
    source_ref: str

    @property
    def width_m(self) -> float:
        return self.end_m - self.start_m


@dataclass(frozen=True)
class SectionBarrier:
    floor: int
    barrier_id: str
    kind: str
    distance_m: float
    source_ref: str


@dataclass(frozen=True)
class SectionFloor:
    floor: int
    elevation_m: float
    clear_height_m: float
    cells: tuple[SectionRoomCell, ...]
    barriers: tuple[SectionBarrier, ...]
    source_ref: str

    @property
    def structural_signature(self) -> tuple[object, ...]:
        """Fingerprint geometry and purpose, intentionally excluding numbers."""
        return (
            round(self.clear_height_m, 6),
            tuple(
                (
                    row.kind,
                    row.name.casefold(),
                    round(row.start_m, 5),
                    round(row.end_m, 5),
                )
                for row in self.cells
            ),
            tuple(
                (row.kind, round(row.distance_m, 5)) for row in self.barriers
            ),
        )


@dataclass(frozen=True)
class ArchitectureSectionModel:
    plan_id: str
    cut_id: str
    cut_length_m: float
    floors: tuple[SectionFloor, ...]
    source_ref: str

    def floor(self, floor: int) -> SectionFloor:
        try:
            return next(row for row in self.floors if row.floor == floor)
        except StopIteration as exc:
            raise KeyError(f"unknown section floor: {floor}") from exc

    @property
    def displayed_floor_numbers(self) -> tuple[int, ...]:
        return _select_displayed_floors(self.floors)

    @property
    def collapsed_floor_ranges(self) -> tuple[tuple[int, int], ...]:
        descending = self.displayed_floor_numbers
        return tuple(
            (lower + 1, upper - 1)
            for upper, lower in zip(descending, descending[1:])
            if upper - lower > 1
        )


@dataclass(frozen=True)
class ArchitectureSectionIssue:
    code: str
    message: str


def _finite(values: Iterable[float]) -> bool:
    return all(isfinite(value) for value in values)


def _clip_segment_to_rect(
    start: PlanPoint,
    end: PlanPoint,
    rect: PlanRect,
) -> tuple[float, float] | None:
    """Liang-Barsky clipping; returns entry/exit parameters on [0, 1]."""
    dx = end.x_m - start.x_m
    dy = end.y_m - start.y_m
    p = (-dx, dx, -dy, dy)
    q = (
        start.x_m - rect.x_m,
        rect.x2_m - start.x_m,
        start.y_m - rect.y_m,
        rect.y2_m - start.y_m,
    )
    lower, upper = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) <= 1e-12:
            if qi < 0:
                return None
            continue
        ratio = qi / pi
        if pi < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return None
    if upper - lower <= 1e-9:
        return None
    return lower, upper


def _segment_intersection_parameter(
    a: PlanPoint,
    b: PlanPoint,
    c: PlanPoint,
    d: PlanPoint,
) -> float | None:
    """Return parameter on AB for a proper/endpoint segment intersection."""
    abx, aby = b.x_m - a.x_m, b.y_m - a.y_m
    cdx, cdy = d.x_m - c.x_m, d.y_m - c.y_m
    denominator = abx * cdy - aby * cdx
    if abs(denominator) <= 1e-12:
        return None
    acx, acy = c.x_m - a.x_m, c.y_m - a.y_m
    t = (acx * cdy - acy * cdx) / denominator
    u = (acx * aby - acy * abx) / denominator
    if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        return min(1.0, max(0.0, t))
    return None


def audit_architecture_plan_registry(
    registry: ArchitecturePlanRegistry,
    *,
    coverage_tolerance_m: float = 0.02,
) -> tuple[ArchitectureSectionIssue, ...]:
    issues: list[ArchitectureSectionIssue] = []

    def add(code: str, message: str) -> None:
        issues.append(ArchitectureSectionIssue(code, message))

    if not registry.plan_id.strip():
        add("plan.id", "не задано обозначение реестра архитектурных планов")
    if not registry.source_ref.strip():
        add("plan.source", "не указано основание архитектурного реестра")
    if not registry.cut.cut_id.strip() or not registry.cut.source_ref.strip():
        add("cut.source", "линия разреза должна иметь обозначение и источник")
    if registry.cut.length_m <= 1e-9:
        add("cut.length", "линия разреза должна иметь положительную длину")
        return tuple(issues)
    if not _finite(
        (
            registry.cut.start.x_m,
            registry.cut.start.y_m,
            registry.cut.end.x_m,
            registry.cut.end.y_m,
        )
    ):
        add("cut.coordinates", "координаты линии разреза должны быть конечными")
    floor_numbers = [row.floor for row in registry.floors]
    if not floor_numbers:
        add("floor.missing", "в реестре нет этажей")
    if len(set(floor_numbers)) != len(floor_numbers):
        add("floor.duplicate", "номера этажей в реестре повторяются")
    room_ids: list[str] = []
    barrier_ids: list[str] = []
    cut_length = registry.cut.length_m
    for floor in registry.floors:
        if floor.clear_height_m <= 0:
            add("floor.height", f"этаж {floor.floor}: высота должна быть положительной")
        if not floor.source_ref.strip():
            add("floor.source", f"этаж {floor.floor}: не указано основание плана")
        if not _finite((floor.elevation_m, floor.clear_height_m)):
            add("floor.values", f"этаж {floor.floor}: отметка/высота не конечны")
        intervals: list[tuple[float, float, str]] = []
        for room in floor.rooms:
            room_ids.append(room.room_id)
            if not room.room_id.strip():
                add("room.id", f"этаж {floor.floor}: помещение без идентификатора")
            if not room.number.strip() or not room.name.strip():
                add(
                    "room.label",
                    f"{room.room_id or floor.floor}: нужны номер и наименование помещения",
                )
            if not room.source_ref.strip():
                add("room.source", f"{room.room_id}: не указана ссылка на план/экспликацию")
            if room.bounds.width_m <= 0 or room.bounds.height_m <= 0:
                add("room.bounds", f"{room.room_id}: размеры контура должны быть положительными")
                continue
            clipped = _clip_segment_to_rect(
                registry.cut.start,
                registry.cut.end,
                room.bounds,
            )
            if clipped is not None:
                intervals.append(
                    (clipped[0] * cut_length, clipped[1] * cut_length, room.room_id)
                )
        if not intervals:
            add("floor.cut", f"этаж {floor.floor}: разрез не пересекает ни одного помещения")
        else:
            intervals.sort()
            if intervals[0][0] > coverage_tolerance_m:
                add(
                    "floor.coverage",
                    f"этаж {floor.floor}: от начала разреза до первого помещения "
                    f"есть неподтверждённый разрыв {intervals[0][0]:.3f} м",
                )
            for left, right in zip(intervals, intervals[1:]):
                gap = right[0] - left[1]
                if gap > coverage_tolerance_m:
                    add(
                        "floor.coverage",
                        f"этаж {floor.floor}: между {left[2]} и {right[2]} "
                        f"не описана зона длиной {gap:.3f} м",
                    )
                elif gap < -coverage_tolerance_m:
                    add(
                        "floor.overlap",
                        f"этаж {floor.floor}: помещения {left[2]} и {right[2]} "
                        f"перекрываются по линии разреза на {-gap:.3f} м",
                    )
            if cut_length - intervals[-1][1] > coverage_tolerance_m:
                add(
                    "floor.coverage",
                    f"этаж {floor.floor}: после последнего помещения остаётся "
                    f"неподтверждённая зона {cut_length-intervals[-1][1]:.3f} м",
                )
        for barrier in floor.barriers:
            barrier_ids.append(barrier.barrier_id)
            if not barrier.barrier_id.strip() or not barrier.kind.strip():
                add("barrier.id", f"этаж {floor.floor}: преграда без обозначения/типа")
            if not barrier.source_ref.strip():
                add("barrier.source", f"{barrier.barrier_id}: не указано основание АР/КР")
            if _segment_intersection_parameter(
                registry.cut.start,
                registry.cut.end,
                barrier.start,
                barrier.end,
            ) is None:
                add(
                    "barrier.cut",
                    f"{barrier.barrier_id}: преграда не пересекает линию разреза",
                )
    for value in sorted({row for row in room_ids if room_ids.count(row) > 1}):
        add("room.duplicate", f"идентификатор помещения {value} повторяется")
    for value in sorted({row for row in barrier_ids if barrier_ids.count(row) > 1}):
        add("barrier.duplicate", f"идентификатор преграды {value} повторяется")
    return tuple(issues)


def build_architecture_section(
    registry: ArchitecturePlanRegistry,
) -> ArchitectureSectionModel:
    """Intersect the confirmed cut with every floor plan."""
    issues = audit_architecture_plan_registry(registry)
    if issues:
        raise ValueError(
            "architecture plan registry is incomplete: "
            + "; ".join(row.message for row in issues)
        )
    cut_length = registry.cut.length_m
    section_floors: list[SectionFloor] = []
    for floor in sorted(registry.floors, key=lambda row: row.floor):
        cells: list[SectionRoomCell] = []
        for room in floor.rooms:
            clipped = _clip_segment_to_rect(
                registry.cut.start,
                registry.cut.end,
                room.bounds,
            )
            if clipped is None:
                continue
            cells.append(
                SectionRoomCell(
                    floor=floor.floor,
                    room_id=room.room_id,
                    number=room.number,
                    name=room.name,
                    kind=room.kind,
                    start_m=clipped[0] * cut_length,
                    end_m=clipped[1] * cut_length,
                    source_ref=room.source_ref,
                )
            )
        cells.sort(key=lambda row: (row.start_m, row.end_m, row.room_id))
        barriers: list[SectionBarrier] = []
        for barrier in floor.barriers:
            parameter = _segment_intersection_parameter(
                registry.cut.start,
                registry.cut.end,
                barrier.start,
                barrier.end,
            )
            if parameter is None:
                continue
            barriers.append(
                SectionBarrier(
                    floor=floor.floor,
                    barrier_id=barrier.barrier_id,
                    kind=barrier.kind,
                    distance_m=parameter * cut_length,
                    source_ref=barrier.source_ref,
                )
            )
        barriers.sort(key=lambda row: row.distance_m)
        section_floors.append(
            SectionFloor(
                floor=floor.floor,
                elevation_m=floor.elevation_m,
                clear_height_m=floor.clear_height_m,
                cells=tuple(cells),
                barriers=tuple(barriers),
                source_ref=floor.source_ref,
            )
        )
    return ArchitectureSectionModel(
        plan_id=registry.plan_id,
        cut_id=registry.cut.cut_id,
        cut_length_m=cut_length,
        floors=tuple(section_floors),
        source_ref=registry.source_ref,
    )


def _select_displayed_floors(
    floors: tuple[SectionFloor, ...],
) -> tuple[int, ...]:
    """Keep basement, first two levels and top; collapse only equal geometry."""
    ascending = tuple(sorted(floors, key=lambda row: row.floor))
    underground = tuple(row for row in ascending if row.floor <= 0)
    above = tuple(row for row in ascending if row.floor > 0)
    if len(above) <= 4:
        selected = underground + above
        return tuple(row.floor for row in reversed(selected))
    middle = above[1:]
    if len({row.structural_signature for row in middle}) != 1:
        selected = underground + above
        return tuple(row.floor for row in reversed(selected))
    selected = underground + (above[0], above[1], above[-1])
    return tuple(row.floor for row in reversed(selected))


def _point(value: Any, owner: str) -> PlanPoint:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{owner}: expected [x, y]")
    return PlanPoint(float(value[0]), float(value[1]))


def _rect(value: Any, owner: str) -> PlanRect:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{owner}: expected [x, y, width, height]")
    return PlanRect(*(float(row) for row in value))


def architecture_plan_registry_from_mapping(
    data: Mapping[str, Any],
) -> ArchitecturePlanRegistry:
    """Read the strict normalized plan exchange format."""
    cut_data = data.get("cut")
    if not isinstance(cut_data, Mapping):
        raise ValueError("architecture plan: cut must be an object")
    floors_data = data.get("floors")
    if not isinstance(floors_data, list):
        raise ValueError("architecture plan: floors must be a list")
    floors: list[ArchitectureFloorPlan] = []
    for floor_data in floors_data:
        if not isinstance(floor_data, Mapping):
            raise ValueError("architecture plan: every floor must be an object")
        rooms: list[ArchitectureRoomPlan] = []
        for room_data in floor_data.get("rooms", []):
            if not isinstance(room_data, Mapping):
                raise ValueError("architecture plan: every room must be an object")
            rooms.append(
                ArchitectureRoomPlan(
                    room_id=str(room_data.get("id", "")),
                    number=str(room_data.get("number", "")),
                    name=str(room_data.get("name", "")),
                    kind=str(room_data.get("kind", "room")),
                    bounds=_rect(room_data.get("rect"), f"room {room_data.get('id', '')}"),
                    source_ref=str(room_data.get("source_ref", "")),
                )
            )
        barriers: list[ArchitectureBarrierPlan] = []
        for barrier_data in floor_data.get("barriers", []):
            if not isinstance(barrier_data, Mapping):
                raise ValueError("architecture plan: every barrier must be an object")
            barriers.append(
                ArchitectureBarrierPlan(
                    barrier_id=str(barrier_data.get("id", "")),
                    kind=str(barrier_data.get("kind", "")),
                    start=_point(
                        barrier_data.get("start"),
                        f"barrier {barrier_data.get('id', '')}.start",
                    ),
                    end=_point(
                        barrier_data.get("end"),
                        f"barrier {barrier_data.get('id', '')}.end",
                    ),
                    source_ref=str(barrier_data.get("source_ref", "")),
                )
            )
        floors.append(
            ArchitectureFloorPlan(
                floor=int(floor_data.get("floor", 0)),
                elevation_m=float(floor_data.get("elevation_m", 0)),
                clear_height_m=float(floor_data.get("clear_height_m", 0)),
                rooms=tuple(rooms),
                barriers=tuple(barriers),
                source_ref=str(floor_data.get("source_ref", "")),
            )
        )
    return ArchitecturePlanRegistry(
        plan_id=str(data.get("plan_id", "")),
        cut=ArchitectureSectionCut(
            cut_id=str(cut_data.get("id", "")),
            start=_point(cut_data.get("start"), "cut.start"),
            end=_point(cut_data.get("end"), "cut.end"),
            source_ref=str(cut_data.get("source_ref", "")),
        ),
        floors=tuple(floors),
        source_ref=str(data.get("source_ref", "")),
    )


def load_architecture_plan_registry(path: str | Path) -> ArchitecturePlanRegistry:
    source = Path(path)
    with source.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, Mapping):
        raise ValueError("architecture plan root must be an object")
    return architecture_plan_registry_from_mapping(data)


def architecture_section_to_wastewater_layout(
    model: ArchitectureSectionModel,
) -> WastewaterSchemeLayout:
    """Convert the verified section into the existing K1/K2 overlay model."""
    displayed = model.displayed_floor_numbers
    x0, x1 = 80.0, 680.0
    top_y = 75.0
    room_height = 62.0
    normal_gap = 8.0
    break_gap = 28.0
    origins: dict[int, float] = {}
    cursor = top_y
    previous: int | None = None
    for floor_no in displayed:
        if previous is not None:
            cursor += room_height + (
                break_gap if previous - floor_no > 1 else normal_gap
            )
        origins[floor_no] = cursor
        previous = floor_no
    layout = WastewaterSchemeLayout(
        mode=WastewaterLayoutMode.STANDALONE,
        individual_floors_required=False,
    )
    for floor_no in displayed:
        floor = model.floor(floor_no)
        group_id = f"architecture-floor-{floor_no}"
        layout.floor_groups.append(
            WastewaterFloorGroup(
                group_id=group_id,
                label=("Подвал" if floor_no == 0 else f"{floor_no} этаж"),
                floors=(floor_no,),
                elevation_m=floor.elevation_m,
                y_mm=origins[floor_no] + room_height,
                kind="basement" if floor_no <= 0 else "floor",
                source_ref=floor.source_ref,
            )
        )
        for cell in floor.cells:
            left = x0 + (x1 - x0) * cell.start_m / model.cut_length_m
            right = x0 + (x1 - x0) * cell.end_m / model.cut_length_m
            layout.spaces.append(
                WastewaterSpace(
                    space_id=f"section-{floor_no}-{cell.room_id}",
                    group_id=group_id,
                    label=f"№{cell.number} {cell.name}",
                    frame=RectMm(left, origins[floor_no], right - left, room_height),
                    kind=cell.kind,
                    source_ref=cell.source_ref,
                )
            )
    lowest_y = max(origins.values()) + room_height
    layout.slabs.append(
        WastewaterSlab(
            slab_id="architecture-foundation-section",
            frame=RectMm(x0, lowest_y, x1 - x0, 18.0),
            kind="basement_foundation_slab",
            hatch="diagonal",
            source_ref=f"{model.source_ref}; конструкция/толщина уточняется по КР",
        )
    )
    return layout


def _wrap_label(value: str, max_chars: int = 22) -> tuple[str, ...]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines[:3]) or ("",)


def build_architecture_section_control_svg(
    model: ArchitectureSectionModel,
) -> str:
    """Render a standalone A1 control sheet for the architecture engine."""
    width, height = 2800, 1980
    margin = 50
    x_left, x_right = 180.0, 2580.0
    room_height = 275.0
    start_y = 245.0
    normal_gap = 22.0
    break_gap = 170.0
    displayed = model.displayed_floor_numbers
    origins: dict[int, float] = {}
    cursor = start_y
    previous: int | None = None
    for floor_no in displayed:
        if previous is not None:
            cursor += room_height + (
                break_gap if previous - floor_no > 1 else normal_gap
            )
        origins[floor_no] = cursor
        previous = floor_no
    lowest_bottom = max(origins.values()) + room_height
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        'viewBox="0 0 2800 1980">',
        '<defs><pattern id="architecture-hatch" width="22" height="22" '
        'patternUnits="userSpaceOnUse" patternTransform="rotate(35)">'
        '<line x1="0" y1="0" x2="0" y2="22" stroke="#777" stroke-width="2"/>'
        '</pattern><pattern id="shaft-hatch" width="18" height="18" '
        'patternUnits="userSpaceOnUse"><path d="M0,18 L18,0" stroke="#bbb" '
        'stroke-width="1"/></pattern></defs>',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{margin}" y="{margin}" width="{width-2*margin}" '
        f'height="{height-2*margin}" fill="none" stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        'font-size="30" font-weight="bold">Контрольный модуль «План - принципиальный разрез»</text>',
        f'<text x="{margin+38}" y="{margin+84}" font-family="{FONT}" '
        f'font-size="16" fill="{GRAY}">Реестр {escape(model.plan_id)}; '
        f'разрез {escape(model.cut_id)}; длина {_fmt(model.cut_length_m)} м; '
        'помещения не генерируются — только пересекаются линией разреза</text>',
        f'<line data-architecture-roof="true" x1="{x_left}" y1="{start_y-35}" '
        f'x2="{x_right}" y2="{start_y-35}" stroke="#777" stroke-width="2"/>',
        f'<text x="{x_left-25}" y="{start_y-47}" text-anchor="end" '
        f'font-family="{FONT}" font-size="14">Кровля</text>',
    ]
    for floor_no in displayed:
        floor = model.floor(floor_no)
        y = origins[floor_no]
        body.append(
            f'<g data-section-floor="{floor_no}" data-floor-source="{escape(floor.source_ref)}">'
        )
        body.append(
            f'<line x1="{x_left}" y1="{y+room_height:.1f}" x2="{x_right}" '
            f'y2="{y+room_height:.1f}" stroke="#777" stroke-width="2"/>'
        )
        body.append(
            f'<text x="{x_left-25}" y="{y+room_height-28:.1f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="15" font-weight="bold">'
            f'{"Подвал" if floor_no == 0 else f"{floor_no} этаж"}</text>'
        )
        body.append(
            f'<text x="{x_left-25}" y="{y+room_height-8:.1f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="12">отм. {_fmt(floor.elevation_m)}</text>'
        )
        for cell in floor.cells:
            left = x_left + (x_right - x_left) * cell.start_m / model.cut_length_m
            right = x_left + (x_right - x_left) * cell.end_m / model.cut_length_m
            fill = 'url(#shaft-hatch)' if cell.kind == "shaft" else "white"
            body.append(
                f'<rect data-section-room="{escape(cell.room_id)}" '
                f'data-room-number="{escape(cell.number)}" '
                f'data-room-name="{escape(cell.name)}" x="{left:.1f}" y="{y:.1f}" '
                f'width="{right-left:.1f}" height="{room_height:.1f}" '
                f'fill="{fill}" stroke="{BLACK}" stroke-width="1.5"/>'
            )
            lines = _wrap_label(f"№{cell.number} {cell.name}")
            centre_x = (left + right) / 2
            label_y = y + 32.0
            for index, line in enumerate(lines):
                body.append(
                    f'<text x="{centre_x:.1f}" y="{label_y+index*20:.1f}" '
                    f'text-anchor="middle" font-family="{FONT}" '
                    f'font-size="13" font-weight="{("bold" if index == 0 else "normal")}">'
                    f'{escape(line)}</text>'
                )
        for barrier in floor.barriers:
            x = x_left + (x_right - x_left) * barrier.distance_m / model.cut_length_m
            body.extend(
                (
                    f'<line data-section-barrier="{escape(barrier.barrier_id)}" '
                    f'data-barrier-kind="{escape(barrier.kind)}" x1="{x:.1f}" y1="{y:.1f}" '
                    f'x2="{x:.1f}" y2="{y+room_height:.1f}" stroke="{BLACK}" '
                    'stroke-width="6" stroke-dasharray="18 7"/>',
                    f'<rect x="{x+8:.1f}" y="{y+room_height-35:.1f}" '
                    'width="190" height="22" fill="white"/>',
                    f'<text x="{x+13:.1f}" y="{y+room_height-19:.1f}" '
                    f'font-family="{FONT}" font-size="11">{escape(barrier.kind)}</text>',
                )
            )
        body.append("</g>")

    for upper, lower in zip(displayed, displayed[1:]):
        if upper - lower <= 1:
            continue
        gap_top = origins[upper] + room_height
        gap_bottom = origins[lower]
        centre = (gap_top + gap_bottom) / 2
        body.extend(
            (
                f'<g data-collapsed-architecture-floors="{lower+1}-{upper-1}">',
                f'<path d="M{x_left-18},{centre-12} L{x_left+18},{centre+12}" '
                f'stroke="{BLACK}" stroke-width="2" fill="none"/>',
                f'<path d="M{x_right-18},{centre-12} L{x_right+18},{centre+12}" '
                f'stroke="{BLACK}" stroke-width="2" fill="none"/>',
                f'<text x="{(x_left+x_right)/2:.1f}" y="{centre+5:.1f}" '
                f'text-anchor="middle" font-family="{FONT}" font-size="14">'
                f'этажи {lower+1}-{upper-1} не показаны; архитектурная структура повторяется</text>',
                '</g>',
            )
        )

    slab_y = lowest_bottom
    body.extend(
        (
            f'<rect data-foundation-slab="true" x="{x_left}" y="{slab_y:.1f}" '
            f'width="{x_right-x_left}" height="80" fill="url(#architecture-hatch)" '
            'stroke="#777" stroke-width="1.5"/>',
            f'<text x="{margin+38}" y="{height-margin-76}" font-family="{FONT}" '
            'font-size="13">Выход движка: этажные ячейки с номером, названием, '
            'типом, границами, шахтами и преградами. Следующий слой — привязка К1/К2.</text>',
            f'<text x="{margin+38}" y="{height-margin-48}" font-family="{FONT}" '
            f'font-size="12" fill="{GRAY}">Источник: {escape(model.source_ref)}. '
            'Контрольный лист компонента, не лист проектной документации.</text>',
            f'<text x="{margin+38}" y="{height-margin-24}" font-family="{FONT}" '
            f'font-size="12" fill="{GRAY}">Состав помещений соответствует '
            'ГОСТ Р 21.620-2023, 5.2.2.4; координаты получены из линии разреза.</text>',
            '</svg>',
        )
    )
    return "".join(body)


def _fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def generate_architecture_section_control_pdf(
    output_path: str,
    registry: ArchitecturePlanRegistry,
) -> str:
    """Write one vector A1 control sheet for the Plan-to-Section engine."""
    import cairosvg

    model = build_architecture_section(registry)
    svg = build_architecture_section_control_svg(model)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=str(path))
    return str(path)
