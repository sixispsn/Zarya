"""Explicit fan evidence in Studio; no inferred modes, dimensions or approvals."""
import math

from app.intake.registry_input_error import RegistryInputError, field_error
from app.intake.request_dto import SewerPipeRequest
from app.pz.wastewater_topology import _is_riser
from app.pz.wastewater_ventilation import FanInputError, FanVentilationInput

MAX_ROWS = 200
LABELS = {
    "terminal_id": "Обозначение окончания", "riser_ids": "ID стояков К1 — каждый с новой строки",
    "kind": "Тип окончания", "source_ref": "Источник подтверждения (лист / редакция)",
    "height_m": "Высота над кровлей / шахтой, м", "diameter_mm": "DN вытяжки, мм",
    "collector_diameter_mm": "DN сборного трубопровода, мм",
    "opening_distance_m": "До открываемых окон / балконов по горизонтали, м",
    "no_openings_confirmed": "Отсутствие окон / балконов подтверждено",
    "open_end_confirmed": "Открытое устье без колпака подтверждено",
    "separate_from_other_systems": "Отдельность от ОВ и дымоходов подтверждена",
    "condensate_drains_to_risers": "Сток конденсата к стоякам подтверждён",
    "cold_attic": "Сборный трубопровод на холодном чердаке",
    "attic_insulated": "Теплоизоляция на чердаке подтверждена",
    "plastic_exposed": "Пластик открыт солнечному воздействию",
    "uv_protected": "Защита от УФ подтверждена",
    "valve_above_highest_fixture": "Клапан выше борта наиболее высокого прибора",
    "valve_on_top_floor": "Клапан над полом верхнего этажа",
    "valve_sizing_verified": "Подбор воздушного клапана проверен",
    "valve_sizing_ref": "Основание подбора клапана",
}
TEXT = {"terminal_id", "kind", "source_ref", "valve_sizing_ref"}
NUMBERS = {"height_m", "diameter_mm", "collector_diameter_mm", "opening_distance_m"}
BOOLEANS = set(LABELS) - TEXT - NUMBERS - {"riser_ids"}
KINDS = [("unknown", "Не определён"), ("roof", "На кровлю / шахту"),
         ("valve", "Воздушный клапан"), ("unventilated", "Невентилируемый")]


def _issue(detail, index, field, code, message):
    return RegistryInputError([detail], [dict(code=code, registry="wastewater_fan_ventilation",
        row_index=index, field=field, message=f"Фановое окончание, строка {index + 1}: {message}")])


def _global_issue(detail, field, code):
    message = ("Вентиляция наружной сети: выберите «Да», «Нет» или «Неизвестно»."
               if field == "external_ventilation_verified"
               else "Основание вентиляции наружной сети: текст до 200 символов.")
    return RegistryInputError([detail], [dict(code=code, registry="wastewater_fan_ventilation",
        scope="global", field=field, message=message)])


def _global_value(value, field):
    try:
        if field == "external_ventilation_verified":
            return _boolean(value.get(field), "Вентиляция наружной сети")
        return _text(value.get(field, ""), "Основание вентиляции наружной сети")
    except ValueError as exc:
        raise _global_issue(str(exc), field,
                            "fan_global_boolean" if field == "external_ventilation_verified" else "fan_global_text") from exc


def _model(value):
    try:
        return FanVentilationInput.from_mapping(value)
    except FanInputError as exc:
        if exc.scope == "global":
            raise _global_issue(str(exc), exc.field, exc.code) from exc
        reasons = {
            "fan_model_id": "задайте обозначение окончания.",
            "fan_model_riser_ids": "задайте непустые уникальные ID стояков в строке.",
            "fan_model_kind": "тип окончания не поддерживается; выберите значение явно.",
            "fan_model_number": "введите конечное неотрицательное число либо оставьте неизвестным.",
            "fan_model_boolean": "выберите «Да», «Нет» или «Неизвестно».",
            "fan_model_reference": "основание должно быть текстом.",
            "fan_model_duplicate_id": "обозначение окончания повторяется; задайте уникальное обозначение.",
        }
        if exc.code not in reasons or exc.field not in LABELS or exc.row_index is None:
            raise
        raise _issue(str(exc), exc.row_index, exc.field, exc.code,
                     f"«{LABELS[exc.field]}»: {reasons[exc.code]}") from exc


