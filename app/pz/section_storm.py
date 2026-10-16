"""Current K2 inputs -> existing calculation -> representative drawing.

No split of the building's flow, no hydraulic formula and no cached result.
Riser DN is a design selection checked against the existing capacity table.
"""
from dataclasses import dataclass
from math import isfinite

from app.calc.storm import StormInput, StormNetworkInput, calculate_storm, assess_storm_network


@dataclass(frozen=True)
class SectionStormInput:
    city_code: str = ""
    roof_area_m2: float = 0
    walls_area_m2: float = 0
    period_years: int = 1
    roof_type: str = "not_set"
    selected_riser_dn_mm: int = 0
    risers_count: int = 0
    max_riser_flow_lps: float | None = None
    funnels_on_different_levels: bool = False
    # Actual project quantity; never inferred from the representative symbol.
    funnels_count: int = 0

    def __post_init__(self):
        for key in ("roof_area_m2", "walls_area_m2", "max_riser_flow_lps"):
            value = getattr(self, key)
            if value is not None and (type(value) not in (int, float) or not isfinite(value)
                    or value < 0 or (key == "max_riser_flow_lps" and value == 0)):
                raise ValueError("К2: некорректная площадь или нагрузка стояка")
        for key in ("selected_riser_dn_mm", "risers_count", "funnels_count"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 0:
                raise ValueError("К2: DN и количества элементов — неотрицательные целые числа")
        if type(self.funnels_on_different_levels) is not bool:
            raise ValueError("К2: уровни воронок задаются явно")

    @classmethod
    def from_project(cls, storm):
        return cls(**{key: getattr(storm, key) for key in cls.__dataclass_fields__})

    @property
    def result(self):
        if not self.city_code or self.roof_area_m2 <= 0:
            return None
        return calculate_storm(StormInput(self.city_code, self.roof_area_m2, self.walls_area_m2, self.period_years))

    @property
    def assessment(self):
        result = self.result
        if result is None:
            return None
        return assess_storm_network(result, StormNetworkInput(
            roof_type=self.roof_type, selected_riser_dn_mm=self.selected_riser_dn_mm,
            risers_count=self.risers_count, max_riser_flow_lps=self.max_riser_flow_lps,
            funnels_on_different_levels=self.funnels_on_different_levels))

    @property
    def riser_status(self):
        """Check the declared riser load, not the count of all building risers."""
        a = self.assessment
        if a is None or not self.selected_riser_dn_mm:
            return "pending"
        if a.riser_capacity_ok is False:
            return "fail"
        return "verified" if a.riser_capacity_ok is True else "pending"

    @property
    def aggregate_riser_status(self):
        a = self.assessment
        value = a.aggregate_riser_capacity_ok if a else None
        return "verified" if value is True else "fail" if value is False else "pending"

    @property
    def quantity_notice(self):
        count = (f"Количество воронок в проектных исходных: {self.funnels_count} шт."
                 if self.funnels_count else "Количество воронок по плану кровли не задано.")
        return ("На разрезе показана характерная ветвь К2, а не все воронки и стояки здания. "
                + count + " Количество для спецификации не определяется по символам на схеме.")

    @property
    def notice(self):
        if not self.selected_riser_dn_mm:
            return "DN стояка К2 не задан; общий расход между стояками автоматически не распределяется."
        text = f"Характерный стояк К2 DN{self.selected_riser_dn_mm}: "
        a = self.assessment
        if a is None:
            return text + "для проверки нужен расчёт дождя по текущим исходным."
        if self.riser_status == "verified":
            text += (f"нагрузка {self.max_riser_flow_lps:g} л/с ≤ {a.effective_riser_capacity_lps:g} л/с; "
                     "проверена табличная пропускная способность этого стояка. ")
        elif self.riser_status == "fail":
            text += "НЕ СООТВЕТСТВУЕТ заданной нагрузке; требуется пересмотр решения. "
        else:
            text += "DN принят, проверка нагрузки не завершена; нагрузку по символам на схеме не определяем. "
        if self.aggregate_riser_status == "fail":
            text += "Суммарная способность заданных стояков НЕДОСТАТОЧНА для расхода здания. "
        elif self.aggregate_riser_status == "verified":
            text += "Суммарная табличная способность заданных стояков достаточна. "
        return text + "Это не проверка воронок, горизонтальных труб и всей сети."
