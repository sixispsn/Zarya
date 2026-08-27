"""Веб-вход для первого прохода по архитектурным PDF-планам."""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.analysis.architecture_pdf import (
    MAX_ARCHITECTURE_PDF_BYTES,
    ArchitecturePdfError,
    survey_architecture_pdf,
)


router = APIRouter(prefix="/wizard", tags=["architecture-import"])
_TPL = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)


def _context(**values):
    return {
        "errors": [],
        "survey": None,
        "kind_labels": {
            "vector": "Векторный план",
            "vector_sparse": "Недостаточно векторов",
            "raster": "Растровый скан",
            "text_only": "Только текст",
            "empty": "Геометрия не найдена",
        },
        **values,
    }


@router.get("/architecture", response_class=HTMLResponse)
def architecture_form(request: Request):
    return _TPL.TemplateResponse(request, "wizard_architecture.html", _context())


@router.post("/architecture/survey", response_class=HTMLResponse)
async def architecture_survey(request: Request):
    form = await request.form()
    upload = form.get("plan_pdf")
    confirmation = bool(form.get("confirm_rights"))
    errors: list[str] = []
    if not confirmation:
        errors.append("Подтвердите право на обработку архитектурного плана.")
    if not isinstance(upload, UploadFile) or not upload.filename:
        errors.append("Добавьте один архитектурный PDF-план.")
    if errors:
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            _context(errors=errors),
            status_code=422,
        )
    content = await upload.read(MAX_ARCHITECTURE_PDF_BYTES + 1)
    await upload.close()
    if len(content) > MAX_ARCHITECTURE_PDF_BYTES:
        errors.append("Архитектурный PDF превышает лимит 40 МБ.")
    if upload.filename and not upload.filename.lower().endswith(".pdf"):
        errors.append("На этом этапе поддерживается только PDF.")
    if errors:
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            _context(errors=errors),
            status_code=422,
        )
    try:
        survey = await run_in_threadpool(
            survey_architecture_pdf,
            content,
            original_name=upload.filename,
        )
    except ArchitecturePdfError as exc:
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            _context(errors=[str(exc)]),
            status_code=422,
        )
    return _TPL.TemplateResponse(
        request,
        "wizard_architecture.html",
        _context(survey=survey),
    )
