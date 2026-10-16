"""Object-specific orchestration of approved L06 solvers, not new hydraulics.

Only explicitly named cabinet groups/isolations are reviewed. No floor expansion,
automatic aperture selection, repair section inference or Samara defaults.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json

NOTICE = (
    "Исследовательская проверка заданных групп ПК и отключений. "
    "Справочная характеристика ВНИИПО и номограмма не подтверждают паспорт изделий, "
    "NPSH, покрытие помещений и реальные границы ремонтных секций. "
    "Проверяемый насос не принят автоматически в проект. Резерв не суммируется."
)
MAX_SOLVES = 384


def validate_review(value, model):
    from app.intake.studio_fire_station import _object, _id, _number, _rows
    from app.data.fire_pump_study import STUDY_CANDIDATES
    from app.data.fire_diaphragm_nomogram import APOGEY_SOURCE
    keys = "basis pump_id characteristic hose_material nozzle_kind loss_boundary apertures_mm groups repairs axis_offsets_px"
    if isinstance(value, dict) and "document_use" in value:
        keys += " document_use"
    r = _object(value, keys, "Проверка L06")
    if r.get("document_use", "review_only") not in ("review_only", "preliminary_project"):
        raise ValueError("L06: использование результата — review_only или preliminary_project")
    if not isinstance(r["basis"], str) or not 1 <= len(r["basis"].strip()) <= 1200:
        raise ValueError("L06: нужно основание групп ПК и границ отключений")
    if not isinstance(r["pump_id"], str) or r["pump_id"] not in {p.id for p in STUDY_CANDIDATES}:
        raise ValueError("L06: насос отсутствует в проверенном исследовательском каталоге")
    if (r["characteristic"] != "handbook_study" or r["nozzle_kind"] != "non_shutoff"
            or r["hose_material"] not in ("rubber_lined", "unlined")):
        raise ValueError("L06: пока поддержана явно выбранная справочная характеристика неперекрывного ствола")
    from app.intake.studio_fire_pipework import BOUNDARY
    expected_boundary = BOUNDARY if model['schema_version'] == 3 else 'all_pipework_explicit_in_supplies_and_network'
    if r["loss_boundary"] != expected_boundary:
        raise ValueError("L06: граница потерь не соответствует версии модели; двойной учёт обвязки запрещён")
    names = {row["name"] for row in model["network"]["risers"]}
    apertures = r["apertures_mm"]
    if not isinstance(apertures, dict) or set(apertures) != names:
        raise ValueError("L06: для каждого расчётного ПК задайте отверстие или null (без диафрагмы)")
    for diameter in apertures.values():
        if diameter is not None:
            _number(diameter, "Отверстие диафрагмы", positive=True)
            if model["cabinet"]["dn"] != 50 or diameter not in APOGEY_SOURCE["apertures_mm"]:
                raise ValueError("L06: оцифрована только номограмма DN50, отверстия 12–25 мм с шагом 0,5")
    seen = set()
    for group in _rows(r["groups"], "Группы ПК", 1, 16):
        if (not isinstance(group, list) or not group or len(group) > 8
                or any(not isinstance(n, str) or n not in names for n in group)
                or len(set(group)) != len(group) or tuple(sorted(group)) in seen):
            raise ValueError("L06: группы должны содержать известные ПК без повторов")
        seen.add(tuple(sorted(group)))
    if set().union(*[set(g) for g in r["groups"]]) != names:
        raise ValueError("L06: каждый заданный ПК должен участвовать хотя бы в одной группе")
    ports = {model["network"][k] for k in ("source_node", "second_source_node")}
    pairs = {frozenset((s["from_node"], s["to_node"])) for s in model["network"]["runs"]}
    repair_ids, closures = {"intact"}, set()
    for case in _rows(r["repairs"], "Отключения", 1, 8):
        _object(case, "id basis closed_runs closed_ports", "Отключение")
        name = _id(case["id"])
        if name in repair_ids or not isinstance(case["basis"], str) or not 1 <= len(case["basis"].strip()) <= 300:
            raise ValueError("L06: нужны уникальное имя отключения и его основание")
        repair_ids.add(name)
        selected = []
        for pair in _rows(case["closed_runs"], "Закрытые участки", 0, 32):
            if (not isinstance(pair, list) or len(pair) != 2 or
                    any(not isinstance(n, str) for n in pair) or frozenset(pair) not in pairs):
                raise ValueError("L06: неизвестный отключаемый участок")
            selected.append(tuple(sorted(pair)))
        cp = _rows(case["closed_ports"], "Закрытые выходы", 0, 1)
        if any(not isinstance(p, str) or p not in ports for p in cp):
            raise ValueError("L06: неизвестный выход коллектора")
        signature = (tuple(sorted(selected)), tuple(cp))
        if not (selected or cp) or len(set(selected)) != len(selected) or signature in closures:
            raise ValueError("L06: пустое или повторное отключение")
        closures.add(signature)
    offsets = _rows(r["axis_offsets_px"], "Чувствительность номограммы", 1, 3)
    for offset in offsets:
        _number(offset, "Смещение шкалы")
        if offset not in (-2, 0, 2):
            raise ValueError("L06: доступны проверенные смещения шкалы −2, 0, +2 px")
    if 0 not in offsets or len(set(offsets)) != len(offsets):
        raise ValueError("L06: нужна номинальная шкала 0, без повторов")
    if len(r["groups"])*(len(r["repairs"])+1)*5*len(offsets) > MAX_SOLVES:
        raise ValueError(f"L06: матрица превышает {MAX_SOLVES} расчёта; уменьшите явный набор, он не обрезается автоматически")
    return deepcopy(r)


def calculate_review(project, network):
    from app.calc.fire_hydraulics import MPA_TO_M, SpecificResistanceBackend
    from app.calc.fire_pressure_flow import handbook_characteristic
    from app.calc.fire_nomogram_flow import check_nomogram_operating_point
    from app.calc.fire_repair_flow import check_repair_operating_point
    from app.calc.pump_curve import interpolate_head
    from app.data.fire_pump_study import STUDY_CANDIDATES

    model = project.fire_station_model_input
    from app.intake.studio_fire_pipework import from_model
    pipework = from_model(model)
    internal = pipework.resistances() if pipework else dict(suction=0., discharge=0.)
    review = validate_review(model["pressure_review"], model)
    if any(len(group) != project.fire.streams for group in review["groups"]):
        raise ValueError("В каждой группе должно быть нормативное количество одновременно действующих ПК")
    station = project.fire_station_input
    pump = next(p for p in STUDY_CANDIDATES if p.id == review["pump_id"])
    cabs = {c.riser_id: c for c in network.cabinets}
    boundaries = []
    maxima = []
    for supply in station.supplies:
        resistance = sum(SpecificResistanceBackend().segment_loss(s, 1.) for s in supply.segments)
        for label, head in (("Hгар", supply.guaranteed_head_m), ("Hmax", supply.maximum_head_m)):
            if head is not None:
                boundaries.append(dict(id=f"{supply.name}/{label}", supply=supply.name,
                    static_head_m=head+supply.source_elevation_m-station.pump_axis_m,
                    resistance=resistance, kind="single_supply"))
        if supply.maximum_head_m is not None:
            maxima.append(supply.maximum_head_m+supply.source_elevation_m-station.pump_axis_m)
    maximum_known = len(maxima) == len(station.supplies)
    if maximum_known:
        boundaries.append(dict(id="Верхняя огибающая", supply=None, static_head_m=max(maxima),
            resistance=0., kind="upper_bound_without_external_losses"))
    cases = [dict(id="intact", basis="Целая сеть", closed_runs=[], closed_ports=[])] + review["repairs"]
    by_pair = {frozenset((s.from_node, s.to_node)): s.segment_id for s in network.segments}
    rows = []
    for group in review["groups"]:
        net = deepcopy(network)
        net.cabinets = [deepcopy(cabs[name]) for name in group]
        chars = [handbook_characteristic(c, hose_material=review["hose_material"],
                    nozzle_kind=review["nozzle_kind"]) for c in net.cabinets]
        apertures = {cabs[name].cabinet_id: review["apertures_mm"][name] for name in group
                     if review["apertures_mm"][name] is not None}
        for case in cases:
            for boundary in boundaries:
                for offset in review["axis_offsets_px"]:
                    kwargs = dict(suction_static_head_m=boundary["static_head_m"],
                        supply_resistance=boundary["resistance"], apertures_mm=apertures,
                        axis_offset_px=offset, station_suction_resistance=internal['suction'],
                        station_discharge_resistance=internal['discharge'])
                    row = dict(group=group, case=case["id"], boundary=boundary["id"], axis_offset_px=offset)
                    try:
                        if case["id"] == "intact":
                            result = check_nomogram_operating_point(net, chars, pump.curve, **kwargs)
                        else:
                            result = check_repair_operating_point(net, chars, pump.curve,
                                closed_segment_ids=[by_pair[frozenset(pair)] for pair in case["closed_runs"]],
                                closed_port_ids=case["closed_ports"], **kwargs)
                        row.update(result=asdict(result), error=None)
                    except ValueError as exc:
                        row.update(result=None, error=str(exc))
                    op = row["result"]["operating"] if row["result"] else None
                    row["minimum_ok"] = bool(row["result"] and row["result"]["status"] == "meets_minimum")
                    row["dynamic_ok"] = bool(op and all(c["outlet_head_m"] <= .45*MPA_TO_M for c in op["cabinets"]))
                    rows.append(row)
    shutoff = interpolate_head(pump.curve, 0.)
    static_rows = [dict(riser=name, cabinet_id=c.cabinet_id,
        pressure_mpa=(max(maxima)+shutoff+station.pump_axis_m-network.nodes[c.node_id].elevation_m)/MPA_TO_M
        if maximum_known and shutoff is not None else None) for name, c in cabs.items()]
    static_known = all(r["pressure_mpa"] is not None for r in static_rows)
    solved = [r for r in rows if r["result"] and r["result"]["operating"]]
    complete = len(solved) == len(rows) and static_known
    return dict(state="checked" if complete else "incomplete", note=NOTICE,
        input_sha256=sha256(json.dumps(model, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest(),
        basis=review["basis"], pump=asdict(pump), groups=review["groups"], cases=cases,
        boundaries=boundaries, apertures_mm=review["apertures_mm"], rows=rows,
        scenario_count=len(rows), solved_count=len(solved), maximum_source_known=maximum_known,
        minimum_pass_count=sum(r["minimum_ok"] for r in rows),
        all_model_minima_met=all(r["minimum_ok"] for r in rows),
        all_model_dynamic_limits_met=all(r["dynamic_ok"] for r in rows),
        static_rows=static_rows, static_limit_mpa=.9, dynamic_limit_mpa=.45,
        all_model_static_limits_met=static_known and all(r["pressure_mpa"] <= .9 for r in static_rows),
        complete=complete, duty_pumps=1, reserve_pumps=1, reserve_in_flow_sum=False,
        pipework=pipework.audit(0.) if pipework else None,
        release_ready=False, product_verified=False, room_coverage_confirmed=False,
        normative_sectioning_confirmed=False)
