"""Orientation eligibility is not a rotated drawing or installation approval."""
from dataclasses import dataclass

from app.data.metering_installation import ORIENTATIONS


@dataclass(frozen=True)
class OrientationCheck:
    orientation: str
    allowed: bool | None
    qmin_m3h: float | None = None
    metrological_class: str = ''
    reference: str = ''
    errors: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()


def check_product_orientation(product, orientation):
    if orientation in ('unknown', 'vertical'):
        return OrientationCheck(orientation, None, pending=(
            'Для проверки ориентации задайте положение и направление потока (вверх/вниз).',))
    if orientation not in ORIENTATIONS:
        return OrientationCheck(orientation, False, errors=('Неизвестная ориентация монтажа.',))
    profile = product.installation
    if profile:
        reference = f"{profile['source_id']}; {profile['reference']}"
        if orientation not in profile['allowed']:
            return OrientationCheck(orientation, False, reference=reference,
                errors=(f'{product.name}: паспорт не разрешает {orientation}.',),
                pending=tuple(profile['conditions']))
        minimum = profile['minima'].get(orientation, {})
        return OrientationCheck(orientation, True, minimum.get('qmin_m3h'), minimum.get('class',''),
                                reference, pending=tuple(profile['conditions']))
    # Preserve previously reviewed horizontal evidence; do not generalise it
    # to vertical installations or transfer class A/B between manufacturers.
    if orientation == 'horizontal_dial_up' and product.mounting in (
            'horizontal_dial_up', 'horizontal_cap_down'):
        return OrientationCheck(orientation, True, product.flows_m3h.get('qmin_B'),
            'B' if 'qmin_B' in product.flows_m3h else '',
            '; '.join(product.source_ids) + '; ранее проверенный горизонтальный профиль')
    if product.mounting == 'any' and product.kind != 'meter':
        return OrientationCheck(orientation, True, reference='; '.join(product.source_ids))
    return OrientationCheck(orientation, None, pending=(
        f'{product.name}: паспортное подтверждение заданной ориентации ещё не внесено в базу.',))


def component_orientation(detail, role):
    if role == 'meter':
        return detail.meter_mounting
    return detail.component_orientations.get(role, detail.assembly_orientation)


def meter_orientation(detail, node):
    return detail.meter_orientations.get(node, detail.meter_mounting)


def filter_offset_choices(detail, meter_dn):
    """Explicit family opt-in, exact DN only; actual products are revalidated.

    Derived IDs are never persisted over manual assignments or used as fallback
    products. An unavailable size, RU preference or conflict stays an error.
    """
    from dataclasses import replace
    errors = []
    if detail.filter_inline_family:
        if detail.filter_inline_family != 'valtec_vt386':
            return detail, ['Неизвестное исполнение фильтра на оси']
        if detail.filter_offset_family or any(detail.fitting_items.get(r) for r in FILTER_TURN_ROLES):
            errors.append('Фильтр VT.386 на оси несовместим с выбранным горизонтальным смещением/отводами фильтра')
        if component_orientation(detail, 'filter') != detail.assembly_orientation:
            errors.append('Фильтр VT.386 на оси должен иметь ориентацию основного узла')
        if meter_dn not in (15,20,25):
            return detail, errors + ['Для фильтра VT.386 подтверждены только DN15, DN20 и DN25; другой DN не подставляется']
        choices = dict(detail.catalogue_items)
        ident = f'valtec-vt386-dn{meter_dn}'
        if choices.get('filter', ident) != ident:
            errors.append('filter: ручное изделие противоречит выбранному исполнению VT.386')
        else:
            choices['filter'] = ident
        return replace(detail, catalogue_items=choices), errors
    if not detail.filter_offset_family:
        return detail, errors
    if not horizontal_filter_offset(detail):
        errors.append("Горизонтальный фильтр со смещением требует вертикального счётчика и горизонтальной оси фильтра")
    if meter_dn is None:
        errors.append("Для исполнения фильтра не определён текущий DN водомера")
    choices, fittings = dict(detail.catalogue_items), dict(detail.fitting_items)
    assignments = [(choices, 'filter', f'valtec-vt192-dn{meter_dn}')]
    assignments += [(fittings, r, f'valtec-vtr090-dn{meter_dn}') for r in FILTER_TURN_ROLES]
    for target, role, ident in assignments:
        if role in target and target[role] != ident:
            errors.append(f"{role}: ручное изделие противоречит выбранному исполнению фильтра")
        else:
            target[role] = ident
    return replace(detail, catalogue_items=choices, fitting_items=fittings), errors


FILTER_TURN_ROLES = ('filter_turn_in', 'filter_turn_out')


def horizontal_filter_offset(detail):
    """Supported mixed topology: vertical flow, one horizontal filter island.

    This predicate describes the requested axes, not approved products. Both
    elbows must still be explicitly bound and pass the fitting/port checks.
    """
    axis = detail.assembly_orientation
    return (axis in ('vertical_up', 'vertical_down')
            and detail.meter_mounting == axis
            and component_orientation(detail, 'filter') == 'horizontal_dial_up'
            and all(role == 'filter' or value == axis
                    for role, value in detail.component_orientations.items()))


def nonhorizontal_layout_pending(detail):
    """Only supported axes with explicit turns may be drawn as mixed."""
    if horizontal_filter_offset(detail):
        return not (detail.filter_offset_family or all(detail.fitting_items.get(r) for r in FILTER_TURN_ROLES))
    axis = detail.assembly_orientation
    return (axis not in ORIENTATIONS
            or detail.meter_mounting not in (('unknown', axis) if axis=='horizontal_dial_up' else (axis,))
            or any(x != axis for x in detail.component_orientations.values()))
