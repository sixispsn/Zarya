"""Composition checks for a COMMON BUILDING COLD-WATER meter assembly.

SP 30.13330.2020, changes 1–5, reviewed 2026-09-30. These checks do not
recalculate meters, head losses or automatically change a bypass decision.
Apartment, individual-house and hot-water assemblies need separate profiles.
`requirement` describes a design obligation, NOT a passed engineering check.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MeteringRule:
    code: str
    clause: str
    status: str  # checked / requirement / needs_data / review / error
    message: str


def remote_readout_required(project) -> bool:
    purpose = getattr(project.building.purpose, "value", project.building.purpose)
    return purpose in ("residential", "public") or bool(project.meters.has_askue)


def control_cock_dn(meter) -> int | None:
    """§12.9 specifies both meter TYPE and diameter, not diameter alone."""
    if meter is None:
        return None
    kind = (meter.type_label or "").casefold()
    if "крыльчат" in kind and 0 < meter.dn <= 50:
        return 15
    if "турбин" in kind and meter.dn > 50:
        return 25
    return None


def seismic_metering_rules(project) -> tuple[MeteringRule, ...]:
    """One source for seismic requirements in checks, selection, layout and SO.

    Requirements are not product instances: neither a hose count nor a body
    length can be inferred from intensity, inlet count, DN or pipe material.
    This helper must not resolve the catalogue (the selector also calls it).
    """
    seismic = project.building.seismicity or 0
    if seismic > 9:
        return (MeteringRule("VU-SEISMIC-SCOPE", "СП 30.13330.2020, п. 15.2.1", "error",
            "Сейсмичность выше области 7–9 баллов данного набора правил; требуется отдельное обоснование."),)
    if seismic < 7:
        return ()
    basis = project.metering_detail.seismic_design_basis.strip()
    return (
        MeteringRule("VU-SEISMIC-FLEX", "СП 30.13330.2020, пп. 15.2.1, 15.2.6",
            "review" if basis else "needs_data",
            f"Сейсмичность {seismic} баллов: на вводах и перед водомерами нужны гибкие соединения, "
            "допускающие угловые и продольные перемещения. Тип, количество, перемещения, DN, P/T "
            "и присоединения определяют по компоновке, КР и паспорту изделия. "
            "Обычная подводка или вибровставка без этих данных не подтверждает решение. "
            "Гибкое соединение не заменяет паспортный прямой участок перед счётчиком. "
            + ("Основание решения: " + basis if basis else "Решение не задано.")),
        MeteringRule("VU-SEISMIC-PASSAGE", "СП 30.13330.2020, пп. 15.2.3–15.2.5", "review",
            "Запрещена жёсткая заделка; проходы через стены — с зазором не менее 0,2 м и эластичным "
            "негорючим водогазонепроницаемым заполнением. Проход под фундаментом и компенсацию "
            "на деформационных швах проверить отдельно по КР."),
    )


def evaluate_metering_rules(project, meter, *, inputs_count: int, bypass: bool) -> tuple[MeteringRule, ...]:
    d, b = project.metering_detail, project.building
    errors = d.validate()
    if errors:
        raise ValueError("; ".join(errors))
    rules = []
    def add(code, clause, status, text):
        rules.append(MeteringRule(code, f"СП 30.13330.2020, {clause}", status, text))

    dn = control_cock_dn(meter)
    add("VU-CONTROL", "п. 12.9", "requirement" if dn else "needs_data",
        "Два контрольных шаровых крана с постоянно установленными заглушками: "
        "между счётчиком и второй запорной арматурой; второй — не далее 0,5 м после неё. "
        + (f"Контрольные краны DN{dn}." if dn else "DN уточнить по типу счётчика; автоматически не назначен."))
    add("VU-STRAIGHT", "пп. 12.8–12.9", "requirement",
        "Запорная арматура с двух сторон; ориентация счётчика и прямые участки — по паспорту. "
        "Универсальные 5DN/3DN и монтажная длина узла не назначаются.")
    from app.pz.metering_orientation import nonhorizontal_layout_pending
    if nonhorizontal_layout_pending(d) or d.assembly_orientation.startswith('vertical'):
        add("VU-ORIENTATION", "пп. 12.6, 12.8–12.9", "needs_data",
            "Задана вертикальная/смешанная компоновка ВУ. Проверяются направление потока, "
            "паспортный класс счётчика, положение фильтра, прямые участки и разгрузка прибора от веса труб. "
            + ("Смешанная геометрия с поворотами ещё не сформирована." if nonhorizontal_layout_pending(d) else
               "Вертикальная/смешанная принципиальная компоновка не подтверждает опоры и монтажные посадки."))
    if d.flexible_connections:
        from app.pz.metering_flexible import check_flexible_choices
        for check in check_flexible_choices(d,meter.dn if meter else None):
            add('VU-FLEX-SELECTION-' + check['role'].upper(), 'пп. 12.6, 12.9; п. 15.2.6 для сейсмических районов',
                'error' if check['errors'] else 'needs_data',
                'Гибкое соединение ' + check['role'] + ': '
                + '; '.join([*check['errors'],*check['pending']]))
    add("VU-FILTER", "п. 12.13", "requirement",
        "Перед домовым счётчиком на металлическом трубопроводе — механический или магнитно-механический "
        "фильтр; после счётчика — обратный клапан. Для иных труб фильтр проверяется по паспорту и решению проекта.")
    add("VU-SUPPORT", "п. 12.6", "requirement",
        "Опоры должны исключать передачу нагрузки от труб и арматуры на счётчик; обеспечить защиту от вибрации. "
        "Высота и конструкция опор требуют привязки к помещению, а не универсальной подставки.")
    add("VU-SERVICE-ISOLATION", "пп. 11.7–11.9, 12.9", "requirement",
        "Для снятия прибора проверяется отключение со всех сторон, включая обводную и обратную подачу "
        "из здания. Обратный клапан не считается ремонтной отсечкой. Снимаемая арматура не может "
        "сама изолировать место своего демонтажа; может потребоваться отключение за пределами ВУ.")
    add("VU-SERVICE-DRAIN", "пп. 11.17, 12.9; паспорт изделия", "review",
        "Контрольный отбор не подтверждает опорожнение. Для обслуживания проверить сброс давления, "
        "нижние точки слива внутри отсечек, впуск воздуха, карманы корпусов и безопасный приём воды. "
        "Пункт 11.17 задаёт требования к системе; конкретный слив и воздушное устройство ВУ определяют "
        "по его компоновке. Отчёт связности приведён на листах обслуживания.")
    add("VU-VALVE-INSTALLATION", "пп. 11.6, 12.8, 12.13; паспорта арматуры", "requirement",
        "Направление обратного клапана - по потоку, допустимое положение и прямые участки - по паспорту "
        "его модели. Ориентация шпинделя, доступ к приводу, разгрузка корпуса и применение запорной "
        "арматуры для регулирования проверяются отдельно. Разрешение для одного изделия не переносится "
        "на все задвижки, вентили или обратные клапаны.")

    common = inputs_count > 1 and d.inlet_metering_mode == "common"
    needs_bypass = inputs_count == 1 or common or bool(meter and meter.need_bypass)
    add("VU-BYPASS", "пп. 12.10–12.12", "error" if needs_bypass and not bypass else "requirement",
        ("В принятом решении нет требуемой обводной линии. Расчётное решение не изменено автоматически."
         if needs_bypass and not bypass else
         "Обводная предусмотрена. В штатном режиме её запорная арматура закрыта и опломбирована."
         if bypass else
         "Два ввода: отсутствие обводной допустимо при проверке каждого счётчика по п. 12.16б. "
         "Само число вводов не подтверждает эту проверку." if inputs_count == 2 else
         "Обводная не предусмотрена расчётным решением. Нужна проверка принятой топологии."))
    if inputs_count > 2:
        add("VU-MULTI-INLET", "п. 12.12", "review",
            "Более двух вводов: требуется отдельное обоснование топологии. "
            "Исключение для двух вводов не распространяется автоматически на эту схему.")
    if common:
        add("VU-COMMON-INLETS", "пп. 8.5, 8.23, 12.2, 12.12", "review",
            ("Принят общий счётчик на перемычке двух магистралей по рисунку Г.1; две обводные ветви. "
             if d.common_topology == 'gost_g1' and inputs_count == 2 else
             "Принят общий ВУ после объединения вводов; ") + "Каждый ввод проверяется на 100% расхода. "
            "Обводная - проектное решение для обслуживания общего счётчика, не применение исключения для двух водомеров. "
            "Границу учёта, давления вводов и режимы переключений согласовать по ТУ; размеры соединительного участка уточнить.")
    if meter and meter.need_bypass:
        add("VU-FIRE-AUTOMATION", "п. 12.11", "review",
            "Требуется проверка алгоритма открытия обводной по СП 10 и СП 484. "
            "Символ электропривода не подтверждает проект автоматизации.")

    if remote_readout_required(project):
        # Read the explicitly named model only; never auto-upgrade it to an
        # impulse version or equate planned ASKUE to an actual meter passport.
        from app.data.metering_products import get_metering_catalogue
        catalog = get_metering_catalogue()
        product = catalog.products.get(d.catalogue_items.get("meter", ""))
        if meter is not None and (d.meter_products or d.meter_selection_mode == "catalogue_proposal"):
            from app.pz.meter_products import evaluate_meter_product
            product = evaluate_meter_product(project, meter).product
        valid = (product is not None and meter is not None and product.kind == "meter"
                 and product.dn == meter.dn and d.catalogue_revision == catalog.revision)
        remote = product.remote_readout if valid else None
        add("VU-REMOTE", "п. 12.13", "checked" if remote is True else "error" if remote is False else "needs_data",
            "Дистанционная передача данных предусмотрена исполнением выбранного счётчика; интерфейс согласовать."
            if remote is True else
            "Выбранное исполнение счётчика не имеет требуемой дистанционной передачи данных. Нужна другая модификация."
            if remote is False else
            "Требуется счётчик с дистанционной передачей данных. Возможность подтвердить паспортом исполнения; "
            "отсутствие АСКУЭ в настройках не отменяет требования.")

    t = d.room_min_temperature_c
    add("VU-ROOM-TEMP", "п. 12.5", "needs_data" if t is None else "error" if t < 5 else "checked",
        "Минимальная температура помещения не задана; требуется не ниже +5 °C."
        if t is None else f"Минимальная температура помещения {t:g} °C; требуется не ниже +5 °C.")
    access = d.service_access_confirmed
    add("VU-ACCESS", "п. 12.5", "needs_data" if access is None else "checked" if access else "error",
        "Доступ для считывания и обслуживания " + ("подтверждён исходными данными." if access else
        "не подтверждён." if access is None else "не обеспечен: изменить размещение."))
    if d.room_location == "outside":
        add("VU-OUTSIDE", "п. 12.7", "review",
            "Установка вне здания требует подтверждения невозможности размещения внутри и паспорта "
            "с разрешением работы при затоплении. Обычная схема помещения не подтверждает эти условия.")

    rules.extend(seismic_metering_rules(project))

    if b.permafrost:
        location = d.room_location
        add("VU-FROZEN-LOCATION", "пп. 15.4.10–15.4.11",
            "needs_data" if location == "unknown" else "checked" if location == "first_floor" else "error",
            "Узел управления требуется на первом этаже; в проветриваемом подполье запорно-регулирующая "
            "арматура, спускные и воздушные краны не допускаются. "
            + ("Первый этаж задан." if location == "first_floor" else
               "Место установки не задано." if location == "unknown" else "Заданное размещение не соответствует требованию."))
        inlet_dn = d.inlet_dn
        add("VU-FROZEN-DN", "п. 15.4.17",
            "needs_data" if inlet_dn is None else "error" if inlet_dn < 50 else "checked",
            "Диаметр ввода — не менее DN50 независимо от расчёта; это НЕ минимальный DN водомера. "
            + (f"Задан ввод DN{inlet_dn}." if inlet_dn else "DN ввода не задан."))
        add("VU-FROZEN-PROTECTION", "пп. 15.4.1–15.4.2, 15.4.10, 15.4.13, 15.4.17–15.4.18",
            "review" if d.permafrost_design_basis.strip() else "needs_data",
            "Нужны защита от замерзания в штатном и нарушенном режиме, учёт воздействия на грунт, "
            "тепло- и гидроизоляция цокольного перекрытия, компенсация перемещений и возможность опорожнения. "
            "Материал арматуры ввода — по п. 15.4.17, уклон ввода не менее 0,002. "
            + ("Основание решения: " + d.permafrost_design_basis if d.permafrost_design_basis.strip() else "Решение не задано."))
    if d.catalogue_items or d.fitting_items or d.meter_products or d.meter_selection_mode == "catalogue_proposal" or d.pipe_sections or d.support_pipe_section or d.connection_items or d.connection_thread_items or d.reducer_items:
        # Local import avoids the selector's remote_readout_required import
        # cycle. Unknown installation dimensions do not block stage P; known
        # incompatible explicitly selected items must not pass release.
        from app.pz.metering_product_selection import resolve_metering_products
        selection = resolve_metering_products(project, meter, bypass=bypass,
            electric_bypass=bool(bypass and meter and meter.need_bypass))
        if selection.errors:
            rules.append(MeteringRule("VU-CATALOGUE", "Комплектация ВУ и данные труб", "error",
                                      "; ".join(selection.errors)))
    if d.pipe_sections:
        rules.append(MeteringRule("VU-PIPE-JOINTS", "Исходные по трубам и паспорта соединителей", "review",
            "Материалы и размеры заданы отдельно по участкам ВУ. Совместимость соединителей, "
            "крепления, монтажные длины и условия применения требуют проверки; DN не заменяет наружный диаметр. "
            "Гидравлический расчёт этими данными автоматически не изменяется."))
    from app.pz.metering_options import option_requests, OPTIONS_NOTICE
    from app.pz.metering_extras import metering_option_rows, resolve_metering_extras
    requests = metering_option_rows(project)
    if requests:
        rules.append(MeteringRule("VU-OPTIONS", "Задание пользователя, не нормативное требование", "review", OPTIONS_NOTICE))
        rules.extend(MeteringRule("VU-OPTION-" + row["key"].upper(),
            "Дополнительное оборудование: " + row["title"] + " — " + row["label"], "review", row["requirement"])
            for row in requests)
        rules.extend(MeteringRule("VU-EXTRA-CONFLICT-" + str(i), "Совместимость дополнительного оборудования",
                                  "error", issue)
                     for i, issue in enumerate(resolve_metering_extras(project)["issues"], 1))
    return tuple(rules)


def special_layout_pending(project) -> bool:
    """Special physical layouts aren't generated by an ordinary inlet template."""
    from app.pz.metering_orientation import nonhorizontal_layout_pending
    return bool(project.building.seismic or project.building.permafrost
                or project.metering_detail.room_location == "outside"
                or project.metering_detail.flexible_connections
                or nonhorizontal_layout_pending(project.metering_detail))


def metering_composition_warnings(project) -> list[str]:
    """Identical warnings for calculation-only Studio and the PDF pipeline."""
    from app.pz.metering_detail import drawing_state
    state = drawing_state(project)
    warnings = [f"Водомерный узел: {message}" for message in state.missing]
    warnings += [f"Водомерный узел [{r.code}; {r.clause}]: {r.message}"
                 for r in evaluate_metering_rules(project,state.meter,
                     inputs_count=state.inputs_count,bypass=state.bypass)
                 if r.status in ("needs_data", "review", "error")]
    if special_layout_pending(project):
        warnings.append("Водомерный узел: специальная физическая компоновка не сформирована; "
                        "доступны только базовая обвязка и условия для привязки")
    return warnings
