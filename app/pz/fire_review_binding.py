"""One explicit, freshly checked preliminary V2 variant for all output media.

No hydraulic method, aperture search, floor expansion or factory certification.
The ordinary object's model is deliberately separate from the frozen study case.
"""
from copy import deepcopy
from hashlib import sha256
import json
import math

from app.pz.fire_station_binding import digest, input_signature
from app.pz.project import PumpSystem

BOUND_NOTE = (
    "Принят единый предварительный вариант для заданных ПК. "
    "Характеристика ПК справочная; NPSH, паспортные допуски, покрытие помещений "
    "и реальные границы ремонтных секций требуют подтверждения. "
    "Это не окончательный допуск к выпуску. Резерв не суммируется."
)


def requested(project):
    return ((project.fire_station_model_input or {}).get("pressure_review") or {}).get(
        "document_use") == "preliminary_project"


def apply_review(bundle):
    p, r = bundle.project, bundle.fire_pressure_review
    if not requested(p):
        return
    failure = None
    if not r or r.get("error") or not r.get("complete"):
        failure = "расчёт неполон или не выполнен"
    elif not r["all_model_minima_met"]:
        failure = "не обеспечены минимумы расхода/давления"
    elif not r["all_model_dynamic_limits_met"] or not r["all_model_static_limits_met"]:
        failure = "не выполнены ограничения давления"
    elif bundle.fire_station_result is None:
        failure = "нет исходного расчёта станции"
    if failure:
        # Do not silently retain a different automatic catalogue candidate.
        p.fire_pumps = PumpSystem(required=True, purpose="В2",
            selection_note="Вариант В2 не принят: " + failure + ". См. расчёт диафрагм.")
        if r is not None:
            r["adoption"] = dict(state="rejected", reason=failure)
        bundle.warnings.append("fire_review_adoption: " + p.fire_pumps.selection_note)
        return
    data = deepcopy(r)
    data["note"] = BOUND_NOTE
    data["adoption"] = dict(state="preliminary", reason="Явный выбор; заданная матрица проверена заново")
    data["project_input_sha256"] = input_signature(p, p.fire_station_input)
    # Name the limiting intact guaranteed-supply case, not a fictional single
    # operating point for the whole building or for all repair scenarios.
    candidates = [x for x in data["rows"] if x["case"] == "intact" and
                  x["axis_offset_px"] == 0 and x["boundary"].endswith("/Hгар")]
    selected = min(candidates, key=lambda row: min(
        c["outlet_head_m"]-c["minimum_head_m"] for c in row["result"]["operating"]["cabinets"]))
    data["control_mode"] = deepcopy(selected)
    from app.intake.studio_fire_pipework import from_model
    pipework = from_model(p.fire_station_model_input)
    if pipework:
        data['pipework'] = pipework.audit(selected['result']['pump_flow_m3h'])
    data["schedule"] = [dict(id=f"Д{i+1}", riser=s["name"],
        elevation_m=s["cabinet_elevation_m"], valve_dn=p.fire.nozzle_dn,
        aperture_mm=data["apertures_mm"][s["name"]])
        for i, s in enumerate(p.fire_station_model_input["network"]["risers"])]
    # Reuse the already accepted 1+1 assignment, not the Samara pipework data.
    from app.data.fire_station_design import AUTOMATION_ASSIGNMENT
    data["automation"] = deepcopy(AUTOMATION_ASSIGNMENT)
    data["content_sha256"] = digest(data)
    op, pump = selected["result"], data["pump"]
    p.fire_pumps = PumpSystem(required=True, purpose="В2", model=pump["pump_model"],
        q_m3h=op["pump_flow_m3h"], head_m=op["pump_head_m"],
        wp_q=op["pump_flow_m3h"], wp_h=op["pump_head_m"],
        power_kw=pump["power_per_pump_kw"], curve=pump["curve"],
        working_units=1, reserve_units=1, curve_kind="pressure_flow_study",
        count_note="1 рабочий + 1 установленный резервный; расход резерва не суммируется",
        selection_note=BOUND_NOTE, pressure_review=data, sp10_compliant=None)
    p.fire.required_head_m = p.fire.available_head_m = None
    p.fire.needs_pump = True
    p.fire.pressure_at_lowest_pk_mpa = max(x["pressure_mpa"] for x in data["static_rows"])
    bundle.fire_pressure_review = deepcopy(data)
    bundle.status = [x for x in bundle.status if not x.startswith("fire_pump:")]
    bundle.status.append("fire_pump: " + pump["pump_model"] + "; единый предварительный вариант 1+1")


