"""Explicit fittings for VU junctions and the supported horizontal-filter offset."""
from dataclasses import dataclass
from app.pz.metering_rules import control_cock_dn

FITTING_ROLES = {"bypass_start", "bypass_end", "service_before", "service_after",
                 "fire_takeoff", "reducer_in", "reducer_out", "filter_turn_in", "filter_turn_out",
                 "maintenance_in", "maintenance_out"}


@dataclass(frozen=True)
class FittingCheck:
    role: str
    part: object | None
    errors: tuple[str, ...]
    pending: tuple[str, ...]


def check_fittings(detail, catalog, meter, *, bypass, fire_branch, revision_ok):
    checks = []
    meter_dn = meter.dn if meter else None
    control_dn = control_cock_dn(meter)
    expected = {
        "service_before": ("cross", (meter_dn, meter_dn, 15, control_dn)),
        "service_after": ("tee", (detail.inlet_dn, detail.inlet_dn, control_dn)),
    }
    if detail.maintenance_layout == "serviceable":
        expected.update(maintenance_in=("tee", (meter_dn, meter_dn, control_dn)),
                        maintenance_out=("tee", (detail.inlet_dn, detail.inlet_dn, control_dn)))
    from app.pz.metering_orientation import horizontal_filter_offset, FILTER_TURN_ROLES
    if horizontal_filter_offset(detail):
        expected.update({r: ('elbow90', (meter_dn, meter_dn)) for r in FILTER_TURN_ROLES})
    if bypass:
        expected.update({r:("tee", (detail.inlet_dn, detail.inlet_dn, detail.bypass_dn))
                         for r in ("bypass_start", "bypass_end")})
    if fire_branch:
        expected["fire_takeoff"] = ("tee", (detail.inlet_dn, detail.inlet_dn, detail.fire_branch_dn))
    if meter_dn and detail.inlet_dn and meter_dn != detail.inlet_dn:
        expected.update({r:("reducer", tuple(sorted((meter_dn, detail.inlet_dn), reverse=True)))
                         for r in ("reducer_in", "reducer_out")})
    for role, ident in detail.fitting_items.items():
        part, errors, pending = catalog.fittings.get(ident), [], []
        requirement = expected.get(role)
        if not revision_ok:
            errors.append("Редакция каталога не подтверждена")
        if requirement is None:
            errors.append("Узел отсутствует в текущей схеме")
        if role in detail.reducer_items:
            errors.append("Два изделия назначены одному переходу")
        if role == "reducer_out" and "meter_valve_out" in detail.connection_items:
            errors.append("Выход крана занят соединением С3 и переходом П2 одновременно")
        if part is None:
            errors.append("Неизвестная фасонная часть; автоматической замены нет")
        else:
            if requirement:
                kind, sizes = requirement
                if part.kind != kind or len(part.ports) != len(sizes):
                    errors.append("Число/назначение портов не соответствует узлу; тройник не заменяет крестовину")
                elif any(s is None for s in sizes):
                    errors.append("Не заданы все DN присоединений")
                elif tuple(p.dn for p in part.ports) != sizes:
                    errors.append("DN прохода или ответвления не соответствует текущему проекту")
            from app.pz.equipment_origin import origin_error
            if error := origin_error(detail, ident):
                errors.append(error)
            p, t = detail.design_pressure_bar, detail.water_temperature_c
            if p is not None and p > part.pn_bar:
                errors.append("Давление выше PN фасонной части")
            if t is not None and not part.temperature_c[0] <= t <= part.temperature_c[1]:
                errors.append("Температура вне паспортного диапазона фасонной части")
            table = dict(part.pressure_temperature)
            if p is not None and t in table and p > table[t]:
                errors.append("Давление выше паспортного предела фасонной части при заданной температуре")
            if p is None or t is None:
                pending.append("Нужны расчётные давление и температура")
            pending.append("Проверить сочетание P/T, материал, уплотнения, ответные части и монтажные посадки")
        checks.append(FittingCheck(role, None if errors else part, tuple(errors), tuple(pending)))
    return tuple(checks)
