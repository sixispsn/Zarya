"""Recompute isolated steady states against the signed Samara 1+1 design.

No runtime fixture, pump, apertures, legacy or website is rewritten.
PYTHONPATH=. venv/bin/python scripts/build_samara_repair_review.py
"""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_nomogram_flow import check_nomogram_operating_point
from app.calc.fire_pressure_flow import handbook_characteristic
from app.calc.fire_repair_flow import RepairNetwork, check_repair_operating_point
from app.calc.ring_hydraulics import find_single_cycle
from app.pz.fire_station_binding import digest, input_signature
from app.intake.yaml_io import load_request
from app.intake.project_builder import build_project
from app.pz.geometry_builder import build_network
from scripts.build_samara_section_study import make_fire_station
from scripts.build_samara_fire_flow_review import floor_network

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'output/pdf/samara-section-3-2/repair'
BASELINE = ROOT/'demo/archive/samara_station_review.pre-repair-2026-10-05.json'
BASELINE_SNAPSHOT = '28a56387b48f45a4e6ba4f61e67b88a1e555c1950a3f18ec993af5dfe1b18190'


def load_repair_baseline():
    """Historical inputs, not permission to reuse their old successful outputs."""
    data=json.loads(BASELINE.read_text())
    if data['payload_sha256']!=BASELINE_SNAPSHOT or digest(data['payload'])!=BASELINE_SNAPSHOT:
        raise ValueError('Repair baseline was changed; historical comparison invalid')
    return data