def editor_columns():
    return [dict(key=key, label=label, required=key in {"terminal_id", "riser_ids"},
                 primary=key in {"terminal_id", "riser_ids", "kind", "source_ref"},
                 kind="ids" if key == "riser_ids" else "text" if key in TEXT else
                 "number" if key in NUMBERS else "boolean", options=KINDS if key == "kind" else None)
            for key, label in LABELS.items()]


def _text(raw, label):
    if not isinstance(raw, str) or len(raw.strip()) > 200:
        raise ValueError(f"{label}: текст до 200 символов.")
    return raw.strip()


def _boolean(raw, label):
    if raw is None or raw == "":
        return None
    if type(raw) is not bool:
        raise ValueError(f"{label}: явно да, нет или неизвестно.")
    return raw


def validate_value(value):
    if value is None:
        return None
    allowed = {"terminals", "external_ventilation_verified", "external_ventilation_ref"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Фановая вентиляция: неизвестные поля или неверный формат.")
    rows = value.get("terminals", [])
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError(f"Не более {MAX_ROWS} фановых окончаний.")
    clean = []
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) - LABELS.keys():
            raise ValueError(f"Фановое окончание {i}: неизвестные поля.")
        item = {}
        for key, raw in row.items():
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            if key in TEXT:
                try:
                    item[key] = _text(raw, LABELS[key])
                except ValueError as exc:
                    raise _issue(str(exc), i - 1, key, "fan_text_value",
                                 f"«{LABELS[key]}» — текст до 200 символов.") from exc
            elif key == "riser_ids":
                if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ROWS:
                    raise _issue("Задайте список ID стояков К1.", i - 1, key, "fan_ids_list",
                                 f"задайте список ID стояков К1 (от 1 до {MAX_ROWS} записей).")
                try:
                    item[key] = [_text(rid, "ID стояка") for rid in raw]
                except ValueError as exc:
                    raise _issue(str(exc), i - 1, key, "fan_ids_list",
                                 "каждый ID стояка должен быть текстом до 200 символов.") from exc
            elif key in BOOLEANS:
                try:
                    item[key] = _boolean(raw, LABELS[key])
                except ValueError as exc:
                    raise field_error(str(exc), "wastewater_fan_ventilation", i - 1,
                                      key, LABELS[key], "boolean_required") from exc
            else:
                try:
                    number = float(str(raw).strip().replace(",", "."))
                except (ValueError, TypeError) as exc:
                    raise field_error(f"{LABELS[key]}: требуется число.", "wastewater_fan_ventilation",
                                      i - 1, key, LABELS[key], "invalid_number") from exc
                if isinstance(raw, bool) or not math.isfinite(number):
                    raise field_error(f"{LABELS[key]}: требуется конечное число.", "wastewater_fan_ventilation",
                                      i - 1, key, LABELS[key], "nonfinite_number")
                item[key] = number
        if not item.get("terminal_id") or not item.get("riser_ids"):
            key = "terminal_id" if not item.get("terminal_id") else "riser_ids"
            raise field_error(f"Фановое окончание {i}: задайте обозначение и ID стояков К1.",
                              "wastewater_fan_ventilation", i - 1, key, LABELS[key], "required_value")
        clean.append(item)
    model = _model(dict(
        terminals=clean,
        external_ventilation_verified=_global_value(value, "external_ventilation_verified"),
        external_ventilation_ref=_global_value(value, "external_ventilation_ref"),
    ))
    return model.to_mapping() if model.terminals or model.external_ventilation_verified is not None or model.external_ventilation_ref else None


def validate_links(values):
    value = values.get("wastewater_fan_ventilation")
    if value is None:
        return
    model = _model(value)
    pipes = [SewerPipeRequest(**p) for p in values.get("sewer_pipes") or []]
    ids = {p.section_id for p in pipes if p.system == "K1" and _is_riser(p)}
    assigned = set()
    for index, terminal in enumerate(model.terminals):
        for rid in terminal.riser_ids:
            if rid not in ids:
                raise _issue(f"{terminal.terminal_id}: {rid} не является введённым стояком К1.",
                             index, "riser_ids", "fan_unlinked_riser", f"«{rid}» не является введённым стояком К1; проверьте список ID и реестр труб.")
            if rid in assigned:
                raise _issue(f"Стояк {rid} включён в несколько фановых окончаний.",
                             index, "riser_ids", "fan_repeated_riser", f"стояк «{rid}» включён в несколько окончаний; проверьте назначения.")
            assigned.add(rid)


def from_values(values):
    value = values.get("wastewater_fan_ventilation")
    return FanVentilationInput.from_mapping(value) if value else None
