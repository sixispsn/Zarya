"""Visible roof choices mapped to the existing rain and fan contracts.

Legacy `flat` remains ambiguous: never infer accessibility from that answer.
The fan minima come from the same table used by the validator and renderer.
"""
from app.pz.wastewater_ventilation import ROOF_VENT_HEIGHT_M

ROOF_CHOICES = {
    "single_slope": "Односкатная",
    "gable": "Двускатная",
    "complex": "Сложная / составная",
    "flat_accessible": "Плоская эксплуатируемая",
    "flat_non_accessible": "Плоская неэксплуатируемая",
}
ROOF_MAPPING = {
    "single_slope": ("sloped", "single_slope"),
    "sloped": ("sloped", "pitched"),
    "gable": ("sloped", "gable"),
    # Compound roofs can include accessible terraces: no single global rule.
    "complex": ("not_set", "complex"),
    "flat_accessible": ("flat", "flat_accessible"),
    "flat_non_accessible": ("flat", "flat_non_accessible"),
    "flat": ("flat", "unknown"),
}


def roof_rule(value: str | None) -> dict:
    rain_type, fan_kind = ROOF_MAPPING.get(value, ("not_set", "unknown"))
    minimum = ROOF_VENT_HEIGHT_M.get(fan_kind)
    if fan_kind == "complex":
        note = "Многоскатная или смешанная кровля: нужны участки, их отметки и места фановых выходов. Общую высоту вывода и водосбор пока не назначаем."
    elif value == "sloped":
        note = "Ранее указана скатная кровля без формы. Выберите односкатную, двускатную или сложную; прежние данные сохранены."
    elif minimum is None:
        note = "Уточните вид кровли: без него высота фанового вывода не определена."
    elif fan_kind == "flat_accessible":
        note = "Фановый вывод — минимум 3 м над кровлей. Нужна общая вытяжная часть минимум четырёх стояков; трасса объединения подтверждается отдельно."
    else:
        note = "Фановый вывод — минимум 0,2 м над кровлей в месте выхода."
        if fan_kind in {"pitched", "single_slope", "gable"}:
            note += " Для скатов нужна местная отметка кровли, не только отметка конька."
    return {"rain_type": rain_type, "fan_kind": fan_kind, "minimum_height_m": minimum,
            "minimum_group_risers": 4 if fan_kind == "flat_accessible" else None,
            "note": note, "reference": "СП 30.13330.2020, пп. 18.18, 18.22"}
