"""L05: repeat average-flow admission against current demand, not saved flags."""
from math import isfinite

from app.data.water_meters import get_meter_by_d


def meter_node_key(row) -> str | None:
    label = row.label.lower()
    return ("total" if "ввод" in label else "hot" if "гвс" in label or "горяч" in label
            or "нагревател" in label else "cold" if "хвс" in label or "холодн" in label else None)


def check_meter_average(row, flows, source) -> tuple[bool | None, str]:
    key = {"total": "tot", "cold": "c", "hot": "h"}.get(meter_node_key(row))
    meter = get_meter_by_d(row.dn)
    if key is None or meter is None:
        return None, "Не определены назначение узла или каталожный типоразмер для проверки Qсред"
    day = getattr(flows, f"q_day_{key}", None)
    period = source.water_use_period_h
    if (day is None or period is None or not isfinite(day) or day < 0
            or not isfinite(period) or period <= 0):
        return None, "Не заданы корректные суточный расход и период потребления для проверки Qсред"
    average = day / period
    if not isfinite(average):
        return None, "Qсред выходит за численный диапазон"
    ok = average <= meter.q_expl
    # Use actual catalog capacity, not a forged/stale row.qexpl or ok_average.
    return ok, (f"Qсред={average:.6g} м³/ч {'≤' if ok else '>'} "
                f"Qэкспл={meter.q_expl:.6g} м³/ч для DN{meter.d_mm} (п. 12.14)")
