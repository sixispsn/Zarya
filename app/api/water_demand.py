"""
API endpoints для расчёта водопотребления.
"""
from fastapi import APIRouter, HTTPException

from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.data.sp30_tables import list_consumer_norms
from app.schemas.water_demand import (
    ConsumerNormInfo,
    FlowOutput,
    WaterDemandRequest,
    WaterDemandResponse,
)

router = APIRouter(prefix="/water-demand", tags=["Водопотребление"])


@router.get("/norms", response_model=list[ConsumerNormInfo])
def get_available_norms():
    """
    Получить список доступных типов потребителей (таблица А.2 СП 30).
    """
    norms = list_consumer_norms()
    return [
        ConsumerNormInfo(code=n.code, label=n.label, unit=n.unit)
        for n in norms
    ]


@router.post("/calculate", response_model=WaterDemandResponse)
def calculate(request: WaterDemandRequest):
    """
    Расчёт водопотребления по СП 30.13330.2020.

    Возвращает расчёты для трёх потоков: общего, холодного и горячего,
    а также расход бытовых стоков и тепловые потоки на ГВС.
    """
    groups = [
        ConsumerGroup(code=g.code, count=g.count)
        for g in request.groups
    ]

    try:
        result = calculate_water_demand(
            groups=groups,
            apply_k06=request.apply_k06,
            sewage_max_fixture_lps=request.sewage_max_fixture_lps,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return WaterDemandResponse(
        total=FlowOutput(**result.total.__dict__),
        cold=FlowOutput(**result.cold.__dict__),
        hot=FlowOutput(**result.hot.__dict__),
        sewage_flow=result.sewage_flow,
        sewage_fixture_discharge=result.sewage_fixture_discharge,
        heat_max_kw=result.heat_max_kw,
        heat_avg_kw=result.heat_avg_kw,
    )
