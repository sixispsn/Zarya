"""Загрузка и подтверждение архитектурных PDF-планов."""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.analysis.architecture_confirmation import (
    ConfirmedArchitectureSectionInput,
    PdfFloorSectionConfirmation,
    PdfScaleConfirmation,
    PdfSectionCellConfirmation,
    PdfSectionCutConfirmation,
    audit_confirmed_architecture_section,
    build_confirmed_architecture_section,
    build_pdf_plan_preview_svg,
    build_section_interval_drafts,
    confirmed_architecture_section_from_mapping,
    confirmed_architecture_section_to_mapping,
    find_cut_intersection_candidates,
)
from app.analysis.architecture_import_store import ArchitectureImportStore
from app.analysis.architecture_wastewater_binding import (
    RECEIVER_DEFINITIONS,
    ArchitectureWastewaterBindingIssue,
    ConfirmedArchitectureWastewaterBinding,
    ConfirmedReceiverPlacement,
    ConfirmedRiserFloorPlacement,
    architecture_wastewater_binding_from_mapping,
    architecture_wastewater_binding_to_mapping,
    audit_architecture_wastewater_binding,
    build_bound_wastewater_layout,
)
from app.analysis.architecture_pdf import (
    MAX_ARCHITECTURE_PDF_BYTES,
    ArchitecturePdfError,
    PdfPlanPoint,
    survey_architecture_pdf,
)
from app.intake.project_builder import RequestValidationError, build_project
from app.intake.project_store import ProjectStore
from app.pz.wastewater_layout import audit_wastewater_layout
from app.pz.wastewater_structure_renderer import (
    WastewaterStructureScope,
    build_wastewater_structure_svg,
)
from app.pz.wastewater_scheme_service import generate_wastewater_scheme


router = APIRouter(prefix="/wizard", tags=["architecture-import"])
_TPL = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)
_STORE = ArchitectureImportStore()
_PROJECT_STORE = ProjectStore()
_EXPORT_ROOT = os.environ.get(
    "ZARYA_ARCHITECTURE_EXPORT_ROOT",
    "/tmp/zarya_architecture_exports",
)


def _context(**values):
    return {
        "errors": [],
        "survey": None,
        "import_id": None,
        "selected_page": None,
        "preview_svg": "",
        "form_values": {},
        "candidates": (),
        "selected_stations": (),
        "intervals": (),
        "cell_values": (),
        "confirmed_model": None,
        "wastewater_binding": None,
        "wastewater_binding_issues": (),
        "projects": (),
        "project_link": None,
        "linked_project": None,
        "linked_project_registry": None,
        "wastewater_control_ready": False,
        "receiver_definitions": tuple(RECEIVER_DEFINITIONS.values()),
        "kind_labels": {
            "vector": "Векторный план",
            "vector_sparse": "Недостаточно векторов",
            "raster": "Растровый скан",
            "text_only": "Только текст",
            "empty": "Геометрия не найдена",
        },
        **values,
    }


def _page(survey, page_number: int):
    try:
        return next(row for row in survey.pages if row.page_number == page_number)
    except StopIteration as exc:
        raise ValueError("Страница отсутствует в загруженном PDF.") from exc


def _initial_page(survey, requested: int | None = None):
    if requested is not None:
        return _page(survey, requested)
    return next(
        (row for row in survey.pages if row.selectable_for_vector_confirmation),
        survey.pages[0],
    )


