"""Pydantic-схемы для API расчёта тепловой изоляции."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PipeGvsInput(BaseModel):
    dn: int = Field(..., gt=0, description="Условный диаметр DN, мм", examples=[25])
    t_water: float = Field(default=60, description="Температура воды, °С", examples=[60])
    label: str = Field(default="", description="Описание (стояк, магистраль)")


class PipeHvsInput(BaseModel):
    dn: int = Field(..., gt=0, description="Условный диаметр DN, мм", examples=[25])
    t_water: float = Field(default=10, description="Температура воды, °С", examples=[10])
    label: str = Field(default="", description="Описание")


class InsulationRequest(BaseModel):
    location: Literal["room_hot", "room_cold", "parking"] = Field(
        default="room_hot",
        description="Место прокладки: room_hot (отапл., 20°С) / room_cold (ввести t) / parking (5°С)",
    )
    t_room_manual: float = Field(default=5.0, description="Температура помещения для room_cold, °С")
    humidity: Literal[40, 50, 60, 70, 80, 90] = Field(default=60, description="Влажность, %")
    gvs_pipes: list[PipeGvsInput] = Field(default_factory=list, description="Трубы ГВС")
    hvs_pipes: list[PipeHvsInput] = Field(default_factory=list, description="Трубы ХВС")


class GvsResultOutput(BaseModel):
    dn: int
    label: str
    t_water: float
    d_mm: float
    ql: float
    rnl: float
    delta_calc: float
    delta: int


class HvsResultOutput(BaseModel):
    dn: int
    label: str
    t_water: float
    need_insulation: bool
    dt: float
    t_surf: float
    d_mm: float
    delta_calc: Optional[float] = None
    delta: Optional[int] = None


class InsulationResponse(BaseModel):
    t_room: float
    is_parking: bool
    gvs: list[GvsResultOutput]
    hvs: list[HvsResultOutput]