"""Pydantic-схемы для API подбора насосов."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PumpRequest(BaseModel):
    q_design_m3h: float = Field(..., gt=0, description="Расчётный расход, м³/ч", examples=[5])
    pump_type: Literal["boost", "circ", "fire"] = Field(default="boost", description="Тип насоса")
    mode: Literal["1", "2p", "2s"] = Field(default="1", description="1 / 2 параллельно (2p) / 2 последовательно (2s)")
    h_geom_manual: Optional[float] = Field(default=None, description="H_geom вручную, м (если не задано — по этажам)")
    floors: Optional[int] = Field(default=None, ge=1, description="Число этажей, если не заданы отметки")
    floor_height: float = Field(default=3.0, gt=0, description="Высота этажа, м")
    h_losses: Optional[float] = Field(default=None, ge=0, description="Потери ΣH_l при Qрасч, м; требуется задать")
    h_pr: float = Field(default=20.0, ge=0, description="Свободный напор у прибора, м")
    h_gar: Optional[float] = Field(default=None, ge=0, description="Гарантированный напор сети по ТУ, м; обязателен для повысительного режима")
    npsh_a: Optional[float] = Field(default=None, ge=0, description="Располагаемый кавитационный запас системы, м")
    circulation_head_m: Optional[float] = Field(default=None, gt=0, description="Т4: отдельный напор по расчёту циркуляционного кольца, м")
    circulation_basis: str = Field(default="", description="Т4: основание Q/H; теплопотери, температурный режим, расчёт кольца")


class CurvePointOutput(BaseModel):
    q: float
    h: float


class WorkingPointOutput(BaseModel):
    q: float
    h: float
    h_sys: float


class PumpInfoOutput(BaseModel):
    model: str
    brand: str
    type: str
    p_kw: float
    p_max_bar: float
    npshr: Optional[float]
    q_opt: float
    note: str
    archived: bool


class PumpCandidateOutput(BaseModel):
    pump: PumpInfoOutput
    working_point: WorkingPointOutput
    score: int
    h_excess_pct: float
    q_ratio: float
    npsh_ok: Optional[bool]
    npshr_at_working_point: Optional[float]
    reasons: list[str]
    curve: list[CurvePointOutput]  # для построения графика на фронте
    head_at_design: Optional[float] = None


class PumpResponse(BaseModel):
    q_design: float
    required: bool
    curve_kind: str
    notes: list[str]
    h_required: float
    h_geom: Optional[float]
    h_stat: Optional[float]
    k_sys: Optional[float]
    candidates: list[PumpCandidateOutput]
