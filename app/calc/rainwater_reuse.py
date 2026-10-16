"""Optional atmospheric-water reuse study; independent of legacy peak K2.

Daily reservoir mass balance, NOT a tank-sizing formula from SP 30. No climate,
collection efficiency, supply reliability or equipment passport is invented.
The chosen useful capacity is tested, not automatically approved for design.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta


PURPOSES = {
    "irrigation": "Полив",
    "toilets": "Смыв унитазов и писсуаров",
    "irrigation_toilets": "Полив и смыв унитазов",
    "other": "Другие технические нужды",
}
LOCATIONS = {"basement": "Подвал", "site": "Вне здания", "attic": "Чердак"}
REFERENCE = "СП 30.13330.2020, пп. 4.10, 14.18, 23.5, 26.17"
LIMITATIONS = (
    "Проверяется выбранный полезный объём бака, а не автоматически подобранная ёмкость. "
    "Начальное заполнение принято нулевым. В каждом суточном шаге сначала поступление и перелив, затем водоразбор. "
    "Покрытие потребности относится только к заданному периоду; это не гарантия водоснабжения в засуху. "
    "Суточный баланс не подтверждает качество воды и допустимый срок её хранения. "
    "Учитывается дождь; снег, снеготаяние и замерзание не моделируются. "
    "Расходы В1/Т3 и пиковый расход К2 не уменьшаются автоматически."
)


@dataclass
class RainwaterReuseInput:
    enabled: bool = False
    purpose: str = ""
    location: str = ""
    demand_m3_day: float | None = None
    useful_volume_m3: float | None = None
    collection_area_m2: float | None = None
    collection_factor: float | None = None
    profile: str = ""
    source: str = ""
    technical_use: str = ""
    treatment_setup: str = ""
    treatment_surface: str = ""
    treatment_selection_flow_lps: float | None = None
    treatment_filter_loss_m: float | None = None
    treatment_uv_loss_m: float | None = None
    treatment_selection_source: str = ""
    treatment_quality_basis: str = ""
    pump_setup: str = ""
    pump_flow_lps: float | None = None
    pump_geometric_head_m: float | None = None
    pump_terminal_head_m: float | None = None
    pump_network_loss_m: float | None = None
    pump_treatment_loss_m: float | None = None
    pump_loss_source: str = ""
    pump_min_submergence_m: float | None = None
    pump_max_submergence_m: float | None = None
    pump_temperature_c: float | None = None
    pump_clean_water: str = ""
    pump_pipe_inner_mm: float | None = None
    pump_pipe_length_m: float | None = None
    outlets_count: int | None = None
    hose_choice: str = ""
    hose_model: str = ""
    hose_length_m: float | None = None
    hose_inner_mm: float | None = None
    hose_pn_bar: float | None = None
    hose_loss_m: float | None = None
    hose_sets: int | None = None
    design_basis: str = ""
    design_storage: str = ""
    design_diversion: str = ""
    design_quality: str = ""
    design_network: str = ""
    design_annual: str = ""
    design_storage_days: float | None = None
    design_annual_saving_m3: float | None = None
    design_winter: str = ""
    design_discharge: str = ""
    design_review: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = []
        if type(self.enabled) is not bool:
            errors.append("Дождевая вода: включение должно быть true/false.")
        if self.purpose not in {"", *PURPOSES}:
            errors.append("Дождевая вода: неизвестное назначение.")
        if self.location not in {"", *LOCATIONS}:
            errors.append("Дождевая вода: неизвестное размещение бака.")
        for name in ("demand_m3_day", "useful_volume_m3", "collection_area_m2", "collection_factor"):
            value = getattr(self, name)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
                errors.append(f"Дождевая вода: {name} должно быть конечным положительным числом.")
        if type(self.collection_factor) in (int, float) and self.collection_factor > 1:
            errors.append("Коэффициент сбора дождевой воды не может превышать 1.")
        for name in ("source", "technical_use"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 200:
                errors.append(f"Дождевая вода: {name} — текст до 200 символов.")
        try:
            parse_profile(self.profile)
        except ValueError as exc:
            errors.append(str(exc))
        from app.calc.rainwater_pump import validate
        errors.extend(validate(self))
        from app.calc.rainwater_treatment import validate as validate_treatment
        errors.extend(validate_treatment(self))
        from app.calc.rainwater_design import validate as validate_design
        errors.extend(validate_design(self))
        return errors


def parse_profile(text: str) -> list[dict]:
    """ISO date; rainfall mm; optional demand m³. Consecutive daily records."""
    if not isinstance(text, str) or len(text) > 150_000:
        raise ValueError("Профиль дождя: требуется текст не длиннее 150 000 символов.")
    rows = []
    previous = None
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) not in (2, 3):
            raise ValueError("Профиль дождя: строка имеет вид ГГГГ-ММ-ДД; осадки, мм; потребность, м³ (необязательно).")
        try:
            day = date.fromisoformat(parts[0])
            rain = float(parts[1].replace(",", "."))
            demand = float(parts[2].replace(",", ".")) if len(parts) == 3 and parts[2] else None
        except (ValueError, OverflowError) as exc:
            raise ValueError("Профиль дождя: проверьте дату и числовые значения.") from exc
        if any(not math.isfinite(v) or v < 0 for v in (rain, demand) if v is not None):
            raise ValueError("Профиль дождя: осадки и потребность должны быть конечными неотрицательными числами.")
        if previous and day != previous + timedelta(days=1):
            raise ValueError("Профиль дождя: нужны последовательные дни, включая дни без осадков (0 мм).")
        rows.append({"date": day.isoformat(), "rain_mm": rain, "demand_m3": demand})
        previous = day
    if len(rows) > 3660:
        raise ValueError("Профиль дождя: максимум 3660 суток.")
    return rows


def from_dict(data: dict | None) -> RainwaterReuseInput:
    if data is None:
        return RainwaterReuseInput()
    if not isinstance(data, dict):
        raise ValueError("rainwater_reuse: требуется объект параметров.")
    unknown = set(data) - {f.name for f in fields(RainwaterReuseInput)}
    if unknown:
        raise ValueError("rainwater_reuse: неизвестные поля: " + ", ".join(sorted(unknown)))
    result = RainwaterReuseInput(**data)
    errors = result.validate()
    if errors:
        raise ValueError(" ".join(errors))
    return result


def from_studio(values: dict) -> RainwaterReuseInput:
    return from_dict({
        "enabled": values.get("rainwater_enabled") == "yes",
        **{f.name: values["rainwater_" + f.name] for f in fields(RainwaterReuseInput)
           if f.name != "enabled" and "rainwater_" + f.name in values},
    })


def assess(data: RainwaterReuseInput, *, building_kind=None, roof_kind=None) -> dict:
    context = dict(building_kind=building_kind, roof_kind=roof_kind)
    result = _assess_balance(data, **context)
    from app.calc.rainwater_design import assess_design
    result["design"] = assess_design(data, result, **context)
    return result


def _assess_balance(data: RainwaterReuseInput, *, building_kind=None, roof_kind=None) -> dict:
    from app.calc.rainwater_pump import assess_pump
    from app.calc.rainwater_treatment import assess_treatment
    context = dict(building_kind=building_kind, roof_kind=roof_kind)
    result = {"enabled": data.enabled, "status": "disabled", "input": asdict(data),
              "purpose": PURPOSES.get(data.purpose, "Не задано"),
              "location": LOCATIONS.get(data.location, "Не задано"),
              "reference": REFERENCE, "limitations": LIMITATIONS,
              "missing": [], "errors": [], "days": [], "totals": None,
              "treatment": assess_treatment(data, **context),
              "pump": assess_pump(data, **context)}
    if not data.enabled:
        return result
    errors = data.validate()
    if errors:
        result.update(status="invalid", errors=errors)
        return result
    profile = parse_profile(data.profile)
    needed = {
        "purpose": "назначение повторно используемой воды",
        "location": "место установки резервуара",
        "useful_volume_m3": "проверяемый полезный объём бака",
        "collection_area_m2": "площадь кровли, подключённая к баку",
        "collection_factor": "обоснованный коэффициент сбора с учётом потерь",
        "profile": "суточные осадки, включая сухие дни",
        "source": "источник осадков и коэффициента сбора",
    }
    missing = [title for key, title in needed.items()
               if not (getattr(data, key).strip() if isinstance(getattr(data, key), str) else getattr(data, key))]
    if not profile or any(row["demand_m3"] is None for row in profile):
        if data.demand_m3_day is None:
            missing.append("суточная потребность или полный график водоразбора")
    if data.purpose == "other" and not data.technical_use.strip():
        missing.append("описание технического потребителя и требований к воде")
    result["missing"] = missing
    result["storage_rule"] = (
        "Для полива СП 30, п. 14.18 устанавливает срок хранения 3–7 суток; конкретный режим требует обоснования."
        if data.purpose == "irrigation" else
        "При использовании для смыва унитазов/писсуаров срок хранения не более суток (СП 30, п. 14.18)."
        if data.purpose in {"toilets", "irrigation_toilets"} else
        "Допустимый срок хранения и качество воды определяются по назначению технического потребителя."
    )
    result["design_pending"] = [
        "Задание на систему; для жилого здания — технико-экономическое обоснование.",
        "Качество исходной и очищенной воды, отстаивание и обеззараживание; обслуживание и санитарная обработка.",
        "Раздельная маркированная сеть технической воды, параметры насоса и защита от сухого хода.",
        "Допустимый срок хранения, управление застоем воды и резервное обеспечение потребителей.",
        "Отметки, безопасный перелив и согласованная точка отвода избытка; соединение К2 с К1 не добавляется.",
        "Нагрузки на конструкции, доступ к резервуару и защита от замерзания по месту установки.",
    ]
    if missing:
        result["status"] = "needs_data"
        return result
    stored = 0.0
    totals = dict(inflow_m3=0.0, demand_m3=0.0, supplied_m3=0.0, deficit_m3=0.0, overflow_m3=0.0)
    for row in profile:
        inflow = row["rain_mm"] * data.collection_area_m2 * data.collection_factor / 1000
        demand = row["demand_m3"] if row["demand_m3"] is not None else data.demand_m3_day
        available = stored + inflow
        if not math.isfinite(available):
            result.update(status="invalid", errors=["Профиль дождя: объёмы превышают числовой диапазон."], days=[])
            return result
        overflow = max(0.0, available - data.useful_volume_m3)
        available = min(available, data.useful_volume_m3)
        supplied = min(available, demand)
        stored = available - supplied
        day = {**row, "inflow_m3": inflow, "demand_m3": demand, "supplied_m3": supplied,
               "deficit_m3": demand - supplied, "overflow_m3": overflow, "stored_m3": stored}
        result["days"].append(day)
        for key in totals:
            totals[key] += day[key]
        if not all(math.isfinite(value) for value in totals.values()):
            result.update(status="invalid", errors=["Профиль дождя: суммарные объёмы превышают числовой диапазон."], days=[])
            return result
    totals["stored_m3"] = stored
    totals["coverage_percent"] = 100 * totals["supplied_m3"] / totals["demand_m3"] if totals["demand_m3"] else None
    totals["mass_residual_m3"] = totals["inflow_m3"] - totals["supplied_m3"] - totals["overflow_m3"] - stored
    result.update(status="preliminary", totals=totals)
    return result
