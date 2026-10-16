"""Explicit accessories and opt-in meter kits, not a support/installation BOM."""
from dataclasses import dataclass, replace
from app.pz.metering_pipes import PIPE_ROLES, support_pipe


def _n(value):
    return f"{value:g}".replace(".", ",")


@dataclass(frozen=True)
class AccessoryCheck:
    role: str
    title: str
    details: tuple[str, ...]
    source_ids: tuple[str, ...]
    errors: tuple[str, ...]
    pending: tuple[str, ...]
    catalogue_id: str = ""


def connection_kit_matches(catalog, kit, meter):
    """Match both interfaces and source, not DN alone; L1 stays reference-only."""
    return bool(kit and meter and meter.kind == "meter"
        and meter.dimension_status == "verified"
        and meter.connection_standard == "G" and meter.connection_sex == "male"
        and kit.status == "reference_only" and meter.id in kit.meter_ids
        and kit.meter_thread == meter.thread and kit.pipe_thread == meter.kit_pipe_thread
        and kit.source_ids and all(s in catalog.sources for s in kit.source_ids))


def propose_connection_kit(catalog, meter):
    kits = [k for k in catalog.connection_kits.values() if connection_kit_matches(catalog, k, meter)]
    return kits[0] if len(kits) == 1 else None


def select_connection_kit(catalog, meter, *, explicit_id=None, automatic=False, revision_ok=True):
    if not revision_ok:
        return None
    if explicit_id:
        kit = catalog.connection_kits.get(explicit_id)
        return kit if connection_kit_matches(catalog, kit, meter) else None
    return propose_connection_kit(catalog, meter) if automatic else None


def check_accessories(detail, catalog, selected_meter, *, revision_ok):
    checks = []
    kit_id = detail.catalogue_items.get("meter_connections")
    automatic = (not kit_id and detail.meter_selection_mode == "catalogue_proposal"
                 and not (selected_meter and selected_meter.flange))
    if selected_meter and selected_meter.straight_sections:
        straight = selected_meter.straight_sections
        checks.append(AccessoryCheck("meter_straight_sections", "Прямые участки фланцевого счётчика",
            (f"До счётчика не менее {straight.before_dn:g}DN, после — {straight.after_dn:g}DN.",
             straight.reference), (straight.source_id,), (),
            ("Длины заготовок, ответные фланцы, прокладки и крепёж определяются отдельно; накидной комплект не применяется.",)))
    if kit_id or automatic:
        kit = catalog.connection_kits.get(kit_id) if kit_id else (
            propose_connection_kit(catalog, selected_meter) if revision_ok else None)
        errors, lines, sources = [], [], ()
        if not revision_ok:
            errors.append("Редакция каталога не подтверждена")
        elif kit is None and kit_id:
            errors.append("Неизвестный комплект присоединительных частей")
        elif selected_meter is None and kit_id:
            errors.append("Нет подтверждённого исполнения счётчика для проверки комплекта")
        elif kit_id and not connection_kit_matches(catalog, kit, selected_meter):
            errors.append("Комплект не соответствует выбранному счётчику и его присоединениям")
        elif kit:
            sources = kit.source_ids
            lines = [kit.name,
                     f"Со стороны счётчика G{kit.meter_thread}; со стороны трубы G{kit.pipe_thread}.",
                     f"L1 со счётчиком = {_n(kit.length_with_meter_reference_mm)} мм СПРАВОЧНО."]
            if kit.contents:
                lines.append("Состав предлагаемого комплекта: " + "; ".join(f"{name} - {qty} шт." for name, qty in kit.contents) + ".")
            if kit.meter_seal == "flat_gasket":
                lines.append("К счётчику - накидная гайка с плоской прокладкой; к трубе - наружная резьба. Это разные типы стыков.")
        checks.append(AccessoryCheck(
            "meter_connections", "Присоединительный комплект", tuple(lines), sources, tuple(errors),
            ("Подтвердить состав и монтажную длину комплекта при заказе; длины отдельных штуцеров не заданы.",
             "Прямые участки обеспечивает штатный комплект; переходы должны находиться за его пределами.",
             "Совпадение резьб не подтверждает все соединения узла: нужны уплотнения, соединители и глубины свинчивания."),
            catalogue_id=kit.id if kit and not errors else "",
        ))
        if automatic:
            checks[-1] = replace(checks[-1], pending=checks[-1].pending + (
                "Предложение по текущей модели; если комплект входит в поставку счётчика, повторно не закупать."
                if kit and not errors else "Нет единственного совместимого комплекта; требуется подбор.",))
    clamp_id = detail.catalogue_items.get("pipe_clamp")
    if clamp_id:
        clamp = catalog.pipe_clamps.get(clamp_id)
        errors, lines, pending, sources = [], [], [], ()
        if not revision_ok:
            errors.append("Редакция каталога не подтверждена")
        elif clamp is None:
            errors.append("Неизвестный хомут")
        else:
            sources = clamp.source_ids
            low, high = clamp.outer_diameter_mm
            dims = clamp.dimensions_mm
            lines = [f"{clamp.name}, арт. {clamp.article}; резьба {clamp.thread}.",
                     f"Наружный диаметр трубы {_n(low)}–{_n(high)} мм; B={_n(dims['B'])}, H={_n(dims['H'])}, h={_n(dims['h'])} мм.",
                     f"Паспортная нагрузка хомута Fa,z = {_n(clamp.fa_z_n)} Н. Для нержавеющих труб."]
            diameter, material, binding_errors = support_pipe(detail)
            errors.extend(binding_errors)
            if detail.support_pipe_section:
                ident, title = PIPE_ROLES[detail.support_pipe_section]
                lines.append(f"Привязка крепления: {ident} - {title}.")
            elif detail.pipe_sections:
                pending.append("Хомут не привязан к участку ВУ; локальные размеры заданы отдельно")
            if diameter is None:
                pending.append("Нужен наружный диаметр трубы в месте крепления; DN его не заменяет")
            elif not low <= diameter <= high:
                errors.append("Наружный диаметр трубы вне диапазона хомута")
            else:
                lines.append(f"Диаметр в месте крепления {_n(diameter)} мм входит в диапазон хомута.")
            if material == "unknown":
                pending.append("Материал трубы в месте крепления не задан")
            elif material != clamp.pipe_material:
                errors.append("Применимость хомута к заданному материалу трубы не подтверждена источником")
            load = detail.support_design_load_z_n
            if load is None:
                pending.append("Расчётная нагрузка на хомут в направлении z не задана")
            elif load > clamp.fa_z_n:
                errors.append("Нагрузка z превышает паспортную Fa,z хомута")
            else:
                lines.append(f"Заданная нагрузка z = {_n(load)} Н не превышает паспортную Fa,z.")
        pending.append("Это хомут, не готовая опора: количество, координаты, стойка/шпилька, анкеры, основание, "
                       "прочие нагрузки и перемещения требуют отдельного решения. Крепление на корпус счётчика не назначалось.")
        checks.append(AccessoryCheck("pipe_clamp", "Крепление трубопровода", tuple(lines), sources,
                                     tuple(errors), tuple(pending)))
    return tuple(checks)
