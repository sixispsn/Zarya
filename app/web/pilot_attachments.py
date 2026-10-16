"""Private download-only expertise PDF attachments; no automatic ingestion."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.intake.pilot_attachments import MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, PilotAttachmentStore
from app.intake.pilot_objects import SnapshotConflict, SnapshotLimit
from app.intake.studio_intake import IntakeError
from app.web.pilot_objects import participant
from app.web.studio import mutation

router = APIRouter(prefix="/studio", include_in_schema=False, dependencies=[Depends(participant)])


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    object_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    version: int = Field(ge=1)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    note: str = Field(default="", max_length=2000)
    expertise_ref: str = Field(default="", max_length=200)
    consent: bool
    expertise_declared: bool


@router.post("/api/pilot-attachments", dependencies=[Depends(mutation)])
async def upload(request: Request):
    user = participant(request)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_TOTAL_BYTES + 128 * 1024:
            raise HTTPException(413, "Комплект превышает 40 МБ.")
        raw.extend(chunk)
    sent = False

    async def receive():
        nonlocal sent
        body = bytes(raw) if not sent else b""
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    bounded = Request(request.scope, receive)
    async with bounded.form(max_files=MAX_FILES, max_fields=1) as form:
        if set(form.keys()) != {"metadata", "files"} or len(form.getlist("metadata")) != 1:
            raise HTTPException(422, "Нужны файлы и описание комплекта.")
        metadata = form.get("metadata")
        if not isinstance(metadata, str) or len(metadata) > 16384:
            raise HTTPException(422, "Некорректное описание комплекта.")
        try:
            payload = AttachmentInput.model_validate(json.loads(metadata))
        except ValueError as exc:
            raise HTTPException(422, "Проверьте описание и подтверждения комплекта.") from exc
        if not payload.consent or not payload.expertise_declared:
            raise HTTPException(422, "Подтвердите права на передачу PDF и сведения о прохождении экспертизы.")
        archive = await run_in_threadpool(PilotAttachmentStore)
        try:
            await run_in_threadpool(archive.author, user, payload.object_id, payload.version)
            uploads, total = [], 0
            for item in form.getlist("files"):
                if not isinstance(item, UploadFile):
                    raise IntakeError("Выберите PDF-файлы.")
                content = await item.read(MAX_FILE_BYTES + 1)
                total += len(content)
                if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise HTTPException(413, "Лимит: 20 МБ на PDF и 40 МБ на комплект.")
                uploads.append((item.filename or "", content))
            saved = await run_in_threadpool(archive.add, user, object_id=payload.object_id,
                                           number=payload.version, request_id=payload.request_id,
                                           note=payload.note, expertise_ref=payload.expertise_ref, uploads=uploads)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Версия объекта не найдена.") from exc
        except SnapshotConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except SnapshotLimit as exc:
            raise HTTPException(429, str(exc)) from exc
        except IntakeError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Сохранение временно недоступно. Повторите тот же запрос.") from exc
    return JSONResponse(saved, headers={"Cache-Control": "no-store"})


@router.get("/pilot-attachments/{bundle_id}/files/{file_id}")
def download(request: Request, bundle_id: str, file_id: str):
    try:
        path, file = PilotAttachmentStore().download(participant(request), bundle_id, file_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Файл не найден.") from exc
    except IntakeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, filename=file["name"], media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "sandbox; default-src 'none'"})
