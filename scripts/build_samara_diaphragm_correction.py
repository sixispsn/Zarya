"""Explicit Samara revision: unchanged pump/pipes, floor 15 only, all modes.

Not a universal optimiser: fixed, disclosed trials of neighbouring apertures.
Historical baseline is preserved and every candidate is freshly recomputed.
"""
from copy import deepcopy

from scripts.build_samara_repair_review import calculate_repair_review, load_repair_baseline


def compact_review(r):
    out=deepcopy(r)
    for case in out['cases']:
        for v in case['variants']:v.pop('scenarios',None)
    return out


def calculate_correction():
    baseline=load_repair_baseline()
    old={int(f):d for f,d in baseline['payload']['result']['nominal_apertures_mm'].items()}
    trials=[];selected=None
    # No guessed coefficients or pipe diameter changes to force the result.
    for scope,diameter in [('group',20.),('group',20.5),('group',21.),
                           ('floor15',20.),('floor15',20.5),('floor15',21.)]:
        layout={f:(diameter if (f>=13 if scope=='group' else f==15) else d) for f,d in old.items()}
        r=calculate_repair_review(apertures_override=layout,include_intact=True)
        variants=[v for c in r['cases'] for v in c['variants']]
        trials.append(dict(scope=scope,diameter_mm=diameter,
            all_minima_met=r['all_model_minima_met'],all_dynamic_limits_met=r['all_model_dynamic_limits_met'],
            passed=sum(v['summary'].get('meets_minimum',0) for v in variants),
            total=sum(v['scenario_count'] for v in variants),
            minimum_pressure_mpa=min(v['pressure_range_mpa'][0] for v in variants),
            maximum_pressure_mpa=max(v['pressure_range_mpa'][1] for v in variants)))
        if scope=='floor15' and diameter==21.:
            selected=r
    if not selected['all_model_minima_met'] or not selected['all_model_dynamic_limits_met']:
        raise ValueError('Proposed 21 mm floor-15 correction failed; no automatic alternative adopted')
    selected['correction']=dict(changed_floors=[15],old_mm=old[15],new_mm=21.,trials=trials,
        decision='21 мм только на этаже 15; 20,5 мм формально проходит, но запас модели почти нулевой. '
                 'Это проектный выбор среди проверенных размеров, не нормативный коэффициент запаса.',
        product_tolerances_verified=False,full_building_quantity_confirmed=False)
    return selected


if __name__=='__main__':
    import json
    from scripts.build_samara_repair_review import OUTPUT
    r=calculate_correction();OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'diaphragm-correction.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps(r['correction'],ensure_ascii=False,indent=2))