def validate_binding(project):
    p = project.fire_pumps
    r = p.pressure_review
    if r is None:
        return None
    from app.calc.pump_curve import interpolate_head
    model = project.fire_station_model_input
    if (not requested(project) or digest({k:v for k,v in r.items() if k != "content_sha256"}) != r["content_sha256"]
            or r["project_input_sha256"] != input_signature(project, project.fire_station_input)
            or r["input_sha256"] != sha256(
                json.dumps(model, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()):
        raise ValueError("Вариант В2 устарел или изменён: пересчитайте перед формированием документов")
    op = r["control_mode"]["result"]
    if (p.model != r["pump"]["pump_model"] or digest(p.curve) != digest(r["pump"]["curve"])
            or p.power_kw != r["pump"]["power_per_pump_kw"]
            or p.working_units != 1 or p.reserve_units != 1 or p.top3
            or not math.isclose(p.wp_q, op["pump_flow_m3h"], abs_tol=1e-9)
            or not math.isclose(p.wp_h, op["pump_head_m"], abs_tol=1e-9)
            or not math.isclose(interpolate_head(p.curve, p.wp_q), p.wp_h, abs_tol=1e-5)):
        raise ValueError("Насос и единый вариант В2 расходятся: пересчитайте документы")
    return r


def station_requirement_rows(model=None):
    """Installed 1+1 minimum, with no implied branch DN or catalogue selection.

    Shared graphic/specification positions; no renderer or hydraulic dependency.
    A selected factory block may supply these items as part of its own BOM.
    """
    note = ("Минимальный состав СП 10, п.12.30; DN и исполнение уточнить. "
            "Не дополнительная закупка к готовому блоку; потери по заданной модели.")
    rows = [
        dict(id="ЗС1/ЗС2", name="Запорная арматура на всасывании насосов", mark="ЗС1, ЗС2; DN не задан",
             qty=2, unit="шт.", note=note),
        dict(id="ЗН1/ЗН2", name="Запорная арматура на напоре насосов", mark="ЗН1, ЗН2; DN не задан",
             qty=2, unit="шт.", note=note),
        dict(id="КО1/КО2", name="Обратный клапан на напоре насоса", mark="КО1, КО2; DN не задан",
             qty=2, unit="шт.", note=note),
        dict(id="PG1/PG2/PG3/PG4", name="Манометр с подключением и контрольной арматурой",
             mark="PG1-PG4; до и после каждого насоса", qty=4, unit="компл.",
             note="СП 10, п.12.30 с изм.1; виброустойчивое исполнение; диапазон и подключение уточнить"),
    ]
    from app.intake.studio_fire_pipework import from_model, connection_rows, ROLES
    from app.intake.studio_fire_fittings import coverage
    pipework = from_model(model)
    if pipework is None:
        return rows
    by_role = {e.id:e for e in pipework.elements}
    fittings = coverage(model)
    for row, role in zip(rows, ('suction_valve','discharge_valve','discharge_check')):
        e = by_role[role]
        row['mark'] = f"{row['id']}; DN{e.dn}; Kv ≥ {e.value:g} м³/ч"
        row['note'] = ('Требование проекта, не паспорт изделия. При другом фактическом Kv повторить '
                       'проверку давлений и диафрагм. ' + e.basis)
    for e in pipework.elements:
        side, count, method, name = ROLES[e.id]
        if method != 'A_L': continue
        from app.data.pipe_catalog import steel_vgp_ordinary
        pipe = steel_vgp_ordinary(e.dn)
        rows.append(dict(id=e.id, name=f'Труба стальная ВГП: {name.lower()}',
            mark=f'DN{e.dn}; dвн={pipe.inner_mm:g} мм', qty=count*e.length_m, unit='м',
            note=f"{count} участок(а) по {e.length_m:g} м; предварительная геометрия; {e.basis}"))
    for side in ('suction','discharge'):
        header, branch = by_role[side+'_header'], by_role[side+'_branch']
        if header.dn != branch.dn:
            rows.append(dict(id='ПС1/ПС2' if side=='suction' else 'ПН1/ПН2',
                name='Переход трубопровода насосной', mark=f'DN{header.dn}×{branch.dn}',
                qty=2, unit='шт.', note='Исполнение по компоновке. ' +
                    ('Входит в суммарные местные сопротивления; без повторной надбавки.' if fittings['included'] else
                     'Учёт потерь в суммарных местных сопротивлениях требует увязки.')))
    for c in connection_rows(model):
        rows.append(dict(id=c['id'], name=c['name'], mark=f"{c['id']}; DN{c['dn']}",
            qty=1, unit='шт.' if c['kind']!='test' else 'компл.',
            note=f"{c['destination']}. {c['basis']}. В пожарном режиме водоотбор отсутствует; испытательный режим не рассчитан"))
    return rows


def spec_rows(project):
    r = validate_binding(project)
    pump = r["pump"]
    rows = [dict(id="Н1/Н2", name="Насос вертикальный многоступенчатый", mark=pump["pump_model"],
        qty=2, unit="шт.", note=f"1 рабочий + 1 резервный; двигатель {pump['power_per_pump_kw']:g} кВт каждый; предварительно")]
    from app.data.fire_pump_geometry import connection_review
    geometry = connection_review(project.fire_station_model_input, pump['pump_model'])
    if geometry:
        rows[0]['mark'] += f"; патрубки DN{geometry['nozzle_dn']}"
        rows[0]['note'] += '. Стандартный двигатель; каталог CDM/CDMF, с.62. PN и опоры уточнить.'
        if geometry['mismatched_sides']:
            rows[0]['note'] += (' Переходы учтены в суммарных местных сопротивлениях; см. расчёт насосной.'
                               if geometry['fittings_coverage']['included'] else
                               ' Переходы к ветвям и потери увязать; см. расчёт насосной.')
    rows.append(dict(id="ШУ-В2", name="Шкаф управления пожарными насосами 1+1",
        mark="По заданию автоматизации", qty=1, unit="компл.",
        note="Алгоритм 1+1 см. в ПЗ; конкретное исполнение не выбрано; не дополнительная закупка к готовому блоку"))
    rows.extend(station_requirement_rows(project.fire_station_model_input))
    if geometry:
        for transition in geometry['transitions']:
            prefix = transition['prefix']
            ids = [f'{prefix}{i+1}' for i in range(project.fire_pumps.working_units+project.fire_pumps.reserve_units)]
            big, small = sorted((transition['branch_dn'], transition['nozzle_dn']), reverse=True)
            rows.append(dict(id='/'.join(ids), name='Переход к патрубку насоса',
                mark=f"{', '.join(ids)}; DN{big}×{small}", qty=len(ids), unit='шт.',
                note='Предварительно; не добавлять к комплектному блоку. '
                     + ('Потери в суммарном ζ ветви; без повторной надбавки.' if geometry['fittings_coverage']['included'] else
                        'Исполнение и учёт потерь требуют увязки.')))
    # Each hydraulic terminal is representative, not a census of the building.
    for row in r["schedule"]:
        if row["aperture_mm"] is not None:
            rows.append(dict(id=row["id"], name=f"Диафрагма ПК DN{row['valve_dn']} ({row['id']})",
                mark=f"Отверстие {row['aperture_mm']:g} мм", qty=None, unit="шт.",
                note=f"{row['riser']}, отм. {row['elevation_m']:+.3f}; в расчётной модели 1 шт.; количество по зданию уточнить по планам; посадка/допуски по изделию"))
    return rows
