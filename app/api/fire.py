"""
API endpoints для расчёта ВПВ.
"""
from fastapi import APIRouter, HTTPException

from app.calc.fire import FireInput, calculate_fire
from app.schemas.fire import FireRequest, FireResponse

router = APIRouter(prefix="/fire", tags=["Внутреннее пожаротушение (ВПВ)"])


@router.post("/calculate", response_model=FireResponse)
def calculate(request: FireRequest):
    """
    Расчёт расхода на внутреннее пожаротушение по СП 10.13130.2020.

    Определяет число струй и расход в зависимости от типа здания
    (таблицы 7.1/7.2) и параметров пожарного крана (таблица 7.3).
    """
    try:
        result = calculate_fire(FireInput(
            building_type=request.building_type,
            floors=request.floors,
            corridor_length_m=request.corridor_length_m,
            seats=request.seats,
            area_m2=request.area_m2,
            fire_degree=request.fire_degree,
            category=request.category,
            construction_class=request.construction_class,
            volume_thousand_m3=request.volume_thousand_m3,
            dn=request.dn,
            nozzle_mm=request.nozzle_mm,
            hose_m=request.hose_m,
            jet_m=request.jet_m,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return FireResponse(
        required=result.required,
        streams=result.streams,
        q_per_stream=result.q_per_stream,
        q_total=result.q_total,
        pressure_mpa=result.pressure_mpa,
        table_used=result.table_used,
        nozzle_found=result.nozzle_found,
        message=result.message,
    )