# -*- coding: utf-8 -*-
"""
app/intake/project_builder.py — Project Builder (слой 2 цепочки ввода).

ЕДИНСТВЕННОЕ место, где из намерения (IOS2Request) рождается Project.
Все входы (Wizard, YAML, Excel, IFC, REST, CLI) собирают IOS2Request,
Builder делает остальное. UI и форматы не знают модель Project вообще.

Builder:
  • маппит термины проектировщика в модель (residential → BuildingPurpose...);
  • разворачивает namespace сети (runs/risers → FireNetworkSpec);
  • НЕ считает (расчёт — в design_ios2) и НЕ выдумывает (чего нет — ошибка).
"""
from __future__ import annotations

from typing import List

from app.intake.request_dto import IOS2Request
from app.pz.project import (
    Project, DocumentInfo, BuildingFlags, BuildingPurpose, FireSystem,
    PumpSystem, FlowsData, FireRoomSpec, FireNetworkSpec,
    MainNodeSpec, MainSegmentSpec, RiserSpec, V1SectionSpec,
    V1NodeSpec, V1NetworkSectionSpec, V1NetworkSpec,
)


class RequestValidationError(ValueError):
    """Намерение не прошло валидацию — список проблем в args[0]."""
    def __init__(self, problems: List[str]):
        super().__init__("вход не пригоден для сборки Project:\n  - " +
                         "\n  - ".join(problems))
        self.problems = problems


_BUILDING_MAP = {
    "residential": BuildingPurpose.RESIDENTIAL,
    "public": BuildingPurpose.PUBLIC,
    "industrial": BuildingPurpose.INDUSTRIAL,
}


def build_project(req: IOS2Request) -> Project:
    """IOS2Request → Project. Валидация намерения → маппинг → сборка.

    streams: если None — оставляем 0 в FireSystem (задел: авто по табл. 7.1
    через категорию; сейчас honest-поведение — билдер геометрии потребует
    streams явно, см. geometry_builder.build_layout_inputs).
    """
    problems = req.validate()
    if problems:
        raise RequestValidationError(problems)

    p = Project()

    d = req.document
    p.document = DocumentInfo(
        cipher=d.cipher, object_name=d.object_name, object_address=d.object_address,
        object_part=d.object_part, stage=d.stage, organization=d.organization,
        developer_name=d.developer, inspector_name=d.inspector,
        dept_head_name=d.dept_head, gip_name=d.gip, norm_control_name=d.norm_control,
        sheet_no="1", sheet_total="1")

    p.building = BuildingFlags(
        purpose=_BUILDING_MAP[req.building_type],
        floors_above=req.floors, height_m=req.building_height_m, zones=req.zones)

    from app.pz.project import WaterSource
    sd = req.source_data
    if sd is not None:
        p.source = WaterSource(
            description=sd.customer, connection_point=sd.connection_point,
            tu_number=sd.tu_number, tu_date=sd.tu_date,
            guaranteed_head_m=sd.guaranteed_head_m,
            maximum_head_m=sd.maximum_head_m,
            tu_limit_q_day=sd.tu_limit_q_day,
            tu_fire_outdoor_l_s=sd.tu_fire_outdoor_l_s,
            elev_header_m=sd.elev_header_m, elev_fixture_m=sd.elev_fixture_m,
            h_geom_m=sd.h_geom_m, il_dict_m=sd.il_dict_m, h_il_m=sd.h_il_m,
            network_kind=sd.network_kind, h_pr_m=sd.h_pr_m,
            h_tepl_m=sd.h_tepl_m, il_vvod_m=sd.il_vvod_m,
            h_vvod_m=sd.h_vvod_m, water_use_period_h=sd.water_use_period_h,
            inputs_count=sd.inputs_count, npsh_available_m=sd.npsh_available_m)

    streams = req.streams if req.streams is not None else 0
    q_total = round(streams * req.q_per_stream_lps, 3) if streams else 0.0
    p.fire = FireSystem(
        required=True, streams=streams, q_per_stream=req.q_per_stream_lps,
        q_total=q_total, nozzle_dn=req.cabinet_dn, hose_length_m=req.hose_length_m)

    p.pumps = PumpSystem(required=req.needs_booster_pumps)
    p.flows = FlowsData()

    # помещения ПК
    p.fire_rooms = [
        FireRoomSpec(r.name, length_m=r.length_m, width_m=r.width_m,
                     height_m=r.height_m, space_kind=r.space_kind,
                     placement_mode=r.placement)
        for r in req.rooms]

    # сеть В2: узлы собираются из участков (namespace runs), отметки из карты
    if req.network is not None:
        n = req.network
        node_ids = sorted({x for r in n.runs for x in (r.from_node, r.to_node)})
        nodes = [MainNodeSpec(nid, float(n.node_elevations.get(nid, 0.0)))
                 for nid in node_ids]
        segments = [
            MainSegmentSpec(f"М{i+1}", r.from_node, r.to_node, length_m=r.length_m,
                            A=r.A, dn=r.dn, equiv_length_m=r.equiv_length_m)
            for i, r in enumerate(n.runs)]
        risers = [
            RiserSpec(r.name, r.at_node, length_m=r.height_m,
                      cabinet_elevation_m=r.cabinet_elevation_m, A=r.A,
                      dn=r.dn, equiv_length_m=r.equiv_length_m)
            for r in n.risers]
        p.fire_network = FireNetworkSpec(
            nodes=nodes, segments=segments, risers=risers,
            source_node=n.source_node, source_kind=n.source_kind,
            available_head_m=n.available_head_m, water_level_m=n.water_level_m,
            suction_head_loss_m=n.suction_head_loss_m,
            second_source_node=n.second_source_node,
            second_available_head_m=n.second_available_head_m)

    p.consumer_groups = [(g.code, g.count) for g in req.consumers]
    p.v1_sections = [V1SectionSpec(**vars(s)) for s in req.v1_sections]
    if req.v1_network is not None:
        p.v1_network = V1NetworkSpec(
            source_node=req.v1_network.source_node,
            nodes=[V1NodeSpec(
                node_id=n.node_id,
                elevation_m=n.elevation_m,
                consumer_groups=[(g.code, g.count) for g in n.consumers],
                direct_demand_lps=n.direct_demand_lps,
                h_pr_m=n.h_pr_m,
                max_static_head_m=n.max_static_head_m,
            ) for n in req.v1_network.nodes],
            sections=[V1NetworkSectionSpec(**vars(s)) for s in req.v1_network.sections],
        )
        # Топология является источником состава потребителей для общего расхода:
        # это исключает расхождение расхода водомера и корневого участка сети.
        counts = {}
        for node in req.v1_network.nodes:
            for group in node.consumers:
                counts[group.code] = counts.get(group.code, 0) + group.count
        if counts:
            p.consumer_groups = list(counts.items())
    p.sewage_max_fixture_lps = req.sewage_max_fixture_lps
    p.storm_city = req.storm_city

    return p
