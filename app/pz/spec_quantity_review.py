"""Read-only review of SO quantities, not equipment or release approval.

Uses exactly the rows sent to the PDF. No takeoff from drawing symbols, no
conversion of hydraulic-path length into network metres, no invented counts.
"""
from math import isfinite

from app.pz.spec import build_water_specification, format_spec_qty

ESTIMATED_BASES = frozenset({'area_estimate', 'assembly_estimate'})
NOTICE = ('Проверены только количества ИОС2, не подбор оборудования и не готовность '
          'к закупке или экспертизе. Пустое поле не означает ноль. '
          'Предпросмотр принципиальной схемы остаётся доступен.')


def review_spec_quantities(spec):
    counts = dict(positions=0, assigned=0, estimated=0, missing=0, invalid=0, requirements=0)
    groups, missing_ids, needs_area = [], set(), False
    for section in spec.sections:
        items = []
        for row in section.rows:
            # Textual requirements (e.g. telemetry wishes) are not BOM items.
            if not row.unit:
                counts['requirements'] += 1
                continue
            counts['positions'] += 1
            state = 'missing' if row.qty is None else 'assigned'
            if state == 'assigned':
                try:
                    if type(row.qty) not in (int, float) or not isfinite(row.qty) or row.qty < 0:
                        raise ValueError('invalid quantity')
                    format_spec_qty(row.qty, row.unit)
                except (ValueError, TypeError, OverflowError):
                    state = 'invalid'
            counts[state] += 1
            if state == 'assigned':
                if row.quantity_basis in ESTIMATED_BASES:
                    counts['estimated'] += 1
                continue
            missing_ids.update(row.component_ids)
            needs_area |= row.quantity_basis == 'needs_area'
            items.append(dict(position=row.diagram_pos or (str(row.pos) if row.pos is not None else ''),
                name=row.name, unit=row.unit, state=state,
                detail=('Некорректное количество: проверьте исходные данные.' if state == 'invalid' else
                        '; '.join(filter(None, (row.note, row.quantity_source))) or
                        'Нужно количество и основание; автоматически не назначено.')))
        if items:
            groups.append(dict(title=section.title, items=items, count=len(items)))
    actions = []
    if needs_area:
        actions.append(dict(id='area', title='Указать общую площадь для предварительной оценки',
            fields=['building_area_m2'], note='Используется существующая оценка по площади. Это не обмер труб; метраж ГВС и вводов ею не заполняется.'))
    risers = [('v1-riser-valve', 'risers_v1'), ('t3-riser-valve', 'risers_t3'),
              ('t4-riser-valve', 'risers_t4')]
    keys = list(dict.fromkeys(key for ident, key in risers if ident in missing_ids))
    if keys:
        actions.append(dict(id='risers', title='Указать известное число стояков',
            fields=keys, note='В1, Т3 и Т4 задаются отдельно. Это заполнит количество арматуры, не метраж труб.'))
    if 'v1-sectional-valves' in missing_ids:
        actions.append(dict(id='sectional_valves', title='Уточнить секционные краны В1',
            fields=['v1_sectional_valves_count', 'v1_sectional_valves_basis'],
            note='Необязательно для расчёта и принципиальной схемы. Количество и основание по компоновке, без повторного учёта арматуры узлов.'))
    if any(ident.endswith(('-air-collector', '-air-isolation', '-air-vent', '-drain-valve')) for ident in missing_ids):
        actions.append(dict(id='service_nodes', title='Уточнить воздушные и спускные узлы',
            fields=['water_service_mode', *('water_service_' + s + '_' + p
                    for s in ('v1', 't3', 't4') for p in ('upper', 'lower'))],
            note='Можно принять по одному верхнему и нижнему узлу на стояк либо задать точки отдельно. Без выдуманного DN; расчёт и схема доступны.'))
    if any(ident.startswith('circulation-balance') for ident in missing_ids):
        actions.append(dict(id='balancing', title='Уточнить схему балансировки ГВС',
            fields=['hws_balance_mode', 'hws_balance_count', 'hws_balance_collector_count'],
            note='Количество по точкам подключения выбранной схемы; DN, Kv и настройки требуют расчёта колец.'))
    if any(ident.startswith(('apartment-v1-', 'apartment-t3-')) for ident in missing_ids):
        actions.append(dict(id='apartments', title='Уточнить число квартирных узлов',
            fields=['apartment_units_mode', 'apartment_units_cold_count', 'apartment_units_hot_count'],
            note='По одному на квартиру или явное количество. РД дополнительно требуют поэтажной ведомости.'))
    return dict(scope='ios2', state='reviewed', counts=counts, groups=groups, actions=actions, notice=NOTICE)


def water_spec_quantity_review(project):
    try:
        return review_spec_quantities(build_water_specification(project))
    except ValueError as exc:
        # SO input validation must not roll back a successfully calculated flow.
        # This is NOT an empty/complete review; PDF/release checks stay separate.
        return dict(scope='ios2', state='unavailable',
            notice='Проверка количеств не выполнена: ' + str(exc))
