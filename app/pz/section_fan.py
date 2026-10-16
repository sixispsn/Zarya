"""Explicit fan decisions for a representative cutaway, never a full-network audit.

Reuse SP30 checks. Paper axes are presentation only: not route lengths or a
source of takeoff quantities. A collector needs its own declared AR space.
"""
from dataclasses import dataclass, fields
from collections.abc import Mapping
from math import isfinite
import re

from app.pz.wastewater_ventilation import (
    ROOF_VENT_HEIGHT_M, FanRiser, FanTerminal, FanVentilationInput, audit_fan_ventilation,
)


@dataclass(frozen=True)
class SectionFanInput:
    mode: str = "auto"  # auto / individual / common / unresolved
    height_m: float | None = None
    member_ids: tuple[str, ...] = ()
    roof_level_m: float | None = None
    space: str = "unknown"
    space_floor_m: float | None = None
    collector_low_m: float | None = None
    collector_high_m: float | None = None
    source_ref: str = ""
    building_attic_kind: str = "unknown"  # Existing building answer, not a second UI question.
    working_diameter_mm: int | None = None  # Explicit homogeneous representative group, not sizing.
    opening_distance_m: float | None = None
    no_openings_confirmed: bool | None = None
    attic_insulated: bool | None = None
    plastic_exposed: bool | None = None
    uv_protected: bool | None = None

    def __post_init__(self):
        if self.mode not in {"auto", "individual", "common", "unresolved"}:
            raise ValueError("Неизвестное решение фановой вентиляции")
        if self.space not in {"unknown", "cold_attic", "warm_attic", "technical_storey"}:
            raise ValueError("Укажите чердак или технический этаж; трасса в квартирах не моделируется")
        if self.building_attic_kind not in {"unknown", "none", "cold", "warm", "technical"}:
            raise ValueError("Неизвестный вид чердака в исходных здания")
        if (not isinstance(self.member_ids, tuple) or len(self.member_ids) > 8 or
                any(not isinstance(x, str) or not re.fullmatch(r"[КK]1(?:[-.][\w.-]+)?", x) or len(x) > 24 for x in self.member_ids)
                or len(set(self.member_ids)) != len(self.member_ids)):
            raise ValueError("Укажите до 8 различных марок стояков К1")
        for name in ("height_m", "roof_level_m", "space_floor_m", "collector_low_m", "collector_high_m"):
            v = getattr(self, name)
            if v is not None and (type(v) not in (int, float) or not isfinite(v)):
                raise ValueError("Отметки и высота вытяжки должны быть конечными числами")
        if self.height_m is not None and not 0 < self.height_m <= 20:
            raise ValueError("Высота вытяжки над кровлей: больше 0 и до 20 м")
        if self.working_diameter_mm is not None and (type(self.working_diameter_mm) is not int
                or not 100 <= self.working_diameter_mm <= 2000):
            raise ValueError("DN одинаковых рабочих стояков К1: целое число 100–2000 мм")
        if self.opening_distance_m is not None and (type(self.opening_distance_m) not in (int, float)
                or not isfinite(self.opening_distance_m) or self.opening_distance_m < 0):
            raise ValueError("Расстояние до открываемых окон/балконов: неотрицательное число")
        for name in ("no_openings_confirmed", "attic_insulated", "plastic_exposed", "uv_protected"):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                raise ValueError(f"{name}: да, нет или отсутствие данных")
        if not isinstance(self.source_ref, str) or len(self.source_ref) > 200:
            raise ValueError("Основание решения вентиляции: текст до 200 символов")

    def to_mapping(self):
        return {f.name: list(self.member_ids) if f.name == "member_ids" else getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping) or set(value) - cls.__dataclass_fields__.keys():
            raise ValueError("Неизвестные параметры вентиляции характерного разреза")
        data = dict(value)
        if "member_ids" in data:
            if not isinstance(data["member_ids"], (list, tuple)):
                raise ValueError("Марки стояков должны быть списком")
            data["member_ids"] = tuple(data["member_ids"])
        return cls(**data)


