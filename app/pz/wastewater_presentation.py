"""Saved presentation intent; never a source of pipes or quantities."""
from dataclasses import dataclass
from collections.abc import Mapping
from math import isfinite
from app.pz.section_fan import SectionFanInput


@dataclass(frozen=True)
class SectionMainInput:
    """An explicitly assigned characteristic main, not a measured pipe route.

    DN is nominal, never an inferred outer/inner diameter for hydraulics.
    The same DN applies on both sides of the through junction; its smaller
    riser joins a reducing wye, without a spurious downstream transition.
    """
    dn_mm: int | None = None
    slope: float | None = None
    outlet_invert_m: float | None = None
    discharge_point: str = ""
    source_ref: str = ""
    # Optional evidence for the FINAL collecting segment, never all branches.
    flow_basis: str = "manual"
    design_flow_lps: float | None = None
    outer_diameter_mm: float | None = None
    wall_thickness_mm: float | None = None
    material: str = ""
    manning_n: float | None = None
    roughness_source: str = ""
    # Invert at the START of the shown collecting main. Never inferred from
    # paper length/slope, and never used to dimension other hidden branches.
    start_invert_m: float | None = None
    # Formula 5.7 uses connected fixtures and L from table 5.1, not paper geometry.
    q_hour_max_m3h: float | None = None
    fixtures_count: int | None = None
    receiving_length_m: float | None = None
    fixture_max_lps: float | None = None
    flow_source: str = ""

    def __post_init__(self):
        if self.dn_mm is not None and (isinstance(self.dn_mm, bool) or
                not isinstance(self.dn_mm, int) or not 100 <= self.dn_mm <= 2000):
            raise ValueError("DN магистрали характерного жилого разреза: целое число 100–2000 мм")
        for key in ("slope", "outlet_invert_m", "start_invert_m"):
            value = getattr(self, key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)):
                raise ValueError("Уклон и отметка должны быть конечными числами")
        if self.slope is not None and not 0 < self.slope < 1:
            raise ValueError("Уклон задаётся в м/м: больше 0 и меньше 1; это не проценты")
        if (self.start_invert_m is not None and self.outlet_invert_m is not None
                and self.start_invert_m <= self.outlet_invert_m):
            raise ValueError("Начало самотечной магистрали должно быть выше лотка выпуска")
        for key in ("discharge_point", "source_ref"):
            value = getattr(self, key)
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError("Точка сброса и источник: текст до 200 символов")
        if self.flow_basis not in {"manual", "whole_building", "section_hourly"}:
            raise ValueError("Расход участка: собственный или весь расход здания")
        if self.material not in {"", "pp", "pvc", "pe", "cast_iron", "steel"}:
            raise ValueError("Материал трубы не поддерживается проверкой К1")
        for key in ("design_flow_lps", "outer_diameter_mm", "wall_thickness_mm", "manning_n",
                    "q_hour_max_m3h", "receiving_length_m", "fixture_max_lps"):
            value = getattr(self, key)
            if value is not None and (type(value) not in (int, float) or not isfinite(value) or value <= 0):
                raise ValueError("Расход, размеры трубы и n должны быть положительными конечными числами")
        if self.fixtures_count is not None and (type(self.fixtures_count) is not int or self.fixtures_count <= 0):
            raise ValueError("N: целое положительное число подключённых приборов")
        if not isinstance(self.flow_source, str) or len(self.flow_source) > 200:
            raise ValueError("Основание расхода: текст до 200 символов")
        if (self.outer_diameter_mm is not None and self.wall_thickness_mm is not None
                and self.inner_diameter_mm <= 0):
            raise ValueError("Толщина стенки не оставляет внутреннего сечения трубы")
        if not isinstance(self.roughness_source, str) or len(self.roughness_source) > 200:
            raise ValueError("Источник n: текст до 200 символов")

    @property
    def inner_diameter_mm(self):
        if self.outer_diameter_mm is None or self.wall_thickness_mm is None:
            return None
        return self.outer_diameter_mm - 2 * self.wall_thickness_mm

    @property
    def material_label(self):
        return {"":"не задан", "pp":"полипропилен", "pvc":"ПВХ", "pe":"полиэтилен",
                "cast_iron":"чугун", "steel":"сталь"}[self.material]

    def to_mapping(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping) or set(value) - cls.__dataclass_fields__.keys():
            raise ValueError("Неизвестные параметры магистрали характерного разреза")
        return cls(**value)

    @property
    def missing(self):
        return tuple(label for key, label in (
            ("dn_mm", "DN"), ("slope", "уклон"), ("outlet_invert_m", "лоток выпуска"),
            ("discharge_point", "точка сброса"), ("source_ref", "основание решения"),
        ) if getattr(self, key) is None or getattr(self, key) == "")


