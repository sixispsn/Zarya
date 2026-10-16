"""PZ wording consumes the same inlet selection and service graph as the sheet."""


def metering_presentation(project):
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_spec import build_metering_spec_section
    state = drawing_state(project)
    if state.meter is None:
        inlet = 'Вводной учёт воды: расчётный водомер не определён; исходные и подбор требуют уточнения.'
    else:
        inlet = ((f'Вводной учёт воды: один общий ВУ со счётчиком DN{state.meter.dn} '
                  f'для {state.inputs_count} вводов. Вводы объединяются до узла учёта. '
                  if state.common_inlets else
                  f'Вводной учёт воды: узлов — {state.assemblies_count}; '
                  f'по одному счётчику DN{state.meter.dn} на каждом вводе. ')
                 + ('Предусмотрена обводная линия.' if state.bypass else 'Обводная линия не предусмотрена.'))
        if state.common_inlets:
            inlet += (' Общая обводная принята для обслуживания; в штатном режиме закрыта и опломбирована. '
                      'Исключение п. 12.12 СП 30 для двух отдельных счётчиков здесь не применяется. '
                      'Схему коммерческого учёта и режим переключений согласовать с ТУ. '
                      'Каждый ввод проверяется на полный расход при отключении второго; расход через общий счётчик не делится пополам.')
    detail = project.metering_detail
    if state.switching_bridge:
        inlet = (f'Вводной учёт воды: один общий ВУ со счётчиком DN{state.meter.dn} ' if state.meter else
                 'Вводной учёт воды: общий ВУ, расчётный счётчик не определён. ')
        inlet += ('на перемычке между двумя проходными магистралями по рисунку Г.1 ГОСТ Р 21.619-2023. '
                  'Предусмотрены четыре переключающих затвора, две обводные ветви с обратными клапанами '
                  'и отдельные отсечки на входах и выходах. В режиме учёта обводная арматура закрыта и опломбирована. '
                  'Каждый ввод проверяется на полный расход; расход общего счётчика не делится пополам. '
                  'Монтажная привязка и потери переключающей обвязки требуют проверки; '
                  'режимы переключения и границу учёта согласовать по ТУ.')
    if detail.room_name or detail.room_number:
        room = ' '.join(v for v in (f'№ {detail.room_number}' if detail.room_number else '', detail.room_name) if v)
        inlet += f' Помещение узла: {room}.'
    else:
        inlet += ' Размещение узла уточняется по архитектурным данным.'
    service = ''
    if detail.maintenance_layout == 'serviceable':
        selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                              electric_bypass=state.electric_bypass)
        chain = build_metering_chain(detail, state, selection)
        marks = {ident: r.diagram_pos for r in build_metering_spec_section(project).rows
                 for ident in r.component_ids}
        ids = {n.id for n in chain.nodes}
        required = {'outlet_valve', 'maintenance_cock_in', 'maintenance_cock_out'}
        if required <= ids:
            service = (f'В сервисной компоновке основного ВУ предусмотрены выходная отсечка '
                       f'(поз. {marks["outlet_valve"]}) и два сервисных отбора с заглушками '
                       f'(поз. {marks["maintenance_cock_in"]}, {marks["maintenance_cap_in"]}) на каждый узел. '
                       'Контрольные краны по п. 12.9 СП 30 сохранены. '
                       'Обратный клапан не заменяет ремонтную отсечку. '
                       'Нижние точки, впуск воздуха, безопасный отвод воды и опорожнение полостей изделий '
                       'уточняются при монтажной привязке; наличие отборов не подтверждает полный слив. '
                       'Самостоятельный узел учёта ГВС / перед водонагревателем проверяется отдельно.')
    modes_notice = ''
    if state.switching_bridge:
        modes_notice = ('Положения арматуры по режимам приведены в таблице на листах ВУ; '
            'З1/З2 - вводы, З3-З6 - переключающая арматура вставки, З7/З8 - обводы, '
            'З9/З10 - выходы, З11/З12 - отсечки счётчика. '
            'В штатном режиме обводы закрыты и опломбированы (СП 30, п. 12.11 с изм. 3). '
            'Связь двух вводов до счётчика требует проверки давлений наружной сети и ТУ. '
            'Таблица проверяет проектные пути воды, не подтверждает гидравлику и не заменяет инструкцию переключений.')
        if state.fire_branch:
            modes_notice += ' В2 отбирается до учёта: команда пожара не переносится автоматически на обводы В1.'
    return dict(inlet=inlet, service=service, modes_notice=modes_notice, common_inlets=state.common_inlets,
                assemblies_count=state.assemblies_count, bypass=state.bypass, switching_bridge=state.switching_bridge)
