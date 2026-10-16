"""Explicit support points and conservative removal coverage on MeteringChain.

No equal division of total mass, no automatic pair of stands, no beam/anchor
calculation. Graph coverage is necessary but NEVER proof of stability.
"""
from math import isfinite
from app.data.metering_supports import PRODUCTS, fingerprint

# Bind only to permanent pipe nodes, never to a meter/valve body or a union.
POINTS = {
    'inlet': ('ОП1', 'Труба до узла', 'inlet', 'inlet'),
    'outlet': ('ОП2', 'Труба после узла', 'outlet', 'outlet'),
    'bypass': ('ОП3', 'Труба обводной до арматуры', 'bypass_route_in', 'bypass'),
    'bypass_after': ('ОП4', 'Труба обводной после арматуры', 'bypass_route_out', 'bypass'),
}


def validate_supports(points):
    errors = []
    if not isinstance(points, dict) or len(points) > len(POINTS):
        return ['supports: требуется словарь точек опор']
    allowed = {'product_id', 'fingerprint', 'basis', 'height_mm', 'reaction_n',
               'reaction_basis', 'load_case', 'foundation_basis'}
    for key, row in points.items():
        if key not in POINTS or not isinstance(row, dict):
            errors.append('supports: неизвестная точка или формат')
            continue
        if set(row) - allowed:
            errors.append(f'supports.{key}: неизвестные поля')
        for name in ('product_id', 'fingerprint', 'basis'):
            if not isinstance(row.get(name), str) or not row[name].strip():
                errors.append(f'supports.{key}.{name}: требуется непустая строка')
        for name in ('reaction_basis', 'foundation_basis'):
            if name in row and not isinstance(row[name], str):
                errors.append(f'supports.{key}.{name}: требуется строка')
        for name in ('height_mm', 'reaction_n'):
            v = row.get(name)
            if v is not None and (type(v) not in (int, float) or not isfinite(v) or v <= 0):
                errors.append(f'supports.{key}.{name}: нужно положительное конечное число')
        if row.get('reaction_n') is not None and (not isinstance(row.get('reaction_basis'), str)
                                                or not row['reaction_basis'].strip()):
            errors.append(f'supports.{key}: требуется основание нагрузки')
        if row.get('load_case', 'unknown') not in ('unknown', 'center', 'end'):
            errors.append(f'supports.{key}: неизвестная схема нагрузки')
    return errors


def studio_supports(values):
    """Only explicitly selected points, not a product-wide installation default."""
    result = {}
    for key in POINTS:
        product = values.get(f'vu_support_{key}')
        if not product or product == 'none':
            continue
        if product not in PRODUCTS:
            raise ValueError('Неизвестная опора ВУ')
        row = dict(product_id=product, fingerprint=fingerprint(product),
                   basis='Точка постоянной опоры явно выбрана пользователем в Studio')
        height = values.get('vu_support_height_mm')
        if height is not None and PRODUCTS[product].kind == 'floor_stand':
            row['height_mm'] = height
        result[key] = row
    return result


