# -*- coding: utf-8 -*-
"""
app/intake/yaml_io.py — YAML-вход/выход проекта (второй потребитель Builder'а).

    project.yaml  ──load_request──▶  IOS2Request  ──build_project──▶  Project
    IOS2Request   ──dump_request──▶  project.yaml   (сохранение/обмен/git)

YAML — человекочитаемое зеркало IOS2Request в терминах проектировщика.
Парсер НЕ знает Project (как и форма): собирает намерение, Builder делает
остальное. Этот же формат — основа персистентности проектов.

Пример файла:

    document:
      cipher: 2026-089-ИОС2
      object_name: Многоквартирный жилой дом, 16 этажей
      organization: ООО «ПроектСервис»
    building:
      type: residential
      floors: 16
      height_m: 48
      zones: 2
    fire:
      streams: 2
    rooms:
      - name: Коридор тип. этажа
        length_m: 42
        width_m: 2.4
        height_m: 3.0
        kind: corridor
        placement: two_opposite_sides
    network:
      source: {node: К1, kind: city_main, available_head_m: 32}
      runs:
        - {from: К1, to: К2, length_m: 36, dn: 100, equiv_length_m: 6}
      risers:
        - {name: СТ-В2-1, at: К1, height_m: 46.5, cabinet_elevation_m: 45.6}
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml

from app.intake.request_dto import (
    IOS2Request, DocumentRequest, RoomRequest, NetworkRequest,
    MainRunRequest, RiserRequest, SourceDataRequest, ConsumerGroupRequest,
)


class YamlFormatError(ValueError):
    """Файл не является валидным YAML-проектом Зари (структурные проблемы)."""
    def __init__(self, problems: List[str]):
        super().__init__("файл проекта не разобран:\n  - " + "\n  - ".join(problems))
        self.problems = problems


# ── YAML → IOS2Request ───────────────────────────────────────────────────────

def load_request(text: str) -> IOS2Request:
    """Разбирает YAML-текст проекта в IOS2Request.

    Структурные ошибки (не тот тип, нет секции) → YamlFormatError со списком.
    Смысловая валидация значений — как всегда, в req.validate()/Builder.
    """
    problems: List[str] = []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise YamlFormatError([f"синтаксис YAML: {e}"])
    if not isinstance(data, dict):
        raise YamlFormatError(["корень файла должен быть словарём (mapping)"])

    def sect(name: str, required: bool = True) -> Dict[str, Any]:
        s = data.get(name)
        if s is None:
            if required:
                problems.append(f"нет секции '{name}'")
            return {}
        if not isinstance(s, dict):
            problems.append(f"секция '{name}' должна быть словарём")
            return {}
        return s

    doc = sect("document")
    bld = sect("building")
    fire = sect("fire", required=False)
    source_data_s = sect("source_data", required=False)
    insulation_s = sect("insulation", required=False)
    net_s = sect("network", required=False)
    rooms_s = data.get("rooms", [])
    if rooms_s is not None and not isinstance(rooms_s, list):
        problems.append("'rooms' должна быть списком")
        rooms_s = []

    if problems:
        raise YamlFormatError(problems)

    document = DocumentRequest(
        cipher=str(doc.get("cipher", "")),
        object_name=str(doc.get("object_name", "")),
        organization=str(doc.get("organization", "")),
        object_address=str(doc.get("object_address", "") or doc.get("address", "")),
        object_part=str(doc.get("object_part", "") or doc.get("part", "")),
        stage=str(doc.get("stage", "П")),
        developer=str(doc.get("developer", "")),
        inspector=str(doc.get("inspector", "")),
        dept_head=str(doc.get("dept_head", "")),
        gip=str(doc.get("gip", "")),
        norm_control=str(doc.get("norm_control", "")))

    rooms: List[RoomRequest] = []
    for i, r in enumerate(rooms_s or []):
        if not isinstance(r, dict):
            raise YamlFormatError([f"rooms[{i}] должен быть словарём"])
        rooms.append(RoomRequest(
            name=str(r.get("name", f"room_{i+1}")),
            length_m=float(r.get("length_m", 0)),
            width_m=float(r.get("width_m", 0)),
            height_m=float(r.get("height_m", 0)),
            space_kind=str(r.get("kind", r.get("space_kind", "corridor"))),
            placement=str(r.get("placement", "two_opposite_sides"))))

    network: Optional[NetworkRequest] = None
    if net_s:
        src = net_s.get("source", {}) or {}
        if not isinstance(src, dict):
            raise YamlFormatError(["network.source должен быть словарём"])
        runs_s = net_s.get("runs", []) or []
        risers_s = net_s.get("risers", []) or []
        if not isinstance(runs_s, list) or not isinstance(risers_s, list):
            raise YamlFormatError(["network.runs и network.risers должны быть списками"])
        runs = [MainRunRequest(
                    from_node=str(r.get("from", "")), to_node=str(r.get("to", "")),
                    length_m=float(r.get("length_m", 0)),
                    dn=int(r.get("dn", 100)),
                    equiv_length_m=float(r.get("equiv_length_m", 0)),
                    A=float(r.get("A", 0.0023)),
                    repair_section_id=str(r.get("repair_section_id", "")))
                for r in runs_s if isinstance(r, dict)]
        risers = [RiserRequest(
                      name=str(r.get("name", f"СТ-{i+1}")),
                      at_node=str(r.get("at", r.get("at_node", ""))),
                      height_m=float(r.get("height_m", 0)),
                      cabinet_elevation_m=float(r.get("cabinet_elevation_m", 0)),
                      dn=int(r.get("dn", 65)),
                      equiv_length_m=float(r.get("equiv_length_m", 0)),
                      A=float(r.get("A", 0.011)),
                      repair_section_id=str(r.get("repair_section_id", "")))
                  for i, r in enumerate(risers_s) if isinstance(r, dict)]
        network = NetworkRequest(
            runs=runs, risers=risers,
            source_node=str(src.get("node", "")),
            source_kind=str(src.get("kind", "city_main")),
            available_head_m=(float(src["available_head_m"])
                              if src.get("available_head_m") is not None else None),
            water_level_m=(float(src["water_level_m"])
                           if src.get("water_level_m") is not None else None),
            suction_head_loss_m=float(src.get("suction_head_loss_m", 0)),
            second_source_node=str((net_s.get("source2") or {}).get("node", "")),
            second_available_head_m=(float((net_s.get("source2") or {})["available_head_m"])
                                     if (net_s.get("source2") or {}).get("available_head_m")
                                     is not None else None),
            node_elevations={str(k): float(v) for k, v in
                             (net_s.get("node_elevations") or {}).items()})

    fire_streams = fire.get("streams")
    source_data = None
    if source_data_s:
        sd = source_data_s
        def optional_float(name):
            return float(sd[name]) if sd.get(name) is not None else None
        source_data = SourceDataRequest(
            customer=str(sd.get("customer", "")),
            designer_org=str(sd.get("designer_org", "")),
            basis=str(sd.get("basis", "")),
            design_stage=str(sd.get("design_stage", "Проектная документация (П)")),
            source_description=str(sd.get("source_description", "")),
            water_protection_note=str(sd.get("water_protection_note", "")),
            reserve_water_note=str(sd.get("reserve_water_note", "")),
            tu_org=str(sd.get("tu_org", "")), tu_number=str(sd.get("tu_number", "")),
            tu_date=str(sd.get("tu_date", "")),
            connection_point=str(sd.get("connection_point", "")),
            guaranteed_head_m=optional_float("guaranteed_head_m"),
            maximum_head_m=optional_float("maximum_head_m"),
            tu_limit_q_day=optional_float("tu_limit_q_day"),
            tu_fire_outdoor_l_s=optional_float("tu_fire_outdoor_l_s"),
            water_main_dn=int(sd.get("water_main_dn", 0)),
            elev_header_m=optional_float("elev_header_m"),
            elev_fixture_m=optional_float("elev_fixture_m"),
            h_geom_m=optional_float("h_geom_m"), il_dict_m=optional_float("il_dict_m"),
            h_il_m=optional_float("h_il_m"), network_kind=str(sd.get("network_kind", "domestic")),
            h_pr_m=float(sd.get("h_pr_m", 20.0)), h_tepl_m=float(sd.get("h_tepl_m", 0.0)),
            il_vvod_m=optional_float("il_vvod_m"), h_vvod_m=optional_float("h_vvod_m"),
            water_use_period_h=float(sd.get("water_use_period_h", 24.0)),
            inputs_count=int(sd.get("inputs_count", 1)),
            npsh_available_m=optional_float("npsh_available_m"),
        )
    consumers = [ConsumerGroupRequest(str(x.get("code", "")), int(x.get("count", 0)))
                 for x in (data.get("consumers") or []) if isinstance(x, dict)]
    return IOS2Request(
        document=document,
        building_type=str(bld.get("type", "residential")),
        floors=int(bld.get("floors", 0)),
        building_height_m=float(bld.get("height_m", 0)),
        total_area_m2=float(bld.get("total_area_m2", 0)),
        risers_v1=int(bld.get("risers_v1", 0)),
        risers_t3=int(bld.get("risers_t3", 0)),
        risers_t4=int(bld.get("risers_t4", 0)),
        insulation_location=str(insulation_s.get("location", "room_hot")),
        insulation_t_room_manual=float(insulation_s.get("t_room_manual", 5.0)),
        insulation_humidity=int(insulation_s.get("humidity", 60)),
        insulation_hvs_water_temp=float(insulation_s.get("hvs_water_temp", 10.0)),
        insulation_gvs_water_temp=float(insulation_s.get("gvs_water_temp", 60.0)),
        streams=(int(fire_streams) if fire_streams is not None else None),
        q_per_stream_lps=float(fire.get("q_per_stream_lps", 2.6)),
        hose_length_m=int(fire.get("hose_length_m", 20)),
        cabinet_dn=int(fire.get("cabinet_dn", 50)),
        zones=int(bld.get("zones", 1)),
        rooms=rooms, network=network, source_data=source_data, consumers=consumers)


def load_request_file(path: str) -> IOS2Request:
    with open(path, encoding="utf-8") as f:
        return load_request(f.read())


# ── IOS2Request → YAML ───────────────────────────────────────────────────────

def dump_request(req: IOS2Request) -> str:
    """Сериализует намерение обратно в YAML (сохранение/обмен/git).
    Гарантия: load_request(dump_request(x)) эквивалентен x (round-trip)."""
    d = req.document
    data: Dict[str, Any] = {
        "document": {
            "cipher": d.cipher, "object_name": d.object_name,
            "organization": d.organization,
            **({"object_address": d.object_address} if d.object_address else {}),
            **({"object_part": d.object_part} if d.object_part else {}),
            "stage": d.stage,
            **({"developer": d.developer} if d.developer else {}),
            **({"inspector": d.inspector} if d.inspector else {}),
            **({"dept_head": d.dept_head} if d.dept_head else {}),
            **({"gip": d.gip} if d.gip else {}),
            **({"norm_control": d.norm_control} if d.norm_control else {}),
        },
        "building": {
            "type": req.building_type, "floors": req.floors,
            "height_m": req.building_height_m, "zones": req.zones,
            "total_area_m2": req.total_area_m2,
            "risers_v1": req.risers_v1,
            "risers_t3": req.risers_t3,
            "risers_t4": req.risers_t4,
        },
        "fire": {
            **({"streams": req.streams} if req.streams is not None else {}),
            "q_per_stream_lps": req.q_per_stream_lps,
            "hose_length_m": req.hose_length_m,
            "cabinet_dn": req.cabinet_dn,
        },
        "insulation": {
            "location": req.insulation_location,
            "t_room_manual": req.insulation_t_room_manual,
            "humidity": req.insulation_humidity,
            "hvs_water_temp": req.insulation_hvs_water_temp,
            "gvs_water_temp": req.insulation_gvs_water_temp,
        },
    }
    if req.source_data is not None:
        sd = req.source_data
        data["source_data"] = {
            key: value for key, value in vars(sd).items()
            if value not in (None, "")
        }
    if req.consumers:
        data["consumers"] = [{"code": x.code, "count": x.count} for x in req.consumers]
    if req.rooms:
        data["rooms"] = [{
            "name": r.name, "length_m": r.length_m, "width_m": r.width_m,
            "height_m": r.height_m, "kind": r.space_kind, "placement": r.placement,
        } for r in req.rooms]
    if req.network is not None:
        n = req.network
        src: Dict[str, Any] = {"node": n.source_node, "kind": n.source_kind}
        if n.available_head_m is not None:
            src["available_head_m"] = n.available_head_m
        if n.water_level_m is not None:
            src["water_level_m"] = n.water_level_m
        if n.suction_head_loss_m:
            src["suction_head_loss_m"] = n.suction_head_loss_m
        s2: Dict[str, Any] = {}
        if n.second_source_node:
            s2 = {"node": n.second_source_node}
            if n.second_available_head_m is not None:
                s2["available_head_m"] = n.second_available_head_m
        data["network"] = {
            "source": src,
            **({"source2": s2} if s2 else {}),
            "runs": [{"from": r.from_node, "to": r.to_node, "length_m": r.length_m,
                      "dn": r.dn, "equiv_length_m": r.equiv_length_m, "A": r.A,
                      **({"repair_section_id": r.repair_section_id}
                         if r.repair_section_id else {})}
                     for r in n.runs],
            "risers": [{"name": r.name, "at": r.at_node, "height_m": r.height_m,
                        "cabinet_elevation_m": r.cabinet_elevation_m,
                        "dn": r.dn, "equiv_length_m": r.equiv_length_m, "A": r.A,
                        **({"repair_section_id": r.repair_section_id}
                           if r.repair_section_id else {})}
                       for r in n.risers],
            **({"node_elevations": n.node_elevations} if n.node_elevations else {}),
        }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)


def dump_request_file(req: IOS2Request, path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump_request(req))
    return path
