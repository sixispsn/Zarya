"""Preliminary apartment product proposals; never a new hydraulic method.

DN and representative flow are recalculated by the approved Studio calculator.
Current inputs, not house meter DN, SVG size or an old product assignment, rule.
Matching nominal/thread ports is only a composition proposal: it does not prove
the installed connection chain, branch pressure or the manufacturer's h(Q).
"""
from dataclasses import dataclass
from math import isfinite

from app.data.metering_products import MeteringProduct, MeterConnectionKit, get_metering_catalogue
from app.data import apartment_regulators as regulator_catalogue
from app.data.apartment_filters import filter_evidence, preferred_apartment_filter
from app.calc.apartment_meters import estimate_apartment_meters


@dataclass(frozen=True)
class ApartmentProductPosition:
    kind: str
    product: MeteringProduct | None
    candidates: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ApartmentProductProposal:
    dn: int
    flow_lps: float
    reference_loss_m: float
    design_residents: float
    basis: str
    catalogue_revision: str
    positions: tuple[ApartmentProductPosition, ...]
    status: str = 'preliminary'


@dataclass(frozen=True)
class ApartmentKitProposal:
    kit: MeterConnectionKit | None
    meter: MeteringProduct | None
    reason: str


def apartment_connection_kit(project, system):
    from app.pz.metering_accessories import propose_connection_kit
    proposal = apartment_product_proposal(project, system)
    meter = next((p.product for p in proposal.positions if p.kind == 'meter'), None) if proposal else None
    kit = propose_connection_kit(get_metering_catalogue(), meter)
    return ApartmentKitProposal(kit, meter,
        'Один комплект на счётчик; состав поставки уточняется при заказе' if kit else
        'Нет единственного совместимого присоединительного комплекта')


@dataclass(frozen=True)
class ApartmentRegulatorProposal:
    product: regulator_catalogue.ApartmentRegulator | None
    candidates: tuple[str, ...]
    reason: str
    status: str = 'needs_selection'
    setting_bar: float | None = None


def apartment_regulator_proposal(project, system):
    """Screen a candidate only where the accepted regulation plan requires PRVs.

    Neither the required-head envelope nor the meter DN proves inlet pressure,
    regulation at design/minimum flow, an outlet setting or the number of stages.
    """
    from app.pz.water_regulation_plan import branch_regulation_plan
    plan = branch_regulation_plan(project)
    if plan.state != 'principle' or not plan.floors or system not in plan.systems:
        return None
    proposal = apartment_product_proposal(project, system)
    if not proposal:
        return ApartmentRegulatorProposal(None, (), 'Нет исходных квартирного узла')
    meter = next((p.product for p in proposal.positions if p.kind == 'meter'), None)
    strainer = next((p.product for p in proposal.positions if p.kind == 'filter'), None)
    catalog = get_metering_catalogue()
    evidence = filter_evidence(strainer, catalog)
    mesh = evidence.mesh_microns if evidence else None
    temperature = (project.insulation.hvs_water_temp if system == 'В1'
                   else project.insulation.gvs_water_temp)
    candidates = tuple(p for p in regulator_catalogue.PRODUCTS
        if meter and strainer and mesh is not None and p.status == 'catalogued'
        and p.dn == proposal.dn and p.static_regulation
        and p.connection_standard == meter.connection_standard and p.connection_sex == 'female'
        and p.thread == meter.kit_pipe_thread
        and type(temperature) in (int, float) and isfinite(temperature)
        and p.temperature_c[0] <= temperature <= p.temperature_c[1]
        and mesh <= p.upstream_filter_max_microns)
    return ApartmentRegulatorProposal(candidates[0] if len(candidates) == 1 else None,
        tuple(p.id for p in candidates),
        'Кандидат; уставка и работа при расчётном и малом расходе не подтверждены'
        if len(candidates) == 1 else 'Нет единственного совместимого кандидата РД',
        'candidate' if len(candidates) == 1 else 'needs_selection')


