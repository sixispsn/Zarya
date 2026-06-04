"""
API endpoints для подбора счётчиков воды.
"""
from fastapi import APIRouter, HTTPException

from app.calc.water_meters import MeterInput, calculate_meters
from app.data.water_meters import WATER_METERS
from app.schemas.water_meters import (
    MeterCheckOutput,
    MeterRequest,
    MeterResponse,
    WaterMeterInfo,
)

router = APIRouter(prefix="/meters", tags=["Подбор счётчиков"])


@router.get("/list", response_model=list[WaterMeterInfo])
def get_meter_list():
    """Получить список типоразмеров счётчиков (таблица 12.1 СП 30)."""
    return [
        WaterMeterInfo(
            d_mm=m.d_mm,
            q_min=m.q_min,
            q_expl=m.q_expl,
            q_max=m.q_max,
            q_threshold=m.q_threshold,
            s=m.s,
            type=m.type,
        )
        for m in WATER_METERS
    ]


@router.post("/calculate", response_model=MeterResponse)
def calculate(request: MeterRequest):
    """
    Подбор счётчиков воды по СП 30.13330.2020 (п. 12.14-12.17).

    Возвращает список выбранных счётчиков с тремя проверками:
    (а) потери при норм. расходе, (б) с пожарным, (в) чувствительность.
    """
    try:
        result = calculate_meters(MeterInput(
            hws_type=request.hws_type,
            period_hours=request.period_hours,
            q_fire_l_per_s=request.q_fire_l_per_s,
            inputs_count=request.inputs_count,
            is_individual_house=request.is_individual_house,
            q_sec_tot=request.q_sec_tot,
            q_sec_c=request.q_sec_c,
            q_sec_h=request.q_sec_h,
            q_day_tot=request.q_day_tot,
            q_day_c=request.q_day_c,
            q_day_h=request.q_day_h,
            q_hr_c=request.q_hr_c,
            q_hr_h=request.q_hr_h,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MeterResponse(
        hws_type=result.hws_type,
        meters=[
            MeterCheckOutput(
                label=m.label,
                meter=WaterMeterInfo(
                    d_mm=m.meter.d_mm,
                    q_min=m.meter.q_min,
                    q_expl=m.meter.q_expl,
                    q_max=m.meter.q_max,
                    q_threshold=m.meter.q_threshold,
                    s=m.meter.s,
                    type=m.meter.type,
                ),
                h_normal=m.h_normal,
                h_limit_normal=m.h_limit_normal,
                pass_normal=m.pass_normal,
                h_fire=m.h_fire,
                h_limit_fire=m.h_limit_fire,
                pass_fire=m.pass_fire,
                need_bypass=m.need_bypass,
                pass_sensitivity=m.pass_sensitivity,
                need_combo=m.need_combo,
                has_fire_check=m.has_fire_check,
            )
            for m in result.meters
        ],
        notes=result.notes,
    )