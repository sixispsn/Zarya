"""Port-aware apartment connections, not a hydraulic or installation approval.

Counts follow the accepted apartment-unit schedule. A representative pipe size
is a connection requirement, not evidence for a particular PE-X fitting system.
Meter tails are already included in ONE kit and are never counted as nipples.
"""
from dataclasses import dataclass

from app.data.apartment_pipe_connections import ConnectionPort, propose_pipe_end
from app.pz.apartment_products import (
    apartment_product_proposal, apartment_regulator_proposal,
)
from app.pz.water_pipe_binding import bind_v1_pipes, bind_t3_pipes
from app.pz.water_regulation_plan import branch_regulation_plan


@dataclass(frozen=True)
class ThreadNipple:
    article: str
    thread: str
    # Passport / drawing disagree (DN15 A=23/25, DN20 S=27/26).
    # Thread and article are usable for a proposal, dimensions are NOT approved.
    dimensions_status: str = 'conflict'


NIPPLES = (ThreadNipple('VTr.582.N.0004', '1/2'),
           ThreadNipple('VTr.582.N.0005', '3/4'))
SOURCE_ID = 'vtr-1025'
SOURCE_SHA256 = '44e8069b8d2e0660acd4e1ca60a2e4f9b42c047db86bf31bafc22ca1a76be6f6'
SOURCE_URL = 'https://valtec.ru/document/technical/VTr-1025.pdf'


def _port(product):
    if not product or (getattr(product, 'dimension_status', None) != 'verified'
                       and getattr(product, 'status', None) != 'catalogued'):
        return None
    if product.connection_standard != 'G' or product.connection_sex not in ('female', 'male'):
        return None
    return product.thread, product.connection_sex


def _joint(left, right):
    """No size-only matching; eurocone, flat gasket and G are not synonyms."""
    a, b = _port(left), _port(right)
    if not a or not b or a[0] != b[0]:
        return 'unresolved', None
    if a[1] != b[1]:
        return 'direct', None
    if a[1] != 'female':
        return 'unresolved', None
    from app.data.metering_products import get_metering_catalogue
    source = get_metering_catalogue().sources.get(SOURCE_ID, {})
    options = tuple(n for n in NIPPLES if n.thread == a[0])
    if source.get('sha256') != SOURCE_SHA256 or len(options) != 1:
        return 'unresolved', None
    return 'nipple', options[0]


def apartment_connection_rows(project, system, next_pos):
    from app.pz.spec import SpecRow
    from app.pz.water_apartment_assembly import apartment_components
    if not any(c.kind == 'meter' for c in apartment_components(project, system)):
        return []
    units = project.apartment_water_units
    qty = units.quantity(system, project.building.apartments)
    proposal = apartment_product_proposal(project, system)
    parts = {p.kind: p.product for p in proposal.positions} if proposal else {}
    prefix = 'v1' if system == 'В1' else 't3'
    rows = []

    def append(key, name, mark, number, source, note, product=None):
        rows.append(SpecRow(next_pos(), name, type_mark=mark, unit='шт.', qty=number,
            code=product.article if product else '', manufacturer='VALTEC' if product else '',
            catalogue_id=f'valtec-{product.article.lower()}' if product else '',
            component_ids=(f'apartment-{prefix}-connection-{key}',),
            quantity_basis='apartment_connection_schedule' if number is not None else 'apartment_principle',
            quantity_source=source, note=note))

    # These are two ends of the accepted inline apartment unit, not riser
    # takeoff fittings. The same characteristic pipe does not prove every flat.
    binding = (bind_v1_pipes(project) if system == 'В1' else bind_t3_pipes(project))['apartment']
    pipe = binding.pipe
    geometry = (f'{ {"pex": "PE-X", "steel": "Сталь", "pe": "ПЭ"}[pipe.family]} {pipe.label}'
                if pipe else 'Материал и Dн×s уточнить')
    temperature = (project.insulation.hvs_water_temp if system == 'В1'
                   else project.insulation.gvs_water_temp)
    for end, part, label in [('in', 'valve', 'перед краном'), ('out', 'check', 'после обратного клапана')]:
        port = _port(parts.get(part))
        thread = f'G{port[0]} {"НР" if port[1] == "female" else "ВР"}' if port else 'резьба по подбору'
        candidate = propose_pipe_end(pipe, ConnectionPort('G', *port) if port else None, temperature)
        if candidate:
            append(end, f'Фитинг обжимной трубы квартирного узла {system}, {label}',
                f'PE-X {pipe.label} × евроконус 3/4 ВР', qty,
                f'1 фитинг × {qty} узлов' if qty is not None else '',
                'Кандидат; PN10; нужен доступ для подтяжки каждые 6 мес.; P/T проверить', candidate.fitting)
            append(end + '-adapter', f'Переходник евроконуса квартирного узла {system}, {label}',
                f'Евроконус 3/4 НР × {thread}', qty,
                f'1 переходник × {qty} узлов' if qty is not None else '',
                'Кандидат; габариты в источниках расходятся; не монтажная длина', candidate.adapter)
            continue  # The pair replaces, not duplicates, the generic requirement.
        append(end, f'Присоединение трубы к квартирному узлу {system}, {label}',
            f'{geometry} × {thread}', qty, f'1 присоединение × {qty} узлов' if qty is not None else '',
            'Для принятого типового узла; серия трубы и способ монтажа не подтверждены; артикул по подбору')

    def joint_row(key, left, right, number, title):
        state, nipple = _joint(left, right)
        if state == 'direct':
            return  # No redundant fitting between already mating G ports.
        append(key, f'{"Ниппель" if nipple else "Соединение"} {title}, квартирный узел {system}',
            f'VTr.582.N; G{nipple.thread} НР/НР' if nipple else 'Тип и резьба по подбору',
            number, f'1 соединение × {number} узлов' if number is not None else '',
            'Кандидат; габариты в источниках расходятся; не монтажная длина' if nipple else
            'Нет подтверждённой пары присоединений; автоматическая подстановка запрещена', nipple)

    joint_row('valve-filter', parts.get('valve'), parts.get('filter'), qty, 'кран–фильтр')
    plan = branch_regulation_plan(project)
    if plan.state == 'needs_data':
        append('filter-regulator', f'Соединение фильтр–РД квартирного узла {system}',
               'Состав по уточнённому решению РД', None, '', plan.issue)
    elif plan.state == 'principle' and plan.floors and system in plan.systems:
        rd = apartment_regulator_proposal(project, system)
        number = units.quantity_on_floors(system, project.building.apartments,
            project.building.floors_above, project.building.apartments_by_floor, plan.floors)
        joint_row('filter-regulator', parts.get('filter'), rd.product if rd else None,
                  number, 'фильтр–РД')
    return rows
