"""Расчёт расхода К1 и проверка явно заданных канализационных стояков.

СП 30.13330.2020, п. 5.5, формула (5):
    q_s = q_tot + q_0s,
где q_0s принимают по таблице А.1 для фактически установленного прибора с
максимальным водоотведением. Legacy-калькулятор всегда подставлял 1,6 л/с;
здесь величина является явным входом расчёта.

Проверка стояков выполняется по приложению К СП 30 только для расхода,
явно назначенного конкретному стояку. Общий расход системы между несколькими
стояками модуль не распределяет: без аксонометрии это было бы выдумкой.
"""
from dataclasses import dataclass, replace
from typing import Optional

from app.data.sewage_tables import (
    MATERIAL_LABELS,
    VENTILATION_LABELS,
    get_riser_capacity,
)


@dataclass(frozen=True)
class DomesticSewageResult:
    q_water_total_lps: float
    q_fixture_max_lps: float
    q_sewage_lps: float


@dataclass(frozen=True)
class SewageRiserInput:
    riser_id: str
    design_flow_lps: float
    material: str
    ventilation: str
    riser_dn_mm: int
    branch_dn_mm: int
    branch_angle_deg: float
    has_toilet: bool = True
    working_height_m: Optional[float] = None


@dataclass(frozen=True)
class SewageRiserCheck:
    riser_id: str
    design_flow_lps: float
    material: str
    material_label: str
    ventilation: str
    ventilation_label: str
    riser_dn_mm: int
    branch_dn_mm: int
    branch_angle_deg: float
    minimum_dn_mm: int
    diameter_ok: bool
    capacity_lps: Optional[float]
    capacity_ok: Optional[bool]
    reserve_lps: Optional[float]
    table: str
    status: str
    note: str


@dataclass(frozen=True)
class SewageSystemResult:
    total: DomesticSewageResult
    risers: tuple[SewageRiserCheck, ...]

    @property
    def checked_risers(self) -> int:
        return sum(row.capacity_lps is not None for row in self.risers)

    @property
    def all_checked_risers_ok(self) -> Optional[bool]:
        checked = [row for row in self.risers if row.capacity_ok is not None]
        if not checked:
            return None
        return all(row.status == "verified" for row in checked)


def calculate_domestic_sewage(
    q_water_total_lps: float,
    q_fixture_max_lps: float,
) -> DomesticSewageResult:
    """Рассчитать q_s по формуле (5) п. 5.5 СП 30.13330.2020."""
    if q_water_total_lps < 0:
        raise ValueError("Расход воды q_tot не может быть отрицательным")
    if q_fixture_max_lps < 0:
        raise ValueError("Расход стоков q_0s не может быть отрицательным")
    return DomesticSewageResult(
        q_water_total_lps=round(q_water_total_lps, 3),
        q_fixture_max_lps=round(q_fixture_max_lps, 3),
        q_sewage_lps=round(q_water_total_lps + q_fixture_max_lps, 3),
    )


