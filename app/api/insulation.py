"""API endpoints для расчёта тепловой изоляции."""
from fastapi import APIRouter, HTTPException

from app.calc.insulation import (
    InsulationParams,
    PipeGvs,
    PipeHvs,
    calculate_insulation,
)
from app.schemas.insulation import (
    GvsResultOutput,
    HvsResultOutput,
    InsulationRequest,
    InsulationResponse,
)

router = APIRouter(prefix="/insulation", tags=["Тепловая изоляция"])


@router.post("/calculate", response_model=InsulationResponse)
def calculate(request: InsulationRequest):
    """
    Расчёт толщины тепловой изоляции трубопроводов
    (СП 30.13330.2020 + СП 61.13330.2012).

    ГВС — защита от теплопотерь. ХВС — защита от конденсата.
    """
    params = InsulationParams(
        location=request.location,
        t_room_manual=request.t_room_manual,
        humidity=request.humidity,
    )
    gvs = [PipeGvs(dn=p.dn, t_water=p.t_water, label=p.label) for p in request.gvs_pipes]
    hvs = [PipeHvs(dn=p.dn, t_water=p.t_water, label=p.label) for p in request.hvs_pipes]

    try:
        result = calculate_insulation(params, gvs, hvs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return InsulationResponse(
        t_room=result.t_room,
        is_parking=result.is_parking,
        gvs=[GvsResultOutput(**g.__dict__) for g in result.gvs],
        hvs=[HvsResultOutput(**h.__dict__) for h in result.hvs],
    )