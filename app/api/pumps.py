"""API endpoints для подбора насосов."""
from fastapi import APIRouter, HTTPException

from app.calc.pumps import PumpInput, calculate_pump
from app.schemas.pumps import (
    CurvePointOutput,
    PumpCandidateOutput,
    PumpInfoOutput,
    PumpRequest,
    PumpResponse,
    WorkingPointOutput,
)

router = APIRouter(prefix="/pumps", tags=["Подбор насосов"])


@router.post("/calculate", response_model=PumpResponse)
def calculate(request: PumpRequest):
    """
    Подбор насоса по рабочей точке (СП 30.13330, методика Grundfos).

    Возвращает требуемый напор, кривую системы и Top-3 насосов
    с рабочими точками и обоснованием.
    """
    try:
        result = calculate_pump(PumpInput(
            q_design_m3h=request.q_design_m3h,
            pump_type=request.pump_type,
            mode=request.mode,
            h_geom_manual=request.h_geom_manual,
            floors=request.floors,
            floor_height=request.floor_height,
            h_losses=request.h_losses,
            h_pr=request.h_pr,
            h_gar=request.h_gar,
            npsh_a=request.npsh_a,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PumpResponse(
        h_required=result.h_required,
        h_geom=result.h_geom,
        h_stat=result.h_stat,
        k_sys=result.k_sys,
        candidates=[
            PumpCandidateOutput(
                pump=PumpInfoOutput(
                    model=c.pump.model, brand=c.pump.brand, type=c.pump.type,
                    p_kw=c.pump.p_kw, p_max_bar=c.pump.p_max_bar,
                    npshr=c.pump.npshr, q_opt=c.pump.q_opt,
                    note=c.pump.note, archived=c.pump.archived,
                ),
                working_point=WorkingPointOutput(**c.working_point.__dict__),
                score=c.score,
                h_excess_pct=c.h_excess_pct,
                q_ratio=c.q_ratio,
                npsh_ok=c.npsh_ok,
                reasons=c.reasons,
                curve=[CurvePointOutput(q=p.q, h=p.h) for p in c.eff_curve],
            )
            for c in result.candidates
        ],
    )