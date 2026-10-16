"""Main white workspace. Old editor is retained only for archived projects."""

from __future__ import annotations

import fcntl
import io
import logging
import os
import shutil
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.intake.project_store import ProjectStore
from app.intake.pilot_access import AccessStore, enabled as pilot_enabled
from app.intake.studio_intake import (
    IntakeError,
    MAX_DOCUMENTS,
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
    QUICK_START_PRESETS,
    accepted_values,
    answer_field,
    answer_visible_form,
    build_handoff_request,
    calculate_draft,
    public_draft,
    read_document,
)
from app.intake.studio_store import StaleDraft, StudioStore
from app.intake.studio_project import (
    STUDIO_HANDOFF_VERSION, calculate_project, refresh_document_readiness,
)
from app.intake.pilot_objects import calculation_stamp
from app.pz.water_scheme_delivery import DOCUMENT_RENDER_VERSION
from app.intake.studio_suction import StudioSuctionInput

COOKIE = "zarya_studio_draft"
_TPL = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def is_enabled() -> bool:
    return os.environ.get("ZARYA_STUDIO_ENABLED", "1") == "1"


def enabled():
    if not is_enabled():
        raise HTTPException(404, "Рабочее место временно отключено.")


router = APIRouter(
    prefix="/studio", tags=["studio"], dependencies=[Depends(enabled)]
)


def store(request: Request | None = None) -> StudioStore:
    root = Path(os.environ.get("ZARYA_STUDIO_DIR", str(Path.home() / ".zarya" / "studio")))
    if pilot_enabled():
        user = getattr(request.state, "pilot_user", None) if request else None
        if user is None:
            raise HTTPException(401, "Требуется персональный вход.")
        root = root / "_users" / user.id
    return StudioStore(root)


def current_id(request: Request) -> str:
    if pilot_enabled():
        user = getattr(request.state, "pilot_user", None)
        if user is None:
            raise HTTPException(401, "Требуется персональный вход.")
        did = AccessStore().active_draft(user.id) or ""
    else:
        did = request.cookies.get(COOKIE, "")
    selected = request.headers.get("x-zarya-draft")
    if selected and selected != did:
        raise HTTPException(409, "В другой вкладке открыт другой проект. Обновите страницу, прежде чем сохранять.")
    return did


def mutation(request: Request):
    if request.headers.get("x-zarya-studio") != "1":
        raise HTTPException(403, "Запрос должен быть отправлен из интерфейса ЗАРИ.")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Межсайтовый запрос отклонён.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Межсайтовый запрос отклонён.")


def draft_id(request: Request) -> str:
    value = current_id(request)
    try:
        store(request).load(value)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Черновик не найден. Начните новый проект.")
    return value


def response(draft: dict, request: Request | None = None):
    stale_documents = any(
        draft.get(key) and draft[key].get("state") != "blocked"
        and not documents_current(draft[key], draft)
        for key in ("preview", "package")
    )
    # Re-evaluate old cached readiness after the stage-P preview change, without
    # editing answers, revision or the saved draft on a read request.
    cached = draft.get("project_calculation") or {}
    if not draft.get("study") and cached.get("state") == "calculated" and (
        "preview_notes" not in cached or "presentation" not in cached.get("sewer_scheme", {})
        or cached.get("handoff_version") != STUDIO_HANDOFF_VERSION
        or (draft.get('suction_check') and draft.get('calculation_stamp') != calculation_stamp(draft))
        or stale_documents
    ):
        draft = {**draft, "project_calculation": calculate_project(draft), "preview": None}
    if stale_documents:
        # Keep stored snapshots/files for the pilot archive; only current UI links expire.
        draft = {**draft, **{key: None for key in ("preview", "package")
                            if draft.get(key) and draft[key].get("state") != "blocked"
                            and not documents_current(draft[key], draft)}}
    missing_files = []
    if request is not None and draft.get("project_id") and not draft.get("study"):
        draft, missing_files = preview_file_view(request, draft)
        if request.method == "GET":
            draft = package_file_view(draft)
    public = public_draft(draft)
    public["documents_need_refresh"] = stale_documents or bool(missing_files)
    public["documents_missing_files"] = missing_files
    public["site_location"] = draft.get("site_location")
    if draft.get("project_id"):
        public["project_id"] = draft["project_id"]
    if "pilot_archive" in draft:
        public["pilot_archive"] = draft["pilot_archive"]
    if request is not None and draft.get("project_id"):
        from app.intake.studio_section_review import review_state
        public["section_review"] = review_state(
            draft, store(request).folder(draft["project_id"]), STUDIO_HANDOFF_VERSION)
    return JSONResponse(public, headers={"Cache-Control": "no-store"})


