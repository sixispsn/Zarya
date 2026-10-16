"""Explicit VU service selection; does not alter meter/hydraulic algorithms."""
from dataclasses import dataclass
from app.pz.metering_rules import control_cock_dn


SERVICE_ROLES = {
    "control_cocks": ("Контрольные шаровые краны", "shutoff", ("control_cock_1", "control_cock_2")),
    "control_caps": ("Постоянные заглушки", "plug", ("control_cap_1", "control_cap_2")),
    "gauge_cock": ("Кран манометра", "gauge_cock", ("gauge_cock",)),
    "gauge": ("Манометр", "gauge", ("gauge",)),
    "maintenance_cocks": ("Сервисные шаровые краны", "shutoff", ("maintenance_cock_in", "maintenance_cock_out")),
    "maintenance_caps": ("Заглушки сервисных кранов", "plug", ("maintenance_cap_in", "maintenance_cap_out")),
}


@dataclass(frozen=True)
class ServiceCheck:
    role: str
    part: object | None
    errors: tuple[str, ...]
    pending: tuple[str, ...]
    proposed: bool = False


def check_service_components(detail, meter, catalog, *, revision_ok):
    """A small opt-in profile, not a silently installed factory assembly.

    Unknown pressure cannot be replaced by Hgar. Unknown duty uses the stricter
    published variable-load limit only for an explicitly labelled proposal.
    An invalid manual choice is never silently replaced by the profile.
    """
    parts = {**catalog.products, **catalog.service_products}
    result = []
    p, t = detail.design_pressure_bar, detail.water_temperature_c
    dn = control_cock_dn(meter)
    proposal = detail.service_selection_mode == "catalogue_proposal"
    factor = .75 if detail.gauge_pressure_mode == "constant" else 2 / 3
    for role, (title, kind, _) in SERVICE_ROLES.items():
        if role.startswith("maintenance_") and detail.maintenance_layout != "serviceable":
            if role in detail.service_items:
                result.append(ServiceCheck(role, None, ("Компоновка обслуживания не включена",), ()))
            continue
        requested = detail.service_items.get(role)
        ident, errors, pending = requested, [], []
        if not ident and proposal and revision_ok and p is not None and t is not None:
            if role in ("control_cocks", "maintenance_cocks") and dn in (15, 25):
                ident = f"valtec-vt214-dn{dn}"
            elif role in ("control_caps", "maintenance_caps") and dn in (15, 25):
                ident = f"valtec-vtr583-plug-dn{dn}"
            elif role == "gauge_cock":
                ident = "valtec-vt806-0404"
            elif role == "gauge":
                candidates = sorted((c for c in catalog.service_products.values()
                    if c.kind == "gauge" and p <= c.range_bar * factor), key=lambda c: c.range_bar)
                ident = candidates[0].id if candidates else None
        part = parts.get(ident)
        if ident and not revision_ok:
            errors.append("Редакция каталога не подтверждена")
        if ident and not part:
            errors.append("Неизвестное сервисное изделие")
        if part:
            expected_dn = dn if role.startswith(("control_", "maintenance_")) else 15
            if part.kind != kind or part.dn != expected_dn:
                errors.append("Тип/DN не соответствует роли и текущему счётчику")
            if detail.russian_equipment_only:
                from app.pz.equipment_origin import origin_error
                if error := origin_error(detail, part.id):
                    errors.append(error)
            if p is None or t is None:
                pending.append("Нужны максимальное рабочее давление и температура; Hгар не заменяет их")
            else:
                if part.pn_bar is not None and p > part.pn_bar:
                    errors.append("Давление выше паспортного предела изделия")
                if not part.temperature_c[0] <= t <= part.temperature_c[1]:
                    errors.append("Температура вне паспортного диапазона")
                table = dict(getattr(part, "pressure_temperature", ()))
                if table:
                    if t in table and p > table[t]:
                        errors.append("Превышено допустимое давление при заданной температуре")
                    elif t not in table:
                        pending.append("Рабочая точка P/T отсутствует в таблице; интерполяция не выполнялась")
                elif kind == "plug":
                    # Explicit tabulated upper-temperature bounds from VTr §3.1.
                    allowed = 40 if t <= 120 else 32 if t <= 200 else 27
                    if p > allowed:
                        errors.append("Давление выше консервативного предела P/T пробки")
                if kind == "gauge" and part.kind == "gauge" and p > part.range_bar * factor:
                    errors.append("Максимальное рабочее давление превышает допустимую долю шкалы")
            if kind == "gauge":
                pending.append("Проверить среду, пульсации, вибрацию, IP40 и монтаж циферблата")
                if detail.gauge_pressure_mode == "unknown":
                    pending.append("Предварительно принят более строгий предел 2/3 шкалы; режим давления не подтверждён")
            if part.dimension_status == "passport_nominal":
                pending.append("Для компоновки принят размер по паспорту; расхождение с отдельным чертежом сохранено, монтажную длину уточнить")
            elif part.dimension_status != "verified":
                pending.append("Размеры расходятся в документах изготовителя; осевая длина не принята")
            if kind in ("gauge", "gauge_cock"):
                pending.append("Торцевое уплотнение пары манометр/кран требует монтажной проверки")
        elif not errors:
            pending.append("Нет выбранного изделия допустимого исполнения и диапазона")
        proposed = bool(ident and not requested)
        # Missing candidates are not accepted substitutions; manual errors
        # remain actionable. Country/P/T failure clears the proposed part too.
        if errors:
            part = None
        pending.append("Присоединение отбора к основной трубе и пространство обслуживания уточнить")
        if role.startswith("maintenance_"):
            pending.append("Сервисный DN принят как у контрольных кранов; время слива не рассчитано. Приём воды, полости и порядок впуска воздуха проверить")
        result.append(ServiceCheck(role, part, tuple(errors), tuple(pending), proposed))
    return tuple(result)