@dataclass(frozen=True)
class RepresentativeSectionInput:
    # Only choices not already stored in the engineering model live here.
    # Floors, heights, roof profile and consumers are read afresh from Project.
    basement_kind: str = "unknown"
    drainage: str = "unknown"
    k1: SectionMainInput = SectionMainInput()
    k2: SectionMainInput = SectionMainInput()
    fan: SectionFanInput = SectionFanInput()
    funnel_heated: bool | None = None
    zero_absolute_m: float | None = None
    zero_source_ref: str = ""

    def absolute_level(self, relative_m: float | None) -> float | None:
        # A number without its AR/geodesy/design-assumption reference is not
        # an established datum. Keep relative levels usable independently.
        if self.zero_absolute_m is None or not self.zero_source_ref.strip() or relative_m is None:
            return None
        return self.zero_absolute_m + relative_m

    def __post_init__(self):
        if self.basement_kind not in {"unknown", "none", "basement", "subfloor"}:
            raise ValueError("Неизвестный вид подземного этажа для разреза")
        if self.drainage not in {"unknown", "internal", "external"}:
            raise ValueError("Неизвестный вид водостока для разреза")
        if not isinstance(self.k1, SectionMainInput) or not isinstance(self.k2, SectionMainInput):
            raise ValueError("Ожидаются параметры характерных магистралей")
        if not isinstance(self.fan, SectionFanInput):
            raise ValueError("Ожидается решение фановой вентиляции характерного разреза")
        if self.funnel_heated is not None and type(self.funnel_heated) is not bool:
            raise ValueError("Обогрев воронки: да, нет или отсутствие данных")
        if self.zero_absolute_m is not None and (type(self.zero_absolute_m) not in (int, float)
                or not isfinite(self.zero_absolute_m) or abs(self.zero_absolute_m) > 10000):
            raise ValueError("Абсолютная отметка нуля: конечное число в метрах в пределах ±10000")
        if not isinstance(self.zero_source_ref, str) or len(self.zero_source_ref) > 200:
            raise ValueError("Основание абсолютной отметки: текст до 200 символов")

    def to_mapping(self):
        return {"mode": "representative", "basement_kind": self.basement_kind,
                "drainage": self.drainage, "k1": self.k1.to_mapping(), "k2": self.k2.to_mapping(), "fan": self.fan.to_mapping(),
                "funnel_heated": self.funnel_heated, "zero_absolute_m": self.zero_absolute_m,
                "zero_source_ref": self.zero_source_ref}

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping) or value.get("mode") != "representative":
            raise ValueError("Ожидается описание разреза mode=representative")
        if set(value) - {"mode", "basement_kind", "drainage", "k1", "k2", "fan", "funnel_heated",
                         "zero_absolute_m", "zero_source_ref"}:
            raise ValueError("Неизвестные параметры представления схемы")
        return cls(basement_kind=value.get("basement_kind", "unknown"),
                   drainage=value.get("drainage", "unknown"),
                   k1=SectionMainInput.from_mapping(value.get("k1", {})),
                   k2=SectionMainInput.from_mapping(value.get("k2", {})),
                   fan=SectionFanInput.from_mapping(value.get("fan", {})),
                   funnel_heated=value.get("funnel_heated"), zero_absolute_m=value.get("zero_absolute_m"),
                   zero_source_ref=value.get("zero_source_ref", ""))