def apartment_product_proposal(project, system):
    from app.pz.water_apartment_assembly import apartment_components
    if not apartment_components(project, system) or not project.meters.has_apartment_meters:
        return None
    units = project.apartment_water_units
    if units.validate():
        raise ValueError('; '.join(units.validate()))
    # Do not apply a single household estimate to mixed/unreconciled consumers.
    if sum(row[1] for row in project.consumer_groups) != project.building.residents:
        return None
    try:
        estimate = estimate_apartment_meters(dict(
            residents=project.building.residents, apartments=project.building.apartments,
            consumer_code=project.consumer_groups[0][0], hws_type=project.building.hws_type.value,
            apartment_design_residents=units.design_residents))
    except ValueError:
        return None
    if not estimate:
        return None
    row = estimate['rows']['h_apartment_c_meter_m' if system == 'В1' else 'h_apartment_h_meter_m']
    catalog = get_metering_catalogue()
    temperature = (project.insulation.hvs_water_temp if system == 'В1'
                   else project.insulation.gvs_water_temp)
    def temperature_fits(product):
        # Current design temperature is a screening constraint, not a P/T approval.
        return (type(temperature) in (int, float) and isfinite(temperature)
                and product.temperature_c[0] <= temperature <= product.temperature_c[1])
    # Offer a pulse-output meter, not an assertion that an entire AMR is ready.
    meters = tuple(p for p in catalog.candidates('meter', row['dn'])
        if p.remote_readout is True and p.connection_standard == 'G'
        and p.connection_sex == 'male' and p.kit_pipe_thread
        and p.flows_m3h.get('qmax', 0) >= row['flow_lps'] * 3.6
        and temperature_fits(p))
    meter = meters[0] if len(meters) == 1 else None
    positions = []
    for item in apartment_components(project, system):
        if item.kind == 'meter':
            candidates = meters
        else:
            kind = {'valve': 'shutoff', 'filter': 'strainer', 'check': 'check'}[item.kind]
            # Nominal DN is not the outside diameter of the apartment PE-X pipe.
            candidates = tuple(p for p in catalog.candidates(kind, row['dn'])
                if meter and p.connection_standard == meter.connection_standard
                and p.connection_sex == 'female' and p.thread == meter.kit_pipe_thread
                and (item.kind != 'valve' or p.drive == 'manual') and temperature_fits(p)
                and (item.kind != 'filter' or
                     'horizontal_dial_up' in p.installation.get('allowed', ())))
        product = candidates[0] if len(candidates) == 1 else None
        preferred = preferred_apartment_filter(candidates, catalog) if item.kind == 'filter' else None
        if preferred:
            product = preferred
        reason = ('Предложение; не окончательный подбор' if product else
                  'Нет единственного совместимого предложения каталога')
        if preferred:
            evidence = filter_evidence(preferred, catalog)
            reason += (f'; приоритет очистки и обслуживания: сетка {evidence.mesh_microns} мкм, '
                       'резьба пробки вне рабочей среды; '
                       f'PN{preferred.pn_bar:g}, давление и сопротивление узла требуют проверки')
        if product and item.kind == 'meter' and row['flow_lps'] * 3.6 > product.flows_m3h['qn']:
            reason += '; расход выше Qn: требуется проверка длительности по паспорту'
        positions.append(ApartmentProductPosition(item.kind, product,
                          tuple(p.id for p in candidates), reason))
    return ApartmentProductProposal(row['dn'], row['flow_lps'], row['loss_m'],
        estimate['design_residents'], estimate['basis'], catalog.revision, tuple(positions))


