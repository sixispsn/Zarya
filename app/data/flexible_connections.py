"""Exact catalogue dimensions; no hose/seismic capacity inferred from DN."""
import json
from pathlib import Path


def flexible_catalogue_items():
    from app.data.engineering_catalogue import CatalogueItem, CataloguePort, freeze
    raw = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    expected = ['dn','D10','D16','C10','C16','L','T','n10','n16','H10','H16']
    if raw['columns'] != expected:
        raise ValueError('Неизвестная размерная схема гибких соединений')
    items = []
    for values in raw['dimensions']:
        if len(values) != len(expected):
            raise ValueError('Неполная размерная строка гибкого соединения')
        row = dict(zip(expected, values))
        dn = row['dn']
        for pn, series in ((10,500),(16,501)):
            candidates = [v for v in raw['movements'][str(pn)] if v[0] <= dn <= v[1]]
            if len(candidates) != 1:
                raise ValueError('Нет однозначной паспортной строки перемещений')
            movement = dict(zip(raw['movement_columns'][2:], candidates[0][2:]))
            if any(type(v) not in (int,float) or v <= 0 for v in movement.values()):
                raise ValueError('Неверные перемещения')
            dims = {'L':row['L'], 'D':row[f'D{pn}'], 'T':row['T']}
            ports = tuple(CataloguePort(n,'flanged',dn, standard='ГОСТ 33259-2015',
                bolt_circle_mm=row[f'C{pn}'], bolt_count=row[f'n{pn}'], bolt_hole_mm=row[f'H{pn}'])
                for n in ('in','out'))
            items.append(CatalogueItem(f'rushwork-{series}-dn{dn}', f'rushwork-{series}',
                'flexible_connection', f'РАШВОРК {series} DN{dn} PN{pn}',
                (raw['source_id'],), 'Паспорт, с. 2–3: перемещения/размеры; с. 4–8: монтаж',
                'verified', freeze(dims), ports,
                dimension_meanings=freeze({'L':'Свободная осевая длина, не монтажная после предварительного сжатия',
                                          'D':'Наружный диаметр фланца', 'T':'Толщина фланца'}),
                manufacturer='РАШВОРК', article=f'{series}-{dn:03d}-{pn}-EPDM-FF', material='epdm',
                pn_bar=pn, temperature_c=tuple(raw['requirements']['working_temperature_c']),
                notes=tuple(raw['requirements']['notes']),
                native=freeze({'revision':raw['revision'], 'movement_limits':movement,
                               'requirements':raw['requirements']})))
    return {raw['source_id']: raw['source']}, tuple(items)
