"""Input adapter for the existing V1 solver, not another hydraulic engine."""

import math
import re

from app.intake.request_dto import V1SectionRequest
from app.calc.t3_hydraulics import T3SectionInput, validate_t3_section


MAX_SECTIONS = 30
SECTION_KEYS = {
    "section_id", "role", "length_m", "inner_diameter_mm", "roughness_mm",
    "flow_lps", "material",
}


def validate_sections(value):
    if value is None or value == []:
        return None
    if not isinstance(value, list) or len(value) > MAX_SECTIONS:
        raise ValueError(f"Укажите не более {MAX_SECTIONS} участков одного расчётного пути.")
    result, ids = [], set()
    for index, row in enumerate(value, 1):
        if not isinstance(row, dict) or set(row) - SECTION_KEYS:
            raise ValueError(f"Участок {index}: неизвестные поля.")
        sid = row.get("section_id", "")
        if not isinstance(sid, str) or not sid.strip() or len(sid) > 60 or sid.strip() in ids:
            raise ValueError(f"Участок {index}: нужно уникальное обозначение до 60 символов.")
        sid = sid.strip()
        ids.add(sid)
        role = row.get("role")
        if role not in {"input", "internal"}:
            raise ValueError(f"Участок {sid}: выберите ввод или внутреннюю сеть.")
        material = row.get("material", "")
        if not isinstance(material, str) or len(material) > 120:
            raise ValueError(f"Участок {sid}: материал — текст до 120 символов.")
        item = dict(section_id=sid, role=role, material=material.strip())
        for key, label in (("length_m", "длина"), ("inner_diameter_mm", "внутренний диаметр"),
                           ("roughness_mm", "шероховатость"), ("flow_lps", "расход")):
            raw = row.get(key)
            if key == "flow_lps" and role == "input" and (raw is None or raw == ""):
                item[key] = None  # Recomputed from current demand on every run.
                continue
            text = str(raw).strip().replace(",", ".")
            if isinstance(raw, bool) or not re.fullmatch(r"[+\-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
                raise ValueError(f"Участок {sid}: {label} — укажите число.")
            number = float(text)
            if not math.isfinite(number) or number < 0 or (number == 0 and key != "roughness_mm"):
                raise ValueError(f"Участок {sid}: недопустимое значение ({label}).")
            item[key] = number
        result.append(item)
    return result


def sections_complete(rows):
    # No implicit zero loss for a missing inlet/internal part of the route.
    return {row["role"] for row in rows or []} == {"input", "internal"}


def section_requests(rows, demand, *, heater_in_scope, hws_type):
    flow = demand["total" if hws_type == "local" or heater_in_scope else "cold"]["q_sec"]
    return [V1SectionRequest(**{
        **row, "flow_lps": flow if row["flow_lps"] is None else row["flow_lps"],
    }) for row in rows]


def validate_t3_sections(value):
    if value is None or value == []:
        return None
    if not isinstance(value, list) or len(value) > MAX_SECTIONS:
        raise ValueError(f"Укажите не более {MAX_SECTIONS} участков Т3.")
    result, ids = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) - set(T3SectionInput.__dataclass_fields__):
            raise ValueError("Т3: неизвестные поля участка")
        clean = dict(row)
        for key in ("length_m", "inner_diameter_mm", "roughness_mm", "flow_lps",
                    "circulation_flow_lps", "velocity_limit_mps"):
            raw = row.get(key)
            if key in {"circulation_flow_lps", "velocity_limit_mps"} and raw in (None, ""):
                clean[key] = None
                continue
            if isinstance(raw, bool):
                raise ValueError(f"Т3: {key} должно быть числом")
            try:
                clean[key] = float(str(raw).strip().replace(",", "."))
            except ValueError as exc:
                raise ValueError(f"Т3: {key} должно быть числом") from exc
        try:
            section = T3SectionInput(**clean)
            validate_t3_section(section)
        except TypeError as exc:
            raise ValueError("Т3: не хватает исходных данных участка") from exc
        if section.section_id.strip() in ids:
            raise ValueError("Обозначения участков Т3 повторяются")
        ids.add(section.section_id.strip())
        result.append(vars(section).copy())
    return result
