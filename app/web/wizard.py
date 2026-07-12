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
  • одно помещение и до 6 участков магистрали / 4 стояков в форме
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
    MainRunRequest, RiserRequest,
)
from app.intake.project_builder import build_project, RequestValidationError
from app.pz.ios2_orchestrator import design_ios2

router = APIRouter(prefix="/wizard", tags=["wizard"])
_TPL = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# run_id → {"bundle": IOS2DesignBundle, "outdir": str}
_RUNS: Dict[str, dict] = {}
_OUT_ROOT = "/tmp/zarya_wizard_runs"


@router.get("", response_class=HTMLResponse)
def wizard_form(request: Request):
    return _TPL.TemplateResponse(request, "wizard_form.html", {"errors": []})


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
                equiv_length_m=ff(f"run{i}_leq")))
    # стояки: до 4
    risers = []
    for i in range(1, 5):
        nm = fv(f"riser{i}_name")
        if nm:
            risers.append(RiserRequest(
                nm, at_node=fv(f"riser{i}_node"), height_m=ff(f"riser{i}_h"),
                cabinet_elevation_m=ff(f"riser{i}_elev"), dn=fi(f"riser{i}_dn", 65),
                equiv_length_m=ff(f"riser{i}_leq")))

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

    req = IOS2Request(
        document=DocumentRequest(
            cipher=fv("cipher"), object_name=fv("object_name"),
            organization=fv("organization"), object_address=fv("address"),
            object_part=fv("object_part"), stage=fv("stage", "П"),
            developer=fv("developer"), inspector=fv("inspector"),
            dept_head=fv("dept_head"), gip=fv("gip"), norm_control=fv("norm_control")),
        building_type=fv("building_type", "residential"),
        floors=fi("floors"), building_height_m=ff("height"),
        streams=(fi("streams") if fv("streams") else None),
        zones=fi("zones", 1), rooms=rooms, network=network)

    try:
        project = build_project(req)
    except RequestValidationError as e:
        return _TPL.TemplateResponse(request, "wizard_form.html",
                                     {"errors": e.problems})

    run_id = uuid.uuid4().hex[:10]
    outdir = os.path.join(_OUT_ROOT, run_id)
    bundle = design_ios2(project, output_dir=outdir)
    _RUNS[run_id] = {"bundle": bundle, "outdir": outdir}
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
                        ("Гидравлический расчёт", b.hydraulic_pdf)):
        if path:
            pdfs.append({"label": label, "name": os.path.basename(path)})
    f = b.project.fire
    return _TPL.TemplateResponse(request, "wizard_result.html", {
        "run_id": run_id, "pdfs": pdfs,
        "status": b.status, "warnings": b.warnings,
        "fire": {
            "pk_total": f.pk_total,
            "required_head": f.required_head_m,
            "available_head": f.available_head_m,
            "needs_pump": f.needs_pump,
            "dictating": f.dictating_cabinet_id,
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
