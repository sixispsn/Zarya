"""Recheck explicit VU pipe/equipment joints; never choose a brand by DN.

Only the named pipe/equipment ports are covered. A successful port check is
not a fabrication BOM, a P/T approval, or an installed-length calculation.
"""
from dataclasses import dataclass

from app.data.metering_products import MeteringConnector, ThreadConnector


# mark, human title, pipe zone, adjacent equipment role
CONNECTION_ROLES = {
    "inlet_valve_in": ("С1", "Вход крана ввода", "inlet", "inlet_valve"),
    "filter_in": ("С2", "Вход фильтра", "before_meter", "filter"),
    "meter_valve_out": ("С3", "Выход крана после счётчика", "after_meter", "meter_valves"),
    "check_valve_out": ("С4", "Выход обратного клапана", "outlet", "check_valve"),
    "bypass_valve_in": ("С5", "Вход арматуры обводной", "bypass", "bypass_valve"),
    "bypass_valve_out": ("С6", "Выход арматуры обводной", "bypass", "bypass_valve"),
}


@dataclass(frozen=True)
class ConnectionCheck:
    role: str
    title: str
    requested: MeteringConnector | None
    errors: tuple[str, ...]
    pending: tuple[str, ...]
    ports_confirmed: bool = False
    thread_adapter: ThreadConnector | None = None

    @property
    def connector(self):
        # Incomplete pipe/port identity must not look like an approved fit.
        return self.requested if not self.errors and self.ports_confirmed else None

    @property
    def installed_length_mm(self):
        # Socket depth != actual insertion; body length != assembled length.
        return None


def check_connections(detail, catalog, products, *, bypass, revision_ok):
    results = []
    for role, ident in detail.connection_items.items():
        mark, title, pipe_role, equipment_role = CONNECTION_ROLES[role]
        errors, pending = [], []
        from app.pz.equipment_origin import origin_error
        for item in (ident, detail.connection_thread_items.get(role)):
            if item and (error := origin_error(detail, item)):
                errors.append(error)
        ports_confirmed = False
        part = catalog.connectors.get(ident)
        adapter_id = detail.connection_thread_items.get(role)
        adapter = catalog.thread_connectors.get(adapter_id)
        if adapter_id and adapter is None:
            errors.append("Неизвестный промежуточный резьбовой соединитель; автоматической замены нет")
        if adapter and adapter.dimension_status != "verified":
            errors.append("Габариты промежуточного резьбового соединителя не подтверждены")
        if not revision_ok:
            errors.append("Редакция каталога не подтверждена; повторно проверить соединитель")
        if pipe_role == "bypass" and not bypass:
            errors.append("Обводной линии в принятой схеме нет")
        if part is None:
            errors.append("Неизвестный соединитель; автоматической замены нет")
        else:
            if part.dimension_status != "verified":
                errors.append("Конфликт габаритов производителя: соединитель не допущен в размерную компоновку")
            pipe = detail.pipe_sections.get(pipe_role)
            if pipe is None:
                pending.append("Не задан примыкающий участок трубы")
            else:
                for actual, expected, name, unknown in (
                    (pipe.material, part.pipe_material, "Материал трубы", "unknown"),
                    (pipe.outer_diameter_mm, part.pipe_outer_diameter_mm, "Наружный диаметр трубы", None),
                    (pipe.joining, part.joining, "Способ соединения", "unknown"),
                ):
                    if actual == unknown:
                        pending.append(f"{name} не задан")
                    elif actual != expected:
                        errors.append(f"{name} не соответствует соединителю")
                if not pipe.system_id:
                    pending.append("Трубная система не указана; совпадения наружного диаметра недостаточно")
                elif pipe.system_id != part.pipe_system:
                    pending.append("Другая трубная система: нужна документальная проверка совместимости")
                if pipe.inner_diameter_mm is None or not pipe.geometry_source.strip():
                    pending.append("Подтвердить серию, стенку и источник размеров трубы")
            product = products.get(equipment_role)
            if product is None:
                pending.append("Примыкающая арматура не выбрана или не прошла проверку")
            else:
                pairs = [(product.connection_standard, product.thread, product.connection_sex,
                          part.connection_standard, part.thread, part.connection_sex)]
                if adapter:
                    pairs = [(product.connection_standard, product.thread, product.connection_sex,
                              adapter.connection_standard, adapter.equipment_thread, adapter.equipment_sex),
                             (adapter.connection_standard, adapter.pipe_connector_thread, adapter.pipe_connector_sex,
                              part.connection_standard, part.thread, part.connection_sex)]
                for number, (standard_a, size_a, sex_a, standard_b, size_b, sex_b) in enumerate(pairs, 1):
                    if not all((standard_a, size_a, sex_a, standard_b, size_b, sex_b)):
                        pending.append(f"Стык {number}: не все параметры резьбы заданы")
                    elif (standard_a, size_a) != (standard_b, size_b):
                        errors.append(f"Стандарт/размер резьбы не соответствует смежной детали (стык {number})")
                    elif sex_a not in ("male", "female") or sex_b not in ("male", "female"):
                        pending.append(f"Стык {number}: направление резьбы не подтверждено")
                    elif sex_a == sex_b:
                        errors.append(f"Одинаковое направление резьбы: наружная/наружная или внутренняя/внутренняя (стык {number})")
            ports_confirmed = not errors and not pending
            pressure, temperature = detail.design_pressure_bar, detail.water_temperature_c
            if pressure is not None and part.pn_bar is not None and pressure > part.pn_bar:
                errors.append("Давление выше PN соединителя")
            if temperature is not None and part.max_temperature_c is not None and temperature > part.max_temperature_c:
                errors.append("Температура выше паспортного предела соединителя")
            if part.pn_bar is None or part.max_temperature_c is None:
                pending.append("Предельные P/T соединителя не внесены: проверены размеры, не прочность и срок службы")
            if adapter:
                if pressure is not None and pressure > adapter.pn_bar:
                    errors.append("Давление выше PN промежуточного резьбового соединителя")
                if temperature is not None and not adapter.temperature_c[0] <= temperature <= adapter.temperature_c[1]:
                    errors.append("Температура вне паспортного диапазона промежуточного соединителя")
                table = dict(adapter.pressure_temperature)
                if pressure is not None and temperature in table and pressure > table[temperature]:
                    errors.append("Давление выше паспортного предела промежуточного соединителя при заданной температуре")
            # No guessed lower temperature, service class, derating or seal.
            pending += ["Подтвердить рабочие P/T, класс эксплуатации и уплотнение выбранного исполнения",
                        "Глубины свинчивания и фактическая посадка трубы не заданы; монтажная длина не определена"]
        results.append(ConnectionCheck(role, f"{mark} · {title}", part, tuple(errors), tuple(pending),
                                       ports_confirmed and not errors, adapter))
    return tuple(results)
