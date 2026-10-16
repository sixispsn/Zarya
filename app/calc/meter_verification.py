"""Explicit evidence for SP 30, 12.16в; never derived from peak demand."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class MeterMinimumEvidence:
    dn_mm: int | None = None
    q_min_hourly_m3h: float | None = None
    q_min_passport_m3h: float | None = None
    passport_reference: str = ""
    flow_reference: str = ""


def validate_meter_minimum_checks(raw) -> dict[str, MeterMinimumEvidence]:
    if not isinstance(raw, dict) or set(raw) - {"total", "cold", "hot"}:
        raise ValueError("meter_minimum_checks: допустимы только узлы total, cold, hot")
    result = {}
    for key, value in raw.items():
        try:
            row = MeterMinimumEvidence(**value) if isinstance(value, dict) else value
        except TypeError as exc:
            raise ValueError(f"meter_minimum_checks.{key}: неизвестные поля") from exc
        if not isinstance(row, MeterMinimumEvidence):
            raise ValueError(f"meter_minimum_checks.{key}: нужны данные проверки")
        if row.dn_mm is not None and (type(row.dn_mm) is not int or row.dn_mm <= 0):
            raise ValueError(f"meter_minimum_checks.{key}: DN должен быть положительным целым")
        for name in ("q_min_hourly_m3h", "q_min_passport_m3h"):
            number = getattr(row, name)
            if number is not None and (
                isinstance(number, bool) or not isinstance(number, (float, int))
                or not isfinite(number) or number < 0
                or (name == "q_min_passport_m3h" and number == 0)
            ):
                raise ValueError(f"meter_minimum_checks.{key}.{name}: недопустимый расход")
        for name in ("passport_reference", "flow_reference"):
            text = getattr(row, name)
            if not isinstance(text, str) or len(text) > 500:
                raise ValueError(f"meter_minimum_checks.{key}.{name}: нужна строка до 500 знаков")
        result[key] = row
    return result


def check_minimum_flow(dn_mm: int, evidence: MeterMinimumEvidence | None):
    missing = []
    evidence = evidence or MeterMinimumEvidence()
    if evidence.dn_mm != dn_mm:
        missing.append(f"паспорт выбранного DN{dn_mm}")
    if evidence.q_min_hourly_m3h is None or not evidence.flow_reference.strip():
        missing.append("минимальный расчётный часовой расход и его основание")
    if evidence.q_min_passport_m3h is None or not evidence.passport_reference.strip():
        missing.append("минимальный паспортный расход, модель/класс и ссылка на паспорт")
    if missing:
        return None, "Нужны данные: " + "; ".join(missing)
    passed = evidence.q_min_passport_m3h <= evidence.q_min_hourly_m3h
    return passed, ("Проверка минимального расхода выполнена" if passed
                    else "Минимальный паспортный расход превышает расчётный минимум")