def check_sewage_riser(data: SewageRiserInput) -> SewageRiserCheck:
    """Проверить один стояк по точному узлу таблиц приложения К."""
    if not data.riser_id.strip():
        raise ValueError("Марка канализационного стояка не задана")
    if data.design_flow_lps <= 0:
        raise ValueError(
            f"{data.riser_id}: расчётный расход стояка должен быть больше 0"
        )
    if data.material not in MATERIAL_LABELS:
        raise ValueError(
            f"{data.riser_id}: неподдерживаемый материал {data.material!r}"
        )
    if data.ventilation not in VENTILATION_LABELS:
        raise ValueError(
            f"{data.riser_id}: неподдерживаемая схема вентиляции "
            f"{data.ventilation!r}"
        )
    if min(data.riser_dn_mm, data.branch_dn_mm) <= 0:
        raise ValueError(f"{data.riser_id}: диаметры должны быть больше 0")
    if data.branch_angle_deg not in (45.0, 60.0, 87.5):
        raise ValueError(
            f"{data.riser_id}: угол должен быть 45, 60 или 87,5°"
        )
    if data.working_height_m is not None and data.working_height_m <= 0:
        raise ValueError(
            f"{data.riser_id}: рабочая высота должна быть больше 0"
        )

    minimum_dn = 100 if data.has_toilet else 50
    diameter_ok = data.riser_dn_mm >= minimum_dn
    capacity = get_riser_capacity(
        material=data.material,
        ventilation=data.ventilation,
        riser_dn_mm=data.riser_dn_mm,
        branch_dn_mm=data.branch_dn_mm,
        branch_angle_deg=data.branch_angle_deg,
    )

    if data.ventilation == "unventilated":
        return SewageRiserCheck(
            riser_id=data.riser_id,
            design_flow_lps=round(data.design_flow_lps, 3),
            material=data.material,
            material_label=MATERIAL_LABELS[data.material],
            ventilation=data.ventilation,
            ventilation_label=VENTILATION_LABELS[data.ventilation],
            riser_dn_mm=data.riser_dn_mm,
            branch_dn_mm=data.branch_dn_mm,
            branch_angle_deg=data.branch_angle_deg,
            minimum_dn_mm=minimum_dn,
            diameter_ok=diameter_ok,
            capacity_lps=None,
            capacity_ok=None,
            reserve_lps=None,
            table="К.5–К.7",
            status="stage_r",
            note=(
                "Пропускная способность невентилируемого стояка зависит от "
                "рабочей высоты и полного узла подключения. Требуется точная "
                "аксонометрия; интерполяция таблиц К.5–К.7 не выполняется."
            ),
        )

    if capacity is None:
        return SewageRiserCheck(
            riser_id=data.riser_id,
            design_flow_lps=round(data.design_flow_lps, 3),
            material=data.material,
            material_label=MATERIAL_LABELS[data.material],
            ventilation=data.ventilation,
            ventilation_label=VENTILATION_LABELS[data.ventilation],
            riser_dn_mm=data.riser_dn_mm,
            branch_dn_mm=data.branch_dn_mm,
            branch_angle_deg=data.branch_angle_deg,
            minimum_dn_mm=minimum_dn,
            diameter_ok=diameter_ok,
            capacity_lps=None,
            capacity_ok=None,
            reserve_lps=None,
            table="приложение К",
            status="missing",
            note=(
                "Для заданного сочетания материала, диаметров и угла нет "
                "точного табличного узла. Значение не интерполируется."
            ),
        )

    capacity_ok = data.design_flow_lps <= capacity.capacity_lps
    status = "verified" if capacity_ok and diameter_ok else "fail"
    notes = []
    if not diameter_ok:
        notes.append(
            f"DN стояка меньше конструктивного минимума {minimum_dn} мм"
        )
    if not capacity_ok:
        notes.append("расчётный расход превышает табличную пропускную способность")
    if not notes:
        notes.append("диаметр и пропускная способность подтверждены")

    return SewageRiserCheck(
        riser_id=data.riser_id,
        design_flow_lps=round(data.design_flow_lps, 3),
        material=data.material,
        material_label=MATERIAL_LABELS[data.material],
        ventilation=data.ventilation,
        ventilation_label=VENTILATION_LABELS[data.ventilation],
        riser_dn_mm=data.riser_dn_mm,
        branch_dn_mm=data.branch_dn_mm,
        branch_angle_deg=data.branch_angle_deg,
        minimum_dn_mm=minimum_dn,
        diameter_ok=diameter_ok,
        capacity_lps=capacity.capacity_lps,
        capacity_ok=capacity_ok,
        reserve_lps=round(capacity.capacity_lps - data.design_flow_lps, 3),
        table=capacity.table,
        status=status,
        note="; ".join(notes),
    )


def calculate_sewage_system(
    q_water_total_lps: float,
    q_fixture_max_lps: float,
    risers: list[SewageRiserInput],
) -> SewageSystemResult:
    """Собрать единый результат К1 без распределения расхода по стоякам."""
    total = calculate_domestic_sewage(
        q_water_total_lps,
        q_fixture_max_lps,
    )
    checked = []
    for row in risers:
        result = check_sewage_riser(row)
        if row.design_flow_lps > total.q_sewage_lps:
            result = replace(
                result,
                status="fail",
                note=(
                    result.note
                    + "; нагрузка отдельного стояка превышает общий "
                    "расчётный расход системы К1"
                ),
            )
        checked.append(result)
    return SewageSystemResult(total=total, risers=tuple(checked))