def documents_current(saved: dict, draft: dict) -> bool:
    return (saved.get("render_version") == DOCUMENT_RENDER_VERSION
            and saved.get("handoff_version") == STUDIO_HANDOFF_VERSION
            and saved.get("stamp") == calculation_stamp(draft))


def preview_file_exists(folder: Path, name: str) -> bool:
    if not isinstance(name, str) or not name or Path(name).name != name:
        return False
    try:
        path = folder / name
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def preview_file_view(request: Request, draft: dict) -> tuple[dict, list[str]]:
    """Withdraw lost file evidence in the response only; never save or calculate."""
    saved = draft.get("preview") or {}
    artifacts = current_preview_artifacts(request, draft["project_id"], draft)
    if artifacts is None:
        return draft, []
    folder = store(request).folder(draft["project_id"]) / "previews" / saved["id"]
    names = {doc["name"] for doc in saved.get("documents", [])}
    names.update(name for group in saved["artifact_files"].values() for name in group)
    missing = sorted(name for name in names if not preview_file_exists(folder, name))
    if not missing:
        return draft, []
    from app.pz.artifact_readiness import qualify_artifact_presence
    original_presence = {label: bool(group) for label, group in saved["artifact_files"].items()}
    original = qualify_artifact_presence(original_presence, saved.get("artifact_readiness"),
                                         saved.get("graphic_artifact_requirements"))
    lost = {label for label, group in saved["artifact_files"].items()
            if group and (not any(preview_file_exists(folder, name) for name in group)
                          or original.get(label) and not artifacts.get(label))}
    view = deepcopy(draft)
    preview = view["preview"]
    preview["artifact_readiness"] = {**preview.get("artifact_readiness", {}),
                                     **{label: False for label in lost}}
    affected_names = {name for label in lost for name in saved["artifact_files"][label]}
    for doc in preview.get("documents", []):
        if doc["name"] in affected_names or doc["name"] in missing:
            doc["state"] = "incomplete"
            doc["state_note"] = "Файл или необходимая часть комплекта недоступны. Повторно сформируйте предпросмотр."
        doc["file_missing"] = doc["name"] in missing
    if view.get("project_calculation"):
        from app.intake.preview_file_readiness import restrict_preview_calculation
        view["project_calculation"] = restrict_preview_calculation(
            view["project_calculation"], lost, missing)
    return view, missing


def package_file_view(draft: dict) -> dict:
    """Only current availability changes in the response, never release history."""
    from app.web import wizard
    from app.intake.package_files import package_member_name
    saved = draft.get("package") or {}
    if saved.get("state") != "ready" or not documents_current(saved, draft):
        return draft
    documents = saved.get("documents")
    invalid = not isinstance(documents, list) or not documents
    valid = []
    names = set()
    for doc in documents if isinstance(documents, list) else []:
        name = doc.get("name") if isinstance(doc, dict) else None
        if not package_member_name(name) or name in names:
            invalid = True
            continue
        names.add(name)
        valid.append(doc)
    run_id = saved.get("run_id")
    run = wizard._run_file_context(run_id) if isinstance(run_id, str) and run_id else None
    missing = []
    for doc in valid:
        try:
            path = wizard._run_file(run, doc["name"]) if run else None
            available = path is not None and preview_file_exists(Path(path).parent, Path(path).name)
        except OSError:
            available = False
        if not available:
            missing.append(doc["name"])
    if not invalid and not missing:
        return draft
    view = deepcopy(draft)
    package = view["package"]
    package["state"] = "unavailable"
    package["missing_files"] = missing
    package["availability_note"] = (
        "Некорректный список файлов сохранённого комплекта. " if invalid else
        "Часть файлов сохранённого комплекта отсутствует или пуста. "
    ) + "Скачивание всего комплекта недоступно. Архивный снимок не изменён."
    package["documents"] = deepcopy(valid)
    for doc in package["documents"]:
        doc["file_missing"] = doc["name"] in missing
        if doc["file_missing"]:
            doc["state"] = "incomplete"
            doc["state_note"] = "Сохранённый файл недоступен; архивный снимок не изменён."
    if view.get("project_calculation"):
        from app.intake.preview_file_readiness import restrict_preview_calculation
        view["project_calculation"] = restrict_preview_calculation(
            view["project_calculation"], (), missing + (["некорректный список файлов"] if invalid else []),
            collection="package")
    return view


