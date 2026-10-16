"""Small optional measuring workspace within the existing PDF import session."""
from dataclasses import asdict
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from markupsafe import Markup

from app.analysis.architecture_confirmation import (
    audit_confirmed_architecture_section, build_pdf_plan_preview_svg,
    confirmed_architecture_section_from_mapping,
)
from app.analysis.plan_route_measurement import measurement_context, measure_plan_route, trace_from_mapping

router = APIRouter(prefix="/wizard/architecture", tags=["architecture-measurement"])


def _same_origin(request: Request):
    origin = request.headers.get("origin")
    if (request.headers.get("sec-fetch-site") == "cross-site"
            or origin is not None and origin.rstrip("/") != f"{request.url.scheme}://{request.url.netloc}"):
        raise HTTPException(403, "Изменение измерений разрешено только из этого сайта.")


def _load(import_id):
    from app.web import architecture_import as workspace
    survey = workspace._STORE.survey(import_id)
    value = workspace._STORE.load_confirmations(import_id)
    if not value.get("floors"):
        raise ValueError("Сначала подтвердите масштаб и этаж в импорте плана.")
    architecture = confirmed_architecture_section_from_mapping(value)
    issues = audit_confirmed_architecture_section(architecture)
    if issues:
        raise ValueError("; ".join(i.message for i in issues))
    state = workspace._STORE.load_route_traces(import_id)
    return workspace, survey, architecture, state


def _results(state, architecture, survey):
    results = []
    for row in state["traces"]:
        try:
            trace = trace_from_mapping(row)
            measurement = measure_plan_route(trace, architecture, survey)
            results.append({"trace": asdict(trace), "measurement": asdict(measurement), "error": ""})
        except (ValueError, TypeError) as exc:
            results.append({"trace": row, "measurement": None, "error": str(exc)})
    return results


@router.get("/{import_id}/routes", response_class=HTMLResponse)
def route_workspace(request: Request, import_id: str, floor: int | None = None):
    try:
        workspace, survey, architecture, state = _load(import_id)
        floor = floor if floor is not None else architecture.floors[0].floor
        confirmed, context_hash = measurement_context(architecture, survey, floor)
        page = next(p for p in survey.pages if p.page_number == confirmed.page_number)
        return workspace._TPL.TemplateResponse(request, "wizard_route_measurement.html", {
            "import_id": import_id, "survey": survey, "architecture": architecture,
            "active_floor": confirmed, "context_hash": context_hash, "revision": state["revision"],
            "results": _results(state, architecture, survey),
            "preview_svg": Markup(build_pdf_plan_preview_svg(page, scale=confirmed.scale)),
        })
    except (ValueError, FileNotFoundError) as exc:
        return HTMLResponse("<h2>Измерение недоступно</h2><p>" + str(Markup.escape(str(exc))) + "</p>", status_code=422)


@router.post("/{import_id}/routes/save", dependencies=[Depends(_same_origin)])
async def save_route(request: Request, import_id: str):
    try:
        body = await request.body()
        if len(body) > 100_000:
            raise ValueError("Слишком много данных трассы.")
        payload = json.loads(body)
        workspace, survey, architecture, state = _load(import_id)
        trace = trace_from_mapping(payload["trace"])
        measurement = measure_plan_route(trace, architecture, survey)
        traces = [r for r in state["traces"] if r.get("route_id") != trace.route_id] + [asdict(trace)]
        workspace._STORE.save_route_traces(import_id, traces, expected_revision=payload["revision"])
        return JSONResponse({"revision": payload["revision"]+1, "measurement": asdict(measurement)},
                            headers={"Cache-Control": "private, no-store"})
    except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)


@router.post("/{import_id}/routes/delete", dependencies=[Depends(_same_origin)])
async def delete_route(request: Request, import_id: str):
    try:
        form = await request.form()
        workspace, _, _, state = _load(import_id)
        traces = [r for r in state["traces"] if r.get("route_id") != form.get("route_id")]
        workspace._STORE.save_route_traces(import_id, traces, expected_revision=int(form.get("revision", "")))
        return RedirectResponse(f"/wizard/architecture/{import_id}/routes", status_code=303)
    except (ValueError, TypeError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)


@router.get("/{import_id}/routes.json")
def route_export(import_id: str):
    try:
        _, survey, architecture, state = _load(import_id)
        rows = _results(state, architecture, survey)
        return JSONResponse({"version": 1, "revision": state["revision"], "source_sha256": survey.sha256,
            "routes": rows, "purchase_ready": False,
            "note": "Обмер предложенных осей. Не распознавание сети, не расчёт гидравлики и не раскрой."},
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                     "Content-Disposition": 'attachment; filename="route-measurements.json"'})
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
