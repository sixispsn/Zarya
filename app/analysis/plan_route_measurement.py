"""Calibrated plan traces -> auditable 3D route envelopes, not auto-routing.

Reuses the architecture import's PDF coordinate system and scale confirmation.
Every trace is bound to the PDF hash and exact floor calibration revision.
No heights, hydraulic grades, fitting dimensions or material reserves are guessed.
"""
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from math import dist, fsum, isfinite
import re

from app.analysis.architecture_confirmation import (
    ConfirmedArchitectureSectionInput, PdfFloorSectionConfirmation,
)
from app.analysis.architecture_pdf import ArchitecturePdfSurvey
from app.pz.network_takeoff import NetworkTakeoff, QuantityBasis, QuantityRoute


def _digest(value) -> str:
    def canonical(row):
        # Loading a saved confirmation turns 4 into 4.0; that is not a changed
        # calibration. Preserve booleans and exact strings, normalise numbers.
        if isinstance(row, (int, float)) and not isinstance(row, bool):
            return float(row)
        if isinstance(row, dict):
            return {key: canonical(item) for key, item in row.items()}
        if isinstance(row, (tuple, list)):
            return [canonical(item) for item in row]
        return row
    return sha256(json.dumps(canonical(value), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


@dataclass(frozen=True)
class PlanRouteVertex:
    x_pt: float
    y_pt: float
    elevation_m: float | None = None  # Absolute relative-project elevation, not height above floor.


@dataclass(frozen=True)
class PlanRouteTrace:
    route_id: str
    system: str
    floor: int
    context_hash: str
    start_node: str
    end_node: str
    vertices: tuple[PlanRouteVertex, ...]
    vertical_mode: str  # unknown / level / slope / vertices
    start_elevation_m: float | None = None
    slope: float | None = None  # Downward rise/run; never inferred from line angle.
    reviewed: bool = False


@dataclass(frozen=True)
class PlanRouteMeasurement:
    trace: PlanRouteTrace
    source_name: str
    source_sha256: str
    page_number: int
    metres_per_point: float
    plan_length_m: float
    spatial_length_m: float | None
    points_m: tuple[tuple[float, float, float], ...]

    @property
    def fingerprint(self) -> str:
        return _digest(asdict(self))


def measurement_context(architecture: ConfirmedArchitectureSectionInput, survey: ArchitecturePdfSurvey,
                        floor: int) -> tuple[PdfFloorSectionConfirmation, str]:
    if architecture.source_sha256 != survey.sha256:
        raise ValueError("Исходный PDF изменился. Подтвердите привязку заново.")
    matches = [f for f in architecture.floors if f.floor == floor]
    if len(matches) != 1:
        raise ValueError("Выберите один подтверждённый этаж.")
    f = matches[0]
    pages = [p for p in survey.pages if p.page_number == f.page_number]
    if len(pages) != 1 or not pages[0].selectable_for_vector_confirmation:
        raise ValueError("Для измерения нужна подтверждённая векторная страница.")
    page = pages[0]
    if not _finite(f.scale.real_distance_m) or f.scale.real_distance_m <= 0:
        raise ValueError("Нужен положительный контрольный размер масштаба.")
    for p in (f.scale.first, f.scale.second):
        if not (_finite(p.x_pt) and _finite(p.y_pt) and 0 <= p.x_pt <= page.width_pt
                and 0 <= p.y_pt <= page.height_pt):
            raise ValueError("Точки калибровки должны находиться в пределах листа.")
    if f.scale.pdf_distance_pt <= 1e-9 or not _finite(f.elevation_m):
        raise ValueError("Калибровка или отметка этажа некорректна.")
    return f, _digest({"pdf": survey.sha256, "floor": asdict(f),
                      "width": page.width_pt, "height": page.height_pt, "rotation": page.rotation_deg})


def measure_plan_route(trace: PlanRouteTrace, architecture: ConfirmedArchitectureSectionInput,
                       survey: ArchitecturePdfSurvey) -> PlanRouteMeasurement:
    if not all(isinstance(v, str) for v in (trace.route_id, trace.system, trace.start_node, trace.end_node)):
        raise ValueError("ID участка, узлов и система должны быть строками.")
    f, context = measurement_context(architecture, survey, trace.floor)
    if trace.context_hash != context:
        raise ValueError("Масштаб, этаж или версия плана изменились. Проверьте трассу повторно.")
    if (not re.fullmatch(r"[\w:./-]{1,100}", trace.route_id) or trace.system not in {"K1", "K2", "K3"}
            or any(not v.strip() or len(v) > 100 for v in (trace.start_node, trace.end_node))
            or trace.start_node == trace.end_node):
        raise ValueError("Нужны ID участка, система и разные начальный/конечный узлы.")
    if not isinstance(trace.reviewed, bool) or isinstance(trace.floor, bool) or not isinstance(trace.floor, int):
        raise ValueError("Некорректный этаж или статус проверки.")
    if not 2 <= len(trace.vertices) <= 500:
        raise ValueError("Укажите от 2 до 500 точек трассы.")
    page = next(p for p in survey.pages if p.page_number == f.page_number)
    for v in trace.vertices:
        if not (_finite(v.x_pt) and _finite(v.y_pt) and 0 <= v.x_pt <= page.width_pt
                and 0 <= v.y_pt <= page.height_pt):
            raise ValueError("Точка трассы вне листа или имеет некорректные координаты.")
    mode = trace.vertical_mode
    if mode not in {"unknown", "level", "slope", "vertices"}:
        raise ValueError("Неизвестный способ задания отметок.")
    if mode in {"unknown", "vertices"} and (trace.start_elevation_m is not None or trace.slope is not None):
        raise ValueError("Для выбранного режима начальная отметка/уклон не используются.")
    if mode != "vertices" and any(v.elevation_m is not None for v in trace.vertices):
        raise ValueError("Отметки точек допустимы только в режиме по точкам.")
    if mode in {"level", "slope"} and not _finite(trace.start_elevation_m):
        raise ValueError("Укажите начальную отметку оси трубы, м.")
    if mode == "slope" and (not _finite(trace.slope) or trace.slope < 0):
        raise ValueError("Задайте неотрицательный уклон в направлении стока, доля единицы.")
    if mode == "level" and trace.slope is not None:
        raise ValueError("Постоянная отметка не допускает дополнительный уклон.")
    if mode == "vertices" and any(not _finite(v.elevation_m) for v in trace.vertices):
        raise ValueError("У каждой точки нужна отметка оси трубы.")
    factor, origin = f.scale.metres_per_point, f.scale.first
    xy = tuple(((v.x_pt-origin.x_pt)*factor, (v.y_pt-origin.y_pt)*factor) for v in trace.vertices)
    steps = tuple(dist(a, b) for a, b in zip(xy, xy[1:]))
    if mode != "vertices" and any(d <= 1e-9 for d in steps):
        raise ValueError("Повторяющиеся точки: вертикальный участок задавайте отметками каждой точки.")
    plan_length = fsum(steps)
    points = []
    for i, (x, y) in enumerate(xy):
        if mode == "unknown":
            break
        z = (trace.vertices[i].elevation_m if mode == "vertices" else
             trace.start_elevation_m - fsum(steps[:i])*(trace.slope if mode == "slope" else 0))
        points.append((x, y, z))
    if points and any(dist(a, b) <= 1e-9 for a, b in zip(points, points[1:])):
        raise ValueError("Две соседние пространственные точки совпадают.")
    # These traces describe gravity drainage, not force mains or fan outlets.
    if any(b[2] > a[2] + 1e-9 for a, b in zip(points, points[1:])):
        raise ValueError("Самотечная трасса поднимается по ходу стока. Проверьте порядок точек/отметки.")
    spatial = fsum(dist(a, b) for a, b in zip(points, points[1:])) if points else None
    return PlanRouteMeasurement(trace, survey.original_name, survey.sha256, f.page_number,
                                factor, plan_length, spatial, tuple(points))


def trace_from_mapping(value: dict) -> PlanRouteTrace:
    if not isinstance(value, dict):
        raise ValueError("Неверный формат трассы.")
    try:
        vertices = tuple(PlanRouteVertex(**v) for v in value["vertices"])
        return PlanRouteTrace(**{**value, "vertices": vertices})
    except (KeyError, TypeError) as exc:
        raise ValueError("Неверный состав полей трассы.") from exc


def apply_plan_measurements(network: NetworkTakeoff, measurements: tuple[PlanRouteMeasurement, ...],
                            architecture: ConfirmedArchitectureSectionInput,
                            survey: ArchitecturePdfSurvey) -> NetworkTakeoff:
    """Explicit quantity-only overlay; never changes hydraulic inputs or fittings.

    Caller must map physical route/node IDs, not multiply a representative trace.
    A changed document/calibration invalidates the saved measurements, even if a
    rounded displayed length happens to remain the same. Partial coverage stays
    visible through each route's original provenance and confirmation status.
    """
    network.validate()
    if not measurements:
        return network
    points = {p.point_id: p for p in network.points}
    existing = {r.route_id: r for r in network.routes}
    replacements = {}
    endpoints = {}
    for saved in measurements:
        m = measure_plan_route(saved.trace, architecture, survey)
        if m != saved:
            raise ValueError("Сохранённое измерение не совпадает с пересчётом из исходных точек.")
        t = m.trace
        if t.route_id not in existing or t.route_id in replacements:
            raise ValueError("Участок отсутствует в полной сети или указан повторно.")
        r = existing[t.route_id]
        if (r.start, r.end) != (t.start_node, t.end_node) or points[r.start].system != t.system:
            raise ValueError("ID узлов/система измерения не совпадают с полной сетью.")
        if r.mode == "vent":
            raise ValueError("Измеритель самотечных трасс не заменяет модель фановой вентиляции.")
        if m.spatial_length_m is None or not t.reviewed:
            raise ValueError("Для переноса в ведомость проверьте трассу и задайте отметки.")
        for node, coordinate in ((r.start, m.points_m[0]), (r.end, m.points_m[-1])):
            key = (t.context_hash, node)
            if key in endpoints and dist(endpoints[key], coordinate) > .001:
                raise ValueError("Общий узел измеренных трасс не совпадает по координатам/отметке (1 мм).")
            endpoints[key] = coordinate
        replacements[t.route_id] = QuantityRoute.from_polyline(
            points_m=m.points_m, route_id=r.route_id, start=r.start, end=r.end, pipe=r.pipe,
            role=r.role, mode=r.mode, basis=QuantityBasis("confirmed",
                f"Трасса проверена по {m.source_name}, лист {m.page_number}, этаж {t.floor}; "
                f"SHA-256 {m.source_sha256}; измерение {m.fingerprint}. "
                "Подтверждён обмер предложенной оси, не проектное решение/раскрой."))
    result = replace(network, routes=tuple(replacements.get(r.route_id, r) for r in network.routes),
        limitations=(*network.limitations,
            "Есть обмеры осей по PDF. Расходы, гидравлика и фасонина не пересчитывались этим измерителем.",
            "Новые повороты, монтажные размеры, стены/проходки и совмещение координат разных этажей требуют проверки."))
    result.validate()
    return result
