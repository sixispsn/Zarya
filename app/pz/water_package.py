"""Compose existing IOS2 documents, without rerendering or duplicating appendices."""
from app.pz.generator import merge_pdfs


PARTS = (
    ("pz_pdf", "ИОС2. Пояснительная записка и расчётные приложения"),
    ("scheme_pdf", "ИОС2. Принципиальная схема водоснабжения"),
    ("metering_scheme_pdf", "ИОС2. Вводы и водомерные узлы"),
    ("pump_zone_scheme_pdf", "ИОС2. Насосы, зоны и ГВС"),
    ("fire_station_scheme_pdf", "ИОС2. В2: насосная, стояки и узлы"),
    ("hydraulic_pdf", "ИОС2. Гидравлический расчёт В2"),
    ("resilience_pdf", "ИОС2. Проверка живучести В2"),
    ("spec_pdf", "ИОС2. Спецификация"),
)
REQUIRED = {"pz_pdf", "scheme_pdf", "metering_scheme_pdf", "pump_zone_scheme_pdf", "spec_pdf"}


def missing_water_parts(bundle) -> list[str]:
    return [title for key, title in PARTS if key in REQUIRED and not getattr(bundle, key, None)]


def generate_water_package(bundle, output_path: str) -> str:
    # Balance, V1, pump selection and new V2 calculations already live in PZ.
    # Sewer documents and the joint QA passport must not be appended to IOS2.
    parts = [(getattr(bundle, key, None), title) for key, title in PARTS]
    parts = [(path, title) for path, title in parts if path]
    return merge_pdfs([p for p, _ in parts], output_path,
                      section_titles=[title for _, title in parts])
