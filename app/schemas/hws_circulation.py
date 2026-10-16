"""Явные исходные предварительного теплового баланса Т3/Т4."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class CirculationLossInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    element_id: str = Field(min_length=1)
    system: Literal["T3", "T4", "equipment"]
    heat_loss_w: float | None = Field(default=None, ge=0)
    basis: str = ""


class CirculationDemandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    components: list[CirculationLossInput] = Field(default_factory=list)
    delta_t_c: float | None = None
    temperature_basis: str = ""
    heat_losses_complete: bool = False


class CirculationDemandResponse(BaseModel):
    status: Literal["needs_data", "preliminary"]
    heat_loss_kw: float | None
    delta_t_c: float | None
    flow_lps: float | None
    flow_m3h: float | None
    missing: list[str]
    notes: list[str]
    method: str


class StagePCirculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    enabled: StrictBool = True
    apartment_building: StrictBool | None = None
    water_towel_rails: StrictBool | None = None
    zones: StrictInt | None = None
    hot_temp_c: float = Field(default=65, strict=True)
    cold_temp_c: float = Field(default=5, strict=True)
    delta_t_c: float | None = Field(default=None, strict=True)
    loss_percent: float | None = Field(default=None, strict=True)
    hot_hour_m3h: float | None = Field(default=None, strict=True)
    stage: Literal["П", "Р"] = "П"
    hws_type: Literal["central", "local", "none"] = "central"
    purpose: Literal["residential", "public", "industrial"] = "residential"