def current_preview_artifacts(request: Request, did: str, draft: dict) -> dict[str, bool] | None:
    """Recheck files only for the exact input/build that produced this preview."""
    saved = draft.get("preview") or {}
    preview_id = saved.get("id", "")
    if (draft.get("study") or not documents_current(saved, draft)
            or "artifact_files" not in saved
            or len(preview_id) != 32 or any(c not in '0123456789abcdef' for c in preview_id)):
        return None
    folder = store(request).folder(did) / "previews" / preview_id

    from app.pz.artifact_readiness import qualify_artifact_presence

    presence = {label: any(preview_file_exists(folder, name) for name in names)
                for label, names in saved["artifact_files"].items()}
    return qualify_artifact_presence(
        presence, saved.get("artifact_readiness"), saved.get("graphic_artifact_requirements"),
    )


def calculate_with_current_preview(request: Request, did: str, draft: dict) -> dict:
    artifacts = current_preview_artifacts(request, did, draft)
    return (calculate_project(draft, artifacts=artifacts) if artifacts is not None
            else calculate_project(draft))


def capture_pilot(request: Request, did: str, draft: dict, kind: str):
    """Called under the draft lock, before publishing a new revision."""
    if not pilot_enabled() or draft.get("study"):
        return
    from app.intake.pilot_admin import PilotAdminStore
    from app.intake.pilot_capture import PilotCaptureStore
    user = request.state.pilot_user
    if not PilotAdminStore().has_consent(user):
        return
    try:
        files = []
        if kind == "preview":
            saved = draft["preview"]
            files = [(store(request).folder(did) / "previews" / saved["id"] / doc["name"], doc)
                     for doc in saved["documents"]]
        elif kind == "package":
            from app.web import wizard
            saved = draft["package"]
            if saved["state"] != "ready":
                kind = "calculation"
            else:
                run = wizard._get_run(saved["run_id"])
                files = [(wizard._run_file(run, doc["name"]), doc) for doc in saved["documents"]]
        result = PilotCaptureStore().capture(user, did, {**draft, "revision": draft["revision"] + 1}, kind, files)
        draft["pilot_archive"] = {"state": "saved", **result}
    except Exception:
        logging.getLogger(__name__).error("Автоматическое сохранение версии пилота не завершено.")
        draft["pilot_archive"] = {"state": "failed", "message": "Рабочий результат готов, но его копия в архив пилота не сохранена. Сообщите владельцу и повторите расчёт или формирование PDF."}


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0, strict=True)


class AnswerInput(RevisionInput):
    field: str
    value: str | int | float | list[dict] | dict | None


class VisibleFormInput(RevisionInput):
    answers: dict[str, str | int | float | list[dict] | dict | None] = Field(default_factory=dict)
    preset_keys: list[str] = Field(default_factory=list, max_length=len(QUICK_START_PRESETS))


class StudyInput(RevisionInput):
    kind: str


class RainwaterReviewInput(RevisionInput):
    reviewer: str = Field(min_length=1, max_length=200)
    confirm: bool


class SectionReviewInput(RainwaterReviewInput):
    architecture_ref: str = Field(min_length=1, max_length=500)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/api/section/review", dependencies=[Depends(mutation)])
def review_section(request: Request, payload: SectionReviewInput):
    from app.intake.studio_section_review import record_review
    did = draft_id(request)
    try:
        with store(request).edit(did, payload.revision) as draft:
            record_review(draft, store(request).folder(did), STUDIO_HANDOFF_VERSION,
                          fingerprint=payload.fingerprint, reviewer=payload.reviewer,
                          architecture_ref=payload.architecture_ref, confirm=payload.confirm,
                          actor_id=getattr(getattr(request.state, "pilot_user", None), "id", "local"))
            # A review is not a new calculation or a release. Keep the exact PDF
            # that was reviewed, all existing blockers and artifact access rules.
    except IntakeError as exc:
        failure(exc)
    return response(draft, request)


