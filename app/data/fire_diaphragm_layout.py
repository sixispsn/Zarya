"""Consecutive equal apertures for presentation, never an engineering default."""
from math import isfinite


def diaphragm_groups(apertures):
    pairs=sorted((int(f),float(d)) for f,d in apertures.items())
    if len({f for f,d in pairs})!=len(pairs) or any(f<1 or not isfinite(d) or d<=0 for f,d in pairs):
        raise ValueError('Unique positive floors and apertures required')
    groups=[]
    for floor,diameter in pairs:
        if groups and floor==groups[-1]['end']+1 and diameter==groups[-1]['aperture_mm']:
            groups[-1]['end']=floor
        else:
            groups.append(dict(start=floor,end=floor,aperture_mm=diameter))
    return groups


def floor_label(group):
    return str(group['start']) if group['start']==group['end'] else f"{group['start']}-{group['end']}"
