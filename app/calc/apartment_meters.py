"""Approved Studio estimate: reuse the working demand and meter calculators.

This is a preliminary representative apartment, not a verified governing one.
No new head-loss formula or meter catalogue is introduced here.
"""
from dataclasses import asdict

from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.calc.water_meters import MeterInput, calculate_meters


def estimate_apartment_meters(values: dict) -> dict | None:
    if not all(values.get(key) for key in ("residents", "apartments", "consumer_code", "hws_type")):
        return None
    if values["hws_type"] not in {"central", "none"}:
        return None  # Local heaters need their actual apartment metering arrangement.
    average = values["residents"] / values["apartments"]
    occupants = values.get("apartment_design_residents") or average
    demand = calculate_water_demand([
        ConsumerGroup(values["consumer_code"], occupants)
    ], apply_k06=False, round_consumers=False)
    cold = demand.total if values["hws_type"] == "none" else demand.cold
    result = calculate_meters(MeterInput(
        hws_type="central", q_sec_tot=demand.total.q_sec,
        q_sec_c=cold.q_sec, q_sec_h=demand.hot.q_sec,
        q_day_tot=demand.total.q_day, q_day_c=cold.q_day,
        q_day_h=demand.hot.q_day, q_hr_c=cold.q_hr, q_hr_h=demand.hot.q_hr,
    ))
    rows = {"h_apartment_c_meter_m": result.meters[0]}
    if values["hws_type"] != "none":
        rows["h_apartment_h_meter_m"] = result.meters[1]
    # The existing picker starts with DN15 but may select a larger meter if needed.
    if not all(row.pass_normal and row.pass_average for row in rows.values()):
        return None
    explicit = bool(values.get("apartment_design_residents"))
    occupants_label = f"{occupants:g}".replace(".", ",")
    basis = (
        f"Предварительный расчёт квартирных водомеров: {occupants_label} чел./квартиру"
        + (" заданы вручную." if explicit else
           f"; средняя заселённость — жители / квартиры ({values['residents']}/{values['apartments']}), без округления числа жителей.")
        + " Расходы — рабочий расчётчик; потери h=S·q² — каталог водомеров. "
        "Характеристики конкретной модели и диктующую квартиру необходимо подтвердить."
    )
    return {
        "average_residents": average, "design_residents": occupants,
        "basis": basis,
        "rows": {
            key: {"loss_m": row.h_normal, "dn": row.meter.d_mm, "s": row.meter.s,
                  "flow_lps": cold.q_sec if key.endswith("c_meter_m") else demand.hot.q_sec,
                  "meter": asdict(row.meter)}
            for key, row in rows.items()
        },
    }
