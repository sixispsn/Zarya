"""Typed UI boundary for explicit K1/K2 registry rows, never derived geometry."""
from dataclasses import MISSING, asdict, fields
import math

from app.intake.request_dto import SewerPipeRequest, validate_sewer_pipes
from app.intake.registry_input_error import RegistryInputError, field_error

MAX_ROWS = 200  # UI/request bound, not a normative network limit.
LABELS = {
    "system": "Система", "section_id": "Обозначение участка", "purpose": "Назначение участка",
    "material": "Материал", "standard": "Стандарт / ТУ", "outer_diameter_mm": "Наружный диаметр, мм",
    "wall_thickness_mm": "Толщина стенки, мм", "length_m": "Фактическая длина, м",
    "from_node": "От узла (ID)", "to_node": "К узлу (ID)", "room": "Помещение / трасса",
    "insulated": "Теплоизоляция предусмотрена",
    "calculation_length_m": "Расчётная длина, м", "nominal_diameter_mm": "DN, мм",
    "design_flow_lps": "Заданный расход участка, л/с", "flow_source": "Источник расхода",
    "slope_per_mille": "Уклон, ‰", "fill_ratio": "Наполнение h/d",
    "elevation_start_m": "Начальная относительная отметка, м",
    "elevation_end_m": "Конечная относительная отметка, м",
    "absolute_elevation_start_m": "Начальная абсолютная отметка, м",
    "absolute_elevation_end_m": "Конечная абсолютная отметка, м",
    "manning_n": "Коэффициент Маннинга n", "hydraulic_source": "Основание коэффициента n",
    "critical_velocity_mps": "Критическая скорость, м/с",
    "critical_velocity_source": "Основание критической скорости",
    "critical_fill_ratio": "Предельное наполнение h/d",
    "pressure_rated": "Труба напорная", "pressure_class_bar": "Класс давления, бар",
    "catalog_series_id": "ID серии проверенного каталога",
    "q_hour_max_m3h": "Максимальный часовой расход участка, м³/ч",
    "fixtures_count": "Число подключённых приборов N",
    "receiving_length_m": "Длина приёма стоков L, м", "fixture_max_lps": "Сброс прибора q0s, л/с",
}
TEXT_KEYS = {"system", "section_id", "purpose", "material", "standard", "from_node", "to_node",
             "room", "flow_source", "hydraulic_source", "critical_velocity_source", "catalog_series_id"}
INTEGER_KEYS = {"nominal_diameter_mm", "fixtures_count"}
BOOLEAN_KEYS = {"insulated", "pressure_rated"}
REQUIRED = {f.name for f in fields(SewerPipeRequest) if f.default is MISSING} | {"insulated"}
PRIMARY = REQUIRED | {"from_node", "to_node", "room"}


def editor_columns():
    return [dict(key=key, label=label, required=key in REQUIRED, primary=key in PRIMARY,
                 kind="boolean" if key in BOOLEAN_KEYS else "text" if key in TEXT_KEYS else
                 "integer" if key in INTEGER_KEYS else "number") for key, label in LABELS.items()]


def validate_registry(value):
    if value is None or value == []:
        return None
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        raise ValueError(f"Реестр К1/К2: не более {MAX_ROWS} строк за один ввод.")
    result = []
    for index, row in enumerate(value, 1):
        if not isinstance(row, dict) or set(row) - LABELS.keys():
            raise ValueError(f"Участок {index}: неизвестные поля строки.")
        clean = {}
        for key in LABELS:
            raw = row.get(key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                if key in REQUIRED:
                    raise field_error(f"Участок {index}: укажите «{LABELS[key]}».",
                        "sewer_pipes", index - 1, key, LABELS[key], "required_value")
                continue  # DTO keeps absence; no inferred numbers or relationships.
            if key in TEXT_KEYS:
                if not isinstance(raw, str) or len(raw.strip()) > 200:
                    raise ValueError(f"Участок {index}: {LABELS[key]} — текст до 200 символов.")
                clean[key] = raw.strip()
            elif key in BOOLEAN_KEYS:
                if type(raw) is not bool:
                    raise field_error(f"Участок {index}: {LABELS[key]} — явно да или нет.",
                        "sewer_pipes", index - 1, key, LABELS[key], "boolean_required")
                clean[key] = raw
            else:
                try:
                    number = float(str(raw).strip().replace(",", "."))
                except (ValueError, TypeError) as exc:
                    raise field_error(f"Участок {index}: {LABELS[key]} — число.",
                        "sewer_pipes", index - 1, key, LABELS[key], "invalid_number") from exc
                if isinstance(raw, bool) or not math.isfinite(number):
                    raise field_error(f"Участок {index}: {LABELS[key]} — конечное число.",
                        "sewer_pipes", index - 1, key, LABELS[key], "nonfinite_number")
                if key in INTEGER_KEYS and not number.is_integer():
                    raise field_error(f"Участок {index}: {LABELS[key]} — целое число.",
                        "sewer_pipes", index - 1, key, LABELS[key], "integer_required")
                clean[key] = int(number) if key in INTEGER_KEYS else number
        if clean["system"] not in {"K1", "K2"}:
            raise ValueError(f"Участок {index}: этот редактор поддерживает только К1 и К2.")
        result.append(SewerPipeRequest(**clean))
    issues = []
    if errors := validate_sewer_pipes(result, input_issues=issues):
        raise RegistryInputError(errors, issues)
    return [asdict(pipe) for pipe in result]
