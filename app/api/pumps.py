"""API endpoints для подбора насосов."""
from dataclasses import asdict
from fastapi import APIRouter, HTTPException

from app.calc.hws_circulation import CirculationHeatLoss, calculate_circulation_demand
from app.calc.pumps import PumpInput, calculate_pump
from app.calc.pump_suction import NpshaInput, calculate_npsha
from app.calc.suction_losses import SuctionLoss, bind_suction_losses
from app.schemas.pump_suction import NpshaRequest
from app.schemas.hws_circulation import CirculationDemandRequest, CirculationDemandResponse
from app.schemas.hws_circulation import StagePCirculationRequest
from app.calc.hws_stage_p import HwsStagePInput, calculate_stage_p_circulation
from app.schemas.pumps import (
    CurvePointOutput,
    PumpCandidateOutput,
    PumpInfoOutput,
    PumpRequest,
    PumpResponse,
    WorkingPointOutput,
)

router = APIRouter(prefix="/pumps", tags=["Подбор насосов"])


@router.post("/npsha")
def npsha(request: NpshaRequest):
    """Отдельный баланс CNP, с явными исходными; не меняет подбор/проект."""
    try:
        data = request.model_dump(exclude={"suction_path"})
        trace = None
        if request.suction_path is not None:
            if request.suction_losses_m is not None:
                raise ValueError("Задайте либо готовые потери Hf, либо состав пути, но не оба сразу")
            path = request.suction_path
            trace = bind_suction_losses(path.required_components,
                [SuctionLoss(**{**row.model_dump(), "covers": tuple(row.covers)}) for row in path.losses],
                max_flow_m3h=request.max_flow_m3h, temperature_c=request.temperature_c,
                path_basis=path.path_basis)
            data["suction_losses_m"] = trace.total_loss_m
        result = calculate_npsha(NpshaInput(**data))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    response = {**asdict(result), "inputs": request.model_dump(exclude={"suction_path"})}
    if request.suction_path is not None:
        response.update(suction_path=asdict(trace), effective_suction_losses_m=data["suction_losses_m"],
                        path_inputs=request.suction_path.model_dump())
    return response


@router.post("/circulation-stage-p")
def circulation_stage_p(request: StagePCirculationRequest):
    context = {key: getattr(request, key) for key in ('stage', 'hws_type', 'purpose')}
    data = request.model_dump(exclude={'hot_hour_m3h', *context})
    try:
        return asdict(calculate_stage_p_circulation(
            HwsStagePInput(**data), request.hot_hour_m3h, **context))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/circulation-demand", response_model=CirculationDemandResponse)
def circulation_demand(request: CirculationDemandRequest):
    """Предварительный баланс теплопотерь, не гидравлический расчёт колец."""
    try:
        result = calculate_circulation_demand(
            [CirculationHeatLoss(**part.model_dump()) for part in request.components],
            delta_t_c=request.delta_t_c, temperature_basis=request.temperature_basis,
            heat_losses_complete=request.heat_losses_complete,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return CirculationDemandResponse(**asdict(result))


@router.post("/calculate", response_model=PumpResponse)
def calculate(request: PumpRequest):
    """
    Предварительный подбор по балансу напора СП 30 и оценочной кривой системы.

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
            include_current_catalog=True,
            circulation_head_m=request.circulation_head_m,
            circulation_basis=request.circulation_basis,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PumpResponse(
        q_design=result.q_design,
        required=result.required,
        curve_kind=result.curve_kind,
        notes=result.notes,
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
                npshr_at_working_point=c.npshr_at_working_point,
                reasons=c.reasons,
                curve=[CurvePointOutput(q=p.q, h=p.h) for p in c.eff_curve],
                head_at_design=c.head_at_design,
            )
            for c in result.candidates
        ],
    )
