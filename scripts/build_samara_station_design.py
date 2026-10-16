"""Stage-P station decision, explicitly preliminary, no external correspondence.

PYTHONPATH=. venv/bin/python scripts/build_samara_station_design.py
This annex does not overwrite the historical fixed-flow full Samara packages.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json

from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_nomogram_flow import check_nomogram_operating_point
from app.calc.fire_pressure_flow import handbook_characteristic
from app.calc.fire_station_documents import review_station_documents
from app.calc.fire_station_pipework import station_curve_samples
from app.data.fire_station_design import samara_pipework, AUTOMATION_ASSIGNMENT, SAMARA_PIPEWORK_APERTURES_MM
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from scripts.build_samara_diaphragm_apertures import calculate_apertures
from scripts.build_samara_fire_flow_review import floor_network
from scripts.build_samara_section_study import ROOT, OUTPUT, load_basis, make_draft, make_request, make_fire_station
from scripts.build_samara_station_passport import verify_sources


def calculate_station_design(basis, bundle, apertures=None, *, layout_override=None):
    station=make_fire_station(basis)
    if apertures is None:
        apertures=calculate_apertures(basis,bundle)
    previous=review_station_documents(basis,bundle.fire_station_result,station,apertures)
    pipework=samara_pipework();res=pipework.resistances()
    base=bundle.fire_station_result.network
    chars=[handbook_characteristic(c,hose_material='rubber_lined',nozzle_kind='non_shutoff') for c in base.cabinets]
    pump=deepcopy(previous['candidate'])
    floors=basis['study_assumptions']['residential_floors']
    height=basis['study_assumptions']['floor_to_floor_m']
    old_layout=previous['nominal_apertures_mm']
    layout=deepcopy(SAMARA_PIPEWORK_APERTURES_MM if layout_override is None else layout_override)
    from app.data.fire_diaphragm_nomogram import APOGEY_SOURCE
    if set(layout)!=set(SAMARA_PIPEWORK_APERTURES_MM) or any(d not in APOGEY_SOURCE['apertures_mm'] for d in layout.values()):
        raise ValueError('Explicit existing diaphragm floors and documented aperture sizes required')
    if floors!=16:
        raise ValueError('The explicitly adopted diaphragm layout is for this 16-floor case only')
    source=station.supplies[0]
    external_r=sum(s.A*s.effective_length_m for s in source.segments)
    variants=[]
    configurations=[('previous_layout_with_pipework',1.,0.,old_layout)] + [
        ('adopted_layout',scale,offset,layout) for scale in (0.,1.,2.) for offset in (0.,-2.,2.)]
    for layout_name,scale,offset,active_layout in configurations:
        scenarios=[]
        for a in range(1,floors+1):
            for b in range(1,floors+1):
                net=floor_network(base,(a,b),height)
                holes={c.cabinet_id:active_layout[f] for c,f in zip(chars,(a,b)) if f in active_layout}
                for boundary,hs,r in [('one_supply_guaranteed',previous['suction_static_min_m'],external_r),
                        ('maximum_head_no_supply_loss_bound',previous['suction_static_max_m'],0.)]:
                    out=check_nomogram_operating_point(net,chars,pump['curve'],
                        suction_static_head_m=hs,supply_resistance=r,apertures_mm=holes,
                        axis_offset_px=offset,station_suction_resistance=res['suction']*scale,
                        station_discharge_resistance=res['discharge']*scale)
                    scenarios.append(dict(floors=[a,b],boundary=boundary,result=asdict(out)))
        solved=[s for s in scenarios if s['result']['operating'] is not None]
        rows=[c for s in solved for c in s['result']['operating']['cabinets']]
        counts=dict(Counter(s['result']['status'] for s in scenarios))
        complete=len(solved)==len(scenarios)
        variants.append(dict(layout=layout_name,loss_scale=scale,axis_offset_px=offset,scenarios=scenarios,
            summary=counts,scenario_count=len(scenarios),complete=complete,
            all_minima_met=complete and counts=={'meets_minimum':len(scenarios)},
            all_dynamic_limits_met=complete and all(c['outlet_head_m']/MPA_TO_M<=.45 for c in rows),
            pressure_range_mpa=[min(c['outlet_head_m']/MPA_TO_M for c in rows),
                                max(c['outlet_head_m']/MPA_TO_M for c in rows)] if rows else None,
            flow_range_m3h=[min(s['result']['pump_flow_m3h'] for s in solved),
                           max(s['result']['pump_flow_m3h'] for s in solved)] if solved else None))
    previous_layout_check=variants.pop(0)
    nominal=next(v for v in variants if v['loss_scale']==1 and v['axis_offset_px']==0)
    representative=next(s for s in nominal['scenarios'] if s['floors']==[floors,floors]
                        and s['boundary']=='one_supply_guaranteed')
    duty_q=previous['required_q_m3h'];audit=pipework.audit(duty_q)
    result=dict(
        method='L06 with explicitly adopted preliminary station pipework',
        input_basis_sha256=previous['basis_sha256'], pipework=audit,
        pump=pump, duty_pumps=1, reserve_pumps=1, reserve_in_flow_sum=False,
        station_product_confirmed=False, automation=deepcopy(AUTOMATION_ASSIGNMENT),
        required_q_m3h=duty_q, required_net_station_boost_m=previous['required_station_boost_m'],
        required_bare_pump_head_m=previous['required_station_boost_m']+audit['total_loss_m'],
        catalog_pump_head_at_required_q_m=previous['screen']['duty_head_m'],
        head_margin_at_required_q_m=previous['screen']['dynamic_margin_m']-audit['total_loss_m'],
        nominal_apertures_mm=layout, previous_apertures_mm=old_layout,
        previous_layout_check=previous_layout_check,
        chart_samples=station_curve_samples(pump['curve'],pipework),
        representative_operating_point=representative, variants=variants,
        adopted_assumptions_pass=all(v['all_minima_met'] and v['all_dynamic_limits_met']
            for v in variants if v['loss_scale']==1),
        double_loss_sensitivity_pass=all(v['all_minima_met'] and v['all_dynamic_limits_met']
            for v in variants if v['loss_scale']==2),
        nominal_static_lowest_pc_mpa=previous['static_pressure_lowest_cabinet_mpa'],
        maximum_allowed_pump_shutoff_m=previous['maximum_pump_shutoff_m'],
        source_maximum_is_assumption=True, release_ready=False,
        external_request_sent=False, external_reply_required_for_assignment=False,
        normative_composition=dict(standard='ГОСТ Р21.619-2023',clauses=['5.1.8','5.1.14'],
            scope='Расчётное приложение и текст для включения в ПЗ; не полный комплект ИОС2',
            balance_unchanged=True,full_package_verified=False),
        retained_limits=previous['retained_limits'],
    )
    result['design_inputs_sha256']=sha256(json.dumps(dict(basis=basis,pipework=asdict(pipework),
        curve=pump['curve'],holes=layout),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    result['pz_text']=station_pz_text(result)
    return result


def station_pz_text(r):
    n=lambda x:f'{x:.3f}'.replace('.',',')
    op=r['representative_operating_point']['result']
    success=r['adopted_assumptions_pass']
    paragraphs=[
        'Для самостоятельной системы В2 рассматривается насосная установка на базе двух CNP CDM32-3: '
        'один рабочий и один установленный резервный насос. Мощность каждого двигателя 5,5 кВт; '
        'это номинальная мощность двигателя, не подтверждённая потребляемая мощность в рабочей точке. '
        'Расчётная подача резервного насоса не суммируется с подачей рабочего.',
        f'Минимальная расчётная подача {n(r["required_q_m3h"])} м³/ч. Требуемая добавка напора '
        f'на границах станции {n(r["required_net_station_boost_m"])} м. Предварительные потери '
        f'обвязки при этой подаче {n(r["pipework"]["total_loss_m"])} м; требуемый напор одиночного '
        f'насоса {n(r["required_bare_pump_head_m"])} м. Каталожный напор при той же подаче '
        f'{n(r["catalog_pump_head_at_required_q_m"])} м.',
        'Обвязка принята проектировщиком предварительно: коллекторы DN100, рабочие ветви DN65, '
        'длины и сопротивления приведены в расчётном приложении. Это не подтверждённая характеристика '
        'заводской PFFS; выбранная комплектация должна обеспечить принятые гидравлические параметры '
        'либо потребовать повторного расчёта.',
        'Повторная совместная проверка по принятым допущениям ' +
        ('пройдена.' if success else 'выявила непроходящие режимы; подбор не завершён.'),
    ]
    if op['operating'] is not None:
        paragraphs.append(f'Для двух верхних ПК при гарантированном напоре 30 м рабочая точка '
            f'одиночного насоса составляет Q={n(op["pump_flow_m3h"])} м³/ч, H={n(op["pump_head_m"])} м. '
            'Это результат совместного расчёта, а не маркер введённого задания.')
    paragraphs.extend(AUTOMATION_ASSIGNMENT['requirements'][:3])
    paragraphs.append('Решения по автоматизации передаются заданием смежному разделу. '
        +AUTOMATION_ASSIGNMENT['equipment_acceptance'])
    return paragraphs


def main():
    from app.pz.fire_station_design_report import render_station_design
    verify_sources()
    basis=load_basis()
    bundle=design_ios2(build_project(make_request(make_draft(basis))),
        output_dir=str(OUTPUT/'documents'),fire_station=make_fire_station(basis),render_documents=False)
    result=calculate_station_design(basis,bundle)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'fire-station-design.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    path=OUTPUT/'В2-станция-расчёт-и-автоматика.pdf'
    render_station_design(path,result)
    print(json.dumps(dict(pdf=str(path),loss_m=result['pipework']['total_loss_m'],
        required_bare_pump_head_m=result['required_bare_pump_head_m'],
        nominal_pass=result['adopted_assumptions_pass'],double_loss_pass=result['double_loss_sensitivity_pass'],
        variants=[{k:v for k,v in s.items() if k!='scenarios'} for s in result['variants']]),ensure_ascii=False))


if __name__=='__main__':main()