@dataclass(frozen=True)
class SectionFanPlan:
    kind: str  # individual / common / pending
    height_m: float | None
    height_is_minimum: bool
    reason: str
    source: SectionFanInput
    checks: tuple = ()

    @property
    def diameter_mm(self):
        # Existing 18.19/18.20 rule, verified by audit_fan_ventilation below.
        # The explicit field declares identical working DNs for this group.
        return self.source.working_diameter_mm if self.kind != "pending" else None

    @property
    def diameter_notice(self):
        dn = self.diameter_mm
        return (f"Рабочие стояки показанной типовой группы DN{dn}; вытяжка" +
                (" и сборный вентиляционный трубопровод" if self.kind == "common" else "") +
                f" DN{dn}. Основание: СП 30, 18.19–18.20. Это не проверка пропускной способности стояков."
                if dn else "DN вытяжки не определён: нужны диаметры рабочих стояков группы.")

    @property
    def dimension(self):
        if self.height_m is None:
            return ""
        return ("≥" if self.height_is_minimum else "") + f"{self.height_m*1000:g}"

    @property
    def notice(self):
        if self.kind == "pending":
            return "Фановая вентиляция: " + self.reason
        height = ("не менее " if self.height_is_minimum else "") + f"{self.height_m:g}".replace(".", ",")
        if self.kind == "common":
            return (f"Общая открытая вытяжка {len(self.source.member_ids)} стояков, {height} м над кровлей; "
                    "коллектор в техническом пространстве по указанным отметкам, со стоком конденсата к первому стояку.")
        return f"Самостоятельные открытые фановые выводы: {height} м над местной кровлей; размещение и отступы уточнить по АР."


def resolve_section_fan(roof_kind: str, floors: int, floor_height_m: float, data: SectionFanInput) -> SectionFanPlan:
    minimum = ROOF_VENT_HEIGHT_M.get(roof_kind)
    height = data.height_m if data.height_m is not None else minimum
    def pending(reason, checks=()):
        return SectionFanPlan("pending", height, data.height_m is None, reason, data, checks)
    if minimum is None or data.mode == "unresolved":
        return pending("Решение уточнить по АР/ВК.")
    if data.mode == "auto" and roof_kind == "flat_accessible":
        return pending("Кровля эксплуатируемая: нужна группа минимум 4 стояков. Трасса объединения не задана.")
    common = data.mode == "common"
    ids = data.member_ids if common else ("К1-А", "К1-Б")
    if common and len(ids) < 2:
        return pending("Задайте марки стояков общей вытяжки; число линий разреза не равно числу стояков дома.")
    # Unknown actual DN/window/UV evidence stays pending. Only topology/height
    # failures prevent drawing this preliminary decision, never a release flag.
    # These two properties are explicit in the displayed design: a separate
    # open pipe. They certify the representative decision, not site inspection.
    args = dict(kind="roof", height_m=height, source_ref=data.source_ref,
        diameter_mm=data.working_diameter_mm,
        collector_diameter_mm=data.working_diameter_mm if common else None,
        opening_distance_m=data.opening_distance_m, no_openings_confirmed=data.no_openings_confirmed,
        open_end_confirmed=True, separate_from_other_systems=True,
        cold_attic=None if data.space == "unknown" else data.space == "cold_attic",
        attic_insulated=data.attic_insulated, plastic_exposed=data.plastic_exposed,
        uv_protected=data.uv_protected,
        condensate_drains_to_risers=(True if common and data.collector_low_m is not None and
            data.collector_high_m is not None and data.collector_low_m < data.collector_high_m else None))
    terminals = ((FanTerminal("Общая-вытяжка", ids, **args),) if common else
                 tuple(FanTerminal("Вытяжка-"+rid, (rid,), **args) for rid in ids))
    audit = audit_fan_ventilation(roof_kind=roof_kind, residential=True,
        risers=tuple(FanRiser(rid, data.working_diameter_mm, "ventilated", "Характерный-выпуск-К1") for rid in ids),
        evidence=FanVentilationInput(terminals))
    failures = [c for c in audit.checks if c.status == "fail"]
    if failures:
        return pending("; ".join(dict.fromkeys(c.message for c in failures)), audit.checks)
    if common:
        if roof_kind not in {"flat_accessible", "flat_non_accessible"}:
            return pending("Общая вытяжка под скатной кровлей требует отдельного разреза АР.", audit.checks)
        if data.space == "unknown" or not data.source_ref.strip():
            return pending("Укажите техническое пространство и источник АР; объединение в квартирах не рисуем.", audit.checks)
        declared = {"cold":"cold_attic", "warm":"warm_attic", "technical":"technical_storey", "none":"none"}
        if data.building_attic_kind != "unknown" and declared[data.building_attic_kind] != data.space:
            return pending("Место объединения противоречит виду чердака в блоке «Здание». Согласуйте исходные АР.", audit.checks)
        levels = (data.space_floor_m, data.collector_low_m, data.collector_high_m, data.roof_level_m)
        if any(x is None for x in levels):
            return pending("Нужны отметки пола технического пространства, обоих концов коллектора и кровли.", audit.checks)
        if not floors*floor_height_m - 1e-9 <= levels[0] < levels[1] < levels[2] < levels[3]:
            return pending("Коллектор должен быть выше жилых этажей: пол техпространства < низ коллектора < верх < кровля.", audit.checks)
    return SectionFanPlan("common" if common else "individual", height, data.height_m is None, "", data, audit.checks)
