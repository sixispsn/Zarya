"""
Pydantic-схемы для API расчёта водопотребления.
"""
from pydantic import BaseModel, Field


class ConsumerGroupInput(BaseModel):
    """Группа потребителей на входе API."""
    code: str = Field(..., description="Код типа потребителя", examples=["office"])
    count: int = Field(..., gt=0, description="Количество потребителей U", examples=[480])


class WaterDemandRequest(BaseModel):
    """Входные данные для расчёта водопотребления."""
    groups: list[ConsumerGroupInput] = Field(
        ...,
        min_length=1,
        description="Список групп потребителей",
    )
    apply_k06: bool = Field(
        default=False,
        description="Применить коэффициент 0.6 (для бытового корпуса промпредприятия)",
    )
    sewage_max_fixture_lps: float = Field(
        default=1.6,
        ge=0,
        description="q_0s прибора с максимальным водоотведением по таблице А.1, л/с",
    )


class FlowOutput(BaseModel):
    """Расчёт для одного типа потока."""
    q_sec: float = Field(..., description="Секундный расход, л/с")
    q_hr: float = Field(..., description="Часовой расход, м³/ч")
    q_day: float = Field(..., description="Суточный расход, м³/сут")
    np_sec: float = Field(..., description="∑NP секундный (для отладки)")
    np_hr: float = Field(..., description="∑NP часовой")
    q0_avg: float = Field(..., description="Средневзвешенный q0, л/с")
    q0hr_avg: float = Field(..., description="Средневзвешенный q0_hr, л/ч")
    alpha: float = Field(..., description="Коэффициент α по табл. Б.2")
    alpha_hr: float = Field(..., description="Коэффициент α_hr")


class WaterDemandResponse(BaseModel):
    """Результат расчёта водопотребления."""
    total: FlowOutput = Field(..., description="Общий поток")
    cold: FlowOutput = Field(..., description="Холодная вода")
    hot: FlowOutput = Field(..., description="Горячая вода")
    sewage_flow: float = Field(..., description="Расход хоз.-бытовых стоков, л/с")
    sewage_fixture_discharge: float = Field(..., description="q_0s диктующего прибора, л/с")
    heat_max_kw: float = Field(..., description="Максимальный тепловой поток на ГВС, кВт")
    heat_avg_kw: float = Field(..., description="Среднечасовой тепловой поток на ГВС, кВт")


class ConsumerNormInfo(BaseModel):
    """Информация о норме потребителя (для справочника)."""
    code: str
    label: str
    unit: str