def _workspace_context(
    import_id: str,
    *,
    requested_page: int | None = None,
    errors: list[str] | None = None,
    form_values: dict | None = None,
    scale: PdfScaleConfirmation | None = None,
    cut: PdfSectionCutConfirmation | None = None,
    candidates=(),
    selected_stations=(),
    intervals=(),
    cell_values=(),
    confirmed_model=None,
    wastewater_binding=None,
    wastewater_binding_issues=(),
):
    survey = _STORE.survey(import_id)
    page = _initial_page(survey, requested_page)
    if confirmed_model is None and not form_values and not errors:
        saved = _STORE.load_confirmations(import_id)
        if saved.get("floors"):
            confirmed = confirmed_architecture_section_from_mapping(saved)
            issues = audit_confirmed_architecture_section(confirmed)
            if issues:
                raise ValueError("; ".join(row.message for row in issues))
            if confirmed.source_sha256 != survey.sha256:
                raise ValueError("architecture confirmation checksum mismatch")
            confirmed_model = build_confirmed_architecture_section(confirmed)
            if requested_page is None:
                active_floor = max(confirmed.floors, key=lambda row: row.floor)
                page = _page(survey, active_floor.page_number)
            else:
                page_floors = tuple(
                    row
                    for row in confirmed.floors
                    if row.page_number == page.page_number
                )
                active_floor = (
                    max(page_floors, key=lambda row: row.floor)
                    if page_floors
                    else None
                )
            if active_floor is None:
                form_values = {
                    "plan_id": confirmed.plan_id,
                    "cut_id": confirmed.cut_id,
                }
                return _context(
                    survey=survey,
                    import_id=import_id,
                    selected_page=page,
                    preview_svg=Markup(build_pdf_plan_preview_svg(page)),
                    form_values=form_values,
                    confirmed_model=confirmed_model,
                    **_wastewater_binding_context(import_id),
                )
            scale = active_floor.scale
            cut = active_floor.cut
            candidates = find_cut_intersection_candidates(page, scale, cut)
            selected_stations = tuple(
                row.end_station_pt for row in active_floor.cells[:-1]
            )
            intervals = build_section_interval_drafts(
                scale,
                cut,
                selected_stations,
            )
            cell_values = tuple(
                {
                    "cell_id": row.cell_id,
                    "number": row.number,
                    "name": row.name,
                    "kind": row.kind,
                }
                for row in active_floor.cells
            )
            form_values = {
                "page_number": str(active_floor.page_number),
                "plan_id": confirmed.plan_id,
                "cut_id": confirmed.cut_id,
                "floor": str(active_floor.floor),
                "elevation_m": str(active_floor.elevation_m),
                "clear_height_m": str(active_floor.clear_height_m),
                "calibration_ax": str(scale.first.x_pt),
                "calibration_ay": str(scale.first.y_pt),
                "calibration_bx": str(scale.second.x_pt),
                "calibration_by": str(scale.second.y_pt),
                "calibration_distance_m": str(scale.real_distance_m),
                "cut_ax": str(cut.start.x_pt),
                "cut_ay": str(cut.start.y_pt),
                "cut_bx": str(cut.end.x_pt),
                "cut_by": str(cut.end.y_pt),
            }
    engineering_context = {}
    if confirmed_model is not None:
        engineering_context = _wastewater_binding_context(
            import_id,
            binding=wastewater_binding,
        )
        wastewater_binding = engineering_context.pop("wastewater_binding")
        wastewater_binding_issues = engineering_context.pop(
            "wastewater_binding_issues"
        )
    return _context(
        errors=errors or [],
        survey=survey,
        import_id=import_id,
        selected_page=page,
        preview_svg=Markup(build_pdf_plan_preview_svg(
            page,
            scale=scale,
            cut=cut,
            candidates=candidates,
        )),
        form_values=form_values or {},
        candidates=candidates,
        selected_stations=selected_stations,
        intervals=intervals,
        cell_values=cell_values,
        confirmed_model=confirmed_model,
        wastewater_binding=wastewater_binding,
        wastewater_binding_issues=wastewater_binding_issues,
        **engineering_context,
    )


def _linked_project(
    import_id: str,
    *,
    require_current: bool,
):
    link = _STORE.load_project_link(import_id)
    if not link:
        return None
    project_id = link["project_id"]
    if not _PROJECT_STORE.exists(project_id):
        raise ValueError(
            f"Связанный проект {project_id} удалён или недоступен."
        )
    current_sha256 = _PROJECT_STORE.source_sha256(project_id)
    if require_current and current_sha256 != link["project_source_sha256"]:
        raise ValueError(
            "Сохранённый проект изменён после подтверждения связи. "
            "Повторно выберите его в блоке инженерного графа."
        )
    request_dto = _PROJECT_STORE.load(project_id)
    try:
        project = build_project(request_dto)
    except RequestValidationError as exc:
        raise ValueError(
            "Связанный проект не прошёл проверку исходных данных: "
            + "; ".join(exc.problems)
        ) from exc
    return project