@router.post("/api/rainwater/review", dependencies=[Depends(mutation)])
def review_rainwater(request: Request, payload: RainwaterReviewInput):
    from datetime import datetime, timezone
    from app.calc.rainwater_reuse import assess
    from app.calc.rainwater_design import fingerprint
    from app.intake.studio_intake import rainwater_input, rainwater_review_source
    try:
        with store(request).edit(draft_id(request), payload.revision) as draft:
            if draft.get("study") or not payload.confirm or not payload.reviewer.strip():
                raise IntakeError("Нужно явное подтверждение проектировщика в собственном проекте.")
            values = accepted_values(draft)
            context = dict(building_kind=values.get("building_purpose", "residential"),
                           roof_kind=values.get("roof_type"))
            data = rainwater_input(draft)
            design = assess(data, **context)["design"]
            if not design["ready_for_review"]:
                raise IntakeError("До проверки дождевой системы: " + "; ".join(design["missing"]))
            draft["rainwater_review"] = {
                "source": rainwater_review_source(draft),
                "actor_id": getattr(getattr(request.state, "pilot_user", None), "id", "local"),
                "record": dict(fingerprint=fingerprint(data, **context),
                               reviewer=payload.reviewer.strip(),
                               reviewed_at=datetime.now(timezone.utc).isoformat()),
            }
            draft["project_calculation"] = calculate_project(draft)
            draft["preview"] = draft["package"] = None
            capture_pilot(request, draft_id(request), draft, "calculation")
    except IntakeError as exc:
        failure(exc)
    return response(draft, request)


class DeleteDocumentInput(RevisionInput):
    document_id: str = Field(pattern=r"^[a-f0-9]{24}$")


def switch_cookie(request: Request, did: str, draft: dict):
    result = response(draft, request)
    if pilot_enabled():
        # The selected draft is recoverable after logout/on another device.
        store(request).load(did)
        AccessStore().set_draft(request.state.pilot_user.id, did)
        return result
    result.set_cookie(COOKIE, did, httponly=True, samesite="strict",
                      secure=request.url.scheme == "https", path="/studio", max_age=30*24*3600)
    return result


@router.post("/api/study", dependencies=[Depends(mutation)])
def start_study(request: Request, payload: StudyInput):
    from app.intake.studio_study import initialize_study, TITLES
    if payload.kind not in TITLES:
        raise HTTPException(422, "Неизвестный учебный пример.")
    previous_id = draft_id(request)
    try:
        with store(request).edit(previous_id, payload.revision) as previous:
            return_id = (previous.get("study") or {}).get("return_id") or previous_id
            did, _ = store(request).create()
            with store(request).edit(did, 0) as draft:
                initialize_study(draft, payload.kind, return_id)
    except IntakeError as exc:
        failure(exc)
    return switch_cookie(request, did, draft)


@router.post("/api/study/exit", dependencies=[Depends(mutation)])
def exit_study(request: Request, payload: RevisionInput):
    try:
        with store(request).edit(draft_id(request), payload.revision) as draft:
            did = (draft.get("study") or {}).get("return_id")
            if not did:
                raise IntakeError("Учебный пример не открыт.")
            original = store(request).load(did)
    except IntakeError as exc:
        failure(exc)
    return switch_cookie(request, did, original)


def failure(exc: IntakeError):
    raise HTTPException(409 if isinstance(exc, StaleDraft) else 422, str(exc)) from exc


def input_failure(exc: IntakeError):
    if getattr(exc, "input_issues", None) and not isinstance(exc, StaleDraft):
        return JSONResponse(status_code=422, content={"detail": str(exc),
            "input_issues": exc.input_issues, "input_message": exc.input_message})
    return failure(exc)