def apartment_product_spec_note(project):
    """One readable note, not repeated paragraphs in every narrow SO cell."""
    proposals = [(s, apartment_product_proposal(project, s)) for s in ('В1', 'Т3')]
    proposals = [(s, p) for s, p in proposals if p]
    if not proposals:
        return ''
    def number(v):
        return f'{v:g}'.replace('.', ',')
    lines = [' Квартирные узлы: предварительное предложение изделий по текущему расчёту.']
    for system, p in proposals:
        lines.append(f'{system}: {number(p.design_residents)} чел./квартиру, '
                     f'q={number(p.flow_lps)} л/с, счётчик DN{p.dn}, '
                     f'h={number(p.reference_loss_m)} м по расчётному каталогу, не паспортное h(Q).')
        if any('выше Qn' in pos.reason for pos in p.positions):
            lines.append(f'{system}: расход выше паспортного Qn; проверить допустимую длительность.')
    if any(pos.product and pos.product.id.startswith('valtec-vt386-')
           for _, p in proposals for pos in p.positions):
        lines.append('Фильтр VT.386 предложен по приоритету очистки и обслуживания: сетка 300 мкм '
            'и резьба пробки вне рабочей среды. Это не преимущество по всем характеристикам: '
            'PN16 и +1…+110 °C; проверить рабочее давление и потери, обеспечить доступ для очистки. '
            'Более тонкая сетка не означает меньшее сопротивление или отсутствие засорения.')
    lines.append('Ручные потери в балансе напора сохранены; предложение моделей их не заменяет. '
        'DN арматуры предложен по присоединению счётчика, не по наружному диаметру трубы. '
        'Окончательный подбор требует проверки рабочего давления и температуры квартирного узла, '
        'минимального расхода и паспортного сопротивления; средняя квартира не является подтверждённой диктующей. '
        'Предложен горизонтальный монтаж счётчика циферблатом вверх, фильтра пробкой вниз. '
        'Присоединительные части учтены отдельной строкой: один комплект на счётчик. '
        'Если комплект входит в поставку счётчика, повторно его не закупать; состав и артикул уточнить при заказе. '
        'Прямые участки и пространство обслуживания уточняются отдельно; '
        'габариты корпусов и справочный L1 счётчика не являются монтажной длиной узла. '
        'Импульсный выход не означает готовность АСКУЭ.')
    # Independent of the spec builder: no circular call to connection rows.
    from app.data.apartment_pipe_connections import ConnectionPort, propose_pipe_end
    from app.pz.water_pipe_binding import bind_v1_pipes, bind_t3_pipes
    pipe_candidates = []
    for system, proposal in proposals:
        pipe = (bind_v1_pipes(project) if system == 'В1' else bind_t3_pipes(project))['apartment'].pipe
        temperature = (project.insulation.hvs_water_temp if system == 'В1' else project.insulation.gvs_water_temp)
        for pos in proposal.positions:
            if pos.kind in ('valve', 'check') and pos.product:
                port = ConnectionPort(pos.product.connection_standard, pos.product.thread, pos.product.connection_sex)
                pipe_candidates.append(propose_pipe_end(pipe, port, temperature))
    if any(pipe_candidates):
        lines.append('Для PE-X 20×2 предложены VT.4410.NE.20 и VTr.580.NE.040E: '
            'евроконус не заменяется обычной G3/4. По ПС 47657-2, п. 6.4, гайки подтягивают '
            'каждые 6 месяцев: соединения должны быть доступны. Серия трубы, рабочее давление '
            'и монтаж не подтверждены. Источники: VALTEC ПС 47657-2 и ПС 47639-4.')
    if any((r := apartment_regulator_proposal(project, s)) and r.product for s, _ in proposals):
        lines.append('РД OR.224.G: кандидат, не окончательный подбор. Уставка и потери не назначены; '
            'проверить входное давление в статике и динамике, работу при расчётном и малом расходах, '
            'кавитацию и давление у прибора. Заводская настройка не принята за проектную. '
            'Перед РД нужен фильтр не грубее 500 мкм; место установки проверить по компоновке. '
            'Для настройки нужен поверенный манометр, не входящий в комплект; постоянный манометр '
            'на каждый РД этим предложением не назначается. Резьба его порта требует уточнения: '
            'в паспорте указаны G1/4 и Rp1/4. Источник: ' + regulator_catalogue.SOURCE_TITLE + '.')
    if any(pos.product and pos.product.id.startswith('itap-europa100-')
           for _, proposal in proposals for pos in proposal.positions):
        lines.append('Для ITAP EUROPA 100 паспорт требует 10 диаметров трубы от изгиба/циркуляционного насоса; '
                     'на условной схеме этот размер не подтверждён.')
    catalog = get_metering_catalogue()
    source_ids = sorted({s for _, p in proposals for pos in p.positions if pos.product
                         for s in pos.product.source_ids})
    if source_ids:
        lines.append('Источники каталога: ' + '; '.join(catalog.sources[s]['title'] for s in source_ids) + '.')
    return ' '.join(lines)
