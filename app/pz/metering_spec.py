"""VU subsection of SO, derived from the same composition as Appendix Г.

Counts describe the current schematic, not an installation-ready purchase BOM.
Pipe cuts, support spacing, junction fittings and sealing are not inferred from
SVG coordinates. Rejected product assignments never become approved SO items.
"""
from app.data.metering_products import get_metering_catalogue
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_connections import CONNECTION_ROLES
from app.pz.metering_detail import drawing_state
from app.pz.metering_pipes import MATERIALS, PIPE_ROLES
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_rules import control_cock_dn, seismic_metering_rules
from app.pz.spec import SpecRow, SpecSection


def _dn(value):
    return f"DN{value}" if value else "DN уточнить"


def _number(value):
    return f"{value:g}".replace(".", ",")


def build_metering_spec_section(project):
    state = drawing_state(project)
    detail = project.metering_detail
    selected = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                        electric_bypass=state.electric_bypass)
    chain = build_metering_chain(detail, state, selected)
    from app.pz.metering_mounting import resolve_mounting
    mounting = resolve_mounting(project, state, selected)
    catalog = get_metering_catalogue()
    branch = state.node_key == "hot"
    def position(mark):
        return "Г." + mark if branch else mark

    section = SpecSection(project.node_title if branch else "В1 — Водомерный узел",
        division="Водоснабжение горячее" if branch and project.node_system == "Т3" else "Водоснабжение холодное")
    rows = section.rows
    meter_dn = state.meter.dn if state.meter else None

    def add(name, ids=(), *, mark="—", model="", manufacturer="", unit="шт.",
            known=True, note="", catalogue_id=""):
        ids = tuple(ids)
        rows.append(SpecRow(
            1, name, type_mark=model, manufacturer=manufacturer, unit=unit,
            qty=len(ids) * chain.instances if known else None, note=note,
            quantity_basis="metering_scheme" if known else "",
            quantity_source=f"{len(ids)} на узел × {chain.instances} узлов" if known else "",
            diagram_pos=mark, component_ids=ids, catalogue_id=catalogue_id,
        ))
        return rows[-1]

    def product(role, name, ids, mark, dn):
        part = selected.selected(role)
        if part and part.valve_type == "gate":
            name = name.replace("Кран", "Задвижка")
        position = next((p for p in selected.positions if p.role == role), None)
        if part:
            model = part.model + (f", арт. {part.article}" if part.article else "")
            note = "Исполнение выбрано; паспортные проверки не завершены" if position.pending else ""
        else:
            model, note = "", "Модель не подтверждена" if detail.catalogue_items.get(role) else "Модель уточнить"
        return add(f"{name}, {_dn(dn)}", ids, mark=mark, model=model,
                   manufacturer=part.manufacturer if part else "", note=note,
                   catalogue_id=part.id if part else "")

    # Equipment, shutoff/control valves, other products, instrument takeoffs,
    # pipes, materials — the order of GOST 21.601 §9.4 / 21.110 §4.5.
    product("meter", "Счётчик воды", ("meter",), "7", meter_dn)
    if not branch and not state.switching_bridge:
        product("inlet_valve", "Кран общего ВУ" if state.common_inlets else "Кран ввода", ("inlet_valve",), "1.1", detail.inlet_dn)
    product("meter_valves", "Кран до и после счётчика", ("valve_before", "valve_after"), "1.2", meter_dn)
    product("filter", "Фильтр", ("filter",), "2", meter_dn)
    product("check_valve", "Обратный клапан", ("check_valve",), "5", detail.inlet_dn)
    if detail.maintenance_layout == "serviceable":
        product("outlet_valve", "Ремонтная отсечка со стороны здания", ("outlet_valve",), "1.3", detail.inlet_dn)
    if state.core_bypass:
        title = "Запорная арматура обводной с электроприводом" if state.electric_bypass else "Кран обводной"
        product("bypass_valve", title, ("bypass_valve",), "6", detail.bypass_dn)
    if state.fire_branch and not state.common_inlets:
        add("Запорная арматура ответвления В2 до учёта, " + _dn(detail.fire_branch_dn),
            ("fire_valve",), note=("С электроприводом; " if project.fire.branch_electric_valves else "") + "модель уточнить")
    from app.pz.metering_supply import supply_spec_rows
    supply_rows = supply_spec_rows(project, state, selected)
    rows.extend(supply_rows)

    kit_check = next((a for a in selected.accessories if a.role == "meter_connections"), None)
    kit = catalog.connection_kits.get(kit_check.catalogue_id) if kit_check else None
    if not kit_check or kit_check.errors:
        kit = None
    meter_product = selected.selected("meter")
    if meter_product and meter_product.flange:
        for ident in ("kit_in", "kit_out"):
            node = chain.node(ident)
            add(node.title, (ident,), known=False, unit="м",
                note=(f"Не менее {node.minimum_length_mm:g} мм; {node.dimension_source}. "
                      "Требование к монтажу, не длина заготовки; количество из размера рисунка не определено"))
        flange_row = add("Ответные фланцы, прокладки и крепёж водомерного узла", known=False, unit="компл.",
            note="Исполнение и количество по каждому стыку; накидной резьбовой комплект не применяется")
        flange_row.quantity_basis = "metering_flange_requirement"
    else:
        # Two end pieces are ONE kit; the meter itself is a separate row.
        kit_row = add("Присоединительный комплект счётчика (без счётчика)", ("kit_in", "kit_out"),
                      model=kit.name if kit else "", unit="компл.",
                      manufacturer=selected.selected("meter").manufacturer if kit else "",
                      note=f"К поз. {position('7')}; один комплект на узел. Если входит в поставку счётчика, повторно не закупать",
                      catalogue_id=kit.id if kit else "")
        kit_row.qty = chain.instances
        kit_row.quantity_source = f"1 комплект на узел × {chain.instances} узлов; две присоединительные детали в комплекте"
        if kit and kit.contents:
            kit_row.note += ". Состав на узел: " + "; ".join(f"{name} - {qty} шт." for name, qty in kit.contents)
            kit_row.note += "; уточнить поставку при заказе. Комплектные детали отдельно не дублируются"

    for ident, mark in (("reducer_in", "П1"), ("reducer_out", "П2")):
        node = next((n for n in chain.nodes if n.id == ident), None)
        if node is None:
            continue
        part = catalog.reducers.get(node.catalogue_id) or catalog.fittings.get(node.catalogue_id)
        add(f"Переход {_dn(detail.inlet_dn)} / {_dn(meter_dn)}", (ident,),
            mark=mark, model=(part.article or getattr(part, "name", "")) if part else "",
            manufacturer=part.manufacturer if part else "", catalogue_id=part.id if part else "",
            note="Вне штатного комплекта; сопряжение с магистралью уточнить" if part else "Изделие уточнить")

    for check in selected.connections:
        role = check.role
        prefix = "outlet" if role == "check_valve_out" else f"connection_{role}"
        mark = CONNECTION_ROLES[role][0]
        for suffix, collection, title in (("thread", catalog.thread_connectors, "Резьбовой соединитель"),
                                          ("connector", catalog.connectors, "Соединитель трубы")):
            ident = f"{prefix}_{suffix}"
            node = next((n for n in chain.nodes if n.id == ident), None)
            if node is None:  # Inactive bypass ports are not physical items.
                continue
            part = collection.get(node.catalogue_id)
            add(f"{title}, узел {mark}", (ident,), mark=mark,
                model=part.article if part else "", manufacturer=part.manufacturer if part else "",
                catalogue_id=part.id if part else "",
                note="Сопряжения проверены; P/T и монтаж уточнить" if part else "Назначенное изделие не подтверждено")

    for index, node in enumerate((n for n in chain.nodes if n.role == "inline_nipple"), 7):
        part = catalog.thread_connectors.get(node.catalogue_id)
        check = next((c for c in selected.inline_joints if c.id == node.id), None)
        note = (f"L корпуса {_number(part.body_length_mm)} мм; P/T, уплотнение и посадки уточнить"
                if part else "Для двух выбранных внутренних резьб. Модель, P/T, осевой размер и посадки уточнить; "
                             "не закупать как подтверждённое каталожное изделие")
        if part and check and check.proposed:
            note = "Предварительное каталожное предложение. " + note
        add(node.title, (node.id,), mark=f"С{index}",
            model=part.article if part else "", manufacturer=part.manufacturer if part else "",
            catalogue_id=part.id if part else "", note=note)

    # A three/four-port logical junction is not necessarily one physical tee.
    def fitting_or_requirement(title, ids, note):
        missing = []
        for ident in ids:
            p = catalog.fittings.get(chain.node(ident).catalogue_id)
            if p:
                add(p.name, (ident,), mark={"bypass_start":"Ф1", "bypass_end":"Ф2",
                    "fire_takeoff":"Ф3", "service_before":"Ф4", "service_after":"Ф5",
                    "maintenance_in":"Ф6", "maintenance_out":"Ф7"}[ident],
                    model=p.article or p.name, manufacturer=p.manufacturer, catalogue_id=p.id,
                    note=f"L корпуса {_number(p.body_length_mm)} мм; материал {p.material}; "
                         "P/T, стыки и монтажные посадки проверить")
            else:
                missing.append(ident)
        if missing:
            add(title, missing, unit="компл.", note=note)

    if state.core_bypass:
        fitting_or_requirement("Узлы присоединения обводной линии", ("bypass_start", "bypass_end"),
            "Фасонные части и их состав уточнить; не считать как два готовых тройника")
    if state.fire_branch and not state.common_inlets:
        fitting_or_requirement("Узел ответвления В2 до учёта", ("fire_takeoff",),
            "Фасонные части и их состав уточнить")

    # Elbow A is centre-to-face on EACH leg, never an axial L or pipe cut.
    for ident, mark in (("filter_turn_in", "О1"), ("filter_turn_out", "О2")):
        node = next((n for n in chain.nodes if n.id == ident), None)
        if node is None:
            continue
        part = catalog.fittings.get(node.catalogue_id)
        add(node.title, (ident,), mark=mark, known=part is not None,
            model=part.article or part.name if part else "",
            manufacturer=part.manufacturer if part else "", catalogue_id=part.id if part else "",
            note=(f"От оси до торца A={_number(part.dimensions_mm['A'])} мм по каждой ветви; "
                  "резьбовые посадки/фланцевые уплотнения и монтаж проверить" if part else
                  "Поворот нужен для выбранных осей. Изделие и размер не подтверждены; автоматической замены нет"))

    clamp_check = next((a for a in selected.accessories if a.role == "pipe_clamp"), None)
    clamp = catalog.pipe_clamps.get(detail.catalogue_items.get("pipe_clamp"))
    if not clamp_check or clamp_check.errors:
        clamp = None
    if clamp and not detail.mounting.supports:
        add("Хомут трубопровода ВУ", known=False, model=f"{clamp.name}, арт. {clamp.article}",
            catalogue_id=clamp.id, note="Количество и полная опора по монтажной привязке")
    if detail.mounting.supports:
        from app.pz.metering_supports import support_report, support_spec_rows
        rows.extend(support_spec_rows(support_report(project, state, chain=chain)))
        if clamp:
            add('Ранее выбранный хомут ВУ - привязку к опоре уточнить', known=False,
                model=f'{clamp.name}, арт. {clamp.article}', catalogue_id=clamp.id,
                note='Не добавлен к комплектам опор автоматически: количество неизвестно; исключить двойной учёт.')
    else:
        supports = add("Опоры и крепления трубопровода ВУ", known=False, unit="компл.",
            note="Тип, количество, основание и анкеры уточнить; подставка не назначена автоматически")
    if not detail.mounting.supports and mounting.support_count is not None:
        supports.qty = mounting.support_count
        supports.quantity_basis = "explicit_vu_supports"
        supports.quantity_source = (f"{detail.mounting.support_count} на узел × {chain.instances} узлов; "
                                    + detail.mounting.support_basis.strip())
        supports.note = ("Количество задано проектировщиком; тип опор, анкеры и несущую способность проверить. "
                         "Хомуты выше входят в состав опор, отдельное количество автоматически не назначено")

    from app.pz.metering_service import SERVICE_ROLES
    for role, mark in (("gauge", "3.1"), ("gauge_cock", "3.2"),
                       ("control_cocks", "4.1"), ("control_caps", "4.2"),
                       ("maintenance_cocks", "4.3"), ("maintenance_caps", "4.4")):
        if role.startswith("maintenance_") and detail.maintenance_layout != "serviceable":
            continue
        title, _, ids = SERVICE_ROLES[role]
        check = next((s for s in selected.services if s.role == role), None)
        part = check.part if check else None
        note = "; ".join(check.pending) if check else "Модель уточнить"
        if part and check.proposed:
            note = "Предварительное каталожное предложение. " + note
        if part and role == "gauge_cock":
            note += "; прокладка накидной гайки и винт сервисного порта в комплекте; отдельно не закупать"
        if part and role not in ("control_cocks", "maintenance_cocks"):
            note += "; " + "; ".join(part.notes)
        if role.startswith(("control_", "maintenance_")):
            title += ", " + _dn(control_cock_dn(state.meter))
        add(title, ids, mark=mark, model=part.article if part else "",
            manufacturer=part.manufacturer if part else "", catalogue_id=part.id if part else "", note=note)
    fitting_or_requirement("Соединительный узел манометра и контрольного крана", ("service_before",),
        f"К поз. {position('3.1')}, {position('3.2')} и {position('4.1')}; состав фасонных частей уточнить")
    fitting_or_requirement("Соединительный узел контрольного крана после запорного", ("service_after",),
        f"К поз. {position('4.1')}; состав фасонных частей уточнить")
    if detail.maintenance_layout == "serviceable":
        fitting_or_requirement("Сервисные отборы перед фильтром и за обратным клапаном",
            ("maintenance_in", "maintenance_out"),
            f"К поз. {position('4.3')}; внутри ремонтных отсечек, вне прямых участков счётчика. Фасонные части, монтаж и приём воды уточнить")

    pipe_nodes = {"inlet": ("inlet",), "before_meter": (), "after_meter": (), "outlet": ("outlet",),
                  "bypass": ("bypass_route_in", "bypass_route_out"), "fire_branch": ("fire_outlet",)}
    if state.common_inlets:
        pipe_nodes["fire_branch"] = ()  # Owned by the two external feed branches.
    for role, (mark, title) in PIPE_ROLES.items():
        if (role == "bypass" and not state.core_bypass) or (role == "fire_branch" and not state.fire_branch):
            continue
        pipe = detail.pipe_sections.get(role)
        description = "Материал и размеры уточнить"
        pipe_product = None
        if pipe and pipe.catalogue_id and not pipe.validate():
            from app.data.engineering_catalogue import get_engineering_catalogue
            pipe_product = get_engineering_catalogue().require(pipe.catalogue_id, kind="pipe")
        if pipe:
            size = ""
            if pipe.outer_diameter_mm is not None:
                size = "Ø" + _number(pipe.outer_diameter_mm)
                if pipe.wall_thickness_mm is not None:
                    size += "×" + _number(pipe.wall_thickness_mm)
            description = "; ".join(filter(None, (MATERIALS[pipe.material], pipe.series, size)))
        row = add(f"Труба ВУ — {title.lower()}", pipe_nodes[role], mark=mark if pipe else "—",
            model=description, known=False, unit="м",
            note="Метраж уточнить в составе труб системы; отдельно к общему метражу не добавлен")
        if pipe_product:
            row.catalogue_id = pipe_product.id
            row.manufacturer = pipe_product.manufacturer
            if pipe_product.article:
                row.type_mark += f"; арт. {pipe_product.article}"
            row.note += "; размеры по каталогу; пригодность по P/T проверяется отдельно"
        elif pipe and pipe.catalogue_id:
            row.note += "; каталожная привязка трубы не подтверждена"
        if role in mounting.pipe_lengths_m:
            # The area-based network estimate has no VU exclusion. Do not add
            # a second procurement quantity or subtract precise cuts from an
            # unrelated estimate. Preserve the explicit takeoff as a reference.
            length = mounting.pipe_lengths_m[role]
            cut = detail.mounting.pipe_cuts[role]
            row.quantity_basis = "metering_mounting_reference"
            row.quantity_source = (f"{_number(cut['length_mm'] / 1000)} м на узел × "
                                   f"{chain.instances} узлов; {cut['source'].strip()}")
            row.note = (f"Справочно: {_number(length)} м в составе труб системы; "
                        "повторно к общему метражу не добавлять. Раскрой задан, не измерен по схеме")
        elif isinstance(detail.mounting.pipe_cuts, dict) and role in detail.mounting.pipe_cuts:
            row.note = "Заданный метраж не принят: проверьте исходные данные, активность ветви и сечение трубы"

    add("Прочие соединительные детали обвязки ВУ", known=False, unit="компл.",
        note="Без повторения позиций выше; состав и количество по монтажной привязке")
    add("Уплотнительные материалы соединений ВУ", known=False, unit="кг",
        note="Тип и расход уточнить по соединениям; комплектные уплотнения повторно не учитывать")
    # Catch future graph changes instead of silently omitting new components.
    from app.data.engineering_catalogue import get_engineering_catalogue
    for check in selected.flexible_connections:
        node = chain.node('flex_' + check['role'])
        item = get_engineering_catalogue().require(node.catalogue_id) if node.catalogue_id else None
        length = check['installed_length_mm']
        note = (f"L0={check['dimension_length_mm']:g} мм; " +
                (f"Lмон={length:g} мм по заданному предварительному сжатию. " if length is not None else
                 "предварительное сжатие 3–5 мм не задано, монтажная длина неизвестна. ")
                if item else "Выбор отклонён. ")
        add(node.title, (node.id,), mark='Г1' if check['role'] == 'inlet' else 'Г2',
            known=bool(item), model=item.name if item else '', manufacturer=item.manufacturer if item else '',
            catalogue_id=item.id if item else '',
            note=note + '; '.join([*check['errors'], *check['pending']]) +
                 '. Количество по составу схемы; не подтверждение монтажной или сейсмической пригодности.')
    covered = [ident for row in rows for ident in row.component_ids]
    support_ids = set()
    if detail.mounting.supports:
        support_ids = {i for r in support_spec_rows(support_report(project, state, chain=chain)) for i in r.component_ids}
    from app.pz.metering_supply import supply_component_ids
    supply_ids = supply_component_ids(state)
    if len(covered) != len(set(covered)) or set(covered) != {n.id for n in chain.nodes} | support_ids | supply_ids:
        raise ValueError("Состав спецификации ВУ расходится с цепочкой схемы")
    # The ordinary graph is not a seismic installation. Carry its outstanding
    # requirements into SO, without inventing two hoses per inlet or counting
    # an unselected compensator as a purchased item. No duplicate graph owner.
    for rule in seismic_metering_rules(project):
        rows.append(SpecRow(None, f"Требование к специальной комплектации ВУ: {rule.message}",
            type_mark="Не скомплектовано", unit="", qty=None,
            quantity_basis="metering_special_requirement", quantity_source=rule.clause,
            note="Не закупочная позиция. Исполнение и количество по привязке; "
                 "базовая обвязка не подтверждает выполнение этого требования"))
    for check in selected.flexible_connections:
        if not check['errors']:
            continue  # Physical graph/SO row already owns this exact instance.
        rows.append(SpecRow(None, f"Гибкое соединение ВУ ({check['role']}): "
            + ("выбор отклонён" if check['errors'] else "кандидат требует компоновки"),
            type_mark="Не скомплектовано", unit="", qty=None,
            quantity_basis="metering_special_requirement", quantity_source="СП 30, п. 15.2.6 / паспорт изделия",
            note="Кандидат: " + check['catalogue_id'] + ". "
                 + '; '.join([*check['errors'],*check['pending']]) + ". Не закупочная позиция."))
    # Wishes are not extra physical meters/filters/frames. Blank quantities and
    # no graph ownership prevent double counting a future factory package.
    from app.pz.metering_extras import metering_option_rows, resolve_metering_extras
    extras = resolve_metering_extras(project)
    for part in extras["items"]:
        # Controller shared by telemetry and a one-point leak kit occurs once,
        # not once per option, meter, input or building floor.
        row = add("Дополнительное оборудование ВУ: " + part["model"], known=False,
                  model=part["model"] + (f", арт. {part['article']}" if part["article"] else ""),
                  manufacturer=part["manufacturer"], catalogue_id=part["id"],
                  note=part["note"] + f" Каталог {extras['revision']}.")
        row.qty = part["qty"]
        row.quantity_basis = "explicit_vu_accessory"
    for request in metering_option_rows(project):
        row = add("Требование к подбору ВУ: " + request["title"] + " — " + request["label"]
            + ". " + request["requirement"], known=False, unit="",
            model="Не скомплектовано",
            note="Требуется подбор оборудования. В количество не включено; базовый состав не заменён")
        selection = next(r for r in extras["selections"] if r["key"] == request["key"])
        if selection["status"] == "selected":
            row.type_mark = "Условия подключения"
            row.note = "Оборудование перечислено выше; повторно не считать. Монтажная привязка не выполнена."
        elif selection["status"] == "conflict":
            row.type_mark = "Несовместимость — уточнить"
        row.pos = None  # A requirement must not consume a procurement position.
    if branch:
        for row in rows:
            if row.diagram_pos and row.diagram_pos != "—":
                row.diagram_pos = "Г." + row.diagram_pos
            if row.quantity_basis == "metering_scheme":
                row.quantity_source += "; один расчётный узел ветви, не на каждый ввод"
    return section