def _project_evaluation(
    import_id: str,
    architecture,
    binding: ConfirmedArchitectureWastewaterBinding,
) -> dict:
    projects = tuple(_PROJECT_STORE.list())
    link = _STORE.load_project_link(import_id)
    if not link:
        binding_issues = audit_architecture_wastewater_binding(
            architecture,
            binding,
        )
        return {
            "projects": projects,
            "project_link": None,
            "linked_project": None,
            "linked_project_registry": None,
            "wastewater_control_ready": False,
            "project": None,
            "layout": None,
            "issues": binding_issues,
        }

    project_id = link["project_id"]
    issues = []
    project = None
    layout = None
    current_sha256 = ""
    changed = False
    title = project_id
    try:
        request_dto = _PROJECT_STORE.load(project_id)
        title = (
            request_dto.document.object_name
            or request_dto.document.cipher
            or project_id
        )
        current_sha256 = _PROJECT_STORE.source_sha256(project_id)
        changed = current_sha256 != link["project_source_sha256"]
        if changed:
            issues.append(ArchitectureWastewaterBindingIssue(
                "project.changed",
                "Проект изменён после подтверждения связи. Повторно выберите "
                "его, чтобы зафиксировать новую версию YAML.",
            ))
        project = build_project(request_dto)
    except FileNotFoundError:
        issues.append(ArchitectureWastewaterBindingIssue(
            "project.missing",
            f"Связанный проект {project_id} удалён или недоступен.",
        ))
    except RequestValidationError as exc:
        issues.append(ArchitectureWastewaterBindingIssue(
            "project.invalid",
            "Связанный проект не прошёл проверку исходных данных: "
            + "; ".join(exc.problems),
        ))
    except ValueError as exc:
        issues.append(ArchitectureWastewaterBindingIssue(
            "project.invalid",
            f"Связанный проект не прочитан: {exc}",
        ))

    binding_issues = ()
    registry = None
    if project is not None:
        binding_issues = audit_architecture_wastewater_binding(
            architecture,
            binding,
            project=project,
        )
        receiver_rows = tuple(
            sorted(
                (
                    {
                        "element_id": row.element_id,
                        "kind": row.kind,
                        "system": row.system,
                        "dn_mm": row.dn_mm,
                    }
                    for row in project.sewage.elements
                    if row.kind in RECEIVER_DEFINITIONS
                ),
                key=lambda row: row["element_id"],
            )
        )
        registry = {
            "riser_ids": tuple(sorted({
                row.riser_id for row in project.sewage.risers
            })),
            "receivers": receiver_rows,
            "pipe_count": len(project.sewage.pipes),
        }
        if (
            not changed
            and not any(row.severity == "error" for row in binding_issues)
            and binding.risers
            and binding.receivers
        ):
            try:
                layout = build_bound_wastewater_layout(
                    architecture,
                    binding,
                    project,
                )
                layout_audit = audit_wastewater_layout(project, layout)
                issues.extend(layout_audit.errors)
                issues.extend(layout_audit.warnings)
                if not layout.routes:
                    issues.append(ArchitectureWastewaterBindingIssue(
                        "layout.routes_missing",
                        "Подтверждённая привязка не образовала ни одного участка схемы.",
                    ))
                    layout = None
            except ValueError as exc:
                issues.append(ArchitectureWastewaterBindingIssue(
                    "layout.not_ready",
                    str(exc),
                ))

    all_issues = tuple(binding_issues) + tuple(issues)
    ready = (
        project is not None
        and layout is not None
        and not changed
        and not any(row.severity == "error" for row in all_issues)
    )
    return {
        "projects": projects,
        "project_link": link,
        "linked_project": {
            "project_id": project_id,
            "title": title,
            "source_sha256": link["project_source_sha256"],
            "current_sha256": current_sha256,
            "changed": changed,
        },
        "linked_project_registry": registry,
        "wastewater_control_ready": ready,
        "project": project,
        "layout": layout,
        "issues": all_issues,
    }


