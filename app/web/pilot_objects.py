"""Private pilot archive. All snapshot content is server-derived and explicitly shared."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.intake.pilot_access import enabled
from app.intake.pilot_attachments import PilotAttachmentStore
from app.intake.pilot_capture import PilotCaptureStore
from app.intake.pilot_objects import PilotObjectStore, SnapshotConflict, SnapshotLimit, checksum, make_snapshot
from app.intake.studio_intake import IntakeError
from app.web.studio import current_id, draft_id, failure, mutation, store


def participant(request: Request):
    if not enabled():
        raise HTTPException(404)
    user = getattr(request.state, "pilot_user", None)
    if not user:
        raise HTTPException(401)
    return user


router = APIRouter(prefix="/studio", include_in_schema=False, dependencies=[Depends(participant)])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    object_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    title: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=1000)
    consent: bool


@router.get("/api/pilot-snapshot")
def preview(request: Request):
    user, did = participant(request), draft_id(request)
    try:
        draft = store(request).load(did)
        snapshot = make_snapshot(draft)
    except IntakeError as exc:
        failure(exc)
    archive = PilotObjectStore()
    objects, before = archive.objects(user, own_only=True)
    if before:  # At most 100 owned objects; no other user's objects in the selector.
        objects.extend(archive.objects(user, own_only=True, before=before)[0])
    return JSONResponse({"revision": draft["revision"], "snapshot": snapshot, "snapshot_sha256": checksum(snapshot),
                         "objects": [{"id": row["id"], "title": row["title"], "versions": row["versions"]} for row in objects]},
                        headers={"Cache-Control": "no-store"})


def save(request: Request, payload: SnapshotInput):
    user, did = participant(request), current_id(request)
    if not payload.consent:
        raise HTTPException(422, "Подтвердите передачу снимка владельцу ЗАРИ.")
    title, note = payload.title.strip(), payload.note.strip()
    if not payload.object_id and not title:
        raise HTTPException(422, "Укажите название или псевдоним объекта.")
    intent = checksum({**payload.model_dump(exclude={"request_id"}), "title": title, "note": note,
                       "draft_id": did})
    archive = PilotObjectStore()
    try:
        # Lost replies can be retried even if the working draft has since changed.
        if previous := archive.previous(user, payload.request_id, intent):
            return previous
        with store(request).read_revision(did, payload.revision) as draft:
            snapshot = make_snapshot(draft)
            if checksum(snapshot) != payload.snapshot_sha256:
                raise SnapshotConflict("Содержимое снимка изменилось. Проверьте его заново перед сохранением.")
            return archive.add(user, request_id=payload.request_id, intent=intent,
                               object_id=payload.object_id, title=title, note=note,
                               snapshot=snapshot)
    except SnapshotConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except SnapshotLimit as exc:
        raise HTTPException(429, str(exc)) from exc
    except IntakeError as exc:
        failure(exc)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, "Объект или черновик не найден.") from exc


@router.post("/api/pilot-versions", dependencies=[Depends(mutation)])
async def save_version(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            raise HTTPException(413, "Запрос слишком большой.")
    try:
        payload = SnapshotInput.model_validate_json(raw)
    except ValueError as exc:
        raise HTTPException(422, "Проверьте название, примечание и подтверждение сохранения.") from exc
    return await run_in_threadpool(save, request, payload)


@router.get("/pilot-objects")
def objects(request: Request, before: int | None = Query(default=None, ge=1)):
    rows, cursor = PilotObjectStore().objects(participant(request), before=before)
    return templates.TemplateResponse(request, "pilot_objects.html",
                                      {"objects": rows, "cursor": cursor, "object": None, "version": None},
                                      headers={"Cache-Control": "no-store"})


@router.get("/pilot-objects/{object_id}")
def object_detail(request: Request, object_id: str, before: int | None = Query(default=None, ge=1)):
    try:
        obj, versions, cursor = PilotObjectStore().versions(participant(request), object_id, before)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Объект не найден.") from exc
    return templates.TemplateResponse(request, "pilot_objects.html",
                                      {"object": obj, "versions": versions, "cursor": cursor, "version": None},
                                      headers={"Cache-Control": "no-store"})


@router.get("/pilot-objects/{object_id}/versions/{number}")
def version_detail(request: Request, object_id: str, number: int):
    try:
        obj, version = PilotObjectStore().version(participant(request), object_id, number)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Версия не найдена.") from exc
    except IntakeError as exc:
        failure(exc)
    return templates.TemplateResponse(request, "pilot_objects.html",
                                      {"object": obj, "version": version,
                                       "generated": PilotCaptureStore().generated(participant(request), object_id, number),
                                       "bundles": PilotAttachmentStore().list(participant(request), object_id, number),
                                       "snapshot_text": json.dumps(version["snapshot"], ensure_ascii=False, indent=2)},
                                      headers={"Cache-Control": "no-store"})


@router.get("/pilot-generated/{bundle_id}/files/{file_id}")
def generated_file(request: Request, bundle_id: str, file_id: str):
    try:
        path, metadata = PilotCaptureStore().file(participant(request), bundle_id, file_id)
    except FileNotFoundError:
        raise HTTPException(404, "PDF не найден.")
    except IntakeError as exc:
        failure(exc)
    return FileResponse(path, media_type="application/octet-stream", filename=metadata["name"],
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