def support_report(project, state=None, *, chain=None):
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_rules import special_layout_pending
    d = project.metering_detail
    state = state or drawing_state(project)
    if chain is None:
        selected = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                            electric_bypass=state.electric_bypass)
        chain = build_metering_chain(d, state, selected)
    errors = validate_supports(d.mounting.supports)
    if d.mounting.supports and d.mounting.support_count is not None:
        errors.append('Нельзя одновременно задавать точки и общее количество опор')
    ids = {n.id for n in chain.nodes}
    rows = []
    if not errors:
        for key, point in POINTS.items():
            row = d.mounting.supports.get(key)
            if row is None:
                continue
            mark, title, node, pipe_role = point
            product = PRODUCTS.get(row['product_id'])
            bad, pending = [], []
            if node not in ids:
                bad.append('Участок отсутствует в текущей схеме')
            if product is None:
                bad.append('Неизвестное изделие')
            elif row['fingerprint'] != fingerprint(product.id):
                bad.append('Редакция изделия изменилась; повторите выбор')
            if product and d.russian_equipment_only and product.country != 'RU':
                bad.append('Российское происхождение не подтверждено')
            pipe = d.pipe_sections.get(pipe_role)
            dn = (d.bypass_dn if pipe_role == 'bypass' else d.inlet_dn if pipe_role == 'inlet'
                  else pipe.nominal_dn if pipe else None)
            if pipe and pipe.validate():
                bad.extend(pipe.validate())
            if pipe and pipe.nominal_dn is not None and dn is not None and pipe.nominal_dn != dn:
                bad.append('DN местной трубы расходится с текущей схемой')
            if product and product.dn is not None:
                if dn is None:
                    pending.append('DN трубы в точке крепления не задан')
                elif dn != product.dn:
                    bad.append(f'Опора DN{product.dn} не подходит к DN{dn}')
            if not pipe or pipe.outer_diameter_mm is None or pipe.material == 'unknown':
                pending.append('Нужны наружный диаметр, материал и местный узел крепления трубы')
            else:
                from app.pz.metering_pipes import MATERIALS
                pending.append(f'Проверить контакт/охват трубы Dн={pipe.outer_diameter_mm:g} мм, материал {MATERIALS[pipe.material]}')
            if product and product.kind == 'floor_stand':
                pending.append('Допустимая нагрузка и диапазон наружных диаметров в паспорте стойки не приведены')
                if d.assembly_orientation != 'horizontal_dial_up':
                    bad.append('Напольная стойка горизонтальной трубы не применена к вертикальному ВУ')
                height = row.get('height_mm')
                if height is None:
                    pending.append('Высота стойки от пола не задана')
                elif not product.height_range_mm[0] <= height <= product.height_range_mm[1]:
                    bad.append('Высота вне опубликованного диапазона стойки')
            limit = None
            if product and product.kind == 'wall_console':
                case = row.get('load_case', 'unknown')
                limit = product.center_load_n if case == 'center' else product.end_load_n if case == 'end' else None
                if case == 'unknown':
                    pending.append('Уточнить схему нагрузки: вертикальная сила в L/2 или L')
                pending.append('Подобрать хомут, соединение с консолью и анкеры')
                if d.assembly_orientation != 'horizontal_dial_up':
                    pending.append('Осевое удержание вертикальной трубы не подтверждено консолью')
            load = row.get('reaction_n')
            load_status = 'needs_data'
            if load is None:
                pending.append('Нагрузка на эту опору с водой и при обслуживании не задана')
            elif limit is None:
                pending.append('Нет применимого опубликованного предела нагрузки')
            elif load > limit:
                bad.append(f'Нагрузка {load:g} Н превышает табличную {limit:g} Н')
                load_status = 'overload'
            else:
                load_status = 'component_limit_only'
            pending.append('Проверить основание, анкеры, перемещения и устойчивость всей конструкции')
            if special_layout_pending(project):
                pending.append('Особые условия объекта: требуется отдельное решение опор/перемещений')
            rows.append(dict(key=key, mark=mark, title=title, node=node, product=product,
                             basis=row['basis'], height_mm=row.get('height_mm'),
                             reaction_n=load, load_limit_n=limit, load_status=load_status,
                             errors=bad, pending=pending, active=not bad,
                             quantity=chain.instances if not bad else None,
                             status='incompatible' if bad else 'preliminary'))
    # Remove the actual component, then inspect the remaining undirected graph.
    # The bypass connects only while present; boundaries are NOT implicit supports.
    anchors = {r['node'] for r in rows if r['active']}
    scenarios = []
    targets = ('meter', 'filter', 'check_valve', 'valve_before', 'valve_after',
               'inlet_valve', 'outlet_valve', 'bypass_valve')
    for target in targets:
        if target not in ids:
            continue
        remaining = ids - {target}
        adjacency = {n: set() for n in remaining}
        for a, b in chain.links:
            if a in remaining and b in remaining:
                adjacency[a].add(b); adjacency[b].add(a)
        components = []
        while remaining:
            todo = [min(remaining)]; group = set()
            while todo:
                node = todo.pop()
                if node in group:
                    continue
                group.add(node); todo.extend(adjacency[node] - group)
            remaining -= group
            components.append(sorted(group))
        uncovered = [c for c in components if not anchors.intersection(c)]
        scenarios.append(dict(target=target, title=chain.node(target).title, uncovered=uncovered,
            coverage='uncovered' if uncovered else 'points_present', stability_confirmed=False))
    return dict(rows=rows, errors=errors, scenarios=scenarios, instances=chain.instances,
                installation_ready=False, safe_to_remove=False)


def support_spec_rows(report):
    from app.pz.spec import SpecRow
    rows = []
    for r in report['rows']:
        p = r['product'] if r['active'] else None
        rows.append(SpecRow(1, ('Стойка ВУ' if p and p.kind == 'floor_stand' else 'Консоль крепления ВУ' if p else 'Опора ВУ')
            + ' - ' + r['title'], type_mark=p.title if p else '', manufacturer=p.manufacturer if p else '',
            unit='шт.', qty=r['quantity'], note='Предварительно; нагрузку и крепление проверить. '
                + ('Комплект изготовителя; крепёж повторно не считать.' if p and p.kind == 'floor_stand'
                   else 'Хомуты и анкеры отдельно.' if p else '; '.join(r['errors'])),
            diagram_pos=r['mark'], component_ids=('support_' + r['key'],),
            catalogue_id=p.id if p else '', quantity_basis='explicit_vu_support_points',
            quantity_source=(f"1 на узел × {report['instances']} узлов; {r['basis']}" if p else 'Изделие не допущено')))
        if p and p.kind == 'wall_console':
            rows.append(SpecRow(1, 'Хомут, соединители и анкеры опоры ' + r['mark'],
                unit='компл.', qty=None, note='Не входят в выбранную консоль; подобрать по трубе и основанию.',
                diagram_pos=r['mark'] + '.К', component_ids=('support_fixings_' + r['key'],),
                quantity_basis='metering_special_requirement'))
    if report['errors']:
        rows.append(SpecRow(1, 'Опоры ВУ - исправить исходные данные', unit='компл.', qty=None,
                            note='; '.join(report['errors']), quantity_basis='metering_special_requirement'))
    return rows
