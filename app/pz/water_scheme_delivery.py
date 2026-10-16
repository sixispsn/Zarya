"""Describe the drawing actually built, not a second renderer or release gate."""
from hashlib import sha256

# Presentation revision: independent of calculation formulas and user answers.
DOCUMENT_RENDER_VERSION = "2026-10-16-floor-schematic-rooms"


def describe_scheme(result):
    if 'data-residential-water-section="approval"' in result.svg:
        renderer = "residential_cutaway"
        label = "В1 / Т3 / Т4 · характерный разрез"
        note = "Характерный разрез жилого здания. Не полная разводка и не источник объёмов труб."
    elif 'data-water-section="unified"' in result.svg:
        renderer = "unified_cutaway"
        label = "Водоснабжение · общий разрез"
        note = ("Общая компоновка: подробный квартирный разрез не применён к этим исходным. "
                "Для него нужны профиль с ванной ≥1500 мм, центральное ГВС, одна зона, один подвал, "
                "отметки этажей, кровли и ввода между подвалом и первым этажом.")
    else:
        renderer = "legacy_layout"
        label = "Водоснабжение · прежняя компоновка"
        note = ("Новая компоновка пока не охватывает условия этого проекта. "
                "Зоны, В2 и специальные системы не заменены типовым жилым разрезом.")
    return dict(renderer=renderer, label=label, note=note,
                warnings=list(result.warnings),
                render_version=DOCUMENT_RENDER_VERSION,
                svg_sha256=sha256(result.svg.encode("utf-8")).hexdigest())
