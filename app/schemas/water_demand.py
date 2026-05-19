"""
Pydantic-схемы для API расчёта водопотребления.

Эти классы описывают формат данных, которые принимает и возвращает API.
FastAPI автоматически:
- валидирует входные данные;
- генерирует документацию в /docs;
- сериализует ответы в JSON.
"""
from pydantic import BaseModel, Field


class ConsumerGroupInput(BaseModel):
    """Группа потребителей на входе API."""
    code: str = Field(..., description="Код типа потребителя", examples=["office"])
    count: int = Field(..., gt=0, description="Количество потребителей U", examples=[100])
    appliances: int = Field(
        default=0,
        ge=0,
        description="Число приборов N. Если 0 - примем равным count.",
        examples=[0],
    )


class WaterDemandRequest(BaseModel):
    """Входные данные для расчёта водопотребления."""
    groups: list[ConsumerGroupInput] = Field(
        ...,
        min_length=1,
        description="Список групп потребителей",
    )
    period_hours: float = Field(
        default=24.0,
        gt=0,
        le=24,
        description="Период водопотребления T, часов в сутки",
    )
    apply_k06: bool = Field(
        default=False,
        description="Применить коэффициент 0.6 (для бытового корпуса промпредприятия)",
    )


class FlowOutput(BaseModel):
    """Расчёт для одного типа потока."""
    q_sec: float = Field(..., description="Секундный расход, л/с")
    q_hr: float = Field(..., description="Часовой расход, м³/ч")
    q_day: float = Field(..., description="Суточный расход, м³/сут")
    np_value: float = Field(..., description="Значение NP (для отладки)")
    alpha: float = Field(..., description="Коэффициент α по табл. Б.2")
    alpha_hr: float = Field(..., description="Коэффициент α_hr (часовой)")


class WaterDemandResponse(BaseModel):
    """Результат расчёта водопотребления."""
    total: FlowOutput = Field(..., description="Общий поток")
    cold: FlowOutput = Field(..., description="Холодная вода")
    hot: FlowOutput = Field(..., description="Горячая вода")
    sewage_flow: float = Field(..., description="Расход хоз.-бытовых стоков, л/с")
    heat_max_kw: float = Field(..., description="Максимальный тепловой поток на ГВС, кВт")
    heat_avg_kw: float = Field(..., description="Среднечасовой тепловой поток на ГВС, кВт")


class ConsumerNormInfo(BaseModel):
    """Информация о норме потребителя (для справочника)."""
    code: str
    name: str
    unit: str