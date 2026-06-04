"""
Pydantic-схемы для API расчёта полива.
"""
from typing import Literal

from pydantic import BaseModel, Field


class IrrigationRequest(BaseModel):
    """Входные данные для расчёта полива."""
    grass_m2: float = Field(default=0.0, ge=0, description="Травяной покров, м²")
    football_m2: float = Field(default=0.0, ge=0, description="Футбольное поле, м²")
    sport_m2: float = Field(default=0.0, ge=0, description="Прочие спортивные сооружения, м²")
    paving_m2: float = Field(default=0.0, ge=0, description="Усоверш. покрытия, тротуары, м²")
    paving_norm: Literal["0.4", "0.5"] = Field(
        default="0.5",
        description="Норма для покрытий: 0.4 или 0.5 л/м²",
    )
    lawn_m2: float = Field(default=0.0, ge=0, description="Газоны / насаждения / цветники, м²")
    lawn_soil: Literal["sand", "loam", "clay"] = Field(
        default="loam",
        description="Тип грунта: песок (sand) / суглинок (loam) / глина (clay)",
    )
    rink_m2: float = Field(default=0.0, ge=0, description="Каток (заливка), м²")
    irrigation_times: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Число поливок в сутки (примечание 6, обычно 1)",
    )


class IrrigationItemOutput(BaseModel):
    """Одна строка результата (для детализации)."""
    name: str
    area_m2: float
    norm_l_per_m2: float
    value_m3: float


class IrrigationResponse(BaseModel):
    """Результат расчёта полива."""
    summer_m3_per_day: float = Field(
        ...,
        description="Суточный летний расход, м³/сут",
    )
    winter_m3_per_season: float = Field(
        ...,
        description="Зимний расход на заливку катка, м³ (разово)",
    )
    irrigation_times: int = Field(
        ...,
        description="Число поливок в сутки (для информации)",
    )
    items: list[IrrigationItemOutput] = Field(
        default_factory=list,
        description="Детализация по строкам",
    )