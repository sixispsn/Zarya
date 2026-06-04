"""
API endpoints для расчёта водостоков кровли.
"""
from fastapi import APIRouter, HTTPException

from app.calc.storm import StormInput, calculate_storm
from app.data.storm_cities import list_cities
from app.schemas.storm import StormCityInfo, StormRequest, StormResponse

router = APIRouter(prefix="/storm", tags=["Водостоки кровли"])


@router.get("/cities", response_model=list[StormCityInfo])
def get_cities():
    """
    Получить список доступных городов с параметрами q20 и n
    по СП 32.13330.2018 (приложение Б, таблица 8).
    """
    return [
        StormCityInfo(code=c.code, name=c.name, q20=c.q20, n=c.n, region=c.region)
        for c in list_cities()
    ]


@router.post("/calculate", response_model=StormResponse)
def calculate(request: StormRequest):
    """
    Расчёт расхода дождевых вод с кровли.

    Формулы:
      F  = F_кровли + 0.3 × F_стен (м²)
      q5 = 4^n × q20 × γ(P) (л/(с·га))
      Q  = F × q5 / 10000 (л/с)
    """
    try:
        result = calculate_storm(StormInput(
            city_code=request.city_code,
            roof_area_m2=request.roof_area_m2,
            walls_area_m2=request.walls_area_m2,
            period_years=request.period_years,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StormResponse(
        city=StormCityInfo(
            code=result.city.code,
            name=result.city.name,
            q20=result.city.q20,
            n=result.city.n,
            region=result.city.region,
        ),
        period_years=result.period_years,
        f_calculated_m2=result.f_calculated_m2,
        q20_base=result.q20_base,
        gamma=result.gamma,
        q20_adjusted=result.q20_adjusted,
        n=result.n,
        q5=result.q5,
        q_total_l_per_s=result.q_total_l_per_s,
    )