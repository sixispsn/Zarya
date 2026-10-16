"""Inputs are optional to return a precise missing-data list, never defaults."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SuctionLossRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str
    covers: list[str] = Field(min_length=1)
    loss_m: float | None = Field(None, ge=0)
    flow_m3h: float | None = Field(None, gt=0)
    temperature_c: float | None = None
    basis: str = ""


class SuctionPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    required_components: list[str] = Field(min_length=1)
    losses: list[SuctionLossRequest] = Field(default_factory=list)
    path_basis: str = Field("", description="Границы давления/патрубка, режим арматуры, основание расчёта пути")


class NpshaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pressure_kind: Literal["absolute", "gauge"] | None = None
    pressure_bar: float | None = Field(None, description="Давление в исходном сечении, бар; вид задаётся отдельно")
    atmospheric_pressure_bar: float | None = Field(None, gt=0, description="Только для избыточного давления; не назначается по умолчанию")
    source_elevation_m: float | None = Field(None, description="Отметка исходного сечения давления / уровня резервуара, м")
    pump_elevation_m: float | None = Field(None, description="Отметка оси всасывания насоса, в той же системе, м")
    suction_losses_m: float | None = Field(None, ge=0, description="Все потери от исходного сечения до насоса при максимальном рабочем режиме, м")
    suction_path: SuctionPathRequest | None = Field(None, description="Вместо готового Hf: привязка готовых потерь к одному пути, не распределение по параллельным ветвям")
    vapor_head_m: float | None = Field(None, ge=0, description="Hv по источнику для заданной температуры, м")
    max_flow_m3h: float | None = Field(None, gt=0, description="Максимальная рабочая подача одного насоса, м³/ч")
    temperature_c: float | None = None
    basis: str = Field("", description="Источники давления, отметок, режима, потерь и Hv; не заполняются автоматически")
    npshr_m: float | None = Field(None, ge=0, description="NPSHr при той же максимальной подаче, м")
    npshr_basis: str = Field("", description="Модель, кривая и расход для NPSHr")
    safety_margin_m: float = Field(0.5, ge=0.5, description="Hs: опубликованный минимум CNP 0,5 м, допускается увеличить")


class ProjectSuctionInput(BaseModel):
    """Persist explicit inputs and their binding, never a cached acceptance."""
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    route_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    balance: NpshaRequest
    path_basis: str = Field('', max_length=4000)
    losses: list[SuctionLossRequest] = Field(default_factory=list, max_length=200)

    @model_validator(mode='before')
    @classmethod
    def forbid_numeric_bools(cls, value):
        if isinstance(value, dict):
            losses = value.get('losses', [])
            rows = [value.get('balance', {}), *(losses if isinstance(losses, list) else [])]
            if any(isinstance(row, dict) and any(isinstance(v, bool) for v in row.values())
                   for row in rows):
                raise ValueError('Числовые исходные не принимают true/false')
        return value


def persisted_suction(draft):
    saved = draft.get('suction_check')
    if not saved:
        return None
    data = {k: v for k, v in saved['inputs'].items() if k not in ('revision', 'reviewed')}
    return ProjectSuctionInput.model_validate(data).model_dump()
