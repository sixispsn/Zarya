"""
Pydantic-схемы для API подбора счётчиков воды.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MeterMinimumEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    dn_mm: int | None = Field(default=None, gt=0, strict=True)
    q_min_hourly_m3h: float | None = Field(default=None, ge=0, strict=True)
    q_min_passport_m3h: float | None = Field(default=None, gt=0, strict=True)
    passport_reference: str = Field(default="", max_length=500)
    flow_reference: str = Field(default="", max_length=500)


class MeterRequest(BaseModel):
    """Входные данные подбора счётчиков."""
    model_config = ConfigDict(allow_inf_nan=False)
    hws_type: Literal["central", "local"] = Field(
        default="central",
        description="Тип ГВС: central (централизованное) или local (местный нагрев)",
    )
    period_hours: float = Field(default=24.0, gt=0, le=24, description="T - период, ч")
    q_fire_l_per_s: float = Field(default=0.0, ge=0, description="Расход на пожаротушение, л/с")
    inputs_count: int = Field(default=1, ge=1, le=2, description="Количество вводов: 1 или 2")
    is_individual_house: bool = Field(default=False, description="Индивидуальный жилой дом")
    # Из расчёта водопотребления
    q_sec_tot: float = Field(default=0.0, ge=0, description="Секундный общий, л/с")
    q_sec_c: float = Field(default=0.0, ge=0, description="Секундный холодный, л/с")
    q_sec_h: float = Field(default=0.0, ge=0, description="Секундный горячий, л/с")
    q_day_tot: float = Field(default=0.0, ge=0, description="Суточный общий, м³/сут")
    q_day_c: float = Field(default=0.0, ge=0, description="Суточный холодный, м³/сут")
    q_day_h: float = Field(default=0.0, ge=0, description="Суточный горячий, м³/сут")
    q_hr_c: float = Field(default=0.0, ge=0, description="Часовой холодный, м³/ч")
    q_hr_h: float = Field(default=0.0, ge=0, description="Часовой горячий, м³/ч")
    minimum_flow_checks: dict[Literal["total", "cold", "hot"], MeterMinimumEvidenceRequest] = Field(default_factory=dict)


class WaterMeterInfo(BaseModel):
    """Параметры выбранного типоразмера счётчика."""
    d_mm: int
    q_min: float
    q_expl: float
    q_max: float
    q_threshold: float
    s: float
    type: str  # "wing" / "turbine"


class MeterCheckOutput(BaseModel):
    """Результат проверки одного счётчика."""
    label: str
    q_average_m3h: float | None = None
    pass_average: bool | None = None
    meter: WaterMeterInfo
    h_normal: float
    h_limit_normal: float
    pass_normal: bool
    h_fire: float | None
    h_limit_fire: float | None
    pass_fire: bool | None
    need_bypass: bool
    pass_sensitivity: bool | None
    need_combo: bool
    has_fire_check: bool
    minimum_flow_note: str = ""
    minimum_flow_evidence: MeterMinimumEvidenceRequest | None = None


class MeterResponse(BaseModel):
    """Результат подбора счётчиков."""
    hws_type: str
    meters: list[MeterCheckOutput]
    notes: list[str]