def _wastewater_binding_context(
    import_id: str,
    *,
    binding: ConfirmedArchitectureWastewaterBinding | None = None,
) -> dict:
    saved_architecture = _STORE.load_confirmations(import_id)
    if not saved_architecture.get("floors"):
        return {
            "wastewater_binding": None,
            "wastewater_binding_issues": (),
        }
    architecture = confirmed_architecture_section_from_mapping(saved_architecture)
    if binding is None:
        saved_binding = _STORE.load_wastewater_binding(import_id)
        binding = (
            architecture_wastewater_binding_from_mapping(saved_binding)
            if saved_binding
            else ConfirmedArchitectureWastewaterBinding(
                plan_id=architecture.plan_id,
                cut_id=architecture.cut_id,
                architecture_source_sha256=architecture.source_sha256,
            )
        )
    evaluation = _project_evaluation(import_id, architecture, binding)
    return {
        "wastewater_binding": binding,
        "wastewater_binding_issues": evaluation.pop("issues"),
        "projects": evaluation.pop("projects"),
        "project_link": evaluation.pop("project_link"),
        "linked_project": evaluation.pop("linked_project"),
        "linked_project_registry": evaluation.pop("linked_project_registry"),
        "wastewater_control_ready": evaluation.pop(
            "wastewater_control_ready"
        ),
    }


def _number(form, name: str) -> float:
    raw = str(form.get(name, "")).strip().replace(",", ".")
    if not raw:
        raise ValueError(f"Не заполнено поле {name}.")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Поле {name} должно быть числом.") from exc


def _integer(form, name: str) -> int:
    value = _number(form, name)
    if not value.is_integer():
        raise ValueError(f"Поле {name} должно быть целым числом.")
    return int(value)


def _cell_reference(form, name: str) -> tuple[int, str]:
    raw = str(form.get(name, "")).strip()
    try:
        floor_raw, cell_id = raw.split("::", 1)
        floor = int(floor_raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Не выбрана архитектурная ячейка для поля {name}.") from exc
    if not cell_id.strip():
        raise ValueError(f"Не выбрана архитектурная ячейка для поля {name}.")
    return floor, cell_id.strip()


def _load_architecture_and_binding(import_id: str):
    saved = _STORE.load_confirmations(import_id)
    if not saved.get("floors"):
        raise ValueError("Сначала подтвердите архитектурный разрез.")
    architecture = confirmed_architecture_section_from_mapping(saved)
    binding_data = _STORE.load_wastewater_binding(import_id)
    binding = (
        architecture_wastewater_binding_from_mapping(binding_data)
        if binding_data
        else ConfirmedArchitectureWastewaterBinding(
            plan_id=architecture.plan_id,
            cut_id=architecture.cut_id,
            architecture_source_sha256=architecture.source_sha256,
        )
    )
    return architecture, binding


def _binding_error_context(import_id: str, message: str):
    architecture, binding = _load_architecture_and_binding(import_id)
    model = build_confirmed_architecture_section(architecture)
    return _workspace_context(
        import_id,
        errors=[message],
        confirmed_model=model,
        wastewater_binding=binding,
        wastewater_binding_issues=audit_architecture_wastewater_binding(
            architecture,
            binding,
        ),
    )


def _confirmation_geometry(form):
    page_number = int(_number(form, "page_number"))
    scale = PdfScaleConfirmation(
        first=PdfPlanPoint(
            _number(form, "calibration_ax"),
            _number(form, "calibration_ay"),
        ),
        second=PdfPlanPoint(
            _number(form, "calibration_bx"),
            _number(form, "calibration_by"),
        ),
        real_distance_m=_number(form, "calibration_distance_m"),
    )
    cut = PdfSectionCutConfirmation(
        start=PdfPlanPoint(
            _number(form, "cut_ax"),
            _number(form, "cut_ay"),
        ),
        end=PdfPlanPoint(
            _number(form, "cut_bx"),
            _number(form, "cut_by"),
        ),
    )
    return page_number, scale, cut


def _candidate_geometry(import_id: str, form):
    page_number, scale, cut = _confirmation_geometry(form)
    survey = _STORE.survey(import_id)
    page = _page(survey, page_number)
    if not page.selectable_for_vector_confirmation:
        raise ValueError("Выбранная страница не является пригодным векторным планом.")
    candidates = find_cut_intersection_candidates(page, scale, cut)
    if not candidates:
        raise ValueError(
            "Линия разреза не пересекла векторные границы. "
            "Проверьте страницу и координаты."
        )
    return survey, page_number, scale, cut, candidates


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
        await run_in_threadpool(
            survey_architecture_pdf,
            content,
            original_name=upload.filename,
        )
        import_id = await run_in_threadpool(
            _STORE.create,
            upload.filename,
            content,
        )
    except ArchitecturePdfError as exc:
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            _context(errors=[str(exc)]),
            status_code=422,
        )
    return RedirectResponse(
        url=f"/wizard/architecture/{import_id}",
        status_code=303,
    )


