"""Bind the explicitly reviewed L06 case to every document, not global selection.

The input signature is checked after the normal pipeline and before rendering.
No other building receives the Samara losses, apertures or study pump by default.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import math

from app.pz.project import PumpSystem, PumpComplianceCheck


def digest(value):
    # Floor keys are integers in memory and strings after JSON persistence.
    canonical = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    return sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def input_signature(project, station):
    return digest(dict(network=asdict(project.fire_network), station=asdict(station),
        floors=project.building.floors_above, elevations=project.building.floor_elevations_m,
        residents=project.building.residents, apartments=project.building.apartments,
        nozzle=project.fire.nozzle_mm, valve_dn=project.fire.nozzle_dn,
        hose=project.fire.hose_length_m, streams=project.fire.streams,
        topology=project.fire.network_topology))


def compact_design(result, project, station):
    r = deepcopy(result)
    for variant in r['variants']:
        variant.pop('scenarios', None)
    r['previous_layout_check'].pop('scenarios', None)
    r['project_input_sha256'] = input_signature(project, station)
    r['content_sha256'] = digest(r)
    return r


def validate_design(r, project, station):
    if digest({k:v for k,v in r.items() if k != 'content_sha256'}) != r.get('content_sha256'):
        raise ValueError('Station result changed; recalculate before export')
    if station is None or input_signature(project, station) != r.get('project_input_sha256'):
        raise ValueError('Station result is stale for current project inputs')
    if (r['duty_pumps'] != 1 or r['reserve_pumps'] != 1 or r['reserve_in_flow_sum']
            or not r['adopted_assumptions_pass'] or r['release_ready']):
        raise ValueError('Only the checked preliminary 1+1 design is supported')
    nominal = [v for v in r['variants'] if v['loss_scale'] == 1]
    if len(nominal) != 3 or {v['axis_offset_px'] for v in nominal} != {-2,0,2}:
        raise ValueError('Missing nominal/sensitivity checks')
    if any(v['scenario_count'] != 512 or not v['all_minima_met'] or
           not v['all_dynamic_limits_met'] for v in nominal):
        raise ValueError('Incomplete or failed station check')
    repair=r.get('repair_review')
    if repair:
        if (repair['project_input_sha256']!=r['project_input_sha256']
                or digest(repair['apertures_mm'])!=digest(r['nominal_apertures_mm'])
                or digest(repair['pump'])!=digest(r['pump']) or repair['duty_pumps']!=1 or repair['reserve_in_flow_sum']
                or repair['reserve_pumps']!=1
                or repair['pipework_resistances']!=r['pipework']['resistances_m_per_lps2']
                or repair['nominal_static_lowest_pc_mpa']!=r['nominal_static_lowest_pc_mpa']
                or repair['release_ready'] or not repair['all_model_minima_met']
                or not repair['all_model_dynamic_limits_met']):
            raise ValueError('Repair review is stale or failed for this station/diaphragm layout')
        if {c['id'] for c in repair['cases']}!={'intact','external-1','external-2','header-1','header-2','М3','М4','М5','М6'} or len(repair['cases'])!=9:
            raise ValueError('Missing repair cases')
        for c in repair['cases']:
            if len(c['variants'])!=3 or {v['axis_offset_px'] for v in c['variants']}!={-2,0,2}:
                raise ValueError('Missing repair sensitivity checks')
            if any(not v['complete'] or v['scenario_count']!=512 or
                   v['summary']!={'meets_minimum':512} or not v['all_minima_met'] or
                   not v['all_dynamic_limits_met'] or
                   not v['pressure_range_mpa'] or
                   not all(math.isfinite(p) for p in v['pressure_range_mpa']) or
                   not 0 < v['pressure_range_mpa'][0] <= v['pressure_range_mpa'][1] <= .45
                   for v in c['variants']):
                raise ValueError('Incomplete or failed repair review')
    op = r['representative_operating_point']['result']
    from app.calc.pump_curve import interpolate_head
    if not math.isclose(interpolate_head(r['pump']['curve'], op['pump_flow_m3h']),
                        op['pump_head_m'], abs_tol=1e-5):
        raise ValueError('Operating point does not belong to single-pump curve')


def bind_design(bundle, station, result):
    p = bundle.project
    validate_design(result, p, station)
    r = deepcopy(result)
    op = r['representative_operating_point']['result']
    # A completely new presentation object: no old model, top-3 or compliance
    # statements survive under the new pump's name.
    p.fire_pumps = PumpSystem(required=True, purpose='В2', model=r['pump']['pump_model'],
        q_m3h=op['pump_flow_m3h'], head_m=op['pump_head_m'],
        power_kw=r['pump']['power_per_pump_kw'], working_units=1, reserve_units=1,
        count_note='1 рабочий + 1 установленный резервный; расход резерва не суммируется',
        q_design_m3h=r['required_q_m3h'], h_design_m=r['required_bare_pump_head_m'],
        wp_q=op['pump_flow_m3h'], wp_h=op['pump_head_m'], curve=r['pump']['curve'],
        curve_kind='pressure_flow_study', pump_head_at_design_m=r['catalog_pump_head_at_required_q_m'],
        selection_note='Предварительное решение L06 для явно заданной обвязки; не паспорт PFFS.',
        station_design=r, sp10_compliant=None,
        sp10_checks=[PumpComplianceCheck('12.1','Расчётная подача и напор',
            'Проверены 512 сочетаний неповреждённой расчётной сети при принятых допущениях','verified'),
            PumpComplianceCheck('12.3','Резервирование и управление',
                '1 рабочий + 1 установленный резервный; задание смежникам приложено','specified'),
            PumpComplianceCheck('6.2.20 (изм. 1)','Статическое давление самостоятельного ВПВ',
                f"Нижний ПК: {r['nominal_static_lowest_pc_mpa']:.3f} МПа при принятом Hмакс=35 м",'verified'),
            PumpComplianceCheck('12.20–12.21','Кавитация и область работы',
                'NPSH и паспортный диапазон выбранного исполнения не подтверждены','pending')])
    p.fire.pressure_at_lowest_pk_mpa = r['nominal_static_lowest_pc_mpa']
    # Old fixed-Q required/available heads cannot be relabelled as the new
    # pressure-dependent solution. Its boundary heads are in station_design.
    p.fire.required_head_m = p.fire.available_head_m = None
    p.fire.needs_pump = True
    bundle.status = [s for s in bundle.status if not s.startswith('fire_pump:')]
    bundle.status.append('fire_pump: единое предварительное решение CNP CDM32-3; L06, 1+1')
    if r.get('repair_review'):
        bundle.warnings.append('В2: проверены отключения вводов, выходов НУ и сегментов кольца. '
            'Границы реальных ремонтных секций и полное покрытие здания не подтверждены.')
    else:
        bundle.warnings.append('В2: ремонтные режимы кольца новым расчётом L06 не подтверждены. '
            'Прежний отчёт фиксированного расхода не включён как проверка нового решения.')


def station_spec_rows(r):
    """One component list shared by the schematic and specification.

    Total installed inventory != quantity along the one active hydraulic path.
    Aggregate fitting zeta is not converted into invented elbow/tee quantities.
    """
    rows = [dict(id='pumps', name='Насос вертикальный многоступенчатый', mark=r['pump']['pump_model'],
        unit='шт.', qty=2, note=f"1 рабочий + 1 резервный; N двигателя {r['pump']['power_per_pump_kw']:g} кВт каждый"),
        dict(id='cabinet', name='Шкаф управления пожарными насосами 1+1', mark='По заданию автоматизации',
            unit='компл.', qty=1, note='Автоматический резерв, местный/дистанционный пуск, диспетчеризация; конкретное исполнение не выбрано')]
    for e in r['pipework']['elements']:
        # DN100 header is common; DN65 rows exist in both pump branches.
        branches = 1 if e['dn'] == 100 else 2
        quantity = e['quantity_on_active_path'] * branches
        mark = f"DN{e['dn']}"
        note = 'Предварительный состав; не дополнительная закупка к готовому заводскому блоку'
        if e['method'] == 'A_L':
            quantity *= e['length_m']
            mark += '; 114×4,5' if e['dn'] == 100 else '; 75,5×4,0'
            unit = 'м'
        elif e['method'] == 'Kv':
            mark += f"; Kv ≥ {e['value']:g} м³/ч"
            unit = 'шт.'
        else:
            quantity, unit = None, 'компл.'
            mark += f"; суммарное ζ={e['value']:g} на активной ветви"
            note = 'Состав фасонины и количество определить по компоновке; ζ не является количеством изделий'
        rows.append(dict(id=e['id'], name=e['name'].replace('рабочей ветви','насосных ветвей'),
                         mark=mark, unit=unit, qty=quantity, note=note))
    rows.extend([
        dict(id='pressure', name='Манометр с подключением и контрольной арматурой', mark='До и после каждого насоса',
            unit='компл.', qty=4, note='Предел шкалы и исполнение по рабочему/максимальному давлению'),
        dict(id='service', name='Спуск, удаление воздуха, испытательный отвод, дренаж и опоры',
            mark='По компоновке насосной', unit='компл.', qty=None,
            note='Не входят в расчёт закрытых сервисных ветвей; состав и количество требуют дополнения'),
    ])
    from app.data.fire_diaphragm_layout import diaphragm_groups, floor_label
    for group in diaphragm_groups(r['nominal_apertures_mm']):
        count=2*(group['end']-group['start']+1)
        rows.append(dict(id=f"diaphragm-{group['start']}",
            name=f"Диафрагма ПК DN50, {'этаж' if count==2 else 'этажи'} {floor_label(group)}",
            mark=f"Отверстие {group['aperture_mm']:g} мм", unit='шт.', qty=None,
            note=f'В модели двух стояков {count} шт.; количество по зданию, посадка и допуски по планам/изделию'))
    return rows
