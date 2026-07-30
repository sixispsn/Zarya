# -*- coding: utf-8 -*-
"""
app/web/wizard.py — Wizard: веб-форма ввода объекта ИОС2 (слой 3 цепочки ввода).

Форма НЕ знает Project: она собирает IOS2Request (намерение) из полей,
отдаёт его в ProjectBuilder и показывает результат design_ios2, включая
самостоятельный комплект К1/К2.

    браузер → GET /wizard           форма (одна страница, секциями)
            → POST /wizard/design   сборка DTO → Builder → design_ios2
            → GET /wizard/result/{run_id}         статус + ссылки на PDF
            → GET /wizard/file/{run_id}/{name}    отдача PDF

MVP-упрощения (осознанные):
  • до 12 групп потребителей, одно характерное помещение и до 6 участков
    магистрали / 4 стояков в форме
    (для демо достаточно; полный ввод — следующая итерация);
  • результаты хранятся в памяти процесса (run_id → bundle); без БД.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.intake.request_dto import (
    IOS2Request, DocumentRequest, RoomRequest, NetworkRequest,
    MainRunRequest, RiserRequest, SourceDataRequest, ConsumerGroupRequest,
    SewageRiserRequest, SewerPipeRequest,
)
from app.intake.project_builder import build_project, RequestValidationError
from app.intake.advisories import review_request
from app.pz.ios2_orchestrator import design_ios2
from app.intake.project_store import ProjectStore
from app.intake.yaml_io import load_request_file
from app.pz.generator import cold_meter_loss
from app.pz.impact import (
    ImpactValidationError,
    calculate_impact_preview,
    impact_form_context,
)
from app.pz.proof import build_proof_graph
from app.pz.rules import calc_required_head
from app.schemas.impact import ImpactPreviewInput
from app.data.sp30_tables import list_consumer_norms
from app.data.storm_cities import list_cities

router = APIRouter(prefix="/wizard", tags=["wizard"])
_TPL = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
_TPL.env.filters["ru_num"] = lambda value, precision=1: (
    "—" if value is None else f"{value:.{precision}f}".replace(".", ",")
)

# run_id → {"bundle": IOS2DesignBundle, "outdir": str}
_RUNS: Dict[str, dict] = {}
_OUT_ROOT = "/tmp/zarya_wizard_runs"
_STORE = ProjectStore()
_CONSUMER_NORMS = list_consumer_norms()
_STORM_CITIES = list_cities()
_DEMO_PROJECT = Path(__file__).parents[2] / "demo" / "demo_project.yaml"


def _form_context(**values):
    return {
        "consumer_norms": _CONSUMER_NORMS,
        "storm_cities": _STORM_CITIES,
        "advisories": [],
        "example_mode": False,
        **values,
    }


@router.get("", response_class=HTMLResponse)
def wizard_form(request: Request, example: bool = False):
    prefill = load_request_file(str(_DEMO_PROJECT)) if example else None
    return _TPL.TemplateResponse(
        request,
        "wizard_form.html",
        _form_context(
            errors=[],
            prefill=prefill,
            example_mode=example,
            advisories=(review_request(prefill) if prefill else []),
        ),
    )


@router.post("/design")
async def wizard_design(request: Request):
    """Принимает форму, собирает IOS2Request, строит Project, гонит design_ios2."""
    form = await request.form()

    def fv(name, default=""):
        return str(form.get(name, default)).strip()

    def ff(name, default=0.0):
        try:
            return float(str(form.get(name, default)).replace(",", "."))
        except (TypeError, ValueError):
            return default

    def fi(name, default=0):
        try:
            return int(float(str(form.get(name, default))))
        except (TypeError, ValueError):
            return default

    # магистраль: до 6 участков (пустые строки пропускаются)
    runs = []
    for i in range(1, 7):
        a, b = fv(f"run{i}_from"), fv(f"run{i}_to")
        if a and b:
            runs.append(MainRunRequest(
                a, b, length_m=ff(f"run{i}_len"), dn=fi(f"run{i}_dn", 100),
                equiv_length_m=ff(f"run{i}_leq"),
                repair_section_id=fv(f"run{i}_repair")))
    # стояки: до 4
    risers = []
    for i in range(1, 5):
        nm = fv(f"riser{i}_name")
        if nm:
            risers.append(RiserRequest(
                nm, at_node=fv(f"riser{i}_node"), height_m=ff(f"riser{i}_h"),
                cabinet_elevation_m=ff(f"riser{i}_elev"), dn=fi(f"riser{i}_dn", 65),
                equiv_length_m=ff(f"riser{i}_leq"),
                repair_section_id=fv(f"riser{i}_repair")))

    network = None
    if runs:
        network = NetworkRequest(
            runs=runs, risers=risers, source_node=fv("source_node"),
            source_kind=fv("source_kind", "city_main"),
            available_head_m=(ff("available_head") if fv("available_head") else None),
            water_level_m=(ff("water_level") if fv("water_level") else None),
            suction_head_loss_m=ff("suction_loss"))

    rooms = []
    if fv("room_name"):
        rooms.append(RoomRequest(
            fv("room_name"), length_m=ff("room_len"), width_m=ff("room_wid"),
            height_m=ff("room_h"), space_kind=fv("room_kind", "corridor"),
            placement=fv("room_place", "two_opposite_sides")))

    consumers = []
    for i in range(1, 13):
        code = fv(f"consumer{i}_code")
        count = fi(f"consumer{i}_count")
        if code and count > 0:
            consumers.append(ConsumerGroupRequest(
                code=code,
                count=count,
                name=fv(f"consumer{i}_name"),
            ))
    # Совместимость со старой формой и внешними клиентами Wizard.
    if not consumers and fi("consumer_count") > 0:
        consumers.append(ConsumerGroupRequest(
            fv("consumer_code", "residential_full_bath"),
            fi("consumer_count"),
        ))

    sewage_risers = []
    for i in range(1, 4):
        riser_id = fv(f"sewage_riser{i}_id")
        if riser_id:
            sewage_risers.append(SewageRiserRequest(
                riser_id=riser_id,
                design_flow_lps=ff(f"sewage_riser{i}_flow"),
                material=fv(f"sewage_riser{i}_material", "pp"),
                ventilation=fv(
                    f"sewage_riser{i}_ventilation", "ventilated"
                ),
                riser_dn_mm=fi(f"sewage_riser{i}_dn", 110),
                branch_dn_mm=fi(f"sewage_riser{i}_branch_dn", 110),
                branch_angle_deg=ff(f"sewage_riser{i}_angle", 87.5),
                has_toilet=bool(form.get(f"sewage_riser{i}_toilet")),
                working_height_m=(
                    ff(f"sewage_riser{i}_height")
                    if fv(f"sewage_riser{i}_height") else None
                ),
            ))

    sewer_pipes = []
    for i in range(1, 7):
        section_id = fv(f"sewer_pipe{i}_id")
        if section_id:
            sewer_pipes.append(SewerPipeRequest(
                system=fv(f"sewer_pipe{i}_system", "K1"),
                section_id=section_id,
                purpose=fv(f"sewer_pipe{i}_purpose"),
                material=fv(f"sewer_pipe{i}_material"),
                standard=fv(f"sewer_pipe{i}_standard"),
                outer_diameter_mm=ff(f"sewer_pipe{i}_outer"),
                wall_thickness_mm=ff(f"sewer_pipe{i}_wall"),
                length_m=ff(f"sewer_pipe{i}_length"),
            ))

    req = IOS2Request(
        document=DocumentRequest(
            cipher=fv("cipher"), object_name=fv("object_name"),
            organization=fv("organization"), object_address=fv("address"),
            object_part=fv("object_part"), stage=fv("stage", "П"),
            developer=fv("developer"), inspector=fv("inspector"),
            dept_head=fv("dept_head"), gip=fv("gip"), norm_control=fv("norm_control")),
        building_type=fv("building_type"),
        floors=fi("floors"), building_height_m=ff("height"),
        total_area_m2=ff("total_area"),
        risers_v1=fi("risers_v1"), risers_t3=fi("risers_t3"),
        risers_t4=fi("risers_t4"),
        insulation_location=fv("insulation_location", "room_hot"),
        insulation_t_room_manual=ff("insulation_t_room", 5.0),
        insulation_humidity=fi("insulation_humidity", 60),
        insulation_hvs_water_temp=ff("insulation_hvs_temp", 10.0),
        insulation_gvs_water_temp=ff("insulation_gvs_temp", 60.0),
        fire_mode=fv("fire_mode", "auto"),
        fire_height_m=(ff("fire_height") if fv("fire_height") else None),
        fire_category=fv("fire_category"),
        fire_hall_seats=(
            fi("fire_hall_seats") if fv("fire_hall_seats") else None
        ),
        fire_area_m2=(
            ff("fire_area_m2") if fv("fire_area_m2") else None
        ),
        fire_geometry_confirmed=bool(form.get("fire_geometry_confirmed")),
        streams=(fi("streams") if fv("streams") else None),
        nozzle_mm=fi("nozzle_mm", 13),
        compact_jet_m=fi("compact_jet_m", 12),
        zones=fi("zones", 1), rooms=rooms, network=network,
        apartments=fi("apartments"),
        owner_groups_count=fi("owner_groups_count", 1),
        roof_type=fv("roof_type", "not_set"),
        sewage_max_fixture_lps=ff("sewage_max_fixture_lps", 1.6),
        sewage_risers=sewage_risers,
        sewer_pipes=sewer_pipes,
        sewage_outlets_count=fi("sewage_outlets_count"),
        storm_city=fv("storm_city"),
        storm_roof_area_m2=ff("storm_roof_area"),
        storm_walls_area_m2=ff("storm_walls_area"),
        storm_period_years=fi("storm_period_years", 1),
        storm_roof_sections=fi("storm_roof_sections"),
        storm_funnels_count=fi("storm_funnels_count"),
        storm_sectional_residential_single_funnel=bool(
            form.get("storm_sectional_residential_single_funnel")
        ),
        storm_max_funnel_spacing_m=(
            ff("storm_max_funnel_spacing_m")
            if fv("storm_max_funnel_spacing_m") else None
        ),
        storm_selected_funnel_capacity_lps=(
            ff("storm_selected_funnel_capacity_lps")
            if fv("storm_selected_funnel_capacity_lps") else None
        ),
        storm_max_funnel_flow_lps=(
            ff("storm_max_funnel_flow_lps")
            if fv("storm_max_funnel_flow_lps") else None
        ),
        storm_risers_count=fi("storm_risers_count"),
        storm_selected_riser_dn_mm=fi("storm_selected_riser_dn_mm"),
        storm_max_riser_flow_lps=(
            ff("storm_max_riser_flow_lps")
            if fv("storm_max_riser_flow_lps") else None
        ),
        storm_funnels_on_different_levels=bool(
            form.get("storm_funnels_on_different_levels")
        ),
        catering_type=fv("catering_type", "none"),
        catering_seats=fi("catering_seats"),
        catering_conditional_dishes=fi("catering_conditional_dishes"),
        school_grease_by_assignment=bool(form.get("school_grease_by_assignment")),
        source_data=SourceDataRequest(
            source_description=fv("source_description"),
            water_protection_note=fv("water_protection_note"),
            reserve_water_note=fv("reserve_water_note"),
            tu_org=fv("tu_org"), tu_number=fv("tu_number"), tu_date=fv("tu_date"),
            connection_point=fv("connection_point"),
            guaranteed_head_m=(ff("tu_guaranteed_head") if fv("tu_guaranteed_head") else None),
            maximum_head_m=(ff("tu_maximum_head") if fv("tu_maximum_head") else None),
            tu_limit_q_day=(ff("tu_limit_q_day") if fv("tu_limit_q_day") else None),
            water_main_dn=fi("water_main_dn"),
            h_geom_m=(ff("h_geom") if fv("h_geom") else None),
            h_il_m=(ff("h_il") if fv("h_il") else None),
            network_kind=fv("network_kind", "domestic"),
            h_pr_m=ff("h_pr", 20.0),
            h_vvod_m=(ff("h_vvod") if fv("h_vvod") else None),
            inputs_count=fi("inputs_count", 1),
            npsh_available_m=(ff("npsh_available") if fv("npsh_available") else None),
        ),
        consumers=consumers,
    )
    advisories = review_request(req)

    pid = fv("project_id") or None
    try:
        project = build_project(req)
    except RequestValidationError as e:
        return _TPL.TemplateResponse(request, "wizard_form.html", _form_context(**{
            "errors": e.problems, "advisories": advisories,
            "prefill": req, "project_id": pid,
        }))

    # персистентность: намерение сохраняется (source of truth — вход)
    project_id = _STORE.save(req, project_id=(pid if pid and _STORE.exists(pid) else None))

    run_id = uuid.uuid4().hex[:10]
    outdir = os.path.join(_OUT_ROOT, run_id)
    try:
        bundle = design_ios2(project, output_dir=outdir)
    except Exception as exc:
        return _TPL.TemplateResponse(request, "wizard_form.html", _form_context(**{
            "errors": [f"Комплект не собран: {exc}"],
            "advisories": advisories,
            "prefill": req,
            "project_id": project_id,
        }), status_code=422)
    _RUNS[run_id] = {
        "bundle": bundle, "outdir": outdir, "project_id": project_id,
        "advisories": advisories,
        "request": req,
        "proof_graph": build_proof_graph(
            bundle.project, bundle.commission_report,
        ),
    }
    return RedirectResponse(url=f"/wizard/result/{run_id}", status_code=303)


@router.get("/result/{run_id}", response_class=HTMLResponse)
def wizard_result(request: Request, run_id: str):
    run = _RUNS.get(run_id)
    if run is None:
        return HTMLResponse("<h2>Прогон не найден</h2>", status_code=404)
    b = run["bundle"]
    proof_graph = run["proof_graph"]
    group_defs = (
        ("common", "00", "Основной комплект",
         "Общие документы, баланс и сводные материалы проекта"),
        ("ios2", "ИОС2", "Система водоснабжения",
         "В1, В2, Т3 и Т4: расчёты и обоснования принятых решений"),
        ("ios3", "ИОС3", "Система водоотведения",
         "К1 и К2: отдельная ПЗ, расчёты, схема и спецификация"),
    )
    groups = {
        key: {
            "key": key,
            "code": code,
            "label": label,
            "description": description,
            "documents": [],
        }
        for key, code, label, description in group_defs
    }
    pdfs = []
    for group, label, path in (
            ("common", "Пояснительная записка", b.pz_pdf),
            ("common", "Паспорт проекта и нормативный контроль",
             getattr(b, "commission_control_pdf", None)),
            ("common", "Баланс водопотребления и водоотведения",
             getattr(b, "balance_pdf", None)),
            ("common", "Сводная спецификация", b.spec_pdf),
            ("common", "Сводная принципиальная схема", b.scheme_pdf),
            ("ios2", "Расчётные обоснования В1 и Т3",
             getattr(b, "v1_calculation_pdf", None)),
            ("ios2", "Расчёт и подбор насосов",
             getattr(b, "pump_selection_pdf", None)),
            ("ios2", "Гидравлический расчёт В2", b.hydraulic_pdf),
            ("ios2", "Проверка живучести кольца В2",
             getattr(b, "resilience_pdf", None)),
            ("ios3", "Комплект пояснительной записки К1 и К2",
             getattr(b, "wastewater_package_pdf", None)),
            ("ios3", "Пояснительная записка К1 и К2",
             getattr(b, "wastewater_pz_pdf", None)),
            ("ios3", "Расчётные обоснования К1 и К2",
             getattr(b, "wastewater_calculation_pdf", None)),
            ("ios3", "Принципиальная схема К1 и К2",
             getattr(b, "wastewater_scheme_pdf", None)),
            ("ios3", "Спецификация К1 и К2",
             getattr(b, "wastewater_spec_pdf", None))):
        if path:
            document = {"label": label, "name": os.path.basename(path)}
            pdfs.append(document)
            groups[group]["documents"].append(document)
    document_groups = [
        groups[key] for key, *_ in group_defs if groups[key]["documents"]
    ]
    f = b.project.fire
    p = b.project
    head = calc_required_head(p.source, h_vod_m=cold_meter_loss(p.meters))
    return _TPL.TemplateResponse(request, "wizard_result.html", {
        "run_id": run_id, "pdfs": pdfs, "document_groups": document_groups,
        "project_id": run.get("project_id"),
        "status": b.status,
        "commission": getattr(b, "commission_report", None),
        "proof": proof_graph,
        "impact": impact_form_context(run["request"]),
        "warnings": b.warnings + [
            f"{item.message} ({item.reference})"
            for item in run.get("advisories", [])
        ],
        "project": {
            "title": p.document.object_name,
            "cipher": p.document.cipher,
            "stage": p.document.stage_label,
        },
        "v1": {
            "q_day": p.flows.q_day_tot,
            "q_sec": p.flows.q_sec_c,
            "required_head": head.h_required_m,
            "guaranteed_head": head.h_guaranteed_m,
            "pump_required": p.pumps.required,
            "pump_model": p.pumps.model,
            "pump_q": p.pumps.wp_q or p.pumps.q_m3h,
            "pump_h": p.pumps.wp_h or p.pumps.head_m,
        },
        "fire": {
            "required": f.required,
            "note": f.normative_note,
            "flow": f.q_total,
            "pk_total": f.pk_total,
            "required_head": f.required_head_m,
            "available_head": f.available_head_m,
            "needs_pump": f.needs_pump,
            "dictating": f.dictating_cabinet_id,
        },
        "fire_pump": {
            "model": p.fire_pumps.model,
            "q": p.fire_pumps.wp_q or p.fire_pumps.q_m3h,
            "h": p.fire_pumps.wp_h or p.fire_pumps.head_m,
        },
        "sewage": {
            "flow": (
                p.sewage.result.total.q_sewage_lps
                if p.sewage.result else None
            ),
            "riser_count": len(p.sewage.risers),
            "checked_count": (
                p.sewage.result.checked_risers if p.sewage.result else 0
            ),
            "outlets_count": p.sewage.outlets_count,
        },
        "storm": {
            "required": p.storm.system_kind == "internal",
            "flow": (
                p.storm.result.q_total_l_per_s if p.storm.result else None
            ),
            "funnels_count": p.storm.funnels_count,
            "risers_count": p.storm.risers_count,
            "status": (
                p.storm.network_assessment.status
                if p.storm.network_assessment else "stage_r"
            ),
        },
        "pump_duty": (b.fire_hydraulic_result.pump_duty
                      if b.fire_hydraulic_result else None),
    })


@router.get("/proof/{run_id}")
def wizard_proof(run_id: str):
    """Машиночитаемый доказательный граф того же расчётного прогона."""
    run = _RUNS.get(run_id)
    if run is None:
        return JSONResponse({"detail": "прогон не найден"}, status_code=404)
    graph = run["proof_graph"]
    filename = f"zarya-proof-{graph.project_fingerprint}.json"
    return JSONResponse(
        graph.to_dict(),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/impact/{run_id}")
def wizard_impact(run_id: str, data: ImpactPreviewInput):
    """Предпросмотр «было → станет» без сохранения и выпуска документов."""
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="прогон не найден")
    try:
        preview = calculate_impact_preview(
            run["request"],
            run["bundle"].project,
            run["bundle"].commission_report,
            data,
        )
    except ImpactValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(preview.to_dict())


@router.get("/file/{run_id}/{name}")
def wizard_file(run_id: str, name: str):
    run = _RUNS.get(run_id)
    if run is None:
        return HTMLResponse("нет прогона", status_code=404)
    path = os.path.join(run["outdir"], name)
    if not os.path.isfile(path) or os.path.dirname(os.path.abspath(path)) != os.path.abspath(run["outdir"]):
        return HTMLResponse("нет файла", status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=name)


# ── МОИ ПРОЕКТЫ (персистентность поверх YAML-стора) ─────────────────────────

@router.get("/projects", response_class=HTMLResponse)
def wizard_projects(request: Request):
    """Список сохранённых проектов."""
    return _TPL.TemplateResponse(request, "wizard_projects.html",
                                 {"projects": _STORE.list()})


@router.get("/open/{project_id}", response_class=HTMLResponse)
def wizard_open(request: Request, project_id: str):
    """Открыть сохранённый проект: форма, предзаполненная из YAML."""
    try:
        req_dto = _STORE.load(project_id)
    except (FileNotFoundError, ValueError):
        return HTMLResponse("<h2>Проект не найден</h2>", status_code=404)
    return _TPL.TemplateResponse(request, "wizard_form.html", {
        **_form_context(errors=[], advisories=review_request(req_dto)),
        "prefill": req_dto, "project_id": project_id})


@router.post("/projects/{project_id}/delete")
def wizard_delete(project_id: str):
    try:
        _STORE.delete(project_id)
    except ValueError:
        pass
    return RedirectResponse(url="/wizard/projects", status_code=303)
