# -*- coding: utf-8 -*-
"""
app/calc/fire_models.py — общие модели слоёв ВПВ (нормативный / layout / placement).

Вынесено сюда, чтобы fire_normative.py и fire_layout.py использовали ОДНИ и те же
JetParams / FireCabinetNormative / PlacementMode, а не дублировали их (иначе при
правке одного дубля второй молча разойдётся). Предложение самого автора каркаса.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlacementMode(str, Enum):
    """Схема размещения ПК в прямоугольном помещении."""
    ONE_SIDE = "one_side"                       # вдоль одной продольной стороны
    TWO_OPPOSITE_SIDES = "two_opposite_sides"   # вдоль двух противоположных


@dataclass
class JetParams:
    """Параметры ПК/струи, влияющие на геометрию покрытия.

    hose_length_m: длина рукава lp, м.
    compact_jet_radius_m: радиус компактной части струи Rk, м
        (нормативный минимум по п. 7.15 или расчёт по формуле (3) п. 7.16).
    valve_axis_height_m: высота оси клапана над полом, по СП 1,35 м (п. 6.2.12).
    """
    hose_length_m: float
    compact_jet_radius_m: float
    valve_axis_height_m: float = 1.35


@dataclass
class FireCabinetNormative:
    """Нормативные требования к покрытию (из блока 1-2, п. 6.2.2).

    required_jets: сколько струй в точке (1 или 2).
    require_different_risers: при 2 струях — из ПК на разных стояках.
    placement_mode: одна сторона / две противоположные.
    """
    required_jets: int
    require_different_risers: bool
    placement_mode: PlacementMode
