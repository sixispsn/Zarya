"""Preview a typological building programme before engineering generation."""
from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.architecture.residential_program import (
    BuildingProgramTopology,
    ResidentialProgramInput,
    build_residential_program,
)


router = APIRouter(prefix="/wizard", tags=["building-model"])
_TPL = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

_DEFAULTS = {
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
    errors: tuple[str, ...] = (),
) -> dict[str, Any]:
    system_counts = {
        system: len(model.fixtures_for_system(system)) if model else 0
        for system in ("V1", "T3", "K1", "K2", "K3")
    }
    return {
        "values": values or dict(_DEFAULTS),
        "model": model,
        "errors": errors,
        "system_counts": system_counts,
        "levels": _level_summary(model) if model else (),
    }


@router.get("/building-model", response_class=HTMLResponse)  # type: ignore[misc]
def building_model_page(request: Request) -> HTMLResponse:
    return _TPL.TemplateResponse(
        request,
        "wizard_building_model.html",
        _context(),
    )


@router.post("/building-model", response_class=HTMLResponse)  # type: ignore[misc]
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


@router.post("/building-model.json")  # type: ignore[misc]
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
