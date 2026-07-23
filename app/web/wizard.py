# -*- coding: utf-8 -*-
"""
app/web/wizard.py — Wizard: веб-форма ввода объекта ИОС2 (слой 3 цепочки ввода).

Форма НЕ знает Project: она собирает IOS2Request (намерение) из полей,
отдаёт его в ProjectBuilder и показывает результат design_ios2 (4 PDF).

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
from typing import Dict

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.intake.request_dto import (
    IOS2Request, DocumentRequest, RoomRequest, NetworkRequest,
    MainRunRequest, RiserRequest, SourceDataRequest, ConsumerGroupRequest,
)
from app.intake.project_builder import build_project, RequestValidationError
from app.intake.advisories import review_request
from app.pz.ios2_orchestrator import design_ios2
from app.intake.project_store import ProjectStore
from app.pz.generator import cold_meter_loss
from app.pz.rules import calc_required_head
from app.data.sp30_tables import list_consumer_norms

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


def _form_context(**values):
    return {"consumer_norms": _CONSUMER_NORMS, "advisories": [], **values}


@router.get("", response_class=HTMLResponse)
def wizard_form(request: Request):
    return _TPL.TemplateResponse(
        request, "wizard_form.html", _form_context(errors=[]))


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
            fv("consumer_code", "residential_central_hw"),
            fi("consumer_count"),
        ))

    req = IOS2Request(
        document=DocumentRequest(
            cipher=fv("cipher"), object_name=fv("object_name"),
            organization=fv("organization"), object_address=fv("address"),
            object_part=fv("object_part"), stage=fv("stage", "П"),
            developer=fv("developer"), inspector=fv("inspector"),
            dept_head=fv("dept_head"), gip=fv("gip"), norm_control=fv("norm_control")),
        building_type=fv("building_type", "residential"),
        floors=fi("floors"), building_height_m=ff("height"),
        total_area_m2=ff("total_area"),
        risers_v1=fi("risers_v1"), risers_t3=fi("risers_t3"),
        risers_t4=fi("risers_t4"),
        insulation_location=fv("insulation_location", "room_hot"),
        insulation_t_room_manual=ff("insulation_t_room", 5.0),
        insulation_humidity=fi("insulation_humidity", 60),
        insulation_hvs_water_temp=ff("insulation_hvs_temp", 10.0),
        insulation_gvs_water_temp=ff("insulation_gvs_temp", 60.0),
        streams=(fi("streams") if fv("streams") else None),
        zones=fi("zones", 1), rooms=rooms, network=network,
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
            network_kind=fv("network_kind", "combined"),
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
    }
    return RedirectResponse(url=f"/wizard/result/{run_id}", status_code=303)


@router.get("/result/{run_id}", response_class=HTMLResponse)
def wizard_result(request: Request, run_id: str):
    run = _RUNS.get(run_id)
    if run is None:
        return HTMLResponse("<h2>Прогон не найден</h2>", status_code=404)
    b = run["bundle"]
    pdfs = []
    for label, path in (("Пояснительная записка", b.pz_pdf),
                        ("Спецификация", b.spec_pdf),
                        ("Схема", b.scheme_pdf),
                        ("Гидравлический расчёт", b.hydraulic_pdf),
                        ("Проверка живучести кольца", getattr(b, "resilience_pdf", None))):
        if path:
            pdfs.append({"label": label, "name": os.path.basename(path)})
    f = b.project.fire
    p = b.project
    head = calc_required_head(p.source, h_vod_m=cold_meter_loss(p.meters))
    return _TPL.TemplateResponse(request, "wizard_result.html", {
        "run_id": run_id, "pdfs": pdfs, "project_id": run.get("project_id"),
        "status": b.status,
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
        "pump_duty": (b.fire_hydraulic_result.pump_duty
                      if b.fire_hydraulic_result else None),
    })


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
