"""A control/preliminary PDF is a file, not a completed graphic artifact."""

WASTEWATER_GRAPHIC_ARTIFACTS = {
    "k1-k2": ("Принципиальная схема К1/К2", "wastewater_scheme_pdf"),
    "k3": ("Принципиальная схема К3", "wastewater_k3_scheme_pdf"),
    "pressure": ("Напорная канализация и рабочая точка", "wastewater_pressure_scheme_pdf"),
}
WASTEWATER_PACKAGE = "Комплект ИОС3"

# The same document dependencies drive the commission and read-only withdrawal.
COMMISSION_DOCUMENT_ARTIFACTS = {
    "DOC-01": ("Пояснительная записка", "Расчёты В1", "Баланс ВиВ",
               "Подбор насосов", "Спецификация", "Принципиальная схема"),
    "DOC-03": ("Пояснительная записка К1/К2", "Расчёты К1/К2",
               "Баланс ИОС3 по ГОСТ Р 21.620", "Принципиальная схема К1/К2",
               "Спецификация ИОС3", WASTEWATER_PACKAGE),
}


def qualify_artifact_presence(
    presence: dict[str, bool], readiness: dict | None, required_graphics=None,
) -> dict[str, bool]:
    """Shared by fresh bundles and exact-version saved previews; fail closed."""
    result = dict(presence)
    readiness = readiness if isinstance(readiness, dict) else {}
    for label in [*(label for label, _ in WASTEWATER_GRAPHIC_ARTIFACTS.values()), WASTEWATER_PACKAGE]:
        result[label] = bool(presence.get(label)) and readiness.get(label) is True
    known = {label for label, _ in WASTEWATER_GRAPHIC_ARTIFACTS.values()}
    requirements_valid = (
        isinstance(required_graphics, (list, tuple))
        and WASTEWATER_GRAPHIC_ARTIFACTS["k1-k2"][0] in required_graphics
        and all(isinstance(label, str) and label in known and result.get(label)
                for label in required_graphics)
    )
    result[WASTEWATER_PACKAGE] = result[WASTEWATER_PACKAGE] and bool(requirements_valid)
    return result
