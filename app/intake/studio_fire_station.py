"""Explicit, bounded Studio input for the existing common-station solver.

This adapter contains no hydraulic formula, inferred geometry, catalogue default
or Samara import. Schema 1 is an expert calculation-model interchange, not an
automatic interpretation of plans or a mandatory Studio questionnaire.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict
from math import isfinite
import json
import re

from app.calc.fire_hydraulics import PipeSegment
from app.calc.fire_pump_station import CommonFireStation, StationSupply
from app.data.pipe_catalog import STEEL_VGP_ORDINARY, steel_vgp_ordinary


NOTICE = (
    "Предварительный расчёт В2 по заданной сети и фиксированным расходам ПК. "
    "Не подтверждает покрытие помещений, совместную работу ПК по давлению, "
    "диафрагмы, NPSH и все ремонтные режимы. Резервный насос не суммируется с рабочим."
)
MAX_MODEL_BYTES = 100_000


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ValueError(f"{label}: нужны только поля {keys} (неизвестные поля запрещены)")
    return value


def _number(value, label, *, minimum=None, positive=False):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{label}: требуется конечное число")
    if (minimum is not None and value < minimum) or (positive and value <= 0):
        raise ValueError(f"{label}: недопустимое отрицательное/нулевое значение")
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[\w-]{1,48}", value):
        raise ValueError("Идентификатор: 1–48 букв, цифр, подчёркиваний или дефисов")
    return value


def _rows(value, label, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label}: требуется от {minimum} до {maximum} строк")
    return value


def _pipe(row, label, length_key="length_m"):
    _number(row[length_key], f"{label}: длина", positive=True)
    _number(row["A"], f"{label}: A", positive=True)
    _number(row["equiv_length_m"], f"{label}: эквивалентная длина", minimum=0)
    if type(row["dn"]) is not int or row["dn"] not in STEEL_VGP_ORDINARY:
        raise ValueError(f"{label}: DN отсутствует в выбранном сортаменте")


@dataclass(frozen=True)
class ParsedStation:
    model: dict
    network: object
    station: CommonFireStation


def parse_model(value) -> ParsedStation:
    from app.intake.request_dto import NetworkRequest, MainRunRequest, RiserRequest
    from app.data.fire_tables import get_nozzle_data

    try:
        size = len(json.dumps(value, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Модель В2 должна быть конечным JSON-объектом") from exc
    if size > MAX_MODEL_BYTES:
        raise ValueError("Модель В2 превышает 100 КБ")
    version = value.get("schema_version") if isinstance(value, dict) else None
    if type(version) is not int or version not in (1, 2, 3):
        raise ValueError("Поддерживаются schema_version = 1, 2 и 3")
    keys = "schema_version basis material pump_axis_m cabinet network supplies"
    model = _object(value, keys + (" pressure_review" if version >= 2 else "") +
                    (" pipework" if version == 3 else "") +
                    (" location" if 'location' in value else ""), "Модель В2")
    if model["material"] != "steel_vgp_ordinary":
        raise ValueError("Эта версия модели В2 поддерживает только ВГП обыкновенную сталь; иной материал не подменяется")
    if not isinstance(model["basis"], str) or not 1 <= len(model["basis"].strip()) <= 1200:
        raise ValueError("Укажите основание геометрии, A и местных сопротивлений (до 1200 символов)")
    pump_axis = _number(model["pump_axis_m"], "Отметка оси насоса")
    cab = _object(model["cabinet"], "dn nozzle_mm hose_length_m compact_jet_m", "Комплектация ПК")
    if any(type(v) is not int for v in cab.values()) or not get_nozzle_data(
            cab["dn"], cab["nozzle_mm"], cab["hose_length_m"], cab["compact_jet_m"]):
        raise ValueError("Комплектация ПК отсутствует в действующей таблице 7.3; интерполяция запрещена")
    net = _object(model["network"], "source_node second_source_node node_elevations runs risers", "Сеть после насоса")
    elevations = net["node_elevations"]
    if not isinstance(elevations, dict) or not 2 <= len(elevations) <= 24:
        raise ValueError("Сеть: требуются 2–24 узла с явными отметками")
    for name, elevation in elevations.items():
        _id(name)
        _number(elevation, f"Узел {name}: отметка")
    ports = [net["source_node"], net["second_source_node"]]
    if any(not isinstance(p, str) or p not in elevations for p in ports) or ports[0] == ports[1]:
        raise ValueError("Нужны два разных выхода общего напорного коллектора в сети")
    if any(abs(elevations[p] - pump_axis) > 1e-9 for p in ports):
        raise ValueError("Оба выхода общего коллектора должны иметь отметку оси насоса")
    runs, links, pairs = [], {name: set() for name in elevations}, set()
    for index, row in enumerate(_rows(net["runs"], "Участки", 1, 32)):
        label = f"Участок {index + 1}"
        _object(row, "from_node to_node length_m dn A equiv_length_m", label)
        _pipe(row, label)
        a, b = _id(row["from_node"]), _id(row["to_node"])
        pair = tuple(sorted((a, b)))
        if a not in links or b not in links or a == b or pair in pairs:
            raise ValueError(f"{label}: неизвестный узел, петля или повторное соединение")
        if row["length_m"] + 1e-9 < abs(elevations[a] - elevations[b]):
            raise ValueError(f"{label}: длина меньше перепада отметок")
        pairs.add(pair)
        links[a].add(b)
        links[b].add(a)
        runs.append(MainRunRequest(**row))
    visited, pending = set(), [ports[0]]
    while pending:
        node = pending.pop()
        if node not in visited:
            visited.add(node)
            pending.extend(links[node] - visited)
    if visited != set(elevations):
        raise ValueError("Сеть В2 разорвана: все узлы должны быть соединены с общим коллектором")
    risers, names = [], set(elevations)
    for row in _rows(net["risers"], "Расчётные ПК на стояках", 1, 8):
        _object(row, "name at_node height_m cabinet_elevation_m dn A equiv_length_m", "Стояк")
        name, at = _id(row["name"]), _id(row["at_node"])
        if name in names or f"{name}_top" in names or at not in elevations:
            raise ValueError("Стояк: повторное имя или неизвестный узел присоединения")
        names.update((name, f"{name}_top"))
        _pipe(row, name, "height_m")
        _number(row["cabinet_elevation_m"], f"{name}: отметка ПК")
        if row["height_m"] + 1e-9 < abs(row["cabinet_elevation_m"] - elevations[at]):
            raise ValueError(f"{name}: длина стояка меньше перепада отметок")
        risers.append(RiserRequest(**row))
    supplies, supply_names = [], set()
    for row in _rows(model["supplies"], "Наружные вводы", 2, 2):
        _object(row, "name source_elevation_m guaranteed_head_m maximum_head_m segments", "Ввод")
        name = _id(row["name"])
        if name in supply_names:
            raise ValueError("Имена вводов должны различаться")
        supply_names.add(name)
        _number(row["source_elevation_m"], f"{name}: отметка источника")
        minimum = _number(row["guaranteed_head_m"], f"{name}: гарантированный напор", minimum=0)
        if row["maximum_head_m"] is not None:
            _number(row["maximum_head_m"], f"{name}: максимальный напор", minimum=minimum)
        segments = []
        for index, segment in enumerate(_rows(row["segments"], f"{name}: путь до насоса", 1, 16)):
            _object(segment, "length_m dn A equiv_length_m", f"{name}: участок {index + 1}")
            _pipe(segment, name)
            segments.append(PipeSegment(
                f"{name}-{index+1}", f"{name}-n{index}", f"{name}-n{index+1}",
                length_m=segment["length_m"], A=segment["A"],
                equiv_length_m=segment["equiv_length_m"], diameter_mm=segment["dn"],
                inner_diameter_mm=steel_vgp_ordinary(segment["dn"]).inner_mm))
        supplies.append(StationSupply(name, row["source_elevation_m"], minimum,
                                      row["maximum_head_m"], tuple(segments)))
    from app.intake.studio_fire_location import from_model as location_from_model
    location_from_model(model)
    if version == 3:
        from app.intake.studio_fire_pipework import parse_pipework
        parse_pipework(model['pipework'])
    if version >= 2:
        from app.intake.studio_fire_review import validate_review
        validate_review(model["pressure_review"], model)
    if version == 3 and 'fittings_scope' in model['pipework']:
        from app.data.fire_pump_study import STUDY_CANDIDATES
        from app.intake.studio_fire_fittings import coverage
        pump = next(p for p in STUDY_CANDIDATES if p.id == model['pressure_review']['pump_id'])
        coverage(model, pump.pump_model)
    return ParsedStation(deepcopy(model), NetworkRequest(
        runs=runs, risers=risers, source_node=ports[0], second_source_node=ports[1],
        node_elevations=deepcopy(elevations)), CommonFireStation(
            pump_axis, tuple(supplies), model["basis"], review_notes=(NOTICE,)))


def request_issues(req) -> list[str]:
    if req.fire_station_model is None:
        return []
    try:
        parsed = parse_model(req.fire_station_model)
    except ValueError as exc:
        return [str(exc)]
    issues = []
    if req.building_type != "residential" or req.fire_mode != "auto":
        issues.append("Импорт станции Studio пока применим к жилью с автоматической нормативной проверкой В2")
    if req.fire_topology != "separate" or req.zones != 1:
        issues.append("Модель общей пожарной станции пока поддерживает только раздельную В2 в одной зоне")
    if req.network is not None:
        issues.append("Сеть В2 должна находиться только в модели станции: два независимых описания запрещены")
    cab = parsed.model["cabinet"]
    if (req.cabinet_dn, req.nozzle_mm, req.hose_length_m, req.compact_jet_m) != (
            cab["dn"], cab["nozzle_mm"], cab["hose_length_m"], cab["compact_jet_m"]):
        issues.append("Комплектация ПК в запросе не совпадает с моделью станции")
    return issues


def summary(bundle) -> dict | None:
    project, result = bundle.project, bundle.fire_station_result
    if result is None:
        return None
    pump, hydraulic = project.fire_pumps, result.hydraulic
    from app.intake.studio_fire_location import from_model as location_from_model
    from app.data.fire_pump_geometry import connection_review
    return dict(
        state="preliminary", note=(pump.selection_note if pump.pressure_review else NOTICE), basis=result.basis,
        pump_axis_m=result.pump_axis_m, supplies=[asdict(s) for s in result.supplies],
        flow_lps=hydraulic.dictating_scenario.total_flow_lps,
        required_header_head_m=hydraulic.required_head_at_source_m,
        minimum_suction_head_m=result.minimum_suction_head_m,
        maximum_static_suction_head_m=result.maximum_static_suction_head_m,
        pump_needed=hydraulic.needs_pump,
        pump_head_m=hydraulic.pump_duty.required_head_m if hydraulic.pump_duty else 0,
        pump=asdict(pump) if hydraulic.needs_pump else None,
        pipework=bundle.project.fire_pumps.pressure_review.get('pipework') if pump.pressure_review else result.pipework_audit,
        pressure_review=bundle.fire_pressure_review,
        adopted=bool(pump.pressure_review),
        location=location_from_model(project.fire_station_model_input),
        pump_geometry=connection_review(project.fire_station_model_input, pump.model),
    )