@router.get("/architecture/{import_id}", response_class=HTMLResponse)
def architecture_workspace(
    request: Request,
    import_id: str,
    page: int | None = None,
):
    try:
        context = _workspace_context(import_id, requested_page=page)
    except (ValueError, FileNotFoundError):
        return HTMLResponse("<h2>Импорт архитектуры не найден</h2>", status_code=404)
    return _TPL.TemplateResponse(request, "wizard_architecture.html", context)


@router.post("/architecture/{import_id}/cut", response_class=HTMLResponse)
async def architecture_cut_candidates(request: Request, import_id: str):
    form = await request.form()
    values = {str(key): str(value) for key, value in form.items()}
    try:
        _survey, page_number, scale, cut, candidates = _candidate_geometry(
            import_id, form
        )
        context = _workspace_context(
            import_id,
            requested_page=page_number,
            form_values=values,
            scale=scale,
            cut=cut,
            candidates=candidates,
        )
    except (ValueError, FileNotFoundError) as exc:
        try:
            requested = int(float(values.get("page_number", "1")))
            context = _workspace_context(
                import_id,
                requested_page=requested,
                errors=[str(exc)],
                form_values=values,
            )
        except (ValueError, FileNotFoundError):
            return HTMLResponse("<h2>Импорт архитектуры не найден</h2>", status_code=404)
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            context,
            status_code=422,
        )
    return _TPL.TemplateResponse(
        request,
        "wizard_architecture.html",
        context,
    )


@router.post("/architecture/{import_id}/boundaries", response_class=HTMLResponse)
async def architecture_confirm_boundaries(request: Request, import_id: str):
    form = await request.form()
    values = {str(key): str(value) for key, value in form.items()}
    try:
        _survey, page_number, scale, cut, candidates = _candidate_geometry(
            import_id, form
        )
        selected = sorted(
            float(str(row).replace(",", "."))
            for row in form.getlist("boundary_station_pt")
        )
        candidate_stations = [row.station_pt for row in candidates]
        if any(
            not any(abs(value - candidate) <= 0.02 for candidate in candidate_stations)
            for value in selected
        ):
            raise ValueError("Выбрана граница, которой нет среди кандидатов разреза.")
        intervals = build_section_interval_drafts(scale, cut, selected)
        floor = int(_number(form, "floor"))
        cells = tuple(
            {
                "cell_id": f"F{floor}-{index:02d}",
                "number": "",
                "name": "",
                "kind": "room",
            }
            for index, _row in enumerate(intervals, 1)
        )
        context = _workspace_context(
            import_id,
            requested_page=page_number,
            form_values=values,
            scale=scale,
            cut=cut,
            candidates=candidates,
            selected_stations=tuple(selected),
            intervals=intervals,
            cell_values=cells,
        )
    except (ValueError, FileNotFoundError) as exc:
        try:
            requested = int(float(values.get("page_number", "1")))
            context = _workspace_context(
                import_id,
                requested_page=requested,
                errors=[str(exc)],
                form_values=values,
            )
        except (ValueError, FileNotFoundError):
            return HTMLResponse("<h2>Импорт архитектуры не найден</h2>", status_code=404)
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            context,
            status_code=422,
        )
    return _TPL.TemplateResponse(request, "wizard_architecture.html", context)


