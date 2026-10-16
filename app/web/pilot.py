"""Opt-in, default-deny boundary around the legacy single-owner application."""
from pathlib import Path
from typing import Literal
import logging
import os
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request as StarletteRequest

from app.intake.pilot_access import AccessStore, TooManyAttempts, enabled
from app.intake.pilot_feedback import FeedbackConflict, FeedbackLimit, FeedbackStore
from app.intake.pilot_admin import PilotAdminStore

COOKIE = "zarya_pilot_session"
router = APIRouter(prefix="/access", include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
logger = logging.getLogger(__name__)

# Explicit methods and paths: a future legacy/API route must not accidentally
# become available to participants. Public passports and handoff stay private.
_READ = re.compile(r"^(?:/|/studio/?|/studio/projects|/studio/api/draft|"
                   r"/studio/api/suction|"
                   r"/studio/api/location/config|"
                   r"/studio/pilot-generated/[a-f0-9]{32}/files/[a-f0-9]{32}|"
                   r"/studio/pilot-attachments/[a-f0-9]{32}/files/[a-f0-9]{32}|"
                   r"/studio/api/pilot-snapshot|/studio/pilot-objects(?:/[a-f0-9]{32}(?:/versions/[0-9]+)?)?|"
                   r"/studio/api/files/[a-f0-9]{24}|"
                   r"/studio/api/preview/[a-f0-9]{32}/files/[^/]+|"
                   r"/studio/api/package/[a-f0-9]+/(?:files/[^/]+|download)|"
                   r"/wizard/normatives(?:/status\.json)?)$")
_WRITE = {
    ("POST", "/studio/api/draft"), ("POST", "/studio/api/files"),
    ("PATCH", "/studio/api/answer"), ("PATCH", "/studio/api/answers"),
    ("POST", "/studio/api/calculate"), ("POST", "/studio/api/preview"),
    ("POST", "/studio/api/suction"),
    ("POST", "/studio/api/package"), ("POST", "/studio/api/study"),
    ("POST", "/studio/api/study/exit"), ("POST", "/access/logout"),
    ("POST", "/studio/api/files/delete"), ("POST", "/access/feedback"),
    ("POST", "/studio/api/pilot-versions"),
    ("POST", "/studio/api/pilot-attachments"), ("POST", "/access/participation"),
    ("POST", "/studio/api/projects"),
    ("POST", "/studio/api/rainwater/review"),
    ("POST", "/studio/api/section/review"),
    ("PATCH", "/studio/api/location"), ("POST", "/studio/api/location/search"),
}


def same_origin(request: Request) -> bool:
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    origin = request.headers.get("origin")
    if origin:
        return origin == f"{request.url.scheme}://{request.headers.get('host')}"
    return (request.headers.get("sec-fetch-site") == "same-origin"
            or request.headers.get("x-zarya-studio") == "1"
            or request.headers.get("x-zarya-access") == "1")


def local_http(request: Request) -> bool:
    return (os.environ.get("ZARYA_PILOT_INSECURE_LOCAL", "0") == "1"
            and request.url.hostname in {"127.0.0.1", "localhost", "::1"})


class PilotMiddleware:
    """Pure ASGI, so upload streaming/cancellation stays with the existing app."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        if not enabled():
            required = os.environ.get("ZARYA_REQUIRE_PILOT") == "1" or Path("/app/.require-personal-auth").exists()
            if required and scope.get("path") != "/health":
                if scope["type"] == "websocket":
                    return await send({"type": "websocket.close", "code": 1008})
                return await JSONResponse({"detail": "Персональный вход временно недоступен."}, 503,
                                          headers={"Cache-Control": "no-store"})(scope, receive, send)
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        request = StarletteRequest(scope, receive)
        path, method = scope["path"], request.method
        if path == "/health" and method in {"GET", "HEAD"}:
            return await self.app(scope, receive, send)
        if request.url.scheme != "https" and not local_http(request):
            return await JSONResponse({"detail": "Для персонального входа требуется HTTPS."}, 400)(scope, receive, send)
        # No cross-origin credentials/preflight. HTML forms are covered too.
        if method not in {"GET", "HEAD"} and not same_origin(request):
            return await JSONResponse({"detail": "Межсайтовый запрос отклонён."}, 403)(scope, receive, send)
        public = ((path in {"/access/login"} and method in {"GET", "POST"})
                  or (path.startswith("/static/") and method in {"GET", "HEAD"}))
        try:
            principal = await run_in_threadpool(
                lambda: AccessStore().authenticate(request.cookies.get(COOKIE, ""))
            ) if not public else None
            consent_required = await run_in_threadpool(lambda: PilotAdminStore().needs_consent(principal)) if principal else False
        except Exception:
            logger.error("Хранилище доступа пилота недоступно; доступ закрыт.")
            return await JSONResponse({"detail": "Вход временно недоступен."}, 503)(scope, receive, send)
        if not public and principal is None:
            if method in {"GET", "HEAD"} and "text/html" in request.headers.get("accept", ""):
                result = RedirectResponse("/access/login", 303)
            else:
                result = JSONResponse({"detail": "Войдите по персональному ключу: /access/login"}, 401)
            result.headers["Cache-Control"] = "no-store"
            return await result(scope, receive, send)
        if consent_required and path not in {"/access/participation", "/access/logout"}:
            result = (RedirectResponse("/access/participation", 303)
                      if method in {"GET", "HEAD"} and "text/html" in request.headers.get("accept", "")
                      else JSONResponse({"detail": "Подтвердите условия участия: /access/participation"}, 403))
            result.headers["Cache-Control"] = "no-store"
            return await result(scope, receive, send)
        if not public and principal.role != "admin" and not (
            method in {"GET", "HEAD"} and (_READ.fullmatch(path) or path == "/access/participation") or (method, path) in _WRITE
        ):
            return await JSONResponse({"detail": "Раздел недоступен участникам пилота."}, 403)(scope, receive, send)
        scope.setdefault("state", {})["pilot_user"] = principal

        async def private_send(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])
                           if k.lower() not in {b"access-control-allow-origin", b"access-control-allow-credentials", b"cache-control"}]
                headers.extend([(b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer")])
                message = {**message, "headers": headers}
            await send(message)
        await self.app(scope, receive, private_send)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(min_length=1, max_length=100)
    remember_device: bool = True


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    category: Literal["calculation", "documents", "interface", "other"]
    message: str = Field(min_length=10, max_length=4000)


def feedback_user(request: Request):
    if not enabled():
        raise HTTPException(404)
    user = getattr(request.state, "pilot_user", None)
    if user is None:
        raise HTTPException(401)
    return user


@router.post("/feedback")
async def submit_feedback(request: Request):
    user = feedback_user(request)
    if request.headers.get("x-zarya-studio") != "1" or not same_origin(request):
        raise HTTPException(403)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 32768:
            raise HTTPException(413, "Замечание слишком длинное. Лимит — 4000 символов.")
    try:
        payload = FeedbackInput.model_validate_json(raw)
    except ValueError:
        raise HTTPException(422, "Выберите тему и опишите замечание: от 10 до 4000 символов.")
    message = payload.message.strip()
    if len(message) < 10:
        raise HTTPException(422, "Опишите замечание чуть подробнее: минимум 10 символов.")
    try:
        ticket = await run_in_threadpool(lambda: FeedbackStore().add(user, payload.request_id, payload.category, message))
    except FeedbackLimit:
        raise HTTPException(429, "Слишком много замечаний за час. Повторите позже.")
    except FeedbackConflict:
        raise HTTPException(409, "Это замечание уже отправлено с другим текстом. Откройте новую форму.")
    return JSONResponse({"ticket": ticket}, headers={"Cache-Control": "no-store"})


@router.get("/feedback")
def feedback_inbox(request: Request, before: int | None = Query(default=None, ge=1)):
    if feedback_user(request).role != "admin":
        raise HTTPException(403)
    rows, next_before = FeedbackStore().page(before)
    return templates.TemplateResponse(request, "pilot_feedback.html", {"items": rows, "next_before": next_before},
                                      headers={"Cache-Control": "no-store"})


@router.get("/login")
def login_page(request: Request):
    if not enabled():
        raise HTTPException(404)
    return templates.TemplateResponse(request, "pilot_login.html", headers={"Cache-Control": "no-store"})


@router.post("/login")
def login(request: Request, payload: LoginInput):
    if not enabled():
        raise HTTPException(404)
    if request.headers.get("x-zarya-access") != "1" or not same_origin(request):
        raise HTTPException(403, "Запрос должен быть отправлен со страницы входа.")
    access = AccessStore()
    try:
        token = access.login(payload.key.strip(), request.client.host if request.client else "unknown",
                             remember_device=payload.remember_device)
    except TooManyAttempts:
        raise HTTPException(429, "Слишком много попыток. Повторите через 15 минут.", headers={"Retry-After": "900"})
    if not token:
        raise HTTPException(401, "Ключ неверен, отозван или срок доступа истёк.")
    access.logout(request.cookies.get(COOKIE, ""))
    principal = access.authenticate(token)
    if principal is None:
        access.logout(token)
        raise HTTPException(401, "Срок доступа истёк. Обратитесь к владельцу ЗАРИ.")
    location = "/access/participation" if PilotAdminStore().needs_consent(principal) else "/studio"
    result = JSONResponse({"location": location}, headers={"Cache-Control": "no-store"})
    result.set_cookie(COOKIE, token, httponly=True, secure=not local_http(request),
                      samesite="strict", max_age=access.cookie_max_age(token) if payload.remember_device else None, path="/")
    # Never let a pre-login anonymous/another user's cookie claim a draft.
    result.delete_cookie("zarya_studio_draft", path="/studio")
    return result


@router.post("/logout")
def logout(request: Request):
    if not enabled():
        raise HTTPException(404)
    AccessStore().logout(request.cookies.get(COOKIE, ""))
    result = RedirectResponse("/access/login", 303)
    result.delete_cookie(COOKIE, path="/", secure=not local_http(request), httponly=True, samesite="strict")
    result.delete_cookie("zarya_studio_draft", path="/studio")
    return result
