"""
API endpoints для расчёта полива.
"""
from fastapi import APIRouter, HTTPException

from app.calc.irrigation import IrrigationInput, calculate_irrigation
from app.schemas.irrigation import (
    IrrigationItemOutput,
    IrrigationRequest,
    IrrigationResponse,
)

router = APIRouter(prefix="/irrigation", tags=["Полив территории"])


@router.post("/calculate", response_model=IrrigationResponse)
def calculate(request: IrrigationRequest):
    """
    Расчёт расхода воды на полив территории по СП 30.13330.2020 (п. 26-27).

    Возвращает суточный летний расход (поливка) и зимний (заливка катка).
    Полив учитывается в водопотреблении, но НЕ в стоках (п. 5.13 СП 30).
    """
    data = IrrigationInput(
        grass_m2=request.grass_m2,
        football_m2=request.football_m2,
        sport_m2=request.sport_m2,
        paving_m2=request.paving_m2,
        paving_norm=request.paving_norm,
        lawn_m2=request.lawn_m2,
        lawn_soil=request.lawn_soil,
        rink_m2=request.rink_m2,
        irrigation_times=request.irrigation_times,
    )
    try:
        result = calculate_irrigation(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return IrrigationResponse(
        summer_m3_per_day=result.summer_m3_per_day,
        winter_m3_per_season=result.winter_m3_per_season,
        irrigation_times=result.irrigation_times,
        items=[IrrigationItemOutput(**i.__dict__) for i in result.items],
    )