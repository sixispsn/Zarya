"""Explicit transitions outside the meter kit, with directional port checks.

No hydraulic coefficient or inferred pipe thread. A logical tee is not a
female socket: its port stays unknown until an actual fitting is selected.
"""
from dataclasses import dataclass

from app.data.metering_products import ThreadReducer


REDUCER_ROLES = {
    "reducer_in": ("П1", "Переход перед краном счётчика"),
    "reducer_out": ("П2", "Переход после крана счётчика"),
}


@dataclass(frozen=True)
class ReducerCheck:
    role: str
    title: str
    requested: ThreadReducer | None
    # (thread standard, thread size, sex), in flow order, not drawing order.
    ports: tuple[tuple[str, str, str], ...]
    neighbours: tuple[str, str]
    joints_confirmed: tuple[bool, bool]
    errors: tuple[str, ...]
    pending: tuple[str, ...]
    assignment_confirmed: bool = False

    @property
    def part(self):
        return self.requested if self.assignment_confirmed and not self.errors else None

    @property
    def ports_confirmed(self):
        return self.part is not None and all(self.joints_confirmed)

    @property
    def installed_length_mm(self):
        return None


def port_label(port):
    standard, size, sex = port
    return f"{standard}{size} { {'male': 'НР', 'female': 'ВР'}.get(sex, '?') }"


def check_reducers(detail, catalog, products, *, meter_dn, bypass, revision_ok):
    checks = []
    for role, ident in detail.reducer_items.items():
        mark, title = REDUCER_ROLES[role]
        errors, pending, ports = [], [], ()
        from app.pz.equipment_origin import origin_error
        if error := origin_error(detail, ident):
            errors.append(error)
        assignment_confirmed = False
        confirmed = [False, False]
        part = catalog.reducers.get(ident)
        # Do not skip over the bypass/service tee to a distant known valve.
        if role == "reducer_in":
            products_at_ends = (None if bypass else products.get("inlet_valve"), products.get("meter_valves"))
            neighbours = ("Тройник обводной" if bypass else "Кран ввода", "Кран до счётчика")
            expected_dn = (detail.inlet_dn, meter_dn)
        else:
            products_at_ends = (products.get("meter_valves"), None)
            neighbours = ("Кран после счётчика", "Тройник обводной" if bypass else "Узел контрольного отбора")
            expected_dn = (meter_dn, detail.inlet_dn)
            if "meter_valve_out" in detail.connection_items:
                errors.append("Выход крана занят соединением С3 и переходом П2 одновременно; требуется единая цепочка")
        if not revision_ok:
            errors.append("Редакция каталога не подтверждена; переход необходимо перепроверить")
        if part is None:
            errors.append("Неизвестный переход; автоматической замены нет")
        else:
            if part.dimension_status != "verified":
                errors.append("Размеры перехода не подтверждены")
            if None in expected_dn:
                pending.append("Не заданы текущие DN ввода и счётчика")
            elif expected_dn[0] == expected_dn[1]:
                errors.append("DN одинаковы: выбранный переход отсутствует в текущей схеме")
            elif set(expected_dn) != {part.large_dn, part.small_dn}:
                errors.append("DN перехода не соответствуют текущим DN ввода и счётчика")
            else:
                by_dn = {part.large_dn: (part.connection_standard, part.large_thread, part.large_sex),
                         part.small_dn: (part.connection_standard, part.small_thread, part.small_sex)}
                ports = tuple(by_dn[dn] for dn in expected_dn)
                assignment_confirmed = True
                for index, (port, neighbour) in enumerate(zip(ports, products_at_ends)):
                    prefix = f"{neighbours[index]}"
                    if neighbour is None:
                        pending.append(f"{prefix}: изделие/порт не подтверждены; прямой стык не проверен")
                        continue
                    other = (neighbour.connection_standard, neighbour.thread, neighbour.connection_sex)
                    if not all(other) or other[2] not in ("male", "female"):
                        pending.append(f"{prefix}: не все параметры резьбового порта заданы")
                    elif port[:2] != other[:2]:
                        errors.append(f"{prefix}: стандарт/размер резьбы не совпадает с переходом")
                    elif port[2] == other[2]:
                        errors.append(f"{prefix}: две наружные или две внутренние резьбы не соединяются напрямую")
                    else:
                        confirmed[index] = True
            pressure, temperature = detail.design_pressure_bar, detail.water_temperature_c
            if pressure is not None and pressure > part.pn_bar:
                errors.append("Давление выше PN перехода")
            if temperature is not None and not part.temperature_c[0] <= temperature <= part.temperature_c[1]:
                errors.append("Температура вне паспортного диапазона перехода")
            if pressure is None or temperature is None:
                pending.append("Не заданы рабочие давление и температура перехода")
            else:
                table = dict(part.pressure_temperature)
                if temperature not in table:
                    pending.append("P/T: нет точной табличной точки; интерполяция не выполнялась")
                elif pressure > table[temperature]:
                    errors.append("Давление выше паспортного предела перехода при заданной температуре")
            pending += ["Уплотнение и глубины свинчивания уточняются; L корпуса не равна монтажной длине",
                        "Поперечный габарит не подтверждён; место для ключа и демонтажа не проверено"]
        checks.append(ReducerCheck(role, f"{mark} · {title}", part, ports, neighbours,
                                   tuple(confirmed), tuple(errors), tuple(pending), assignment_confirmed))
    return tuple(checks)


def reducer_contents(project, state):
    """One compact selection sheet, not an invented scaled fitting contour."""
    from app.pz.metering_detail import _text, _lines
    from app.pz.metering_product_selection import resolve_metering_products
    selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    pages, y = [], 35
    g = [_text(28,17,"Переходы водомерного узла",5),
         _text(28,26,"П1 / П2 - вне штатного комплекта прямых участков счётчика",3.5)]
    for check in selection.reducers:
        part = check.requested
        rows = [check.title]
        if part:
            rows += [f"{part.manufacturer} {part.article}; DN{part.large_dn} × DN{part.small_dn}",
                     f"Осевой габарит корпуса L = {part.body_length_mm:g} мм; не монтажная длина"
                     if part.body_length_mm is not None else "Осевой габарит корпуса не подтверждён"]
        if check.ports:
            rows.append("По потоку: " + " -> ".join(map(port_label, check.ports)))
        for name, confirmed in zip(check.neighbours, check.joints_confirmed):
            rows.append(f"{name}: " + ("резьбовой стык проверен" if confirmed and check.part else "стык не подтверждён"))
        rows += list(check.errors)
        rows += list(check.pending)
        if part:
            rows.append("Источники: " + "; ".join(f"{selection_source['title']}, стр. {selection_source['pages']}"
                for selection_source in (get_source(s) for s in part.source_ids)))
        lines = [line for row in rows for line in _lines(row,372,3.5)]
        height = len(lines)*5.5 + 8
        if y+height > 220:
            pages.append(''.join(g))
            g, y = [_text(28,17,"Переходы водомерного узла - продолжение",5)], 30
        for i, line in enumerate(lines):
            g.append(_text(29,y+6+i*5.5,line,3.5))
        y += height
    for i,line in enumerate(_lines("Изделия выбраны явно для текущих DN. Неподтверждённый тройник не считается "
                                  "проверенным стыком. Расходы и потери расчётного ядра не изменены.",376,3.5)):
        g.append(_text(28,y+8+i*5.5,line,3.5))
    pages.append(''.join(g))
    return pages


def get_source(ident):
    from app.data.metering_products import get_metering_catalogue
    return get_metering_catalogue().sources[ident]
