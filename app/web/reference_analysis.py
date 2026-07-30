# -*- coding: utf-8 -*-
"""Веб-сценарий загрузки и разбора проекта, прошедшего экспертизу."""
from __future__ import annotations

import os
from typing import List

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool

from app.analysis.reference_project import (
    MAX_UPLOAD_BYTES,
    ReferenceAnalysisError,
    ReferenceAnalysisStore,
    UploadedPackage,
)


router = APIRouter(prefix="/wizard", tags=["reference-analysis"])
_TPL = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)
_STORE = ReferenceAnalysisStore()


def _upload_context(**values):
    return {
        "analyses": _STORE.list(),
        "errors": [],
        **values,
    }


@router.get("/analyze", response_class=HTMLResponse)
def analysis_form(request: Request):
    return _TPL.TemplateResponse(
        request,
        "wizard_analysis.html",
        _upload_context(),
    )


@router.post("/analyze", response_class=HTMLResponse)
async def analysis_upload(request: Request):
    form = await request.form()
    title = str(form.get("title", "")).strip()
    confirmation = bool(form.get("confirm_rights"))
    uploads: List[UploadFile] = [
        item for item in form.getlist("files")
        if isinstance(item, UploadFile) and item.filename
    ]
    errors = []
    if not confirmation:
        errors.append(
            "Подтвердите право на обработку и отсутствие лишних персональных данных."
        )
    if not uploads:
        errors.append("Добавьте хотя бы один PDF или ZIP.")
    if errors:
        return _TPL.TemplateResponse(
            request,
            "wizard_analysis.html",
            _upload_context(errors=errors, title=title),
            status_code=422,
        )
    packages = []
    total = 0
    try:
        for upload in uploads:
            content = await upload.read(MAX_UPLOAD_BYTES + 1)
            await upload.close()
            if len(content) > MAX_UPLOAD_BYTES:
                raise ReferenceAnalysisError(
                    f"Файл «{upload.filename}» превышает лимит 100 МБ."
                )
            total += len(content)
            if total > MAX_UPLOAD_BYTES:
                raise ReferenceAnalysisError(
                    "Общий размер загруженного комплекта превышает 100 МБ."
                )
            packages.append(UploadedPackage(upload.filename, content))
        analysis_id = await run_in_threadpool(_STORE.create, title, packages)
    except ReferenceAnalysisError as exc:
        return _TPL.TemplateResponse(
            request,
            "wizard_analysis.html",
            _upload_context(errors=[str(exc)], title=title),
            status_code=422,
        )
    except Exception:
        return _TPL.TemplateResponse(
            request,
            "wizard_analysis.html",
            _upload_context(errors=[
                "Комплект не разобран. Проверьте PDF и повторите загрузку."
            ], title=title),
            status_code=422,
        )
    return RedirectResponse(
        url=f"/wizard/analyze/{analysis_id}",
        status_code=303,
    )


@router.get("/analyze/{analysis_id}", response_class=HTMLResponse)
def analysis_result(request: Request, analysis_id: str):
    try:
        analysis = _STORE.load(analysis_id)
    except (ValueError, FileNotFoundError):
        return HTMLResponse("<h2>Разбор не найден</h2>", status_code=404)
    return _TPL.TemplateResponse(
        request,
        "wizard_analysis_result.html",
        {"analysis": analysis},
    )


@router.get("/analyze/{analysis_id}/report.json")
def analysis_report(analysis_id: str):
    try:
        analysis = _STORE.load(analysis_id)
    except (ValueError, FileNotFoundError):
        return JSONResponse({"detail": "Разбор не найден"}, status_code=404)
    return JSONResponse(
        analysis,
        headers={
            "Content-Disposition": (
                f'attachment; filename="zarya-analysis-{analysis_id}.json"'
            )
        },
    )


@router.get("/analyze/{analysis_id}/file/{stored_name}")
def analysis_file(analysis_id: str, stored_name: str):
    try:
        manifest = _STORE.load(analysis_id)
        path = _STORE.file_path(analysis_id, stored_name)
    except (ValueError, FileNotFoundError):
        return HTMLResponse("<h2>Документ не найден</h2>", status_code=404)
    document = next(
        (
            item for item in manifest["documents"]
            if item["stored_name"] == stored_name
        ),
        None,
    )
    if document is None:
        return HTMLResponse("<h2>Документ не найден</h2>", status_code=404)
    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=os.path.basename(document["original_name"]),
        content_disposition_type="inline",
    )


@router.post("/analyze/{analysis_id}/delete")
def analysis_delete(analysis_id: str):
    try:
        _STORE.delete(analysis_id)
    except ValueError:
        pass
    return RedirectResponse(url="/wizard/analyze", status_code=303)
