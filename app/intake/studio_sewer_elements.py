"""Explicit element rows. No quantities, floors or service approval inferred."""
from dataclasses import asdict
import math

from app.intake.registry_input_error import RegistryInputError, field_error
from app.intake.request_dto import (
    SewerElementRequest, SewerPipeRequest, SEWER_ELEMENT_KINDS, validate_sewer_elements,
)

MAX_ROWS = 200  # Technical editor bound, not a normative limit.
LABELS = {
    "element_id": "Обозначение элемента", "system": "Система", "kind": "Вид элемента",
    "name": "Наименование", "quantity": "Общее количество", "floor_from": "Начальный этаж",
    "accessible": "Доступность обслуживания подтверждена", "include_in_spec": "Включить в спецификацию",
    "unit": "Единица измерения", "section_id": "Участок (ID)", "connects_to": "Связь с элементом / узлом / участком (ID)",
    "typical_quantity": "Количество на типовом этаже", "floor_to": "Конечный этаж",
    "room_number": "Номер помещения", "room_name": "Помещение", "elevation_m": "Отметка, м",
    "dn_mm": "DN, мм", "slope_per_mille": "Уклон, ‰", "type_mark": "Тип / марка",
    "standard": "Стандарт / ТУ", "manufacturer": "Изготовитель", "note": "Примечание",
    "layout_column": "Колонка условной раскладки (не координата)",
    "service_direction": "Направление обслуживания", "service_fitting": "Исполнение доступа",
    "service_chainage_m": "Расстояние точки обслуживания от начала участка, м",
}
INTEGER_KEYS = {"quantity", "typical_quantity", "floor_from", "floor_to", "dn_mm", "layout_column"}
NUMBER_KEYS = {"elevation_m", "slope_per_mille", "service_chainage_m"}
BOOLEAN_KEYS = {"accessible", "include_in_spec"}
REQUIRED = {"element_id", "system", "kind", "name", "quantity", "floor_from", "accessible", "include_in_spec"}
PRIMARY = REQUIRED | {"unit", "section_id", "connects_to"}
KINDS = dict(zip(SEWER_ELEMENT_KINDS, (
    "Унитаз", "Умывальник", "Мойка", "Ванна", "Душ", "Трап", "Стиральная машина",
    "Посудомоечная машина", "Жироуловитель", "Водосточная воронка", "Ревизия", "Прочистка",
    "Противопожарная муфта", "Гидрозатвор", "Насос", "Приямок", "Шаровой кран",
    "Обратный клапан", "Петля разрыва давления", "Узел соединения", "Выпуск",
    "Тройник", "Отвод", "Переход", "Другое",
), strict=True))
OPTIONS = {
    "kind": list(KINDS.items()),
    "service_direction": [("downstream", "По потоку"), ("upstream", "Против потока"), ("both", "В обе стороны")],
    "service_fitting": [("wye_45", "Косое присоединение 45°"), ("revision_opening", "Ревизионное отверстие")],
}


def editor_columns():
    return [dict(key=key, label=label, required=key in REQUIRED, primary=key in PRIMARY,
                 kind="boolean" if key in BOOLEAN_KEYS else "integer" if key in INTEGER_KEYS else
                 "number" if key in NUMBER_KEYS else "text", options=OPTIONS.get(key))
            for key, label in LABELS.items()]


def validate_registry(value):
    """Type the rows; linked checks run on the entire proposed pair of registries."""
    if value is None or value == []:
        return None
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        raise ValueError(f"Элементы К1/К2: не более {MAX_ROWS} строк за один ввод.")
    result = []
    for index, row in enumerate(value, 1):
        if not isinstance(row, dict) or set(row) - LABELS.keys():
            raise ValueError(f"Элемент {index}: неизвестные поля строки.")
        # Blank product metadata must not acquire DTO's legacy placeholders.
        clean = {"manufacturer": "", "unit": ""}
        for key, label in LABELS.items():
            raw = row.get(key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                if key in REQUIRED:
                    raise field_error(f"Элемент {index}: укажите «{label}».",
                                      "sewer_elements", index - 1, key, label, "required_value")
                continue
            if key in BOOLEAN_KEYS:
                if type(raw) is not bool:
                    raise field_error(f"Элемент {index}: {label} — явно да или нет.",
                                      "sewer_elements", index - 1, key, label, "boolean_required")
                clean[key] = raw
            elif key in INTEGER_KEYS | NUMBER_KEYS:
                try:
                    number = float(str(raw).strip().replace(",", "."))
                except (ValueError, TypeError) as exc:
                    raise field_error(f"Элемент {index}: {label} — число.",
                                      "sewer_elements", index - 1, key, label, "invalid_number") from exc
                if isinstance(raw, bool) or not math.isfinite(number):
                    raise field_error(f"Элемент {index}: {label} — конечное число.",
                                      "sewer_elements", index - 1, key, label, "nonfinite_number")
                if key in INTEGER_KEYS and not number.is_integer():
                    raise field_error(f"Элемент {index}: {label} — целое число.",
                                      "sewer_elements", index - 1, key, label, "integer_required")
                clean[key] = int(number) if key in INTEGER_KEYS else number
            else:
                if not isinstance(raw, str) or len(raw.strip()) > 200:
                    raise ValueError(f"Элемент {index}: {label} — текст до 200 символов.")
                clean[key] = raw.strip()
        if clean["system"] not in {"K1", "K2"}:
            raise RegistryInputError([f"Элемент {index}: этот редактор поддерживает только К1 и К2."],
                [dict(code="element_system_choice", registry="sewer_elements", row_index=index - 1,
                      field="system", message=f"Элемент К1/К2, строка {index}: этот редактор поддерживает только К1 и К2; выберите систему явно.")])
        result.append(asdict(SewerElementRequest(**clean)))
    return result


def validate_network(values):
    elements = [SewerElementRequest(**row) for row in values.get("sewer_elements") or []]
    pipes = [SewerPipeRequest(**row) for row in values.get("sewer_pipes") or []]
    issues = []
    if errors := validate_sewer_elements(elements, pipes, input_issues=issues):
        raise RegistryInputError(errors, issues)
