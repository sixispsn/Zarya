"""Preview a typological building programme before engineering generation."""
from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.architecture.engineering_handoff import (
    BuildingProgramHandoff,
    build_engineering_handoff,
)
from app.architecture.program_store import (
    BuildingProgramDraft,
    BuildingProgramStore,
)
from app.architecture.residential_program import (
    BuildingProgramTopology,
    ResidentialProgramInput,
    build_residential_program,
)


router = APIRouter(prefix="/wizard", tags=["building-model"])
_TPL = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)
_PROGRAM_STORE = BuildingProgramStore()

_DEFAULTS = {
    "model_title": "Жилой дом",
    "floors_above": "9",
    "apartments_total": "36",
    "floors_below": "1",
    "sections_count": "1",
    "sanitary_shafts_per_section": "2",
    "lift_shafts_per_section": "1",
    "apartments_by_floor": "",
    "apartment_sanitary_room_id": "apartment_sanitary_unit_shower",
    "has_refuse_chamber": "unknown",
    "has_underground_parking": "unknown",
    "apartment_has_washing_machine": "unknown",
    "apartment_has_dishwasher": "unknown",
    "refuse_chamber_has_drain": "unknown",
    "source_ref": "Типологическая модель стадии П — ввод пользователя",
}


def _integer(values: dict[str, str], name: str) -> int:
    raw = values.get(name, "").strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Поле «{name}» должно быть целым числом.") from exc


def _tri_state(value: str) -> bool | None:
    if value == "yes":
        return True
    if value == "no":
        return False
    if value in {"", "unknown"}:
        return None
    raise ValueError("Получен неизвестный вариант ответа да/нет.")


def _floor_distribution(raw: str) -> tuple[tuple[int, int], ...]:
    if not raw.strip():
        return ()
    result: list[tuple[int, int]] = []
    for item in re.split(r"[,;\n]+", raw):
        item = item.strip()
        if not item:
            continue
        parts = re.split(r"[:=]", item, maxsplit=1)
        if len(parts) != 2:
            raise ValueError(
                "Распределение квартир задаётся как «этаж: количество»."
            )
        try:
            result.append((int(parts[0].strip()), int(parts[1].strip())))
        except ValueError as exc:
            raise ValueError(
                "В распределении квартир этаж и количество должны быть целыми."
            ) from exc
    return tuple(result)


def _program_input(values: dict[str, str]) -> ResidentialProgramInput:
    fixture_answers: list[tuple[str, bool]] = []
    for key in (
        "apartment_has_washing_machine",
        "apartment_has_dishwasher",
        "refuse_chamber_has_drain",
    ):
        answer = _tri_state(values.get(key, "unknown"))
        if answer is not None:
            fixture_answers.append((key, answer))
    return ResidentialProgramInput(
        floors_above=_integer(values, "floors_above"),
        apartments_total=_integer(values, "apartments_total"),
        source_ref=values.get("source_ref", "").strip(),
        floors_below=_integer(values, "floors_below"),
        sections_count=_integer(values, "sections_count"),
        sanitary_shafts_per_section=_integer(
            values, "sanitary_shafts_per_section"
        ),
        lift_shafts_per_section=_integer(values, "lift_shafts_per_section"),
        apartments_by_floor=_floor_distribution(
            values.get("apartments_by_floor", "")
        ),
        apartment_sanitary_room_id=values.get(
            "apartment_sanitary_room_id",
            "apartment_sanitary_unit_shower",
        ),
        fixture_condition_answers=tuple(fixture_answers),
        has_refuse_chamber=_tri_state(
            values.get("has_refuse_chamber", "unknown")
        ),
        has_underground_parking=_tri_state(
            values.get("has_underground_parking", "unknown")
        ),
    )


def _form_values(form: Any) -> dict[str, str]:
    return {
        key: str(form.get(key) or "")
        for key in _DEFAULTS
    }


def _level_summary(model: BuildingProgramTopology) -> list[dict[str, Any]]:
    result = []
    for level in reversed(model.levels):
        rooms = tuple(row for row in model.rooms if row.level_id == level.level_id)
        room_ids = {row.room_id for row in rooms}
        fixtures = tuple(
            row for row in model.fixtures if row.room_id in room_ids
        )
        floor = level.floor_number
        apartments = tuple(
            row for row in model.apartments if row.floor_number == floor
        ) if floor is not None else ()
        shafts = tuple(
            row for row in model.sanitary_shafts
            if floor is not None and floor in row.served_floors
        )
        result.append({
            "level_id": level.level_id,
            "floor_number": floor,
            "display_label": (
                "Кровля"
                if floor is None
                else f"Подземный {abs(floor)}"
                if floor < 0
                else f"Этаж {floor}"
            ),
            "role": level.role,
            "apartments": len(apartments),
            "rooms": len(rooms),
            "fixtures": len(fixtures),
            "shafts": len(shafts),
            "room_labels": tuple(dict.fromkeys(row.label for row in rooms)),
        })
    return result


def _context(
    *,
    values: dict[str, str] | None = None,
    model: BuildingProgramTopology | None = None,
    saved_draft: BuildingProgramDraft | None = None,
    errors: tuple[str, ...] = (),
) -> dict[str, Any]:
    system_counts = {
        system: len(model.fixtures_for_system(system)) if model else 0
        for system in ("V1", "T3", "K1", "K2", "K3")
    }
    handoff: BuildingProgramHandoff | None = None
    if model is not None:
        handoff = build_engineering_handoff(
            model,
            basis_confirmed=(
                saved_draft.basis_confirmed if saved_draft is not None else False
            ),
        )
    return {
        "values": values or dict(_DEFAULTS),
        "model": model,
        "saved_draft": saved_draft,
        "errors": errors,
        "system_counts": system_counts,
        "handoff": handoff,
        "levels": _level_summary(model) if model else (),
        "recent_models": _PROGRAM_STORE.list()[:5],
    }


