# -*- coding: utf-8 -*-
"""
app/calc/fire_normative.py — нормативный резолвер ВПВ (слой 1 архитектуры).

Убирает ручной ввод Rk и кратности струй: из контекста объекта/помещения
резолвит JetParams (Rk по п. 7.15 или формуле (3) п. 7.16) и FireCabinetNormative
(число струй + требование разных стояков по п. 6.2.2). Дальше эти параметры идут
в fire_layout.py, а не задаются пользователем «галочкой».

Каркас и логика — авторства Антона. Модели JetParams/FireCabinetNormative/
PlacementMode взяты из общего fire_models (без дублирования).

Формула (3) п. 7.16: величина Hp «расчётная компактная часть водяной струи» в
контексте расстановки тождественна Rk (п. 7.15 нормирует «высоту или радиус
действия» одним минимумом), поэтому имя compute_rk_by_formula_7_16 корректно.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from app.calc.fire_models import PlacementMode, JetParams, FireCabinetNormative


# ============================================================
# DOMAIN ENUMS
# ============================================================

class FireSpaceKind(str, Enum):
    """Тип пространства для логики размещения/кратности ПК."""
    ROOM = "room"
    CORRIDOR = "corridor"
    HALL = "hall"
    STORAGE = "storage"


class FireBuildingKind(str, Enum):
    """Укрупнённый тип здания/объекта (только нужное для резолвера СП 10)."""
    RESIDENTIAL = "residential"
    PUBLIC = "public"
    ADMINISTRATIVE = "administrative"
    INDUSTRIAL = "industrial"
    WAREHOUSE = "warehouse"


class FireJetRadiusMode(str, Enum):
    """Режим определения Rk.

    TABLE_7_15_MINIMUM: минимум по п. 7.15.
    FORMULA_7_16: по формуле (3) п. 7.16; итог = max(formula, minimum_7_15).
    AUTO: формула если хватает входных данных, иначе минимум п. 7.15.
    """
    TABLE_7_15_MINIMUM = "table_7_15_minimum"
    FORMULA_7_16 = "formula_7_16"
    AUTO = "auto"


class FireJetNozzleDiameterMM(int, Enum):
    """Диаметры насадка ствола, для которых в табл. 7.4 дана φ."""
    D13 = 13
    D16 = 16
    D19 = 19


class FireJetMultiplicitySource(str, Enum):
    """Источник решения по кратности/разным стоякам."""
    TABLE_7_1 = "table_7_1"
    TABLE_7_1_AND_P_6_2_2 = "table_7_1_and_p_6_2_2"
    MANUAL = "manual"


# ============================================================
# INPUT CONTEXT
# ============================================================

@dataclass
class FireNormativeContext:
    """Нормативный контекст, из которого резолвим параметры ВПВ/ПК.

    building_kind: тип здания для минимума Rk (п. 7.15) и числа ПК (табл. 7.1).
    space_kind: тип пространства (комната/коридор/зал/склад).
    room_height_m: высота помещения.
    room_width_m: ширина; для коридора — порог 10 м по п. 6.2.2.
    building_height_m: высота здания для выбора 6/8/16 м (п. 7.15).
    hose_length_m: длина рукава → JetParams.
    placement_mode: дефолтная схема размещения для layout-слоя.
    required_jets_override: подпорка, пока табл. 7.1 не закодирована.
    jet_radius_mode / nozzle_diameter_mm / pressure_at_nozzle_mpa: для формулы (3).

    Табл. 7.1 (число расчётных ПК) — отдельный пласт СП; в baseline закладываем
    интерфейс, но «таблицу на весь мир» не выдумываем: либо override, либо
    ограниченный проектный резолвер.
    """
    building_kind: FireBuildingKind
    space_kind: FireSpaceKind
    room_height_m: float
    room_width_m: Optional[float]
    building_height_m: float

    hose_length_m: float = 20.0
    valve_axis_height_m: float = 1.35
    placement_mode: PlacementMode = PlacementMode.ONE_SIDE

    required_jets_override: Optional[int] = None

    jet_radius_mode: FireJetRadiusMode = FireJetRadiusMode.TABLE_7_15_MINIMUM
    nozzle_diameter_mm: Optional[FireJetNozzleDiameterMM] = None
    pressure_at_nozzle_mpa: Optional[float] = None


# ============================================================
# OUTPUT MODELS
# ============================================================

@dataclass
class ResolvedJetMultiplicity:
    """Кратность расчётных ПК/струй + признак обязательности разных стояков."""
    required_jets: int
    require_different_risers: bool
    manual_review_required: bool = False
    source: FireJetMultiplicitySource = FireJetMultiplicitySource.MANUAL
    notes: List[str] = field(default_factory=list)


@dataclass
class ResolvedFireNormative:
    """Итог работы fire_normative.py."""
    jet_params: JetParams
    cabinet_normative: FireCabinetNormative
    jet_multiplicity: ResolvedJetMultiplicity
    notes: List[str] = field(default_factory=list)


# ============================================================
# VALIDATION
# ============================================================

def validate_context(ctx: FireNormativeContext) -> None:
    if ctx.room_height_m <= 0:
        raise ValueError("room_height_m must be > 0")
    if ctx.building_height_m <= 0:
        raise ValueError("building_height_m must be > 0")
    if ctx.room_width_m is not None and ctx.room_width_m <= 0:
        raise ValueError("room_width_m must be > 0 when provided")
    if ctx.hose_length_m <= 0:
        raise ValueError("hose_length_m must be > 0")
    if ctx.valve_axis_height_m <= 0:
        raise ValueError("valve_axis_height_m must be > 0")
    if ctx.required_jets_override is not None and ctx.required_jets_override not in (1, 2):
        raise ValueError("required_jets_override must be 1 or 2")
    if ctx.jet_radius_mode == FireJetRadiusMode.FORMULA_7_16:
        if ctx.nozzle_diameter_mm is None:
            raise ValueError("nozzle_diameter_mm is required when jet_radius_mode=FORMULA_7_16")
        if ctx.pressure_at_nozzle_mpa is None:
            raise ValueError("pressure_at_nozzle_mpa is required when jet_radius_mode=FORMULA_7_16")
        if ctx.pressure_at_nozzle_mpa <= 0:
            raise ValueError("pressure_at_nozzle_mpa must be > 0")


# ============================================================
# Rk RESOLUTION
# ============================================================

def resolve_minimum_rk_by_p_7_15(ctx: FireNormativeContext) -> float:
    """Минимальный радиус компактной части струи по п. 7.15:
    - 6 м: жилые/общественные/административные до 50 м;
    - 8 м: жилые свыше 50 м;
    - 16 м: общественные/производственные/административные свыше 50 м.
    warehouse трактуем через industrial-логику при отсутствии более точного правила.
    """
    h = ctx.building_height_m
    bk = ctx.building_kind
    if bk == FireBuildingKind.RESIDENTIAL:
        return 6.0 if h <= 50.0 else 8.0
    if bk in (FireBuildingKind.PUBLIC, FireBuildingKind.ADMINISTRATIVE):
        return 6.0 if h <= 50.0 else 16.0
    if bk in (FireBuildingKind.INDUSTRIAL, FireBuildingKind.WAREHOUSE):
        # >50 м -> 16 м; <=50 м -> 6 м как минимальный fallback (в п. 7.15 для
        # производственных/складских ≤50 м отдельное число не выделено).
        return 6.0 if h <= 50.0 else 16.0
    raise ValueError(f"Unsupported building_kind: {bk}")


def get_phi_for_nozzle(nozzle_diameter_mm: FireJetNozzleDiameterMM) -> float:
    """φ по табл. 7.4: 13→0.0165, 16→0.0129, 19→0.0097."""
    mapping = {
        FireJetNozzleDiameterMM.D13: 0.0165,
        FireJetNozzleDiameterMM.D16: 0.0129,
        FireJetNozzleDiameterMM.D19: 0.0097,
    }
    try:
        return mapping[nozzle_diameter_mm]
    except KeyError:
        raise ValueError(f"Unsupported nozzle diameter: {nozzle_diameter_mm}")


def compute_rk_by_formula_7_16(
    pressure_at_nozzle_mpa: float,
    nozzle_diameter_mm: FireJetNozzleDiameterMM,
) -> float:
    """Формула (3) п. 7.16: Hp = 100·α·P/(1+100·φ·P), α=0.82, φ по табл. 7.4.

    Hp — расчётная компактная часть струи (в контексте расстановки = Rk).
    """
    if pressure_at_nozzle_mpa <= 0:
        raise ValueError("pressure_at_nozzle_mpa must be > 0")
    alpha = 0.82
    phi = get_phi_for_nozzle(nozzle_diameter_mm)
    p = pressure_at_nozzle_mpa
    return (100.0 * alpha * p) / (1.0 + 100.0 * phi * p)


def resolve_compact_jet_radius(ctx: FireNormativeContext) -> tuple[float, List[str]]:
    """Резолвит compact_jet_radius_m: минимум п. 7.15, формула (3), либо AUTO;
    формульное значение не опускается ниже минимума (max)."""
    notes: List[str] = []
    minimum_by_7_15 = resolve_minimum_rk_by_p_7_15(ctx)
    notes.append(f"Минимальный Rk по п. 7.15: {minimum_by_7_15:.2f} м.")

    if ctx.jet_radius_mode == FireJetRadiusMode.TABLE_7_15_MINIMUM:
        notes.append("Rk принят по минимуму п. 7.15.")
        return minimum_by_7_15, notes

    def formula_branch() -> tuple[float, List[str]]:
        if ctx.nozzle_diameter_mm is None or ctx.pressure_at_nozzle_mpa is None:
            raise ValueError("Formula 7.16 requires nozzle_diameter_mm and pressure_at_nozzle_mpa.")
        fv = compute_rk_by_formula_7_16(ctx.pressure_at_nozzle_mpa, ctx.nozzle_diameter_mm)
        return max(fv, minimum_by_7_15), [
            f"Формула (3) п. 7.16 дала {fv:.2f} м.",
            f"Итог Rk = max(формула, минимум) = max({fv:.2f}, {minimum_by_7_15:.2f}) = {max(fv, minimum_by_7_15):.2f} м.",
        ]

    if ctx.jet_radius_mode == FireJetRadiusMode.FORMULA_7_16:
        rk, extra = formula_branch()
        notes.extend(extra)
        return rk, notes

    if ctx.jet_radius_mode == FireJetRadiusMode.AUTO:
        if ctx.nozzle_diameter_mm is not None and ctx.pressure_at_nozzle_mpa is not None:
            rk, extra = formula_branch()
            notes.append("AUTO: входные данные формулы есть, применена формула.")
            notes.extend(extra)
            return rk, notes
        notes.append("AUTO: данных формулы недостаточно, взят минимум п. 7.15.")
        return minimum_by_7_15, notes

    raise ValueError(f"Unsupported jet_radius_mode: {ctx.jet_radius_mode}")


# ============================================================
# REQUIRED JETS / DIFFERENT RISERS
# ============================================================

def resolve_required_jets_from_context(ctx: FireNormativeContext) -> tuple[int, List[str]]:
    """Число расчётных ПК: override, иначе NotImplemented (табл. 7.1 не выдумываем)."""
    notes: List[str] = []
    if ctx.required_jets_override is not None:
        notes.append(f"required_jets из override: {ctx.required_jets_override}.")
        return ctx.required_jets_override, notes
    raise NotImplementedError(
        "Автоопределение required_jets по табл. 7.1 не реализовано. "
        "Передайте required_jets_override или реализуйте проектный резолвер табл. 7.1."
    )


def resolve_required_jets(ctx: FireNormativeContext) -> ResolvedJetMultiplicity:
    """Кратность + признак разных стояков.

    required_jets=1 → False. required_jets=2:
    - коридор >10 м → разные стояки (п. 6.2.2);
    - коридор ≤10 м → один стояк допустим;
    - не-коридор → False + manual_review_required (СП не нормирует разные стояки
      для не-коридорных пространств; кратность обеспечивается геометрией).
    """
    required_jets, req_notes = resolve_required_jets_from_context(ctx)
    notes = list(req_notes)
    src_manual = FireJetMultiplicitySource.MANUAL

    if required_jets == 1:
        notes.append("required_jets=1 → require_different_risers=False.")
        return ResolvedJetMultiplicity(
            required_jets=1, require_different_risers=False, manual_review_required=False,
            source=(FireJetMultiplicitySource.TABLE_7_1 if ctx.required_jets_override is None else src_manual),
            notes=notes)

    if ctx.space_kind == FireSpaceKind.CORRIDOR:
        if ctx.room_width_m is None:
            notes.append("Коридор, но ширина не задана; п. 6.2.2 не применён точно. "
                         "Fallback: require_different_risers=False, нужна ручная проверка.")
            return ResolvedJetMultiplicity(
                required_jets=2, require_different_risers=False, manual_review_required=True,
                source=FireJetMultiplicitySource.TABLE_7_1_AND_P_6_2_2, notes=notes)
        if ctx.room_width_m > 10.0:
            notes.append("П. 6.2.2: коридор >10 м — каждая точка из двух ПК на разных стояках.")
            return ResolvedJetMultiplicity(
                required_jets=2, require_different_risers=True, manual_review_required=False,
                source=FireJetMultiplicitySource.TABLE_7_1_AND_P_6_2_2, notes=notes)
        notes.append("П. 6.2.2: коридор ≤10 м — два ПК допускаются на одном стояке.")
        return ResolvedJetMultiplicity(
            required_jets=2, require_different_risers=False, manual_review_required=False,
            source=FireJetMultiplicitySource.TABLE_7_1_AND_P_6_2_2, notes=notes)

    notes.append("required_jets=2 для не-коридорного пространства. Требование разных "
                 "стояков из СП для такого пространства автоматически не выведено; "
                 "кратность обеспечивается геометрией, стояковый принцип — на уровне сети.")
    return ResolvedJetMultiplicity(
        required_jets=2, require_different_risers=False, manual_review_required=True,
        source=(FireJetMultiplicitySource.TABLE_7_1 if ctx.required_jets_override is None else src_manual),
        notes=notes)


# ============================================================
# HIGH-LEVEL RESOLVER
# ============================================================

def resolve_fire_normative(ctx: FireNormativeContext) -> ResolvedFireNormative:
    """Главный резолвер: Rk + кратность → JetParams + FireCabinetNormative."""
    validate_context(ctx)
    notes: List[str] = []

    compact_jet_radius_m, rk_notes = resolve_compact_jet_radius(ctx)
    notes.extend(rk_notes)

    jm = resolve_required_jets(ctx)
    notes.extend(jm.notes)

    jet = JetParams(
        hose_length_m=ctx.hose_length_m,
        compact_jet_radius_m=compact_jet_radius_m,
        valve_axis_height_m=ctx.valve_axis_height_m,
    )
    cabinet_normative = FireCabinetNormative(
        required_jets=jm.required_jets,
        require_different_risers=jm.require_different_risers,
        placement_mode=ctx.placement_mode,
    )
    return ResolvedFireNormative(
        jet_params=jet, cabinet_normative=cabinet_normative,
        jet_multiplicity=jm, notes=notes)


def resolve_required_jets_table_7_1_project_specific(ctx: FireNormativeContext) -> int:
    """Заготовка под полноценную табл. 7.1 (тип/этажность/объём/Ф-класс)."""
    raise NotImplementedError


def _example() -> None:
    ctx1 = FireNormativeContext(
        building_kind=FireBuildingKind.PUBLIC, space_kind=FireSpaceKind.CORRIDOR,
        room_height_m=3.3, room_width_m=12.0, building_height_m=18.0,
        placement_mode=PlacementMode.TWO_OPPOSITE_SIDES, required_jets_override=2)
    r1 = resolve_fire_normative(ctx1)
    print("EX1 corridor>10:", r1.jet_multiplicity.required_jets,
          r1.jet_multiplicity.require_different_risers, "Rk=", r1.jet_params.compact_jet_radius_m)

    ctx2 = FireNormativeContext(
        building_kind=FireBuildingKind.WAREHOUSE, space_kind=FireSpaceKind.STORAGE,
        room_height_m=8.0, room_width_m=24.0, building_height_m=24.0,
        required_jets_override=2)
    r2 = resolve_fire_normative(ctx2)
    print("EX2 storage:", r2.jet_multiplicity.require_different_risers,
          "manual_review=", r2.jet_multiplicity.manual_review_required)

    ctx3 = FireNormativeContext(
        building_kind=FireBuildingKind.PUBLIC, space_kind=FireSpaceKind.ROOM,
        room_height_m=4.0, room_width_m=8.0, building_height_m=60.0,
        required_jets_override=1, jet_radius_mode=FireJetRadiusMode.FORMULA_7_16,
        nozzle_diameter_mm=FireJetNozzleDiameterMM.D13, pressure_at_nozzle_mpa=0.2)
    r3 = resolve_fire_normative(ctx3)
    print("EX3 formula: Rk=", round(r3.jet_params.compact_jet_radius_m, 2))


if __name__ == "__main__":
    _example()