@router.post("/architecture/{import_id}/confirm-floor", response_class=HTMLResponse)
async def architecture_confirm_floor(request: Request, import_id: str):
    form = await request.form()
    values = {str(key): str(value) for key, value in form.items()}
    starts = form.getlist("cell_start_pt")
    ends = form.getlist("cell_end_pt")
    ids = form.getlist("cell_id")
    numbers = form.getlist("cell_number")
    names = form.getlist("cell_name")
    kinds = form.getlist("cell_kind")
    try:
        survey, page_number, scale, cut, candidates = _candidate_geometry(
            import_id, form
        )
        lengths = {len(starts), len(ends), len(ids), len(numbers), len(names), len(kinds)}
        if lengths == {0} or len(lengths) != 1:
            raise ValueError("Таблица помещений повреждена или не заполнена.")
        cells = tuple(
            PdfSectionCellConfirmation(
                cell_id=str(cell_id).strip(),
                start_station_pt=float(str(start).replace(",", ".")),
                end_station_pt=float(str(end).replace(",", ".")),
                number=str(number).strip(),
                name=str(name).strip(),
                kind=str(kind).strip() or "room",
            )
            for start, end, cell_id, number, name, kind in zip(
                starts, ends, ids, numbers, names, kinds
            )
        )
        floor = PdfFloorSectionConfirmation(
            page_number=page_number,
            floor=int(_number(form, "floor")),
            elevation_m=_number(form, "elevation_m"),
            clear_height_m=_number(form, "clear_height_m"),
            scale=scale,
            cut=cut,
            cells=cells,
        )
        saved = _STORE.load_confirmations(import_id)
        existing = confirmed_architecture_section_from_mapping(saved) if saved.get("floors") else None
        plan_id = str(form.get("plan_id", "")).strip()
        cut_id = str(form.get("cut_id", "")).strip()
        if existing and (
            existing.plan_id != plan_id
            or existing.cut_id != cut_id
            or existing.source_sha256 != survey.sha256
        ):
            raise ValueError(
                "Обозначение разреза или исходный PDF изменились. "
                "Создайте отдельную сессию подтверждения."
            )
        floors = tuple(row for row in (existing.floors if existing else ()) if row.floor != floor.floor) + (floor,)
        confirmed = ConfirmedArchitectureSectionInput(
            plan_id=plan_id,
            cut_id=cut_id,
            source_name=survey.original_name,
            source_sha256=survey.sha256,
            floors=floors,
        )
        issues = audit_confirmed_architecture_section(confirmed)
        if issues:
            raise ValueError("; ".join(row.message for row in issues))
        model = build_confirmed_architecture_section(confirmed)
        _STORE.save_confirmations(
            import_id,
            confirmed_architecture_section_to_mapping(confirmed),
        )
        selected = tuple(row.end_station_pt for row in cells[:-1])
        intervals = build_section_interval_drafts(scale, cut, selected)
        cell_values = tuple(
            {
                "cell_id": row.cell_id,
                "number": row.number,
                "name": row.name,
                "kind": row.kind,
            }
            for row in cells
        )
        context = _workspace_context(
            import_id,
            requested_page=page_number,
            form_values=values,
            scale=scale,
            cut=cut,
            candidates=candidates,
            selected_stations=selected,
            intervals=intervals,
            cell_values=cell_values,
            confirmed_model=model,
        )
    except (ValueError, FileNotFoundError) as exc:
        try:
            page_number, scale, cut = _confirmation_geometry(form)
            intervals = tuple(
                build_section_interval_drafts(
                    scale,
                    cut,
                    [float(str(row).replace(",", ".")) for row in ends[:-1]],
                )
            ) if ends else ()
            cell_values = tuple(
                {"cell_id": str(i), "number": str(n), "name": str(name), "kind": str(kind)}
                for i, n, name, kind in zip(ids, numbers, names, kinds)
            )
            context = _workspace_context(
                import_id,
                requested_page=page_number,
                errors=[str(exc)],
                form_values=values,
                scale=scale,
                cut=cut,
                intervals=intervals,
                cell_values=cell_values,
            )
        except (ValueError, FileNotFoundError):
            return HTMLResponse("<h2>Импорт архитектуры не найден</h2>", status_code=404)
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            context,
            status_code=422,
        )
    return _TPL.TemplateResponse(request, "wizard_architecture.html", context)


