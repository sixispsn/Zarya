"""Manufacturer evidence for L06 screening, NOT an approved V2 equipment list.

Unknown fields stay unknown. A product family is not a configured order code;
PN/Kv and a generic water application do not establish fire-system suitability.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RegulatorCandidate:
    id: str
    name: str
    dn: int
    source_url: str
    source_locator: str
    source_sha256: str | None
    function: str
    fire_application_declared: bool | None
    excluded_applications: tuple[str, ...]
    flow_range_m3h: tuple[float, float] | None
    setting_range_bar: tuple[float, float] | None
    minimum_drop_bar: tuple[float, float] | None
    nominal_pressure_bar: float | None
    max_inlet_bar: float | None
    kv_m3h: float | None
    nominal_no_flow_extra_bar: float | None
    open_issues: tuple[str, ...]
    notes: tuple[str, ...]


CANDIDATES = (
    RegulatorCandidate(
        id="ridan-c101-082X6100RL", name="Ридан C101-R, 082X6100RL", dn=50,
        source_url="https://ridan.ru/files/1899/1899384-082X6100RL_%D0%9F%D0%B0%D1%81%D0%BF%D0%BE%D1%80%D1%82.pdf",
        source_locator="Паспорт от 08.09.2026: с.2, 4-5",
        source_sha256="ede8969cdddf9fb8c26e8882c6a423751d9c6aaf3278b8a80add8fab8abd8dce",
        function="pressure_reducing", fire_application_declared=None,
        excluded_applications=("automatic_water_foam_fire",),
        flow_range_m3h=(.5, 45), setting_range_bar=(.5, 8),
        minimum_drop_bar=(1.5, 1.5), nominal_pressure_bar=16,
        max_inlet_bar=None, kv_m3h=65, nominal_no_flow_extra_bar=0,
        open_issues=("vpv_application", "accuracy_and_lockup_tolerance",
                     "cavitation_at_duty", "installation_and_failure_scheme"),
        notes=("Паспорт исключает автоматическое водяное/пенное пожаротушение. "
               "Это не доказательство запрета отдельного ВПВ с ПК, но и не его разрешение.",
               "Место изготовления по паспорту - Турция; не считать изделием российского производства.",
               "Ниже 0,5 м³/ч возможна неустойчивость; Q=0 отдельно описан как герметичное закрытие.",
               "Паспорт: 1,5 бар. РЭ с.5: минимум 12 м; каталог: 12-15 м. "
               "В проверке принят паспорт конкретного артикула, расхождение не усредняется.")),
    RegulatorCandidate(
        id="asta-r01-02-dn50-family", name="АСТА Р01/02 DN50 (семейство)", dn=50,
        source_url="https://npoasta.ru/data/description/pilot_valve/ASTA_R01_feb26.pdf",
        source_locator="Описание серии Р01: PDF с.1-4 / печатные с.80-82",
        source_sha256="23f778add79584b5c223d72fb55f8cbe9a96a401b4c899bed238b75b04cb5486",
        function="pressure_reducing", fire_application_declared=None,
        excluded_applications=(), flow_range_m3h=None,
        setting_range_bar=(.4, 14), minimum_drop_bar=(.5, 1.5),
        nominal_pressure_bar=16, max_inlet_bar=None, kv_m3h=50,
        nominal_no_flow_extra_bar=None,
        open_issues=("exact_pilot_and_membrane", "vpv_application", "flow_operating_range",
                     "accuracy_and_lockup_tolerance", "cavitation_at_duty",
                     "installation_and_failure_scheme"),
        notes=("Диапазон конкретного пилота и минимальный перепад - по запросу; "
               "нижнюю границу 0,5 бар нельзя присвоить любому исполнению.",
               "Kvs=50 не означает максимальный регулируемый расход 50 м³/ч.",
               "Кавитационная диаграмма есть, но подбор исполнения по ней ещё не подтверждён.")),
    RegulatorCandidate(
        id="pvo-rkm60-dn50-family", name="ПромВодОчистка РКМ-60 DN50", dn=50,
        source_url="https://prom-water.ru/articles/klapan-dlya-sistem-pozharotusheniya/",
        source_locator="Статья изготовителя: характеристики и описание, проверено 04.10.2026",
        source_sha256=None, function="pressure_reducing", fire_application_declared=True,
        excluded_applications=(), flow_range_m3h=None, setting_range_bar=None,
        minimum_drop_bar=None, nominal_pressure_bar=None, max_inlet_bar=16,
        kv_m3h=None, nominal_no_flow_extra_bar=1,
        open_issues=("configured_passport", "flow_operating_range", "minimum_control_drop",
                     "accuracy_and_lockup_tolerance", "cavitation_at_duty",
                     "installation_and_failure_scheme"),
        notes=("Изготовитель прямо указывает противопожарное водоснабжение.",
               "При работе в тупик заявлено давление уставки плюс 1 бар, а не точно уставка.",
               "Статья не заменяет паспорт и подтверждение характеристик конкретного исполнения.")),
)


def get_candidate(candidate_id: str) -> RegulatorCandidate:
    return next(c for c in CANDIDATES if c.id == candidate_id)