def calculate_repair_review(*, offsets=(0., -2., 2.), apertures_override=None, include_intact=False):
    signed = load_repair_baseline(); payload = signed['payload']; adopted = payload['result']
    basis = payload['basis']; station = make_fire_station(basis)
    project = build_project(load_request(payload['request_yaml']))
    base = build_network(project)
    chars = [handbook_characteristic(c,hose_material='rubber_lined',nozzle_kind='non_shutoff') for c in base.cabinets]
    baseline_layout = {int(k):v for k,v in adopted['nominal_apertures_mm'].items()}
    layout = dict(baseline_layout if apertures_override is None else apertures_override)
    from app.data.fire_diaphragm_nomogram import APOGEY_SOURCE
    if (set(layout)!=set(baseline_layout) or
            any(type(f) is not int or d not in APOGEY_SOURCE['apertures_mm'] for f,d in layout.items())):
        raise ValueError('Explicit aperture for every existing diaphragm floor, from the documented size list, required')
    if not offsets or 0. not in offsets or len(set(offsets))!=len(offsets):
        raise ValueError('Unique axis offsets including nominal zero required')
    res = adopted['pipework']['resistances_m_per_lps2']
    curve = adopted['pump']['curve']
    floors = basis['study_assumptions']['residential_floors']
    height = basis['study_assumptions']['floor_to_floor_m']
    supplies = [dict(name=s.name,static_min=s.guaranteed_head_m+s.source_elevation_m-station.pump_axis_m,
        static_max=s.maximum_head_m+s.source_elevation_m-station.pump_axis_m,
        resistance=sum(p.A*p.effective_length_m for p in s.segments)) for s in station.supplies]
    if len(supplies)!=2 or len(base.cabinets)!=2:
        raise ValueError('This review expects the signed two-supply, two-riser study')
    # Samara has identical inlets. General cases require enumerating unequal
    # Q-dependent supply envelopes; do not choose one by name or nominal Q.
    if len({(s['static_min'],s['static_max'],s['resistance']) for s in supplies})!=1:
        raise ValueError('Separate envelope needed for unequal external supplies')
    common = supplies[0]
    cases = []
    if include_intact:
        cases.append(dict(id='intact',label='Кольцо целое, оба выхода НУ',kind='intact',
            closed_segments=[],closed_ports=[]))
    for failed in (0,1):
        remaining = supplies[1-failed]
        cases.append(dict(id=f'external-{failed+1}',label=f'Наружный ввод {failed+1} отключён',
            kind='external_inlet',closed_segments=[],closed_ports=[],
            boundaries=[('guaranteed_single_supply',remaining['static_min'],remaining['resistance']),
                        ('maximum_single_supply',remaining['static_max'],remaining['resistance'])]))
    for idx,port in enumerate((base.source,base.second_source),1):
        cases.append(dict(id=f'header-{idx}',label=f'Выход НУ {idx} в кольцо отключён',
            kind='header_port',closed_segments=[],closed_ports=[port.node_id]))
    cycle = find_single_cycle(base)
    if cycle is None: raise ValueError('Expected explicit source ring')
    for seg in sorted(cycle[1],key=lambda s:s.segment_id):
        cases.append(dict(id=seg.segment_id,label=f'{seg.from_node} - {seg.to_node}',
            kind='ring_segment',section_id=seg.repair_section_id,
            closed_segments=[seg.segment_id],closed_ports=[]))
    for case in cases:
        if 'boundaries' not in case:
            case['boundaries']=[('guaranteed_single_supply_bound',common['static_min'],common['resistance']),
                                ('maximum_no_supply_loss_bound',common['static_max'],0.)]
        variants=[]
        for offset in offsets:
            scenarios=[]
            for a in range(1,floors+1):
                for b in range(1,floors+1):
                    net=floor_network(base,(a,b),height)
                    apertures={c.cabinet_id:layout[f] for c,f in zip(chars,(a,b)) if f in layout}
                    for boundary,hs,r in case['boundaries']:
                        kwargs=dict(suction_static_head_m=hs,supply_resistance=r,
                            apertures_mm=apertures,axis_offset_px=offset,
                            station_suction_resistance=res['suction'],station_discharge_resistance=res['discharge'])
                        if case['kind'] in ('external_inlet','intact'):
                            result=check_nomogram_operating_point(net,chars,curve,**kwargs)
                        else:
                            result=check_repair_operating_point(net,chars,curve,
                                closed_segment_ids=case['closed_segments'],closed_port_ids=case['closed_ports'],**kwargs)
                        scenarios.append(dict(floors=[a,b],boundary=boundary,result=asdict(result)))
            solved=[s for s in scenarios if s['result']['operating'] is not None]
            rows=[(s,c) for s in solved for c in s['result']['operating']['cabinets']]
            counts=dict(Counter(s['result']['status'] for s in scenarios))
            worst=min(rows,key=lambda sc:sc[1]['outlet_head_m']-sc[1]['minimum_head_m']) if rows else None
            variants.append(dict(axis_offset_px=offset,scenario_count=len(scenarios),summary=counts,
                all_minima_met=counts=={'meets_minimum':len(scenarios)},
                complete=len(solved)==len(scenarios),
                all_dynamic_limits_met=len(solved)==len(scenarios) and all(c['outlet_head_m']/MPA_TO_M<=.45 for _,c in rows),
                pressure_range_mpa=[min(c['outlet_head_m']/MPA_TO_M for _,c in rows),
                                    max(c['outlet_head_m']/MPA_TO_M for _,c in rows)] if rows else None,
                flow_range_m3h=[min(s['result']['pump_flow_m3h'] for s in solved),
                               max(s['result']['pump_flow_m3h'] for s in solved)] if solved else None,
                worst=dict(floors=worst[0]['floors'],boundary=worst[0]['boundary'],cabinet=worst[1],
                    pump_flow_m3h=worst[0]['result']['pump_flow_m3h'],pump_head_m=worst[0]['result']['pump_head_m']) if worst else None,
                scenarios=scenarios))
        case['variants']=variants
    failed = next(c for c in cases if c['id']=='header-1')
    nominal = next(v for v in failed['variants'] if v['axis_offset_px']==0)
    worst = nominal['worst']; net = floor_network(base,worst['floors'],height)
    apertures = {c.cabinet_id:layout[f] for c,f in zip(chars,worst['floors']) if f in layout}
    args = dict(suction_static_head_m=common['static_min'],supply_resistance=common['resistance'],
        apertures_mm=apertures,station_suction_resistance=res['suction'],station_discharge_resistance=res['discharge'])
    comparisons=[]
    for kind, result in [('intact',check_nomogram_operating_point(net,chars,curve,**args)),
                         ('header_1_closed',check_repair_operating_point(net,chars,curve,closed_port_ids=failed['closed_ports'],**args))]:
        total=result.pump_flow_m3h/3.6
        comparisons.append(dict(kind=kind,result=asdict(result),external_loss_m=common['resistance']*total**2,
            station_suction_loss_m=res['suction']*total**2,station_discharge_loss_m=res['discharge']*total**2))
    repaired=comparisons[1]['result']['operating']
    network_audit=RepairNetwork(net,closed_port_ids=failed['closed_ports']).solve(
        {c['cabinet_id']:c['flow_lps'] for c in repaired['cabinets']},repaired['header_head_m'])
    return dict(method='L06 explicit single isolation; steady-state repair extension',
        baseline_snapshot=signed['payload_sha256'],pump=adopted['pump'],apertures_mm=layout,
        project_input_sha256=input_signature(project,station),
        baseline_apertures_mm=baseline_layout,
        pipework_resistances=res,duty_pumps=1,reserve_pumps=1,reserve_in_flow_sum=False,
        supplies=supplies,cases=cases,comparison=dict(floors=worst['floors'],cases=comparisons,
            repair_network=asdict(network_audit)),
        all_model_minima_met=all(v['all_minima_met'] for c in cases for v in c['variants']),
        all_model_dynamic_limits_met=all(v['all_dynamic_limits_met'] for c in cases for v in c['variants']),
        nominal_static_lowest_pc_mpa=adopted['nominal_static_lowest_pc_mpa'],
        normative_sectioning_confirmed=False,room_coverage_confirmed=False,release_ready=False,
        retained_limits=[
            'После изоляции: без расхода утечки, гидроудара и переходного процесса включения резерва.',
            'Отключение трубного сегмента не подтверждает границы реальной ремонтной секции и размещение задвижек.',
            'Два представительных стояка, не проверка всех ПК и покрытия помещений здания.',
            'Для повреждения кольца минимум оценён при полном расходе одного наружного ввода; максимум - без потерь наружных подводов.',
            'Hmax=35 м и обвязка - прежние учебные допущения; +/-2 px - чувствительность номограммы, не допуски изделия.',
            ('Насос и отверстия диафрагм не менялись; каталог и legacy сохранены.' if layout==baseline_layout else
             'Изменены только явно указанные отверстия; насос, обвязка, трубы, каталог и legacy сохранены.'),
        ],engine_sha256={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in (
            'app/calc/fire_repair_flow.py','scripts/build_samara_repair_review.py')})


def main():
    from app.pz.fire_repair_review_report import render_repair_review
    result=calculate_repair_review()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'repair-review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    path=render_repair_review(OUTPUT/'В2_Самара_ремонтные_режимы.pdf',result)
    print(json.dumps(dict(pdf=path,all_model_minima_met=result['all_model_minima_met'],cases=[dict(
        label=c['label'],variants=[dict(offset=s['axis_offset_px'],summary=s['summary']) for s in c['variants']])
        for c in result['cases']]),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
