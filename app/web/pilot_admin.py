from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.intake.pilot_admin import AdminConflict, PARTICIPATION, PilotAdminStore
from app.web.pilot import feedback_user, same_origin, templates

router = APIRouter(prefix="/access", include_in_schema=False)


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    operation: Literal["issue", "reissue", "revoke"]
    name: str = Field(default="", max_length=80)
    days: int = Field(default=30, ge=1, le=90)
    user_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    accepted: Literal[True]
    version: Literal[PARTICIPATION]


async def payload(request, model):
    if not same_origin(request) or request.headers.get("x-zarya-access") != "1":
        raise HTTPException(403)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise HTTPException(413)
    try:
        return model.model_validate_json(raw)
    except ValueError:
        raise HTTPException(422, "Проверьте заполненные поля.")


@router.get("/admin")
def page(request: Request):
    if feedback_user(request).role != "admin":
        raise HTTPException(403)
    users = PilotAdminStore().users()
    now = datetime.now(timezone.utc).timestamp()
    for user in users:
        user["expires"] = datetime.fromtimestamp(user["key_expires"], timezone.utc).strftime("%d.%m.%Y")
        user["status"] = "Отозван" if user["disabled"] else "Истёк" if user["key_expires"] <= now else "Активен"
    return templates.TemplateResponse(request, "pilot_admin.html", {"users": users})


@router.post("/admin")
async def operate(request: Request):
    user = feedback_user(request)
    if user.role != "admin":
        raise HTTPException(403)
    data = await payload(request, AdminInput)
    try:
        return await run_in_threadpool(lambda: PilotAdminStore().operate(user, **data.model_dump()))
    except PermissionError:
        raise HTTPException(403)
    except AdminConflict as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/participation")
def participation(request: Request):
    feedback_user(request)
    return templates.TemplateResponse(request, "pilot_participation.html", {"version": PARTICIPATION})


@router.post("/participation")
async def accept(request: Request):
    user = feedback_user(request)
    await payload(request, ConsentInput)
    await run_in_threadpool(lambda: PilotAdminStore().accept(user))
    return {"location": "/studio"}
