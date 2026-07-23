# -*- coding: utf-8 -*-
"""
app/pz/geometry_builder.py — автопостроение расчётной геометрии из Project.

Разворачивает высокоуровневые спецификации (FireRoomSpec, FireNetworkSpec) в
расчётные входы движка: (FireNormativeContext, RectangularRoom) для layout и
FireNetwork для гидравлики. ЧИСТОЕ ПОСТРОЕНИЕ — никаких расчётов и никаких
выдуманных значений: всё берётся из спецификаций, BuildingFlags и FireSystem;
чего нет — честная ошибка, не дефолт «из воздуха».

Именно этот модуль делает оркестратор truly one-click: project несёт описание
системы в инженерных терминах (помещения/стояки/магистраль), билдер строит граф.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.pz.project import (
    Project, BuildingPurpose, FireRoomSpec, FireNetworkSpec,
)


# ── маппинги «модель проекта → нормативный слой» ────────────────────────────

_PURPOSE_TO_FIRE_KIND = {
    BuildingPurpose.RESIDENTIAL: "residential",
    BuildingPurpose.PUBLIC: "public",
    BuildingPurpose.INDUSTRIAL: "industrial",
}


def build_layout_inputs(project: Project) -> List[Tuple[object, object]]:
    """FireRoomSpec[] → [(FireNormativeContext, RectangularRoom)].

    Нормативный контекст собирается из BuildingFlags (тип/высота здания),
    FireSystem (число струй → override, рукав) и самого спека (тип пространства,
    размеры). Валидирует наличие обязательных данных.
    """
    from app.calc.fire_normative import (
        FireNormativeContext, FireBuildingKind, FireSpaceKind)
    from app.calc.fire_layout import RectangularRoom
    from app.calc.fire_models import PlacementMode

    if not project.fire_rooms:
        raise ValueError("project.fire_rooms пуст — нечего строить")
    b = project.building
    fire_height_m = b.fire_height_m
    if fire_height_m is None or fire_height_m <= 0:
        raise ValueError(
            "building.fire_height_m не задан — нужна пожарно-техническая "
            "высота для СП 10"
        )
    streams = project.fire.streams
    if streams not in (1, 2):
        raise ValueError(f"fire.streams={streams}: нужен 1 или 2 "
                         "(число расчётных струй, табл. 7.1)")

    bk = FireBuildingKind(_PURPOSE_TO_FIRE_KIND[b.purpose])
    out: List[Tuple[object, object]] = []
    for spec in project.fire_rooms:
        ctx = FireNormativeContext(
            building_kind=bk,
            space_kind=FireSpaceKind(spec.space_kind),
            room_height_m=spec.height_m,
            room_width_m=spec.width_m,
            building_height_m=fire_height_m,
            hose_length_m=float(project.fire.hose_length_m),
            placement_mode=PlacementMode(spec.placement_mode),
            required_jets_override=streams,
        )
        room = RectangularRoom(spec.room_id, spec.length_m, spec.width_m, spec.height_m)
        out.append((ctx, room))
    return out


def build_network(project: Project) -> object:
    """FireNetworkSpec → FireNetwork (магистраль + стояки + ПК + источник).

    Стояк разворачивается в: узел ПК (на cabinet_elevation_m) + участок от
    attach_node + FireCabinetNode с параметрами крана из FireSystem
    (Ду, рукав) и jet_m из спека стояка. Топологию (дерево/кольцо) билдер не
    определяет — граф покажет её сам солверу.
    """
    from app.calc.fire_hydraulics import (
        FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode,
        HydraulicSource, SourceKind)
    from app.data.pipe_catalog import steel_vgp_ordinary

    spec = project.fire_network
    if spec is None:
        raise ValueError("project.fire_network не задан — нечего строить")
    if not spec.source_node:
        raise ValueError("fire_network.source_node не задан")
    if not spec.nodes or not spec.segments:
        raise ValueError("fire_network: нужны nodes и segments магистрали")
    if not spec.risers:
        raise ValueError("fire_network: нет стояков (risers) — нет ПК")

    nodes = {n.node_id: HydraulicNode(n.node_id, n.elevation_m) for n in spec.nodes}
    node_ids = set(nodes)
    segments: List[PipeSegment] = [
        PipeSegment(s.segment_id, s.from_node, s.to_node,
                    length_m=s.length_m, A=s.A,
                    equiv_length_m=s.equiv_length_m, diameter_mm=s.dn,
                    inner_diameter_mm=steel_vgp_ordinary(s.dn).inner_mm,
                    repair_section_id=(s.repair_section_id or None))
        for s in spec.segments]

    cabinets: List[FireCabinetNode] = []
    fire = project.fire
    for r in spec.risers:
        if r.attach_node not in node_ids:
            raise ValueError(f"стояк {r.riser_id}: узел {r.attach_node} не в магистрали")
        pk_node = f"{r.riser_id}_top"
        cab_id = r.cabinet_id or f"{r.riser_id}-PK"
        nodes[pk_node] = HydraulicNode(pk_node, r.cabinet_elevation_m)
        segments.append(PipeSegment(
            f"{r.riser_id}_seg", r.attach_node, pk_node,
            length_m=r.length_m, A=r.A,
            equiv_length_m=r.equiv_length_m, diameter_mm=r.dn,
            inner_diameter_mm=steel_vgp_ordinary(r.dn).inner_mm))
        cabinets.append(FireCabinetNode(
            cabinet_id=cab_id, node_id=pk_node,
            dn=fire.nozzle_dn, hose_m=fire.hose_length_m,
            jet_m=r.jet_m, riser_id=r.riser_id,
            repair_section_id=(r.repair_section_id or None)))

    source = HydraulicSource(
        node_id=spec.source_node,
        kind=SourceKind(spec.source_kind),
        available_head_m=spec.available_head_m,
        water_level_m=spec.water_level_m,
        suction_head_loss_m=spec.suction_head_loss_m)

    second = None
    if spec.second_source_node:
        second = HydraulicSource(
            node_id=spec.second_source_node, kind=SourceKind(spec.source_kind),
            available_head_m=spec.second_available_head_m)
    net = FireNetwork(nodes=nodes, segments=segments, cabinets=cabinets,
                      source=source, second_source=second)
    problems = net.validate()
    if problems:
        raise ValueError("построенная сеть невалидна: " + "; ".join(problems))
    return net


def project_has_layout_geometry(project: Project) -> bool:
    return bool(project.fire_rooms)


def project_has_network_geometry(project: Project) -> bool:
    return project.fire_network is not None
