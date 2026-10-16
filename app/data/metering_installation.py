"""Reviewed installation profiles, independent of legacy hydraulic sizing."""
from dataclasses import replace
import json
from math import isfinite
from pathlib import Path
from types import MappingProxyType


ORIENTATIONS = ("horizontal_dial_up", "vertical_up", "vertical_down")


def apply_installation_profiles(products, sources):
    from app.data.engineering_catalogue import freeze
    raw = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    seen = set()
    for profile in raw['profiles']:
        if profile['source_id'] not in sources or not profile['reference']:
            raise ValueError('Нет источника монтажного профиля')
        if not profile['allowed'] or not set(profile['allowed']) <= set(ORIENTATIONS):
            raise ValueError('Неизвестная ориентация монтажного профиля')
        for dn in profile['dns']:
            ident = profile['prefix'] + str(dn)
            if ident in seen or ident not in products:
                raise ValueError('Неизвестное/повторное изделие монтажного профиля: ' + ident)
            seen.add(ident)
            p = products[ident]
            if profile['source_id'] not in p.source_ids:
                raise ValueError('Профиль не относится к паспорту изделия: ' + ident)
            flows = dict(p.flows_m3h)
            if profile.get('qmin_A'):
                qmin = profile['qmin_A'][str(dn)]
                if type(qmin) not in (int, float) or not isfinite(qmin) or qmin <= 0:
                    raise ValueError('Неверный паспортный Qmin: ' + ident)
                flows['qmin_A'] = qmin
            minima = {}
            for orientation, cls in profile['classes'].items():
                if orientation not in profile['allowed'] or 'qmin_' + cls not in flows:
                    raise ValueError('Нет паспортного минимума монтажного профиля: ' + ident)
                minima[orientation] = {'class':cls, 'qmin_m3h':flows['qmin_' + cls]}
            products[ident] = replace(p, flows_m3h=MappingProxyType(flows), installation=freeze({
                'revision':raw['revision'], 'source_id':profile['source_id'],
                'reference':profile['reference'], 'allowed':profile['allowed'],
                'minima':minima, 'conditions':profile['conditions'],
            }))
    return raw['revision']
