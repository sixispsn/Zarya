"""Explicit architectural datums for a principle sheet, not a room layout solver."""
from copy import deepcopy


def from_model(model):
    if not model or 'location' not in model:
        return None
    from app.intake.studio_fire_station import _object, _number
    loc = _object(model['location'],
        'room_number room_name floor_elevation_m suction_nozzle_elevation_m inlet_elevations_m basis',
        'Привязка насосной')
    for key, maximum in (('room_number', 20), ('room_name', 48), ('basis', 1200)):
        value = loc[key]
        if (not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum
                or any(ord(c) < 32 for c in value)):
            raise ValueError(f'Привязка насосной: {key} — непустая строка до {maximum} символов')
    floor = _number(loc['floor_elevation_m'], 'Пол насосной')
    nozzle = _number(loc['suction_nozzle_elevation_m'], 'Ось всасывающих патрубков')
    if nozzle <= floor:
        raise ValueError('Ось всасывающих патрубков должна быть выше заданного пола насосной')
    if abs(nozzle-model['pump_axis_m']) > 1e-9:
        raise ValueError('Отметка всасывающих патрубков должна совпадать с расчётной осью насоса; '
                         'разноуровневые насосы эта модель не поддерживает')
    inlets = loc['inlet_elevations_m']
    names = {row['name'] for row in model['supplies']}
    if not isinstance(inlets, dict) or set(inlets) != names:
        raise ValueError('Привязка насосной: нужны отметки проходок ровно для двух заданных вводов')
    for feed in model['supplies']:
        z = _number(inlets[feed['name']], f"Проходка {feed['name']}")
        minimum_length = abs(feed['source_elevation_m']-z) + abs(z-nozzle)
        if sum(s['length_m'] for s in feed['segments']) + 1e-9 < minimum_length:
            raise ValueError(f"{feed['name']}: длина пути меньше перепада через заданную проходку")
    return deepcopy(loc)


def description(location):
    return f"Помещение {location['room_number']} · {location['room_name']}"
