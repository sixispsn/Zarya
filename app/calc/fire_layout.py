# -*- coding: utf-8 -*-
"""
app/calc/fire_layout.py — расстановка пожарных кранов ВПВ (блок 3, layout).

Слой 3 из архитектуры Антона: НОРМАТИВ (сколько струй, расход) → ПРАВИЛА
РАЗМЕЩЕНИЯ → ОПТИМИЗАТОР РАЗМЕЩЕНИЯ (этот модуль) → ГИДРАВЛИКА.

Число ПК по СП 10.13130.2020 определяется не таблицей, а геометрией орошения
(п. 6.1.13, 6.2.2): каждая точка защищаемого помещения должна орошаться
расчётным числом струй. Для типового прямоугольного помещения СП даёт
аналитический шаг между кранами — формула (1) п. 6.2.12:

    L = √[ (√(Rk² − (H−1,35)²) + (lp − 2))² − (B/2)² ]

где √(Rk²−(H−1,35)²) — горизонтальная проекция компактной струи (струя тратит
часть длины Rk на подъём до верхней точки H над осью клапана 1,35 м),
(lp−2) — вклад рукава с запасом на невозможность натянуть его в струну,
(B/2) — поперечное плечо при расстановке по двум продольным сторонам.
L — продольный шаг, при котором дальний верхний угол берётся по диагонали
свободной струёй, а не «дотягиванием» рукава.

Радиус Rk — нормативный минимум по п. 7.15 (6/8/16 м) либо из формулы (3)
п. 7.16; в этом модуле принимается как вход (считается нормативным слоем).

Каркас модели (enum'ы, dataclass'ы, базовые формулы) — авторства Антона.
Здесь он доведён до рабочего состояния: edge_offset от торцов, автовыбор
симметрия/шахматка, отчёт покрытия с кратностью и разбором нарушений.

Известные упрощения (осознанные, на стадию П):
  • riser_id назначается эвристикой от стены; в целевой Заре стояки приходят
    из модуля трассировки сети В2, а не отсюда;
  • геометрия — прямоугольная (SP_RECTANGULAR); произвольный контур — позже;
  • проверка покрытия по сетке+границам, не аналитическая.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import sqrt, ceil
from typing import List, Optional, Tuple, Dict, Set

from app.calc.fire_models import PlacementMode, JetParams, FireCabinetNormative


# ============================================================
# ENUMS
# ============================================================

class RoomLayoutMode(str, Enum):
    """Режим геометрии помещения."""
    SP_RECTANGULAR = "sp_rectangular"           # типовое прямоугольное (формула СП)
    LAYOUT_CONSTRAINED = "layout_constrained"   # сложная геометрия (не в MVP)


class CoverageScheme(str, Enum):
    """Трактовка длины/ширины относительно расстановки."""
    LONG_WALLS = "long_walls"
    ONE_LONG_WALL = "one_long_wall"


class SidePattern(str, Enum):
    """Взаимное расположение рядов при TWO_OPPOSITE_SIDES."""
    SYMMETRIC = "symmetric"    # оба ряда «лоб в лоб»
    STAGGERED = "staggered"    # правый ряд смещён на полшага (шахматка)


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class RectangularRoom:
    """Типовое прямоугольное помещение."""
    room_id: str
    length_m: float
    width_m: float
    height_m: float
    layout_mode: RoomLayoutMode = RoomLayoutMode.SP_RECTANGULAR


@dataclass
class FireCabinetPlacement:
    """Размещение одного ПК в локальных координатах помещения (x∈[0,L], y∈[0,B])."""
    cabinet_id: str
    room_id: str
    x_m: float
    y_m: float
    wall_side: str                  # "left" / "right"
    riser_id: Optional[str] = None


@dataclass
class RoomCoverageResult:
    """Результат аналитической расстановки ПК."""
    room_id: str
    spacing_L_m: float
    placements: List[FireCabinetPlacement] = field(default_factory=list)
    pattern: Optional[SidePattern] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class PointCoverage:
    """Покрытие одной контрольной точки."""
    x_m: float
    y_m: float
    covering_cabinets: int          # сколько ПК достаёт до точки
    covering_risers: int            # со скольких разных стояков
    ok: bool                        # выполнено ли требование в этой точке


@dataclass
class CoverageCheckResult:
    """Богатый отчёт по покрытию (спринт: кратность, наихудшие, ризеры)."""
    ok: bool
    min_multiplicity: int = 0                       # мин. число ПК на точку по помещению
    worst_points: List[PointCoverage] = field(default_factory=list)
    insufficient_points: List[Tuple[float, float]] = field(default_factory=list)
    riser_violations: List[Tuple[float, float]] = field(default_factory=list)
    checked_points: int = 0
    notes: List[str] = field(default_factory=list)


# ============================================================
# VALIDATION
# ============================================================

def validate_room(room: RectangularRoom) -> None:
    if room.length_m <= 0:
        raise ValueError("room.length_m must be > 0")
    if room.width_m <= 0:
        raise ValueError("room.width_m must be > 0")
    if room.height_m <= 0:
        raise ValueError("room.height_m must be > 0")
    if room.layout_mode != RoomLayoutMode.SP_RECTANGULAR:
        raise ValueError("This MVP supports only RoomLayoutMode.SP_RECTANGULAR")


def validate_jet(jet: JetParams) -> None:
    if jet.hose_length_m <= 0:
        raise ValueError("jet.hose_length_m must be > 0")
    if jet.compact_jet_radius_m <= 0:
        raise ValueError("jet.compact_jet_radius_m must be > 0")
    if jet.valve_axis_height_m <= 0:
        raise ValueError("jet.valve_axis_height_m must be > 0")


def validate_normative(normative: FireCabinetNormative) -> None:
    if normative.required_jets not in (1, 2):
        raise ValueError("Only required_jets = 1 or 2 are supported in MVP")


# ============================================================
# CORE GEOMETRY / SPACING  (формулы СП, каркас Антона)
# ============================================================

def compute_plan_reach(room_height_m: float, jet: JetParams) -> float:
    """Горизонтальная досягаемость в плане: проекция струи + рукав (lp−2).

        reach = √(Rk² − (H − hk)²) + (lp − 2)

    Rk — радиус компактной струи, H — высота помещения, hk — ось клапана (1,35 м),
    lp — рукав. Это нормативная свёртка СП, не CFD-модель струи.
    """
    validate_jet(jet)
    vertical = room_height_m - jet.valve_axis_height_m
    if vertical < 0:
        raise ValueError("Room height is lower than fire cabinet valve axis height.")
    if jet.compact_jet_radius_m <= vertical:
        raise ValueError(
            "Compact jet radius insufficient to reach the upper point of the room "
            f"(Rk={jet.compact_jet_radius_m} <= H-hk={vertical:.2f})."
        )
    jet_horizontal = sqrt(jet.compact_jet_radius_m ** 2 - vertical ** 2)
    return jet_horizontal + (jet.hose_length_m - 2.0)


def compute_spacing_L(
    room_height_m: float,
    room_width_m: float,
    jet: JetParams,
    placement_mode: PlacementMode,
) -> float:
    """Шаг между ПК L по формуле (1) п. 6.2.12:  L = √(reach² − cross²).

    cross — поперечное плечо: ONE_SIDE → B (весь поперечник),
    TWO_OPPOSITE_SIDES → B/2.
    """
    reach = compute_plan_reach(room_height_m, jet)
    if placement_mode == PlacementMode.ONE_SIDE:
        cross = room_width_m
    elif placement_mode == PlacementMode.TWO_OPPOSITE_SIDES:
        cross = room_width_m / 2.0
    else:
        raise ValueError(f"Unsupported placement_mode: {placement_mode}")
    if reach <= cross:
        raise ValueError(
            "Insufficient reach: hose + compact jet projection cannot cover "
            "room width for the selected placement mode."
        )
    return sqrt(reach ** 2 - cross ** 2)


# ============================================================
# LAYOUT GENERATION  (+ edge_offset из спринта)
# ============================================================

def generate_positions_along_length(
    length_m: float,
    max_spacing_m: float,
    edge_offset_m: float = 0.0,
) -> List[float]:
    """Координаты x вдоль длины с шагом ≤ max_spacing_m.

    edge_offset_m: отступ от торцов — ПК не ставится в самый угол (реализм).
    Расстановка идёт в диапазоне [edge_offset, length−edge_offset]; при этом
    контролируется, что даже от первого ПК до торца ≤ max_spacing (иначе угол
    у торца окажется не орошён).
    """
    if length_m <= 0:
        raise ValueError("length_m must be > 0")
    if max_spacing_m <= 0:
        raise ValueError("max_spacing_m must be > 0")
    if edge_offset_m < 0:
        raise ValueError("edge_offset_m must be >= 0")

    # если отступ съедает всю длину — ставим один ПК по центру
    usable = length_m - 2 * edge_offset_m
    if usable <= 0:
        return [length_m / 2.0]

    intervals = max(1, ceil(usable / max_spacing_m))
    xs = [edge_offset_m + i * usable / intervals for i in range(intervals + 1)]

    # контроль торца: от края ПК-ряда до торца помещения не должно быть больше L,
    # иначе точка в углу у торца не орошается. edge_offset тут не должен
    # превышать max_spacing — если превышает, добавим страховочные точки у торцов.
    if edge_offset_m > max_spacing_m + 1e-9:
        xs = [min(max_spacing_m, edge_offset_m)] + xs + \
             [length_m - min(max_spacing_m, edge_offset_m)]
        xs = sorted(set(round(x, 6) for x in xs))
    return xs


def layout_rectangular_room(
    room: RectangularRoom,
    jet: JetParams,
    normative: FireCabinetNormative,
    edge_offset_m: float = 1.0,
    pattern: SidePattern = SidePattern.SYMMETRIC,
) -> RoomCoverageResult:
    """Расставляет ПК в прямоугольном помещении по аналитике СП.

    edge_offset_m: отступ от торцов (спринт v0.2).
    pattern: при TWO_OPPOSITE_SIDES — симметрия или шахматка.
    """
    validate_room(room)
    validate_jet(jet)
    validate_normative(normative)

    L = compute_spacing_L(room.height_m, room.width_m, jet, normative.placement_mode)
    xs = generate_positions_along_length(room.length_m, L, edge_offset_m)
    placements: List[FireCabinetPlacement] = []

    if normative.placement_mode == PlacementMode.ONE_SIDE:
        for idx, x in enumerate(xs, start=1):
            placements.append(FireCabinetPlacement(
                cabinet_id=f"{room.room_id}_left_{idx}", room_id=room.room_id,
                x_m=x, y_m=0.0, wall_side="left"))

    elif normative.placement_mode == PlacementMode.TWO_OPPOSITE_SIDES:
        left_xs = xs
        right_xs = xs.copy()
        if pattern == SidePattern.STAGGERED and len(xs) >= 2:
            step = xs[1] - xs[0]
            shifted = [x + step / 2.0 for x in xs[:-1]]
            right_xs = [x for x in shifted if 0.0 <= x <= room.length_m] or xs.copy()
        for idx, x in enumerate(left_xs, start=1):
            placements.append(FireCabinetPlacement(
                cabinet_id=f"{room.room_id}_left_{idx}", room_id=room.room_id,
                x_m=x, y_m=0.0, wall_side="left"))
        for idx, x in enumerate(right_xs, start=1):
            placements.append(FireCabinetPlacement(
                cabinet_id=f"{room.room_id}_right_{idx}", room_id=room.room_id,
                x_m=x, y_m=room.width_m, wall_side="right"))
    else:
        raise ValueError(f"Unsupported placement mode: {normative.placement_mode}")

    return RoomCoverageResult(
        room_id=room.room_id, spacing_L_m=L, placements=placements,
        pattern=(pattern if normative.placement_mode == PlacementMode.TWO_OPPOSITE_SIDES else None),
        notes=[f"SP rectangular: L={L:.2f} м, ПК={len(placements)}, "
               f"edge_offset={edge_offset_m} м, pattern={pattern.value}"])


# ============================================================
# RISER ASSIGNMENT  (эвристика MVP — каркас Антона)
# ============================================================

def assign_risers(placements: List[FireCabinetPlacement],
                  normative: FireCabinetNormative) -> List[FireCabinetPlacement]:
    """Назначает riser_id (эвристика стадии П; в целевой Заре — из трассировки В2).

    - different_risers не требуется → все R1;
    - TWO_OPPOSITE_SIDES → левый ряд R1, правый R2;
    - ONE_SIDE → чередование R1/R2 вдоль ряда (чтобы соседние точки видели
      два разных стояка).
    """
    if not placements:
        return placements
    if not normative.require_different_risers:
        for p in placements:
            p.riser_id = "R1"
        return placements
    if normative.placement_mode == PlacementMode.TWO_OPPOSITE_SIDES:
        for p in placements:
            p.riser_id = "R1" if p.wall_side == "left" else "R2"
        return placements
    ordered = sorted(placements, key=lambda p: (p.wall_side, p.x_m, p.y_m))
    for idx, p in enumerate(ordered):
        p.riser_id = "R1" if idx % 2 == 0 else "R2"
    return placements


# ============================================================
# CONTROL POINTS  (спринт: углы + середины + сетка + полосы границ)
# ============================================================

def generate_control_points(room: RectangularRoom, step_m: float = 1.0) -> List[Tuple[float, float]]:
    """Контрольные точки: регулярная сетка + гарантированно углы, середины
    сторон и полосы вдоль границ (самые опасные по покрытию места)."""
    if step_m <= 0:
        raise ValueError("step_m must be > 0")
    pts: Set[Tuple[float, float]] = set()

    # регулярная сетка
    nx = max(1, ceil(room.length_m / step_m))
    ny = max(1, ceil(room.width_m / step_m))
    for i in range(nx + 1):
        x = min(room.length_m, i * step_m)
        for j in range(ny + 1):
            y = min(room.width_m, j * step_m)
            pts.add((round(x, 6), round(y, 6)))

    # углы
    for c in ((0.0, 0.0), (room.length_m, 0.0), (0.0, room.width_m), (room.length_m, room.width_m)):
        pts.add((round(c[0], 6), round(c[1], 6)))
    # середины сторон
    for c in ((room.length_m / 2, 0.0), (room.length_m / 2, room.width_m),
              (0.0, room.width_m / 2), (room.length_m, room.width_m / 2)):
        pts.add((round(c[0], 6), round(c[1], 6)))
    # центр
    pts.add((round(room.length_m / 2, 6), round(room.width_m / 2, 6)))
    return sorted(pts)


def _reach(room_height_m: float, jet: JetParams) -> float:
    return compute_plan_reach(room_height_m, jet)


def _covers(cab: FireCabinetPlacement, px: float, py: float, reach: float) -> bool:
    return sqrt((px - cab.x_m) ** 2 + (py - cab.y_m) ** 2) <= reach + 1e-9


def check_required_jet_coverage(
    room: RectangularRoom,
    placements: List[FireCabinetPlacement],
    jet: JetParams,
    normative: FireCabinetNormative,
    control_step_m: float = 1.0,
    worst_n: int = 20,
) -> CoverageCheckResult:
    """Проверка покрытия: для каждой точки — сколько ПК и сколько разных стояков
    достают. Возвращает кратность, наихудшие точки и отдельно нарушения ризеров."""
    validate_room(room)
    validate_jet(jet)
    validate_normative(normative)

    reach = _reach(room.height_m, jet)
    points = generate_control_points(room, control_step_m)
    coverages: List[PointCoverage] = []
    insufficient: List[Tuple[float, float]] = []
    riser_viol: List[Tuple[float, float]] = []
    min_mult = 10 ** 9

    for px, py in points:
        covering = [c for c in placements if _covers(c, px, py, reach)]
        n_cab = len(covering)
        n_ris = len({c.riser_id for c in covering if c.riser_id is not None})
        min_mult = min(min_mult, n_cab)

        if normative.required_jets == 1:
            ok = n_cab >= 1
        else:  # 2 струи
            if normative.require_different_risers:
                ok = n_ris >= 2
                if n_cab >= 2 and n_ris < 2:
                    riser_viol.append((px, py))  # ПК хватает, но один стояк
            else:
                ok = n_cab >= 2
        if not ok:
            insufficient.append((px, py))
        coverages.append(PointCoverage(px, py, n_cab, n_ris, ok))

    coverages.sort(key=lambda c: (c.covering_cabinets, c.covering_risers))
    return CoverageCheckResult(
        ok=(not insufficient),
        min_multiplicity=(0 if min_mult == 10 ** 9 else min_mult),
        worst_points=coverages[:worst_n],
        insufficient_points=insufficient,
        riser_violations=riser_viol,
        checked_points=len(points),
        notes=[f"проверено точек: {len(points)} (шаг {control_step_m} м)",
               f"required_jets={normative.required_jets}",
               f"require_different_risers={normative.require_different_risers}",
               f"мин. кратность по помещению: {0 if min_mult==10**9 else min_mult}"])


# ============================================================
# HIGH-LEVEL ORCHESTRATION  (+ автовыбор схемы из спринта)
# ============================================================

@dataclass
class FireCabinetLayoutSummary:
    room: RectangularRoom
    normative: FireCabinetNormative
    jet: JetParams
    placement_result: RoomCoverageResult
    coverage_result: CoverageCheckResult


def _score(placement: RoomCoverageResult, coverage: CoverageCheckResult) -> Tuple[int, int]:
    """Критерий выбора схемы: сначала меньше непокрытых точек, затем меньше ПК."""
    return (len(coverage.insufficient_points), len(placement.placements))


def design_fire_cabinets_for_room(
    room: RectangularRoom,
    jet: JetParams,
    normative: FireCabinetNormative,
    control_step_m: float = 1.0,
    edge_offset_m: float = 1.0,
    auto_pattern: bool = True,
) -> FireCabinetLayoutSummary:
    """Расстановка + назначение стояков + проверка покрытия.

    auto_pattern: для TWO_OPPOSITE_SIDES с 2 струями пробует симметрию И шахматку,
    выбирает лучшую (меньше непокрытых точек, при равенстве — меньше ПК).
    Для ONE_SIDE всегда симметрия (шахматки нет).
    """
    two_sides = normative.placement_mode == PlacementMode.TWO_OPPOSITE_SIDES
    patterns = ([SidePattern.SYMMETRIC, SidePattern.STAGGERED]
                if (auto_pattern and two_sides) else [SidePattern.SYMMETRIC])

    best: Optional[FireCabinetLayoutSummary] = None
    best_score: Optional[Tuple[int, int]] = None
    for pat in patterns:
        pr = layout_rectangular_room(room, jet, normative, edge_offset_m, pat)
        assign_risers(pr.placements, normative)
        cov = check_required_jet_coverage(room, pr.placements, jet, normative, control_step_m)
        score = _score(pr, cov)
        if best_score is None or score < best_score:
            best_score = score
            best = FireCabinetLayoutSummary(room, normative, jet, pr, cov)
    return best


# ============================================================
# DEBUG / PRINT HELPERS
# ============================================================

def print_layout_summary(summary: FireCabinetLayoutSummary) -> None:
    r = summary.room
    print("=" * 78)
    print(f"ROOM {r.room_id}: {r.length_m}×{r.width_m}×{r.height_m} м")
    print(f"режим: {summary.normative.placement_mode.value}, струй={summary.normative.required_jets}, "
          f"разные стояки={summary.normative.require_different_risers}")
    print(f"шаг L = {summary.placement_result.spacing_L_m:.2f} м, "
          f"схема={summary.placement_result.pattern.value if summary.placement_result.pattern else '—'}, "
          f"ПК={len(summary.placement_result.placements)}")
    cov = summary.coverage_result
    print(f"покрытие: {'OK' if cov.ok else 'НЕ ОК'}, мин.кратность={cov.min_multiplicity}, "
          f"непокрыто={len(cov.insufficient_points)}, наруш.стояков={len(cov.riser_violations)}")
    print("=" * 78)


def main() -> None:
    # Пример 1: одна струя, одна сторона
    r1 = RectangularRoom("room_01", 24.0, 12.0, 6.0)
    j1 = JetParams(20.0, 12.0)
    n1 = FireCabinetNormative(1, False, PlacementMode.ONE_SIDE)
    print_layout_summary(design_fire_cabinets_for_room(r1, j1, n1))

    # Пример 2: две струи, две стороны, разные стояки, автовыбор схемы
    r2 = RectangularRoom("room_02", 36.0, 18.0, 8.0)
    j2 = JetParams(20.0, 14.0)
    n2 = FireCabinetNormative(2, True, PlacementMode.TWO_OPPOSITE_SIDES)
    print_layout_summary(design_fire_cabinets_for_room(r2, j2, n2))


if __name__ == "__main__":
    main()