@router.post(
    "/architecture/{import_id}/wastewater/riser",
    response_class=HTMLResponse,
)
async def architecture_add_wastewater_riser(request: Request, import_id: str):
    form = await request.form()
    try:
        architecture, binding = _load_architecture_and_binding(import_id)
        floor, cell_id = _cell_reference(form, "shaft_ref")
        placement_id = str(form.get("placement_id", "")).strip()
        row = ConfirmedRiserFloorPlacement(
            placement_id=placement_id,
            riser_id=str(form.get("riser_id", "")).strip(),
            system=str(form.get("system", "")).strip(),
            floor=floor,
            shaft_cell_id=cell_id,
            station_m=_number(form, "station_m"),
            dn_mm=_integer(form, "dn_mm"),
            source_ref=str(form.get("source_ref", "")).strip(),
            offset_from_below_confirmed=bool(
                form.get("offset_from_below_confirmed")
            ),
        )
        risers = tuple(
            existing
            for existing in binding.risers
            if existing.placement_id != placement_id
        ) + (row,)
        candidate = ConfirmedArchitectureWastewaterBinding(
            plan_id=binding.plan_id,
            cut_id=binding.cut_id,
            architecture_source_sha256=binding.architecture_source_sha256,
            risers=risers,
            receivers=binding.receivers,
        )
        issues = audit_architecture_wastewater_binding(
            architecture,
            candidate,
            project=_linked_project(import_id, require_current=True),
        )
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("; ".join(errors))
        _STORE.save_wastewater_binding(
            import_id,
            architecture_wastewater_binding_to_mapping(candidate),
        )
        context = _workspace_context(import_id)
    except (ValueError, FileNotFoundError) as exc:
        try:
            context = _binding_error_context(import_id, str(exc))
        except (ValueError, FileNotFoundError):
            return HTMLResponse("<h2>Импорт архитектуры не найден</h2>", status_code=404)
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            context,
            status_code=422,
        )
    return _TPL.TemplateResponse(request, "wizard_architecture.html", context)


@router.post(
    "/architecture/{import_id}/wastewater/receiver",
    response_class=HTMLResponse,
)
async def architecture_add_wastewater_receiver(
    request: Request,
    import_id: str,
):
    form = await request.form()
    try:
        architecture, binding = _load_architecture_and_binding(import_id)
        floor, cell_id = _cell_reference(form, "room_ref")
        placement_id = str(form.get("placement_id", "")).strip()
        row = ConfirmedReceiverPlacement(
            placement_id=placement_id,
            element_id=str(form.get("element_id", "")).strip(),
            kind=str(form.get("kind", "")).strip(),
            system=str(form.get("system", "")).strip(),
            floor=floor,
            room_cell_id=cell_id,
            station_m=_number(form, "station_m"),
            connection_height_m=_number(form, "connection_height_m"),
            quantity=_integer(form, "quantity"),
            dn_mm=_integer(form, "dn_mm"),
            riser_id=str(form.get("riser_id", "")).strip(),
            source_ref=str(form.get("source_ref", "")).strip(),
        )
        receivers = tuple(
            existing
            for existing in binding.receivers
            if existing.placement_id != placement_id
        ) + (row,)
        candidate = ConfirmedArchitectureWastewaterBinding(
            plan_id=binding.plan_id,
            cut_id=binding.cut_id,
            architecture_source_sha256=binding.architecture_source_sha256,
            risers=binding.risers,
            receivers=receivers,
        )
        issues = audit_architecture_wastewater_binding(
            architecture,
            candidate,
            project=_linked_project(import_id, require_current=True),
        )
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("; ".join(errors))
        _STORE.save_wastewater_binding(
            import_id,
            architecture_wastewater_binding_to_mapping(candidate),
        )
        context = _workspace_context(import_id)
    except (ValueError, FileNotFoundError) as exc:
        try:
            context = _binding_error_context(import_id, str(exc))
        except (ValueError, FileNotFoundError):
            return HTMLResponse("<h2>Импорт архитектуры не найден</h2>", status_code=404)
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            context,
            status_code=422,
        )
    return _TPL.TemplateResponse(request, "wizard_architecture.html", context)


@router.post("/architecture/{import_id}/wastewater/project")
async def architecture_link_wastewater_project(
    request: Request,
    import_id: str,
):
    form = await request.form()
    project_id = str(form.get("project_id", "")).strip()
    try:
        _STORE.metadata(import_id)
        request_dto = _PROJECT_STORE.load(project_id)
        build_project(request_dto)
        _STORE.save_project_link(
            import_id,
            project_id=project_id,
            project_source_sha256=_PROJECT_STORE.source_sha256(project_id),
        )
    except (FileNotFoundError, RequestValidationError, ValueError) as exc:
        try:
            context = _workspace_context(import_id, errors=[str(exc)])
        except (FileNotFoundError, ValueError):
            return HTMLResponse(
                "<h2>Импорт архитектуры не найден</h2>",
                status_code=404,
            )
        return _TPL.TemplateResponse(
            request,
            "wizard_architecture.html",
            context,
            status_code=422,
        )
    return RedirectResponse(
        url=f"/wizard/architecture/{import_id}",
        status_code=303,
    )


