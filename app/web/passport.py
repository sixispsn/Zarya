"""Read-only веб-представление постоянного цифрового паспорта выпуска."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.intake.passport_store import (
    PassportIntegrityError,
    PassportNotFoundError,
    PassportStore,
)


router = APIRouter(prefix="/p", tags=["digital-passport"])
_TPL = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
_TPL.env.filters["ru_num"] = lambda value, precision=1: (
    "—" if value is None else f"{value:.{precision}f}".replace(".", ",")
)
_TPL.env.filters["file_size"] = lambda value: (
    f"{value / 1024 / 1024:.1f} МБ".replace(".", ",")
    if value >= 1024 * 1024 else
    f"{value / 1024:.0f} КБ"
)
_STORE = PassportStore()


def _not_found() -> HTMLResponse:
    return HTMLResponse(
        "<h2>Цифровой паспорт не найден</h2>",
        status_code=404,
    )


@router.get("/{passport_id}", response_class=HTMLResponse)
def digital_passport(request: Request, passport_id: str):
    try:
        manifest = _STORE.load(passport_id)
        verification = _STORE.verify(passport_id)
    except (PassportNotFoundError, ValueError):
        return _not_found()
    return _TPL.TemplateResponse(request, "passport_public.html", {
        "passport": manifest,
        "verification": verification,
    })


@router.get("/{passport_id}/manifest.json")
def digital_passport_manifest(passport_id: str):
    try:
        manifest = _STORE.load(passport_id)
        verification = _STORE.verify(passport_id)
    except (PassportNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="паспорт не найден")
    payload = dict(manifest)
    payload["verification"] = verification
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition":
                f'attachment; filename="zarya-passport-{passport_id}.json"',
        },
    )


@router.get("/{passport_id}/file/{name}")
def digital_passport_file(passport_id: str, name: str):
    try:
        path, _ = _STORE.document(passport_id, name)
    except PassportNotFoundError:
        raise HTTPException(status_code=404, detail="документ не найден")
    except PassportIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="контрольная сумма документа не совпадает",
        ) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "private, immutable, max-age=31536000",
        },
    )
