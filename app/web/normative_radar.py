"""Веб-интерфейс и JSON-снимок нормативного радара."""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.normative.baseline import get_active_baseline
from app.normative.radar import NormativeRadarStore, run_radar_check


router = APIRouter(prefix="/wizard/normatives", tags=["normative-radar"])
_TPL = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
_STORE = NormativeRadarStore()

_INDICATOR_LABELS = {
    "green": "Актуально",
    "orange": "Требует анализа",
    "red": "Выпуск ограничен",
    "gray": "Нет автопроверки",
}
_SOURCE_LABELS = {
    "ok": "Источник доступен",
    "error": "Ошибка источника",
    "not_checked": "Онлайн-проверка ожидается",
    "unconfigured": "Источник не подключён",
}


def _payload() -> tuple[dict, list[dict]]:
    snapshot = _STORE.load(get_active_baseline())
    return snapshot.to_dict(), [row.to_dict() for row in _STORE.events(50)]


@router.get("")
def normative_radar_page(request: Request):
    snapshot, events = _payload()
    return _TPL.TemplateResponse(request, "wizard_normatives.html", {
        "radar": snapshot,
        "events": events,
        "indicator_labels": _INDICATOR_LABELS,
        "source_labels": _SOURCE_LABELS,
    })


@router.post("/check")
def check_normatives_now():
    run_radar_check(store=_STORE)
    return RedirectResponse(url="/wizard/normatives?checked=1", status_code=303)


@router.get("/status.json")
def normative_radar_status():
    snapshot, events = _payload()
    return JSONResponse({
        **snapshot,
        "events": events[:10],
    })