@router.get("")
def index(request: Request):
    return _TPL.TemplateResponse(
        request, "studio.html",
        {"view": "project" if request.query_params.get("view") == "project" else "home"},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/projects")
def projects(request: Request):
    """Personal Studio draft; the legacy archive is owner-only during the pilot."""
    from app.web import wizard

    try:
        draft = store(request).load(current_id(request))
    except (ValueError, FileNotFoundError):
        draft = None
    values = accepted_values(draft) if draft else {}
    personal = []
    if pilot_enabled():
        for path in sorted(store(request).root.glob("*/draft.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.parent.name == current_id(request):
                continue
            try:
                item = store(request).load(path.parent.name)
                if not item.get("study"):
                    personal.append({"id":path.parent.name, "title":accepted_values(item).get("object_name") or "Жилой дом"})
            except (ValueError, FileNotFoundError):
                continue
    return _TPL.TemplateResponse(
        request, "studio_projects.html",
        {
            "current": draft is not None,
            "title": (draft.get("study") or {}).get("title") or values.get("object_name") or "Жилой дом" if draft else "",
            "is_study": bool(draft and draft.get("study")),
            "personal": personal,
            "archive": wizard._STORE.list() if not pilot_enabled() or request.state.pilot_user.role == "admin" else [],
        },
        headers={"Cache-Control": "no-store"},
    )


class ProjectChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    project_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    title: str = Field(default="", max_length=120)


@router.post("/api/projects", dependencies=[Depends(mutation)])
def choose_project(request: Request, payload: ProjectChoice):
    if not pilot_enabled():
        raise HTTPException(404)
    scoped = store(request)
    scoped.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (scoped.root / ".current.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if payload.project_id:
            try:
                saved = scoped.load(payload.project_id)
                if saved.get("study"):
                    raise FileNotFoundError
            except (ValueError, FileNotFoundError):
                raise HTTPException(404, "Ваш проект не найден.")
            return switch_cookie(request, payload.project_id, saved)
        if not payload.title.strip():
            raise HTTPException(422, "Назовите новый объект, чтобы не смешивать проекты.")
        # Request identity survives a lost response without creating another object.
        folders = list(scoped.root.glob("*/draft.json"))
        for path in folders:
            saved = scoped.load(path.parent.name)
            if saved.get("creation_request") == payload.request_id:
                if accepted_values(saved).get("object_name") != payload.title.strip():
                    raise HTTPException(409, "Запрос уже использован. Обновите страницу.")
                return switch_cookie(request, path.parent.name, saved)
        if len(folders) >= 100:
            raise HTTPException(429, "Достигнут предел 100 рабочих проектов.")
        did, _ = scoped.create()
        with scoped.edit(did, 0) as saved:
            saved["creation_request"] = payload.request_id
            answer_field(saved, "object_name", payload.title.strip())
        return switch_cookie(request, did, saved)


@router.get("/archive/{project_id}/source.yaml")
def archive_source(request: Request, project_id: str):
    from app.web import wizard

    if pilot_enabled() and request.state.pilot_user.role != "admin":
        raise HTTPException(403, "Архив доступен только владельцу.")

    if not wizard._STORE.exists(project_id):
        raise HTTPException(404, "Проект не найден в архиве.")
    return FileResponse(
        Path(wizard._STORE.root) / f"{project_id}.yaml",
        filename=f"{project_id}.yaml", media_type="application/yaml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/draft")
def get_draft(request: Request):
    try:
        draft = store(request).load(current_id(request))
    except (ValueError, FileNotFoundError):
        return JSONResponse({"draft": None}, headers={"Cache-Control": "no-store"})
    return response(draft, request)


@router.post("/api/draft", dependencies=[Depends(mutation)])
def create_draft(request: Request):
    if pilot_enabled():
        scoped = store(request)
        scoped.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Two first tabs must not create two disconnected personal drafts.
        with (scoped.root / ".current.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            did = current_id(request)
            if did:
                return response(scoped.load(did), request)
            did, draft = scoped.create()
            return switch_cookie(request, did, draft)
    try:
        draft = store(request).load(current_id(request))
        return response(draft, request)
    except (ValueError, FileNotFoundError):
        value, draft = store(request).create()
    result = response(draft, request)
    result.set_cookie(
        COOKIE,
        value,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/studio",
        max_age=30 * 24 * 3600,
    )
    return result


@router.post("/api/files", dependencies=[Depends(mutation)])
async def upload(request: Request):
    did = draft_id(request)
    if store(request).load(did).get("study"):
        raise HTTPException(422, "Документы добавляйте в свой проект, не в учебный пример.")
    # Bound the complete multipart stream, including clients without Content-Length.
    # The project's pinned Starlette does not expose max_part_size on Request.form.
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_TOTAL_BYTES + 1024 * 1024:
            raise HTTPException(413, "Загрузка превышает 40 МБ плюс служебные поля.")
        raw.extend(chunk)
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": bytes(raw), "more_body": False}

    bounded_request = Request(request.scope, receive)
    async with bounded_request.form(max_files=MAX_DOCUMENTS, max_fields=2) as form:
        uploads = [
            item for item in form.getlist("files") if isinstance(item, UploadFile)
        ]
        try:
            raw_revision = str(form.get("revision", ""))
            if not raw_revision.isdigit():
                raise IntakeError("Не указана версия черновика. Обновите страницу.")
            if not uploads or len(uploads) > MAX_DOCUMENTS:
                raise IntakeError("Выберите от 1 до 10 PDF.")
            documents, total = [], 0
            for upload in uploads:
                content = await upload.read(MAX_FILE_BYTES + 1)
                total += len(content)
                if total > MAX_TOTAL_BYTES:
                    raise IntakeError("Общий размер одной загрузки превышает 40 МБ.")
                document = await run_in_threadpool(
                    read_document, content, upload.filename or ""
                )
                documents.append((document, content))
            draft = await run_in_threadpool(
                store(request).add_documents, did, int(raw_revision), documents
            )
        except IntakeError as exc:
            failure(exc)
    return response(draft, request)


@router.post("/api/files/delete", dependencies=[Depends(mutation)])
def delete_document(request: Request, payload: DeleteDocumentInput):
    try:
        draft = store(request).delete_document(draft_id(request), payload.revision, payload.document_id)
    except FileNotFoundError:
        raise HTTPException(404, "Документ не найден в вашем проекте.")
    except IntakeError as exc:
        failure(exc)
    except OSError:
        raise HTTPException(503, "Удаление не завершено. Обновите черновик; очистка файла будет повторена при следующем сохранении.")
    return response(draft, request)


@router.patch("/api/answer", dependencies=[Depends(mutation)])
def answer(request: Request, payload: AnswerInput):
    try:
        with store(request).edit(draft_id(request), payload.revision) as draft:
            answer_field(draft, payload.field, payload.value)
    except IntakeError as exc:
        return input_failure(exc)
    return response(draft, request)


@router.post("/api/calculate", dependencies=[Depends(mutation)])
def calculate(request: Request, payload: VisibleFormInput):
    did = draft_id(request)
    try:
        with store(request).edit(did, payload.revision) as draft:
            answer_visible_form(draft, payload.answers, payload.preset_keys)
            draft["calculation"] = calculate_draft(draft)
            draft["project_calculation"] = calculate_with_current_preview(request, did, draft)
            draft["calculation_stamp"] = calculation_stamp(draft)
            capture_pilot(request, did, draft, "calculation")
    except IntakeError as exc:
        return input_failure(exc)
    return response(draft, request)


@router.get("/api/suction")
def suction_context(request: Request):
    from app.intake.studio_suction import current_context, saved_view
    did = draft_id(request)
    scoped = store(request)
    try:
        with scoped.read_revision(did, scoped.load(did)['revision']) as draft:
            context = current_context(draft)
            result = dict(revision=draft['revision'], project_id=did, context=context,
                          saved=saved_view(draft, context))
    except (IntakeError, ValueError) as exc:
        failure(exc)
    return JSONResponse(result, headers={'Cache-Control': 'no-store'})


@router.post("/api/suction", dependencies=[Depends(mutation)])
def save_suction(request: Request, payload: StudioSuctionInput):
    from app.intake.studio_suction import current_context, save_check, saved_view
    did = draft_id(request)
    try:
        with store(request).edit(did, payload.revision) as draft:
            context = current_context(draft)
            save_check(draft, context, payload)
            saved = saved_view(draft, context)
            # Preserve archived files, expire only live links.
            draft['preview'] = None
            draft['package'] = None
            draft['project_calculation'] = calculate_project(draft)
            draft['calculation_stamp'] = calculation_stamp(draft)
            capture_pilot(request, did, draft, 'calculation')
    except (IntakeError, ValueError) as exc:
        failure(exc)
    return JSONResponse(dict(revision=draft['revision'], project_id=did,
                             context=context, saved=saved), headers={'Cache-Control': 'no-store'})


@router.patch("/api/answers", dependencies=[Depends(mutation)])
def save_visible_form(request: Request, payload: VisibleFormInput):
    try:
        with store(request).edit(draft_id(request), payload.revision) as draft:
            answer_visible_form(draft, payload.answers, payload.preset_keys)
    except IntakeError as exc:
        return input_failure(exc)
    return response(draft, request)


@router.post("/api/package", dependencies=[Depends(mutation)])
def package(request: Request, payload: RevisionInput):
    """Use the SAME release path and gates as Wizard, without navigating away."""
    from app.web import wizard
    did = draft_id(request)
    try:
        with store(request).edit(did, payload.revision) as draft:
            draft["calculation"] = calculate_draft(draft)
            draft["project_calculation"] = calculate_with_current_preview(request, did, draft)
            draft["package"] = None
            draft["calculation_stamp"] = calculation_stamp(draft)
            if not draft["project_calculation"]["can_release"]:
                # Save the latest review instead of losing it in an exception rollback.
                draft["package"] = {"state": "blocked", "documents": []}
            else:
                result = wizard.design_request_response(
                    request,
                    build_handoff_request(draft),
                    force_quality_gates=True,
                )
                if result.status_code == 303:
                    run_id = result.headers["location"].rsplit("/", 1)[-1]
                    run = wizard._get_run(run_id)
                    documents, _ = wizard._run_documents(run)
                    draft["package"] = {
                        "state": "ready",
                        "render_version": DOCUMENT_RENDER_VERSION,
                        "handoff_version": STUDIO_HANDOFF_VERSION,
                        "stamp": calculation_stamp(draft),
                        "run_id": run_id,
                        "documents": documents,
                        "quality_state": run["quality"]["state"],
                    }
                else:
                    draft["package"] = {
                        "state": "blocked",
                        "documents": [],
                        "errors": result.context.get("errors", ["Комплект не собран."]),
                    }
            capture_pilot(request, did, draft, "package")
    except IntakeError as exc:
        failure(exc)
    return response(draft, request)


@router.get("/api/package/{run_id}/files/{name}")
def package_file(request: Request, run_id: str, name: str):
    from app.web import wizard
    from app.intake.package_files import package_member_name, read_package_member

    draft = store(request).load(draft_id(request))
    saved = draft.get("package") or {}
    if (
        saved.get("state") != "ready"
        or not documents_current(saved, draft)
        or saved.get("run_id") != run_id
        or not package_member_name(name)
        or not isinstance(saved.get("documents"), list)
        or not any(isinstance(row, dict) and row.get("name") == name
                   for row in saved.get("documents", []))
    ):
        raise HTTPException(404, "Файл текущего комплекта не найден.")
    run = wizard._get_run(saved["run_id"])
    try:
        path = wizard._run_file(run, name) if run else None
        content = read_package_member(path)
    except OSError:
        raise HTTPException(404, "Файл текущего комплекта недоступен или изменился при чтении.")
    headers = FileResponse(
        path,
        media_type="application/pdf",
        filename=name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    ).headers
    return Response(content, media_type="application/pdf", headers=dict(headers))


@router.get("/api/package/{run_id}/download")
def package_download(request: Request, run_id: str):
    """Only the current, gated release may be downloaded as a complete archive."""
    from app.web import wizard
    from app.intake.package_files import package_member_name, read_package_member

    draft = store(request).load(draft_id(request))
    saved = draft.get("package") or {}
    if (saved.get("state") != "ready" or saved.get("run_id") != run_id
            or not documents_current(saved, draft)):
        raise HTTPException(404, "Готовый комплект не найден.")
    run = wizard._get_run(run_id)
    documents = saved.get("documents", [])
    if not isinstance(documents, list):
        raise HTTPException(404, "Некорректный список документов комплекта.")
    names = []
    for doc in documents:
        name = doc.get("name") if isinstance(doc, dict) else None
        if not package_member_name(name) or name in names:
            raise HTTPException(404, "Некорректный список документов комплекта.")
        names.append(name)
    if not names:
        raise HTTPException(404, "Комплект не содержит документов.")
    content = io.BytesIO()
    try:
        with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                path = wizard._run_file(run, name) if run else None
                archive.writestr(name, read_package_member(path))
    except OSError:
        # Nothing has been sent: discard the in-memory partial archive.
        raise HTTPException(404, "Один из документов комплекта недоступен или изменился при чтении.")
    return Response(content.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="Zarya-PDF.zip"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/api/preview", dependencies=[Depends(mutation)])
def preview(request: Request, payload: RevisionInput):
    """Private review PDFs, explicitly NOT a release or published passport."""
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import bundle_artifact_files, bundle_artifact_readiness, design_ios2
    from app.pz.artifact_readiness import WASTEWATER_GRAPHIC_ARTIFACTS
    from app.web.wizard import _bundle_documents

    did = draft_id(request)
    try:
        with store(request).edit(did, payload.revision, cleanup_preview_on_error=True) as draft:
            draft["calculation"] = calculate_draft(draft)
            calculation = calculate_project(draft)
            if not calculation.get("can_preview"):
                raise IntakeError(
                    "Для предпросмотра подтвердите основные данные здания и устраните ошибки исходных данных."
                )
            preview_id = uuid.uuid4().hex
            folder = store(request).folder(did) / "previews" / preview_id
            artifact_files = {}
            artifact_readiness = {}
            graphic_artifact_requirements = []
            try:
                if draft.get("study"):
                    from app.intake.studio_study import render_study
                    documents, model_hash = render_study(draft, folder)
                    if model_hash != calculation["model_hash"]:
                        raise IntakeError("Версия модели изменилась во время экспорта.")
                else:
                    project = build_project(build_handoff_request(draft))
                    project.document.review_notes = (
                        "Предварительный просмотр. Документы требуют проверки и дополнения перед выпуском.",
                        *calculation.get("preview_notes", []),
                    )
                    project.document.review_head_pending = not calculation.get("head", {}).get("ready", True)
                    bundle = design_ios2(
                        project, output_dir=str(folder)
                    )
                    calculation = refresh_document_readiness(draft, calculation, bundle.commission_report)
                    artifact_files = {label: [Path(path).name for path in paths]
                                      for label, paths in bundle_artifact_files(bundle).items()}
                    artifact_readiness = bundle_artifact_readiness(bundle)
                    graphic_artifact_requirements = [WASTEWATER_GRAPHIC_ARTIFACTS[key][0]
                                                     for key in bundle.wastewater_graphic_required or ()]
                    documents, _ = _bundle_documents(bundle)
                    for document in documents:
                        if document.get("kind") in {"water_package_pdf", "wastewater_package_pdf"} and document["state"] == "ready":
                            document["state"] = "preliminary"
                            document["state_note"] = "Предварительный просмотр. Допуск к выпуску проверяется отдельно."
                    if project.document.review_head_pending:
                        for document in documents:
                            if document.get("kind") in {
                                "pz_pdf", "water_package_pdf", "v1_calculation_pdf", "pump_selection_pdf",
                                "pump_zone_scheme_pdf", "scheme_pdf", "spec_pdf",
                            }:
                                document["state"] = "incomplete"
                                document["state_note"] = "Предпросмотр: напор и подбор насоса не подтверждены."
            except Exception as exc:
                shutil.rmtree(folder, ignore_errors=True)
                if isinstance(exc, IntakeError):
                    raise
                raise IntakeError(
                    "Предпросмотр PDF не сформирован; выпуск не выполнен."
                ) from exc
            draft["project_calculation"] = calculation
            draft["calculation_stamp"] = calculation_stamp(draft)
            draft["preview"] = {
                "state": "preview",
                "id": preview_id,
                "documents": documents,
                "model_hash": calculation.get("model_hash"),
                "notes": calculation.get("preview_notes", []),
                "stamp": calculation_stamp(draft),
                "handoff_version": STUDIO_HANDOFF_VERSION,
                "render_version": DOCUMENT_RENDER_VERSION,
                "artifact_files": artifact_files,
                "artifact_readiness": artifact_readiness,
                "graphic_artifact_requirements": graphic_artifact_requirements,
            }
            capture_pilot(request, did, draft, "preview")
    except OSError as exc:
        raise HTTPException(503,
            "Не удалось подтвердить сохранение предпросмотра. "
            "Обновите данные перед повторной попыткой; выпуск не выполнен.") from exc
    except IntakeError as exc:
        failure(exc)
    return response(draft, request)


@router.get("/api/preview/{preview_id}/files/{name}")
def preview_file(request: Request, preview_id: str, name: str):
    did = draft_id(request)
    draft = store(request).load(did)
    if not draft.get("study") and (draft.get("project_calculation") or {}).get("handoff_version") != STUDIO_HANDOFF_VERSION:
        raise HTTPException(404, "Предпросмотр устарел. Повторно сформируйте PDF по текущим исходным данным.")
    saved = draft.get("preview") or {}
    if (
        saved.get("id") != preview_id
        or not documents_current(saved, draft)
        or (not draft.get("study") and saved.get("stamp") != calculation_stamp(draft))
        or Path(name).name != name
        or not any(row["name"] == name for row in saved.get("documents", []))
    ):
        raise HTTPException(404, "Файл текущего предпросмотра не найден.")
    path = store(request).folder(did) / "previews" / preview_id / name
    if not preview_file_exists(path.parent, path.name):
        raise HTTPException(404, "Файл текущего предпросмотра не найден.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Zarya-Preview": "true"},
    )


@router.get("/api/files/{document_id}")
def document(request: Request, document_id: str):
    try:
        path, data = store(request).document(draft_id(request), document_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Документ не найден.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=data["name"],
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.post("/api/handoff", dependencies=[Depends(mutation)])
def handoff(request: Request, payload: RevisionInput):
    """Save an incomplete DTO for the full wizard, never bypass its release gates."""
    try:
        with store(request).edit(draft_id(request), payload.revision) as draft:
            if draft.get("study"):
                raise IntakeError("Учебная компоновка не переносится в реальный проект. Вернитесь к своему черновику.")
            req = build_handoff_request(draft)
            input_hash = calculation_stamp(draft)['inputs_sha256']
            previous = draft.get("handoff", {})
            projects = ProjectStore(
                os.environ.get(
                    "ZARYA_PROJECTS_DIR", str(Path.home() / ".zarya" / "projects")
                )
            )
            if previous.get("input_hash") == input_hash and projects.exists(
                previous.get("project_id", "")
            ):
                project_id = previous["project_id"]
            else:
                project_id = projects.save(req)
                draft["handoff"] = {"project_id": project_id, "input_hash": input_hash}
    except IntakeError as exc:
        failure(exc)
    return JSONResponse(
        {"next_url": f"/wizard/open/{project_id}", "draft": public_draft(draft)},
        headers={"Cache-Control": "no-store"},
    )
