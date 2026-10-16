"""Personal project location metadata: never a source of hydraulic elevations."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.intake.site_location import Geography, GeographyUnavailable, map_config
from app.intake.studio_store import StaleDraft
from app.web import studio

router = APIRouter(prefix="/studio/api/location", dependencies=[Depends(studio.enabled)], include_in_schema=False)


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    label: str = Field(default="", max_length=400)
    source: Literal["manual", "map", "search"] = "manual"


class SaveLocation(studio.RevisionInput):
    location: Point | None
    lookup_elevation: bool = False
    external_consent: bool = False


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=3, max_length=200)
    external_consent: Literal[True]


@router.get("/config")
def config(request: Request):
    studio.draft_id(request)
    try:
        return map_config()
    except GeographyUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


@router.post("/search")
def search(payload: Search, request: Request):
    studio.mutation(request)
    studio.draft_id(request)
    query = payload.query.strip()
    if len(query) < 3:
        raise HTTPException(422, "Введите город или адрес — минимум три символа.")
    try:
        return {"results": Geography().search(query)}
    except GeographyUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


@router.patch("")
def save(payload: SaveLocation, request: Request):
    studio.mutation(request)
    did = studio.draft_id(request)
    store = studio.store(request)
    try:
        with store.read_revision(did, payload.revision) as current:
            if current.get("study"):
                raise HTTPException(422, "Место учебного примера не меняется. Откройте свой проект.")
            previous = current.get("site_location")
        location = None
        if payload.location is not None:
            location = {**payload.location.model_dump(), "label": payload.location.label.strip(),
                        "reference_only": True, "updated_at": datetime.now(timezone.utc).isoformat(),
                        "elevation": {"status": "not_requested", "metres": None}}
            same_point = previous and all(previous.get(k) == location[k] for k in ("latitude", "longitude"))
            if same_point:
                location["elevation"] = previous.get("elevation", location["elevation"])
            if payload.lookup_elevation:
                if not payload.external_consent:
                    raise HTTPException(422, "Для запроса высоты подтвердите передачу координат справочному сервису.")
                try:
                    location["elevation"] = Geography().elevation(location["latitude"], location["longitude"])
                except GeographyUnavailable as exc:
                    location["elevation"] = {"status": "unavailable", "metres": None, "message": str(exc)}
        # Recheck revision after network I/O. Never hold the engineering draft
        # lock while waiting for a provider; never clear calculations or PDFs.
        if studio.draft_id(request) != did:
            raise HTTPException(409, "В другой вкладке открыт другой проект. Обновите страницу.")
        with store.edit(did, payload.revision) as current:
            current["site_location"] = location
        return JSONResponse({"revision": current["revision"], "site_location": location}, headers={"Cache-Control": "no-store"})
    except StaleDraft as exc:
        raise HTTPException(409, str(exc)) from None
