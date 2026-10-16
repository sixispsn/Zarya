"""
API endpoints для подбора счётчиков воды.
"""
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Query

from app.calc.water_meters import MeterInput, calculate_meters
from app.data.water_meters import WATER_METERS
from app.schemas.water_meters import (
    MeterCheckOutput,
    MeterRequest,
    MeterResponse,
    WaterMeterInfo,
)

router = APIRouter(prefix="/meters", tags=["Подбор счётчиков"])


@router.get("/engineering-catalogue")
def engineering_catalogue(kind: str | None = None, material: str | None = None,
        dn: int | None = Query(None, ge=1, le=5000),
        outer_diameter_mm: float | None = Query(None, gt=0, le=5000),
        system_id: str | None = None, manufacturing: str | None = None,
        connection: str | None = None, include_unverified: bool = False,
        russian_only: bool = False, offset: int = Query(0,ge=0), limit: int = Query(50,ge=1,le=200)):
    """Exact geometry index; no network fetching or hydraulic selection."""
    from app.data.engineering_catalogue import get_engineering_catalogue
    c = get_engineering_catalogue()
    items = c.search(kind=kind, material=material, dn=dn, outer_diameter_mm=outer_diameter_mm,
        system_id=system_id, manufacturing=manufacturing, connection=connection,
        status=None if include_unverified else 'verified', russian_only=russian_only)
    return {**c.summary(), 'matched':len(items), 'offset':offset, 'limit':limit,
            'items':[c.card(p.id) for p in items[offset:offset+limit]]}


@router.get("/engineering-catalogue/{item_id}")
def engineering_catalogue_item(item_id: str):
    from app.data.engineering_catalogue import get_engineering_catalogue
    c = get_engineering_catalogue()
    if item_id not in c.items:
        raise HTTPException(404, 'Позиция не найдена; автоматической замены нет')
    return c.card(item_id)


@router.get("/engineering-catalogue/{item_id}/pipe-section")
def engineering_pipe_section(item_id: str, joining: str):
    """Return an explicit YAML-compatible selection without mutating a project."""
    from app.pz.metering_pipes import MeteringPipeSection
    try:
        section = MeteringPipeSection.from_catalogue(item_id, joining=joining)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {'pipe_section':asdict(section), 'installation_approved':False,
            'note':'Размеры выбраны. Рабочие P/T, пригодность воды, соединители и монтаж проверяются отдельно.'}


@router.get("/engineering-catalogue/{item_id}/flexible-selection")
def engineering_flexible_selection(item_id: str):
    from app.data.engineering_catalogue import get_engineering_catalogue
    from app.pz.metering_flexible import FlexibleConnectionChoice
    c = get_engineering_catalogue()
    try:
        c.require(item_id,kind='flexible_connection')
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    return {'choice':asdict(FlexibleConnectionChoice(item_id,c.fingerprint(item_id))),
            'installation_approved':False,
            'note':'Задайте перемещения по КР и ответные фланцы. Количество/размещение не назначены.'}


@router.get("/engineering-catalogue/{item_id}/pipe-fittings")
def engineering_pipe_fittings(item_id: str, joining: str):
    from app.data.engineering_catalogue import get_engineering_catalogue
    c = get_engineering_catalogue()
    try:
        result = c.pipe_connection_candidates(item_id, joining=joining)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {'candidates':result, 'installation_approved':False,
            'note':'Сопоставлены размеры порта со стороны трубы. Другие порты, P/T, материал и монтаж требуют проверки.'}


@router.get("/assembly-catalogue")
def assembly_catalogue(dn: int = Query(50, ge=1, le=1000), russian_only: bool = False,
                       orientation: str = 'unknown'):
    """Read-only dimensional coverage; separate from hydraulic /list tables."""
    from app.data.metering_coverage import metering_coverage, fitting_card, SUPPORTED_DNS
    from app.data.metering_products import get_metering_catalogue
    c = get_metering_catalogue()
    try:
        coverage = metering_coverage(dn, russian_only=russian_only, orientation=orientation)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    from app.data.engineering_catalogue import plain
    ids = {ident for values in coverage["equipment"].values() for ident in values}
    return {"revision":c.revision, "dimension_revisions":c.dimension_revisions, "range":SUPPORTED_DNS,
        "coverage":coverage,
        "equipment":[{"id":p.id,"name":p.name,"dn":p.dn,"kind":p.kind,"technology":p.technology,
            "dimensions_mm":dict(p.dimensions_mm),"notes":p.notes,"installation":plain(p.installation),
            "sources":[dict(c.sources[s]) for s in p.source_ids]} for p in c.products.values() if p.id in ids],
        "fittings":[fitting_card(p) for p in c.fittings.values()
            if any(p.id in ids for ids in coverage["fittings"].values())]}


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
            minimum_flow_checks={k: v.model_dump() for k, v in request.minimum_flow_checks.items()},
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MeterResponse(
        hws_type=result.hws_type,
        meters=[
            MeterCheckOutput(
                label=m.label,
                q_average_m3h=m.q_average_m3h,
                pass_average=m.pass_average,
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
                minimum_flow_note=m.minimum_flow_note,
                minimum_flow_evidence=(asdict(m.minimum_flow_evidence) if m.minimum_flow_evidence else None),
            )
            for m in result.meters
        ],
        notes=result.notes,
    )
