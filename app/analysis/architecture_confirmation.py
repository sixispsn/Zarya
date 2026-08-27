"""Подтверждение архитектурного разреза поверх кандидатов из PDF.

Модуль переводит координаты PDF в проектные метры только после явной
калибровки. Пересечения векторных линий с разрезом являются кандидатами стен,
а не готовыми границами помещений. Состав ячеек задаёт проектировщик.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from html import escape
from math import hypot, isfinite
from typing import Iterable

from app.analysis.architecture_pdf import (
    ArchitecturePdfPageSurvey,
    PdfPlanPoint,
)
from app.pz.architecture_section_engine import (
    ArchitectureSectionModel,
    SectionBarrier,
    SectionFloor,
    SectionRoomCell,
)


@dataclass(frozen=True)
class PdfScaleConfirmation:
    first: PdfPlanPoint
    second: PdfPlanPoint
    real_distance_m: float

    @property
    def pdf_distance_pt(self) -> float:
        return hypot(
            self.second.x_pt - self.first.x_pt,
            self.second.y_pt - self.first.y_pt,
        )

    @property
    def metres_per_point(self) -> float:
        if self.pdf_distance_pt <= 1e-9:
            raise ValueError("calibration points must be different")
        return self.real_distance_m / self.pdf_distance_pt


@dataclass(frozen=True)
class PdfSectionCutConfirmation:
    start: PdfPlanPoint
    end: PdfPlanPoint

    @property
    def length_pt(self) -> float:
        return hypot(
            self.end.x_pt - self.start.x_pt,
            self.end.y_pt - self.start.y_pt,
        )


@dataclass(frozen=True)
class PdfCutIntersectionCandidate:
    station_pt: float
    station_m: float
    point: PdfPlanPoint
    contributing_lines: int


@dataclass(frozen=True)
class PdfSectionIntervalDraft:
    start_station_pt: float
    end_station_pt: float
    start_m: float
    end_m: float


@dataclass(frozen=True)
class PdfSectionCellConfirmation:
    cell_id: str
    start_station_pt: float
    end_station_pt: float
    number: str
    name: str
    kind: str = "room"


@dataclass(frozen=True)
class PdfSectionBarrierConfirmation:
    barrier_id: str
    station_pt: float
    kind: str


@dataclass(frozen=True)
class PdfFloorSectionConfirmation:
    page_number: int
    floor: int
    elevation_m: float
    clear_height_m: float
    scale: PdfScaleConfirmation
    cut: PdfSectionCutConfirmation
    cells: tuple[PdfSectionCellConfirmation, ...]
    barriers: tuple[PdfSectionBarrierConfirmation, ...] = ()


@dataclass(frozen=True)
class ConfirmedArchitectureSectionInput:
    plan_id: str
    cut_id: str
    source_name: str
    source_sha256: str
    floors: tuple[PdfFloorSectionConfirmation, ...]


@dataclass(frozen=True)
class ArchitectureConfirmationIssue:
    code: str
    message: str


def _intersection_parameter(
    a: PdfPlanPoint,
    b: PdfPlanPoint,
    c: PdfPlanPoint,
    d: PdfPlanPoint,
) -> float | None:
    abx, aby = b.x_pt - a.x_pt, b.y_pt - a.y_pt
    cdx, cdy = d.x_pt - c.x_pt, d.y_pt - c.y_pt
    denominator = abx * cdy - aby * cdx
    if abs(denominator) <= 1e-9:
        return None
    acx, acy = c.x_pt - a.x_pt, c.y_pt - a.y_pt
    t = (acx * cdy - acy * cdx) / denominator
    u = (acx * aby - acy * abx) / denominator
    if -1e-8 <= t <= 1.0 + 1e-8 and -1e-8 <= u <= 1.0 + 1e-8:
        return min(1.0, max(0.0, t))
    return None


def find_cut_intersection_candidates(
    page: ArchitecturePdfPageSurvey,
    scale: PdfScaleConfirmation,
    cut: PdfSectionCutConfirmation,
    *,
    cluster_tolerance_pt: float = 1.5,
    endpoint_tolerance_pt: float = 1.0,
) -> tuple[PdfCutIntersectionCandidate, ...]:
    """Найти пересечения; результат остаётся набором кандидатов."""
    if scale.real_distance_m <= 0 or scale.pdf_distance_pt <= 1e-9:
        raise ValueError("scale confirmation is incomplete")
    if cut.length_pt <= 1e-9:
        raise ValueError("section cut is incomplete")
    raw: list[float] = []
    for line in page.vector_lines:
        parameter = _intersection_parameter(
            cut.start,
            cut.end,
            line.start,
            line.end,
        )
        if parameter is None:
            continue
        station = parameter * cut.length_pt
        if (
            station <= endpoint_tolerance_pt
            or cut.length_pt - station <= endpoint_tolerance_pt
        ):
            continue
        raw.append(station)
    raw.sort()
    clusters: list[list[float]] = []
    for station in raw:
        if not clusters or station - clusters[-1][-1] > cluster_tolerance_pt:
            clusters.append([station])
        else:
            clusters[-1].append(station)
    dx = cut.end.x_pt - cut.start.x_pt
    dy = cut.end.y_pt - cut.start.y_pt
    result: list[PdfCutIntersectionCandidate] = []
    for cluster in clusters:
        station = sum(cluster) / len(cluster)
        parameter = station / cut.length_pt
        result.append(PdfCutIntersectionCandidate(
            station_pt=round(station, 4),
            station_m=round(station * scale.metres_per_point, 6),
            point=PdfPlanPoint(
                round(cut.start.x_pt + parameter * dx, 4),
                round(cut.start.y_pt + parameter * dy, 4),
            ),
            contributing_lines=len(cluster),
        ))
    return tuple(result)


def build_section_interval_drafts(
    scale: PdfScaleConfirmation,
    cut: PdfSectionCutConfirmation,
    selected_stations_pt: Iterable[float],
    *,
    station_tolerance_pt: float = 0.75,
) -> tuple[PdfSectionIntervalDraft, ...]:
    """Разделить разрез только по явно выбранным проектировщиком границам."""
    if scale.real_distance_m <= 0 or scale.pdf_distance_pt <= 1e-9:
        raise ValueError("scale confirmation is incomplete")
    if cut.length_pt <= 1e-9:
        raise ValueError("section cut is incomplete")
    selected = sorted(float(row) for row in selected_stations_pt)
    boundaries = [0.0]
    for station in selected:
        if not isfinite(station):
            raise ValueError("boundary station must be finite")
        if station <= station_tolerance_pt or cut.length_pt - station <= station_tolerance_pt:
            raise ValueError("boundary station is outside the internal cut range")
        if station - boundaries[-1] <= station_tolerance_pt:
            raise ValueError("confirmed boundary stations are duplicated")
        boundaries.append(station)
    boundaries.append(cut.length_pt)
    factor = scale.metres_per_point
    return tuple(
        PdfSectionIntervalDraft(
            start_station_pt=start,
            end_station_pt=end,
            start_m=start * factor,
            end_m=end * factor,
        )
        for start, end in zip(boundaries, boundaries[1:])
    )


def build_pdf_plan_preview_svg(
    page: ArchitecturePdfPageSurvey,
    *,
    scale: PdfScaleConfirmation | None = None,
    cut: PdfSectionCutConfirmation | None = None,
    candidates: Iterable[PdfCutIntersectionCandidate] = (),
) -> str:
    """Показать наблюдаемый слой PDF и подтверждённые пользователем линии."""
    width = page.width_pt
    height = page.height_pt
    body = [
        f'<svg class="architecture-plan-svg" data-plan-preview '
        f'data-pdf-height="{height:.4f}" viewBox="0 0 {width:.4f} {height:.4f}" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Векторная подложка страницы {page.page_number}">',
        '<rect width="100%" height="100%" class="plan-preview-bg"/>',
        f'<g class="plan-vector-layer" transform="translate(0 {height:.4f}) scale(1 -1)">',
    ]
    for line in page.vector_lines[:25_000]:
        body.append(
            f'<line x1="{line.start.x_pt:.4f}" y1="{line.start.y_pt:.4f}" '
            f'x2="{line.end.x_pt:.4f}" y2="{line.end.y_pt:.4f}" '
            'vector-effect="non-scaling-stroke"/>'
        )
    body.append('</g><g class="plan-text-layer">')
    for text in page.texts[:750]:
        font_size = min(max(text.font_size_pt, 2.5), 16.0)
        body.append(
            f'<text x="{text.anchor.x_pt:.4f}" '
            f'y="{height-text.anchor.y_pt:.4f}" font-size="{font_size:.3f}">'
            f'{escape(text.text)}</text>'
        )
    body.append('</g>')

    def overlay_line(kind: str, first: PdfPlanPoint, second: PdfPlanPoint) -> None:
        body.append(
            f'<line data-preview-{kind} x1="{first.x_pt:.4f}" '
            f'y1="{height-first.y_pt:.4f}" x2="{second.x_pt:.4f}" '
            f'y2="{height-second.y_pt:.4f}" vector-effect="non-scaling-stroke"/>'
        )

    if scale is None:
        body.append('<line data-preview-calibration hidden/>')
    else:
        overlay_line("calibration", scale.first, scale.second)
    if cut is None:
        body.append('<line data-preview-cut hidden/>')
    else:
        overlay_line("cut", cut.start, cut.end)
    for index, candidate in enumerate(candidates, 1):
        body.append(
            f'<g data-preview-candidate="{index}"><circle '
            f'cx="{candidate.point.x_pt:.4f}" '
            f'cy="{height-candidate.point.y_pt:.4f}" r="3.5" '
            'vector-effect="non-scaling-stroke"/>'
            f'<text x="{candidate.point.x_pt+5:.4f}" '
            f'y="{height-candidate.point.y_pt-5:.4f}">'
            f'{index}</text></g>'
        )
    body.append('</svg>')
    return ''.join(body)


def audit_confirmed_architecture_section(
    value: ConfirmedArchitectureSectionInput,
    *,
    station_tolerance_pt: float = 0.75,
    length_tolerance_m: float = 0.03,
) -> tuple[ArchitectureConfirmationIssue, ...]:
    issues: list[ArchitectureConfirmationIssue] = []

    def add(code: str, message: str) -> None:
        issues.append(ArchitectureConfirmationIssue(code, message))

    if not value.plan_id.strip() or not value.cut_id.strip():
        add("identity.missing", "нужны обозначения реестра и линии разреза")
    if not value.source_name.strip() or len(value.source_sha256) != 64:
        add("source.missing", "нужны имя исходного PDF и полный SHA-256")
    if not value.floors:
        add("floor.missing", "не подтвержден ни один этаж")
        return tuple(issues)
    floor_numbers = [row.floor for row in value.floors]
    if len(floor_numbers) != len(set(floor_numbers)):
        add("floor.duplicate", "номер подтверждённого этажа повторяется")
    cut_lengths_m: list[float] = []
    cell_ids: list[str] = []
    barrier_ids: list[str] = []
    for floor in value.floors:
        prefix = f"этаж {floor.floor}"
        numeric = (
            floor.elevation_m,
            floor.clear_height_m,
            floor.scale.real_distance_m,
            floor.scale.pdf_distance_pt,
            floor.cut.length_pt,
        )
        if not all(isfinite(row) for row in numeric):
            add("value.nonfinite", f"{prefix}: координаты и размеры должны быть конечными")
            continue
        if floor.page_number < 1:
            add("page.invalid", f"{prefix}: номер страницы должен быть не меньше 1")
        if floor.clear_height_m <= 0:
            add("floor.height", f"{prefix}: чистая высота должна быть положительной")
        if floor.scale.real_distance_m <= 0 or floor.scale.pdf_distance_pt <= 1e-9:
            add("scale.invalid", f"{prefix}: калибровка не задана")
            continue
        if floor.cut.length_pt <= 1e-9:
            add("cut.invalid", f"{prefix}: линия разреза не задана")
            continue
        cut_length_m = floor.cut.length_pt * floor.scale.metres_per_point
        cut_lengths_m.append(cut_length_m)
        if not floor.cells:
            add("cell.missing", f"{prefix}: не подтверждены помещения вдоль разреза")
            continue
        cells = sorted(
            floor.cells,
            key=lambda row: (row.start_station_pt, row.end_station_pt),
        )
        if cells[0].start_station_pt > station_tolerance_pt:
            add("cell.coverage", f"{prefix}: разрез не покрыт от начальной точки")
        previous_end = 0.0
        for cell in cells:
            cell_ids.append(cell.cell_id)
            if not cell.cell_id.strip() or not cell.number.strip() or not cell.name.strip():
                add("cell.label", f"{prefix}: каждой ячейке нужны ID, номер и название")
            if cell.end_station_pt - cell.start_station_pt <= station_tolerance_pt:
                add("cell.length", f"{prefix}, {cell.cell_id}: ячейка имеет нулевую длину")
            gap = cell.start_station_pt - previous_end
            if gap > station_tolerance_pt:
                add("cell.coverage", f"{prefix}: между ячейками есть разрыв {gap:.2f} pt")
            elif gap < -station_tolerance_pt:
                add("cell.overlap", f"{prefix}: ячейки перекрываются на {-gap:.2f} pt")
            if cell.start_station_pt < -station_tolerance_pt:
                add("cell.range", f"{prefix}, {cell.cell_id}: начало за пределами разреза")
            if cell.end_station_pt > floor.cut.length_pt + station_tolerance_pt:
                add("cell.range", f"{prefix}, {cell.cell_id}: конец за пределами разреза")
            previous_end = cell.end_station_pt
        tail = floor.cut.length_pt - previous_end
        if tail > station_tolerance_pt:
            add("cell.coverage", f"{prefix}: до конца разреза остаётся {tail:.2f} pt")
        for barrier in floor.barriers:
            barrier_ids.append(barrier.barrier_id)
            if not barrier.barrier_id.strip() or not barrier.kind.strip():
                add("barrier.label", f"{prefix}: преграде нужны ID и тип")
            if not -station_tolerance_pt <= barrier.station_pt <= floor.cut.length_pt + station_tolerance_pt:
                add("barrier.range", f"{prefix}, {barrier.barrier_id}: преграда вне разреза")
    if cut_lengths_m and max(cut_lengths_m) - min(cut_lengths_m) > length_tolerance_m:
        add("cut.length_mismatch", "подтверждённая длина разреза различается между этажами")
    for duplicate in sorted({row for row in cell_ids if cell_ids.count(row) > 1}):
        add("cell.duplicate", f"идентификатор ячейки {duplicate} повторяется")
    for duplicate in sorted({row for row in barrier_ids if barrier_ids.count(row) > 1}):
        add("barrier.duplicate", f"идентификатор преграды {duplicate} повторяется")
    return tuple(issues)


def build_confirmed_architecture_section(
    value: ConfirmedArchitectureSectionInput,
) -> ArchitectureSectionModel:
    issues = audit_confirmed_architecture_section(value)
    if issues:
        raise ValueError(
            "architecture section confirmation is incomplete: "
            + "; ".join(row.message for row in issues)
        )
    source = (
        f"{value.source_name}; SHA-256 {value.source_sha256}; "
        "геометрия разреза подтверждена проектировщиком"
    )
    floors: list[SectionFloor] = []
    for floor in sorted(value.floors, key=lambda row: row.floor):
        factor = floor.scale.metres_per_point
        floor_source = f"{source}; стр. {floor.page_number}; этаж {floor.floor}"
        cells = tuple(
            SectionRoomCell(
                floor=floor.floor,
                room_id=row.cell_id,
                number=row.number,
                name=row.name,
                kind=row.kind,
                start_m=row.start_station_pt * factor,
                end_m=row.end_station_pt * factor,
                source_ref=floor_source,
            )
            for row in sorted(floor.cells, key=lambda item: item.start_station_pt)
        )
        barriers = tuple(
            SectionBarrier(
                floor=floor.floor,
                barrier_id=row.barrier_id,
                kind=row.kind,
                distance_m=row.station_pt * factor,
                source_ref=floor_source,
            )
            for row in sorted(floor.barriers, key=lambda item: item.station_pt)
        )
        floors.append(SectionFloor(
            floor=floor.floor,
            elevation_m=floor.elevation_m,
            clear_height_m=floor.clear_height_m,
            cells=cells,
            barriers=barriers,
            source_ref=floor_source,
        ))
    first = value.floors[0]
    return ArchitectureSectionModel(
        plan_id=value.plan_id,
        cut_id=value.cut_id,
        cut_length_m=first.cut.length_pt * first.scale.metres_per_point,
        floors=tuple(floors),
        source_ref=source,
    )


def confirmed_architecture_section_to_mapping(
    value: ConfirmedArchitectureSectionInput,
) -> dict:
    return asdict(value)


def confirmed_architecture_section_from_mapping(
    value: dict,
) -> ConfirmedArchitectureSectionInput:
    def point(data: dict) -> PdfPlanPoint:
        return PdfPlanPoint(float(data["x_pt"]), float(data["y_pt"]))

    floors: list[PdfFloorSectionConfirmation] = []
    for row in value.get("floors", []):
        scale_data = row["scale"]
        cut_data = row["cut"]
        floors.append(PdfFloorSectionConfirmation(
            page_number=int(row["page_number"]),
            floor=int(row["floor"]),
            elevation_m=float(row["elevation_m"]),
            clear_height_m=float(row["clear_height_m"]),
            scale=PdfScaleConfirmation(
                first=point(scale_data["first"]),
                second=point(scale_data["second"]),
                real_distance_m=float(scale_data["real_distance_m"]),
            ),
            cut=PdfSectionCutConfirmation(
                start=point(cut_data["start"]),
                end=point(cut_data["end"]),
            ),
            cells=tuple(
                PdfSectionCellConfirmation(
                    cell_id=str(cell["cell_id"]),
                    start_station_pt=float(cell["start_station_pt"]),
                    end_station_pt=float(cell["end_station_pt"]),
                    number=str(cell["number"]),
                    name=str(cell["name"]),
                    kind=str(cell.get("kind", "room")),
                )
                for cell in row.get("cells", [])
            ),
            barriers=tuple(
                PdfSectionBarrierConfirmation(
                    barrier_id=str(barrier["barrier_id"]),
                    station_pt=float(barrier["station_pt"]),
                    kind=str(barrier["kind"]),
                )
                for barrier in row.get("barriers", [])
            ),
        ))
    return ConfirmedArchitectureSectionInput(
        plan_id=str(value.get("plan_id", "")),
        cut_id=str(value.get("cut_id", "")),
        source_name=str(value.get("source_name", "")),
        source_sha256=str(value.get("source_sha256", "")),
        floors=tuple(floors),
    )
