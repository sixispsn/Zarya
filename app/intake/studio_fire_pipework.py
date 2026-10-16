"""Explicit schema-3 station layout composed with the approved pipework solver.

No defaults from the study object. Quantities distinguish one active hydraulic
path from two installed pump branches. Auxiliary paths are closed to water in
the fire duty; their test/drain operating regimes are NOT solved here.
"""
from math import isfinite

from app.calc.fire_station_pipework import PipeworkElement, StationPipework
from app.data.pipe_catalog import STEEL_VGP_ORDINARY, steel_vgp_ordinary

# role: side, installed quantity multiplier, method, description
ROLES = {
    'suction_header': ('suction', 1, 'A_L', 'Всасывающий коллектор'),
    'suction_branch': ('suction', 2, 'A_L', 'Всасывающая ветвь насоса'),
    'suction_valve': ('suction', 2, 'Kv', 'Запорная арматура на всасывании'),
    'suction_fittings': ('suction', 2, 'zeta', 'Фасонные части всасывающей ветви'),
    'discharge_header': ('discharge', 1, 'A_L', 'Напорный коллектор'),
    'discharge_branch': ('discharge', 2, 'A_L', 'Напорная ветвь насоса'),
    'discharge_valve': ('discharge', 2, 'Kv', 'Запорная арматура на напоре'),
    'discharge_check': ('discharge', 2, 'Kv', 'Обратный клапан на напоре'),
    'discharge_fittings': ('discharge', 2, 'zeta', 'Фасонные части напорной ветви'),
}
CONNECTIONS = {'drain': 'Спускной кран', 'air': 'Воздухоотводчик', 'test': 'Испытательный отвод с запорной арматурой'}
BOUNDARY = 'separate_station_pipework_excluded_from_supplies_and_network'


def parse_pipework(value):
    from app.intake.studio_fire_station import _object, _number, _rows
    keys = 'basis material elements connections'
    if isinstance(value, dict) and 'fittings_scope' in value: keys += ' fittings_scope'
    p = _object(value, keys, 'Обвязка')
    if not isinstance(p['basis'], str) or not 1 <= len(p['basis'].strip()) <= 1200:
        raise ValueError('Обвязка: нужно явное основание геометрии и сопротивлений')
    if p['material'] != 'steel_vgp_ordinary':
        raise ValueError('Обвязка: пока поддержаны только стальные ВГП обыкновенные трубы; иной материал не подменяется')
    rows = _rows(p['elements'], 'Обвязка', len(ROLES), len(ROLES))
    if any(not isinstance(r, dict) or not isinstance(r.get('role'), str) for r in rows):
        raise ValueError('Обвязка: нужны именованные элементы')
    if {r['role'] for r in rows} != set(ROLES):
        raise ValueError('Обвязка: каждый коллектор, ветвь, арматура и местные сопротивления задаются один раз')
    elements, by_role = [], {r['role']:r for r in rows}
    for r in rows:
        side, _, method, name = ROLES[r['role']]
        keys = 'role dn value basis' + (' length_m' if method == 'A_L' else '')
        _object(r, keys, name)
        if type(r['dn']) is not int or r['dn'] not in STEEL_VGP_ORDINARY:
            raise ValueError(f'{name}: DN отсутствует в сортаменте')
        if not isinstance(r['basis'], str) or not 1 <= len(r['basis'].strip()) <= 400:
            raise ValueError(f'{name}: нужно основание коэффициента')
        _number(r['value'], name, positive=True)
        if method == 'A_L': _number(r['length_m'], name, positive=True)
        if not r['role'].endswith(('header', 'branch')) and r['dn'] != by_role[f'{side}_branch']['dn']:
            raise ValueError(f'{name}: DN должен совпадать с DN ветви')
        elements.append(PipeworkElement(r['role'], name, side, r['dn'], 1, method,
            r['value'], r['basis'], length_m=r.get('length_m', 0.),
            inner_mm=steel_vgp_ordinary(r['dn']).inner_mm))
    if 'fittings_scope' in p:
        from app.intake.studio_fire_fittings import validate_scope
        validate_scope(p['fittings_scope'], by_role)
    seen = set()
    for c in _rows(p['connections'], 'Вспомогательные подключения', 0, 5):
        _object(c, 'kind at dn destination basis', 'Подключение')
        if (not isinstance(c['kind'], str) or not isinstance(c['at'], str)
                or c['kind'] not in CONNECTIONS or c['at'] not in ('suction_header','discharge_header')
                or (c['kind'] == 'test' and c['at'] != 'discharge_header')):
            raise ValueError('Подключение: спуск/воздух на коллекторе, испытательный отвод только на напоре')
        key = (c['kind'], c['at'])
        if key in seen: raise ValueError('Подключение повторяется')
        seen.add(key)
        if type(c['dn']) is not int or c['dn'] not in STEEL_VGP_ORDINARY or c['dn'] > by_role[c['at']]['dn']:
            raise ValueError('Подключение: DN должен принадлежать сортаменту и не превышать коллектор')
        for field in ('destination','basis'):
            if not isinstance(c[field], str) or not 1 <= len(c[field].strip()) <= 200:
                raise ValueError('Подключение: нужны место назначения и основание')
    result = StationPipework(tuple(elements), p['basis'])
    try:
        resistances = result.resistances()
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError('Обвязка: сопротивление вне числового диапазона') from exc
    if not all(isfinite(r) for r in resistances.values()):
        raise ValueError('Обвязка: сопротивление должно быть конечным')
    return result


def from_model(model):
    return parse_pipework(model['pipework']) if model and model.get('schema_version') == 3 else None


def connection_rows(model):
    """Stable positions shared by the sheet and specification, no implied routes."""
    p = from_model(model)
    if p is None: return []
    prefixes = {'drain':'СК', 'air':'ВО', 'test':'ИО'}
    return [dict(c, id=prefixes[c['kind']]+('1' if c['at']=='suction_header' else '2'),
                 name=CONNECTIONS[c['kind']]) for c in model['pipework']['connections']]