@router.post("/architecture/{import_id}/wastewater/project/delete")
def architecture_unlink_wastewater_project(import_id: str):
    try:
        _STORE.delete_project_link(import_id)
    except (FileNotFoundError, ValueError):
        return HTMLResponse(
            "<h2>Импорт архитектуры не найден</h2>",
            status_code=404,
        )
    return RedirectResponse(
        url=f"/wizard/architecture/{import_id}",
        status_code=303,
    )


@router.get("/architecture/{import_id}/wastewater/control.svg")
def architecture_wastewater_control_svg(import_id: str):
    try:
        evaluation = _ready_wastewater_evaluation(import_id)
        svg = build_wastewater_structure_svg(
            evaluation["project"],
            evaluation["layout"],
            scope=WastewaterStructureScope.FULL_FLOOR_STACK,
        )
        viewport_height_vw = (
            evaluation["layout"].sheet_height_mm
            / evaluation["layout"].sheet_width_mm
            * 100
        )
        svg = svg.replace(
            '<svg xmlns="http://www.w3.org/2000/svg"',
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'style="display:block;width:100vw;height:'
            f'min(100vh,{viewport_height_vw:.4f}vw)"',
            1,
        )
    except FileNotFoundError:
        return PlainTextResponse("Сессия или проект не найдены.", status_code=404)
    except (RequestValidationError, ValueError) as exc:
        return PlainTextResponse(str(exc), status_code=422)
    return Response(
        svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (
                f'inline; filename="architecture-{import_id}-K1-K2.svg"'
            ),
        },
    )


def _ready_wastewater_evaluation(import_id: str) -> dict:
    architecture, binding = _load_architecture_and_binding(import_id)
    evaluation = _project_evaluation(import_id, architecture, binding)
    if not evaluation["wastewater_control_ready"]:
        messages = [
            row.message
            for row in evaluation["issues"]
            if row.severity == "error"
        ]
        raise ValueError(
            "; ".join(messages)
            or "Новая принципиальная схема ещё не прошла обязательные проверки."
        )
    return evaluation


@router.get("/architecture/{import_id}/wastewater/scheme.pdf")
def architecture_wastewater_scheme_pdf(import_id: str):
    try:
        evaluation = _ready_wastewater_evaluation(import_id)
        output_dir = os.path.join(_EXPORT_ROOT, import_id)
        os.makedirs(output_dir, mode=0o700, exist_ok=True)
        output_path = os.path.join(output_dir, "Схема_К1_К2.pdf")
        # Экран архитектурной привязки оставляет SVG-контроль подложки, но
        # кнопка PDF выпускает тот же канонический документ, что и комплект
        # ПЗ. Так пользователь больше не получает «новую» схему только с
        # этажами и иную схему из общего мастера.
        generate_wastewater_scheme(evaluation["project"], output_path)
        os.chmod(output_path, 0o600)
    except FileNotFoundError:
        return PlainTextResponse("Сессия или проект не найдены.", status_code=404)
    except (RequestValidationError, ValueError) as exc:
        return PlainTextResponse(str(exc), status_code=422)
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename="Схема_К1_К2.pdf",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/architecture/{import_id}/wastewater/delete")
async def architecture_delete_wastewater_placement(
    request: Request,
    import_id: str,
):
    form = await request.form()
    try:
        _architecture, binding = _load_architecture_and_binding(import_id)
        placement_id = str(form.get("placement_id", "")).strip()
        candidate = ConfirmedArchitectureWastewaterBinding(
            plan_id=binding.plan_id,
            cut_id=binding.cut_id,
            architecture_source_sha256=binding.architecture_source_sha256,
            risers=tuple(
                row for row in binding.risers if row.placement_id != placement_id
            ),
            receivers=tuple(
                row
                for row in binding.receivers
                if row.placement_id != placement_id
            ),
        )
        _STORE.save_wastewater_binding(
            import_id,
            architecture_wastewater_binding_to_mapping(candidate),
        )
    except (ValueError, FileNotFoundError):
        return HTMLResponse("<h2>Импорт архитектуры не найден</h2>", status_code=404)
    return RedirectResponse(
        url=f"/wizard/architecture/{import_id}",
        status_code=303,
    )


@router.post("/architecture/{import_id}/delete")
def architecture_delete(import_id: str):
    try:
        _STORE.delete(import_id)
    except ValueError:
        pass
    return RedirectResponse(url="/wizard/architecture", status_code=303)