def _tristate_value(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _values_from_draft(draft: BuildingProgramDraft) -> dict[str, str]:
    value = draft.program_input
    fixture_answers = dict(value.fixture_condition_answers)
    return {
        "model_title": draft.title,
        "floors_above": str(value.floors_above),
        "apartments_total": str(value.apartments_total),
        "floors_below": str(value.floors_below),
        "sections_count": str(value.sections_count),
        "sanitary_shafts_per_section": str(value.sanitary_shafts_per_section),
        "lift_shafts_per_section": str(value.lift_shafts_per_section),
        "apartments_by_floor": ", ".join(
            f"{floor}: {count}" for floor, count in value.apartments_by_floor
        ),
        "apartment_sanitary_room_id": value.apartment_sanitary_room_id,
        "has_refuse_chamber": _tristate_value(value.has_refuse_chamber),
        "has_underground_parking": _tristate_value(
            value.has_underground_parking
        ),
        "apartment_has_washing_machine": _tristate_value(
            fixture_answers.get("apartment_has_washing_machine")
        ),
        "apartment_has_dishwasher": _tristate_value(
            fixture_answers.get("apartment_has_dishwasher")
        ),
        "refuse_chamber_has_drain": _tristate_value(
            fixture_answers.get("refuse_chamber_has_drain")
        ),
        "source_ref": value.source_ref,
    }


@router.get("/building-model", response_class=HTMLResponse)
def building_model_page(request: Request) -> HTMLResponse:
    return _TPL.TemplateResponse(
        request,
        "wizard_building_model.html",
        _context(),
    )


@router.post("/building-model", response_class=HTMLResponse)
async def building_model_preview(request: Request) -> HTMLResponse:
    form = await request.form()
    values = _form_values(form)
    try:
        model = build_residential_program(_program_input(values))
    except (ValueError, RuntimeError) as exc:
        return _TPL.TemplateResponse(
            request,
            "wizard_building_model.html",
            _context(values=values, errors=(str(exc),)),
            status_code=422,
        )
    return _TPL.TemplateResponse(
        request,
        "wizard_building_model.html",
        _context(values=values, model=model),
    )


@router.post("/building-model/save")
async def building_model_save(request: Request) -> Response:
    form = await request.form()
    values = _form_values(form)
    model: BuildingProgramTopology | None = None
    try:
        program_input = _program_input(values)
        model = build_residential_program(program_input)
        draft = _PROGRAM_STORE.save(
            program_input,
            title=values.get("model_title", ""),
        )
    except (ValueError, RuntimeError) as exc:
        return _TPL.TemplateResponse(
            request,
            "wizard_building_model.html",
            _context(values=values, model=model, errors=(str(exc),)),
            status_code=422,
        )
    return RedirectResponse(
        url=f"/wizard/building-model/{draft.model_id}",
        status_code=303,
    )


@router.post("/building-model/{model_id}/confirm")
async def building_model_confirm(
    request: Request,
    model_id: str,
) -> Response:
    try:
        draft = _PROGRAM_STORE.load(model_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    form = await request.form()
    try:
        if str(form.get("confirm_typological_basis") or "") != "yes":
            raise ValueError(
                "Подтвердите, что состав и распределение проверены проектировщиком."
            )
        _PROGRAM_STORE.confirm_basis(
            model_id,
            expected_topology_sha256=str(
                form.get("expected_topology_sha256") or ""
            ),
            confirmed_by=str(form.get("confirmed_by") or ""),
            confirmation_note=str(form.get("confirmation_note") or ""),
        )
    except ValueError as exc:
        return _TPL.TemplateResponse(
            request,
            "wizard_building_model.html",
            _context(
                values=_values_from_draft(draft),
                model=draft.topology,
                saved_draft=draft,
                errors=(str(exc),),
            ),
            status_code=422,
        )
    return RedirectResponse(
        url=f"/wizard/building-model/{model_id}",
        status_code=303,
    )


@router.get("/building-model/{model_id}/model.json")
def saved_building_model_json(model_id: str) -> JSONResponse:
    try:
        draft = _PROGRAM_STORE.load(model_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(
        draft.topology.to_dict(),
        headers={
            "Content-Disposition": (
                f'attachment; filename="zarya-building-program-{model_id}.json"'
            ),
        },
    )


@router.get("/building-model/{model_id}", response_class=HTMLResponse)
def saved_building_model_page(request: Request, model_id: str) -> HTMLResponse:
    try:
        draft = _PROGRAM_STORE.load(model_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _TPL.TemplateResponse(
        request,
        "wizard_building_model.html",
        _context(
            values=_values_from_draft(draft),
            model=draft.topology,
            saved_draft=draft,
        ),
    )


@router.post("/building-model.json")
async def building_model_json(request: Request) -> JSONResponse:
    form = await request.form()
    values = _form_values(form)
    try:
        model = build_residential_program(_program_input(values))
    except (ValueError, RuntimeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    return JSONResponse(
        model.to_dict(),
        headers={
            "Content-Disposition": (
                'attachment; filename="zarya-building-program.json"'
            ),
        },
    )


__all__ = ["router"]
