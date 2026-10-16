"""Explicit calculation records for existing K1 pipes, without inferred data."""
from dataclasses import MISSING, asdict, fields
import math

from app.data.sewage_tables import MATERIAL_LABELS, VENTILATION_LABELS
from app.intake.request_dto import SewageRiserRequest, SewerPipeRequest, validate_sewage_risers
from app.intake.registry_input_error import RegistryInputError, field_error
from app.pz.wastewater_topology import _is_riser

MAX_ROWS = 200
LABELS = {
    "riser_id": "ID стояка К1 из реестра труб", "design_flow_lps": "Расход именно этого стояка, л/с",
    "material": "Материал расчётной таблицы", "ventilation": "Режим вентиляции стояка",
    "riser_dn_mm": "Размер стояка для расчётной таблицы, мм",
    "branch_dn_mm": "Размер отвода для расчётной таблицы, мм",
    "branch_angle_deg": "Угол присоединения отвода, °", "has_toilet": "К стояку подключён унитаз",
    "working_height_m": "Рабочая высота стояка, м", "inner_diameter_mm": "Внутренний диаметр стояка, мм",
    "branch_inner_diameter_mm": "Внутренний диаметр отвода, мм",
    "minimum_trap_seal_mm": "Минимальная высота гидрозатвора, мм",
    "pressure_input_source": "Основание данных проверки давления",
    "air_valve_free_area_mm2": "Свободная площадь воздушного клапана, мм²",
    "air_valve_source": "Паспорт / источник площади клапана",
}
TEXT = {"riser_id", "material", "ventilation", "pressure_input_source", "air_valve_source"}
INTEGER = {"riser_dn_mm", "branch_dn_mm"}
REQUIRED = {f.name for f in fields(SewageRiserRequest) if f.default is MISSING} | {"has_toilet"}
OPTIONS = {"material":list(MATERIAL_LABELS.items()), "ventilation":list(VENTILATION_LABELS.items()),
           "branch_angle_deg":[("45", "45"), ("60", "60"), ("87.5", "87,5")]}


def editor_columns():
    return [dict(key=key, label=label, required=key in REQUIRED, primary=key in REQUIRED,
                 kind="boolean" if key == "has_toilet" else "text" if key in TEXT else
                 "integer" if key in INTEGER else "number", options=OPTIONS.get(key))
            for key, label in LABELS.items()]


def validate_value(value):
    if value is None or value == []:
        return None
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        raise ValueError(f"Не более {MAX_ROWS} расчётных стояков К1.")
    result = []
    for i, row in enumerate(value, 1):
        if not isinstance(row, dict) or set(row) - LABELS.keys():
            raise ValueError(f"Стояк {i}: неизвестные поля строки.")
        clean = {}
        for key, label in LABELS.items():
            raw = row.get(key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                if key in REQUIRED:
                    raise field_error(f"Стояк {i}: укажите «{label}».",
                        "sewage_risers", i - 1, key, label, "required_value")
                continue
            if key in TEXT:
                if not isinstance(raw, str) or len(raw.strip()) > 200:
                    raise ValueError(f"{label}: текст до 200 символов.")
                clean[key] = raw.strip()
            elif key == "has_toilet":
                if type(raw) is not bool:
                    raise field_error("Наличие унитаза: явно да или нет.",
                        "sewage_risers", i - 1, key, label, "boolean_required")
                clean[key] = raw
            else:
                try:
                    number = float(str(raw).strip().replace(",", "."))
                except (ValueError, TypeError) as exc:
                    raise field_error(f"{label}: требуется число.",
                        "sewage_risers", i - 1, key, label, "invalid_number") from exc
                if isinstance(raw, bool) or not math.isfinite(number):
                    raise field_error(f"{label}: требуется конечное число.",
                        "sewage_risers", i - 1, key, label, "nonfinite_number")
                if key in INTEGER and not number.is_integer():
                    raise field_error(f"{label}: требуется целое число.",
                        "sewage_risers", i - 1, key, label, "integer_required")
                clean[key] = int(number) if key in INTEGER else number
        result.append(SewageRiserRequest(**clean))
    issues = []
    if errors := validate_sewage_risers(result, input_issues=issues):
        raise RegistryInputError(errors, issues)
    return [asdict(r) for r in result]


def validate_links(values):
    pipes = [SewerPipeRequest(**row) for row in values.get("sewer_pipes") or []]
    ids = {p.section_id for p in pipes if p.system == "K1" and _is_riser(p)}
    for index, row in enumerate(values.get("sewage_risers") or []):
        if row["riser_id"] not in ids:
            raise RegistryInputError(
                [f"{row['riser_id']}: расчётная запись не связана с введённым стояком К1."],
                [dict(code="unlinked_riser", registry="sewage_risers", row_index=index,
                    field="riser_id", message=f"Расчётный стояк, строка {index + 1}: обозначение «{row['riser_id']}» не связано с введённым стояком К1. Проверьте обозначение и реестр труб; связь автоматически не назначается.")])
    # A declared mode and terminal kind are independent inputs. Their mismatch
    # stays a failure of the existing fan audit, never an automatic correction.
