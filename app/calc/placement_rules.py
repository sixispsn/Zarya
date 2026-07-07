# -*- coding: utf-8 -*-
"""
app/calc/placement_rules.py — генератор допустимых позиций ПК (слой 2 архитектуры).

Отделяет вопрос «ГДЕ можно ставить ПК» от «СКОЛЬКО их нужно» (слой 3, fire_layout).
По СП 10 п. 6.2.1 ПК размещают на путях эвакуации, у выходов, в вестибюлях,
коридорах; НЕ размещают в незадымляемых лестничных клетках и безопасных зонах.

В этом baseline реализован только контракт + прямоугольный адаптер
(RectangularWallPlacementEngine), который генерирует позиции вдоль стен без учёта
дверей/лестниц/запретных зон. Полноценный PlanAwarePlacementEngine (по контурам
плана из АР) — точка расширения на будущее, интерфейс под него уже готов.

Каркас — по плану Антона (Этап B двухходовки).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import List, Protocol, runtime_checkable

from app.calc.fire_models import PlacementMode
# RectangularRoom живёт в fire_layout; импортируем лениво в адаптере, чтобы
# не создавать жёсткую связь слоёв на уровне импорта модуля.


@dataclass
class CandidatePosition:
    """Допустимая позиция установки ПК (кандидат для слоя 3).

    x_m, y_m: координаты в локальной системе помещения.
    wall_side: "left"/"right" — сторона, к которой отнесён кандидат.
    reason: почему позиция допустима ("wall", "corridor", "exit", "lobby").
    """
    x_m: float
    y_m: float
    wall_side: str
    reason: str = "wall"


@runtime_checkable
class PlacementRuleEngine(Protocol):
    """Контракт движка размещения: из геометрии/плана даёт допустимые позиции ПК.

    Слой 3 (fire_layout) просит у движка кандидатов и выбирает из них по шагу L,
    вместо того чтобы самому «выдумывать» точки на стене.
    """
    def generate_candidates(self, room, mode: PlacementMode) -> List[CandidatePosition]:
        ...


@dataclass
class RectangularWallPlacementEngine:
    """MVP-движок: кандидаты вдоль продольных стен прямоугольного помещения.

    Без учёта дверей/выходов/запретных зон — только геометрия стен. Плотность
    кандидатов управляется candidate_step_m; edge_offset_m держит их не в самом углу.
    Слой 3 сам проредит кандидатов до нужного шага L.

    mode:
      ONE_SIDE — кандидаты только вдоль стороны y=0;
      TWO_OPPOSITE_SIDES — вдоль y=0 и y=width.
    """
    candidate_step_m: float = 1.0
    edge_offset_m: float = 1.0

    def generate_candidates(self, room, mode: PlacementMode) -> List[CandidatePosition]:
        if self.candidate_step_m <= 0:
            raise ValueError("candidate_step_m must be > 0")
        if self.edge_offset_m < 0:
            raise ValueError("edge_offset_m must be >= 0")

        length = room.length_m
        width = room.width_m
        usable = length - 2 * self.edge_offset_m
        if usable <= 0:
            xs = [length / 2.0]
        else:
            n = max(1, ceil(usable / self.candidate_step_m))
            xs = [self.edge_offset_m + i * usable / n for i in range(n + 1)]

        two_sides = (mode == PlacementMode.TWO_OPPOSITE_SIDES)
        out: List[CandidatePosition] = []
        for x in xs:
            out.append(CandidatePosition(round(x, 6), 0.0, "left", "wall"))
        if two_sides:
            for x in xs:
                out.append(CandidatePosition(round(x, 6), width, "right", "wall"))
        return out


@dataclass
class PlanAwarePlacementEngine:
    """Будущий движок по реальной планировке (контуры/двери/лестницы из АР).

    Пока не реализован — заглушка, фиксирующая контракт. Когда появится источник
    плановой геометрии, здесь генерируются только НОРМАТИВНО допустимые позиции
    (п. 6.2.1: пути эвакуации/выходы/вестибюли; запрет — незадымляемые лестничные
    клетки, безопасные зоны), а слой 3 остаётся без изменений.
    """
    def generate_candidates(self, room, mode: PlacementMode) -> List[CandidatePosition]:
        raise NotImplementedError(
            "PlanAwarePlacementEngine требует плановой геометрии (контуры/двери/"
            "лестницы). Пока используйте RectangularWallPlacementEngine."
        )


def select_cabinets_from_candidates(
    candidates: List[CandidatePosition],
    spacing_L_m: float,
    *,
    side: str = "left",
) -> List[CandidatePosition]:
    """Прореживает кандидатов одной стороны до шага ≤ L (жадно слева направо).

    Вспомогалка для слоя 3: из плотного ряда кандидатов оставляет те, что нужны
    для соблюдения шага L. Возвращает выбранные позиции указанной стороны.
    """
    if spacing_L_m <= 0:
        raise ValueError("spacing_L_m must be > 0")
    row = sorted((c for c in candidates if c.wall_side == side), key=lambda c: c.x_m)
    if not row:
        return []
    chosen = [row[0]]
    for c in row[1:]:
        if c.x_m - chosen[-1].x_m >= spacing_L_m - 1e-9:
            chosen.append(c)
    # гарантируем последнюю точку ряда (торец)
    if chosen[-1].x_m < row[-1].x_m - 1e-9:
        chosen.append(row[-1])
    return chosen


def uniform_positions_along_length(
    length_m: float,
    max_spacing_m: float,
    edge_offset_m: float = 0.0,
) -> List[float]:
    """Равномерные координаты x вдоль длины с шагом ≤ max_spacing_m.

    Слой 3 использует это для типовой прямоугольной расстановки (шаг ровно L,
    точки равномерны). В отличие от select_cabinets_from_candidates (прореживание
    плотной решётки) — здесь точки ставятся сразу равномерно. Это «изменение №2»
    в варианте, сохраняющем выверенную геометрию прямоугольного случая.

    edge_offset_m: отступ от торцов — ПК не в самом углу. Диапазон
    [edge_offset, length−edge_offset]; при edge_offset > max_spacing добавляются
    страховочные точки у торцов, чтобы углы не выпали.
    """
    if length_m <= 0:
        raise ValueError("length_m must be > 0")
    if max_spacing_m <= 0:
        raise ValueError("max_spacing_m must be > 0")
    if edge_offset_m < 0:
        raise ValueError("edge_offset_m must be >= 0")

    usable = length_m - 2 * edge_offset_m
    if usable <= 0:
        return [length_m / 2.0]
    intervals = max(1, ceil(usable / max_spacing_m))
    xs = [edge_offset_m + i * usable / intervals for i in range(intervals + 1)]
    if edge_offset_m > max_spacing_m + 1e-9:
        xs = [min(max_spacing_m, edge_offset_m)] + xs + \
             [length_m - min(max_spacing_m, edge_offset_m)]
        xs = sorted(set(round(x, 6) for x in xs))
    return xs


if __name__ == "__main__":
    from app.calc.fire_layout import RectangularRoom
    room = RectangularRoom("demo", 36.0, 18.0, 8.0)
    eng = RectangularWallPlacementEngine(candidate_step_m=1.0, edge_offset_m=1.0)
    cands = eng.generate_candidates(room, PlacementMode.TWO_OPPOSITE_SIDES)
    print(f"кандидатов всего: {len(cands)} (обе стороны)")
    print(f"из них левая сторона: {sum(1 for c in cands if c.wall_side=='left')}")
    sel = select_cabinets_from_candidates(cands, spacing_L_m=12.0, side="left")
    print(f"выбрано по шагу L=12: {[round(c.x_m,1) for c in sel]}")
    print(f"движок реализует контракт: {isinstance(eng, PlacementRuleEngine)}")