def branch_meter_kit_row(project, meter, check):
    """One kit per separately counted branch meter, NOT per building inlet.

    These nodes have no detailed assembly graph yet. Do not copy the common
    inlet's kit assignment, mounting length, valves or support quantities here.
    """
    from app.pz.metering_accessories import select_connection_kit
    if check.node not in ("cold", "hot"):
        return None
    d, catalog = project.metering_detail, get_metering_catalogue()
    kit = select_connection_kit(catalog, check.product,
        automatic=d.meter_selection_mode == "catalogue_proposal",
        revision_ok=d.catalogue_revision == catalog.revision)
    return SpecRow(1, f"Присоединительный комплект счётчика DN{meter.dn} — {meter.label}",
        type_mark=kit.name if kit else "по подбору", unit="компл.", qty=1,
        manufacturer=check.product.manufacturer if kit else "",
        catalogue_id=kit.id if kit else "",
        component_ids=(f"meter_{check.node}_kit",), quantity_basis="metering_scheme",
        quantity_source="1 комплект × 1 счётчик ветви; не на каждый ввод",
        note="Без счётчика; если входит в его поставку, повторно не закупать. "
             "Состав и прямые участки уточнить" if kit else
             "Нет подтверждённого предложения комплекта; состав и присоединения уточнить")
