"""Shared composition of the representative apartment branch, not a takeoff.

The consumer profile supplies a type, not the number of feeds in every flat.
Quantities require an explicit feed-count choice; products are proposed separately.
Pressure regulators have their own accepted plan and are not duplicated here.
"""
from dataclasses import dataclass
from app.pz.hws_presentation import hws_zone_count


@dataclass(frozen=True)
class ApartmentComponent:
    key: str
    kind: str
    name: str
    system: str


def apartment_components(project, system):
    if (system not in ('В1', 'Т3')
            or project.building.purpose.value != 'residential'
            or project.building.hws_type.value != 'central'
            or project.document.stage != 'П'
            or project.building.zones != 1 or hws_zone_count(project) != 1
            or project.fixtures
            or {row[0] for row in project.consumer_groups} != {'residential_full_bath'}):
        return ()
    prefix = 'v1' if system == 'В1' else 't3'
    names = [('valve', 'Арматура запорная'), ('filter', 'Фильтр'),
             *([('meter', 'Счётчик воды')] if project.meters.has_apartment_meters else []),
             ('check', 'Клапан обратный')]
    return tuple(ApartmentComponent(f'apartment-{prefix}-{kind}', kind,
        f'{name} квартирного ответвления {system}', system) for kind, name in names)


def apartment_spec_rows(project, system, next_pos):
    from app.pz.spec import SpecRow
    from app.pz.apartment_products import apartment_product_proposal, apartment_connection_kit
    units = project.apartment_water_units
    qty = units.quantity(system, project.building.apartments)
    proposal = apartment_product_proposal(project, system)
    positions = {p.kind: p for p in proposal.positions} if proposal else {}
    rows = []
    for item in apartment_components(project, system):
        position = positions.get(item.kind)
        product = position.product if position else None
        size = f'DN{proposal.dn}' if proposal else 'DN уточнить'
        mark = (f'{product.model}; {size}; G{product.thread}' if product else
                f'{size}; модель уточнить')
        rows.append(SpecRow(next_pos(), item.name, type_mark=mark, unit='шт.', qty=qty,
        code=product.article if product else '', manufacturer=product.manufacturer if product else '',
        catalogue_id=product.id if product else '',
        component_ids=(item.key,), quantity_basis='apartment_schedule' if qty is not None else 'apartment_principle',
        quantity_source=units.quantity_source(system, project.building.apartments),
        note=('Предварительное предложение' if product else 'Подбор не завершён') +
             ('; присоединения учтены отдельно' if item.kind == 'meter' else '')))
    if any(item.kind == 'meter' for item in apartment_components(project, system)):
        found = apartment_connection_kit(project, system)
        kit = found.kit
        prefix = 'v1' if system == 'В1' else 't3'
        rows.append(SpecRow(next_pos(), f'Присоединительный комплект квартирного счётчика {system}',
            type_mark=(f'{found.meter.model}; DN{found.meter.dn}; G{kit.meter_thread} × G{kit.pipe_thread}' if kit else 'по подбору'),
            manufacturer=found.meter.manufacturer if kit else '',
            unit='компл.', qty=qty, catalogue_id=kit.id if kit else '',
            component_ids=(f'apartment-{prefix}-meter-kit',),
            quantity_basis='apartment_schedule' if qty is not None else 'apartment_principle',
            quantity_source=(f'1 комплект на счётчик {system} × {qty} узлов' if qty is not None else ''),
            note=('Включая поставку счётчика; повторно не закупать; состав уточнить' if kit else
                  'Совместимость и состав требуют подбора')))
    return rows
