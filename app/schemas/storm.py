"""
Pydantic-схемы для API расчёта водостоков.
"""
from typing import Literal

from pydantic import BaseModel, Field


class StormRequest(BaseModel):
    """Входные данные расчёта водостоков."""
    city_code: str = Field(..., description="Код города", examples=["moscow"])
    roof_area_m2: float = Field(..., gt=0, description="Площадь кровли, м²", examples=[1000])
    walls_area_m2: float = Field(default=0.0, ge=0, description="Площадь примыкающих стен, м²", examples=[0])
    period_years: Literal[1, 2, 3, 5, 10] = Field(
        default=1,
        description="Период расчёта P (раз в N лет): 1, 2, 3, 5 или 10",
    )


class StormCityInfo(BaseModel):
    """Информация о городе."""
    code: str
    name: str
    q20: float
    n: float
    region: str


class StormResponse(BaseModel):
    """Результат расчёта водостоков."""
    city: StormCityInfo = Field(..., description="Данные города")
    period_years: int = Field(..., description="Период P")
    f_calculated_m2: float = Field(..., description="F = F_кр + 0.3×F_ст, м²")
    q20_base: float = Field(..., description="q20 базовое, л/(с·га)")
    gamma: float = Field(..., description="Коэффициент γ для периода P")
    q20_adjusted: float = Field(..., description="q20 × γ, л/(с·га)")
    n: float = Field(..., description="Показатель степени n")
    q5: float = Field(..., description="q5 = 4^n × q20_adj, л/(с·га)")
    q_total_l_per_s: float = Field(..., description="Итоговый расход Q, л/с")