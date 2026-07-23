# -*- coding: utf-8 -*-
"""Тесты app/pz/geometry_builder.py — автопостроение геометрии из спецификаций."""
import pytest

from app.pz.project import (
    Project, DocumentInfo, BuildingFlags, BuildingPurpose, FireSystem,
    FireRoomSpec, FireNetworkSpec, MainNodeSpec, MainSegmentSpec, RiserSpec,
)
from app.pz.geometry_builder import (
    build_layout_inputs, build_network,
    project_has_layout_geometry, project_has_network_geometry,
)


def _project():
    p = Project()
    p.building = BuildingFlags(
        purpose=BuildingPurpose.PUBLIC,
        floors_above=9,
        height_m=30.0,
        fire_height_m=30.0,
    )
    p.fire = FireSystem(required=True, streams=2, nozzle_dn=50, hose_length_m=20)
    p.fire_rooms = [FireRoomSpec("corr", 48, 12, 3.0, space_kind="corridor",
                                 placement_mode="two_opposite_sides")]
    p.fire_network = FireNetworkSpec(
        nodes=[MainNodeSpec("R0"), MainNodeSpec("R1"), MainNodeSpec("R2"),
               MainNodeSpec("R3")],
        segments=[MainSegmentSpec("L01", "R0", "R1", 20, 0.002, dn=100),
                  MainSegmentSpec("L12", "R1", "R2", 25, 0.002, dn=100),
                  MainSegmentSpec("L23", "R2", "R3", 20, 0.002, dn=100),
                  MainSegmentSpec("L30", "R3", "R0", 25, 0.002, dn=100)],
        risers=[RiserSpec("СТ-1", "R1", 27.5, 27.5),
                RiserSpec("СТ-2", "R2", 27.5, 27.5)],
        source_node="R0", source_kind="city_main", available_head_m=39.0)
    return p


# ── layout inputs ────────────────────────────────────────────────────────────

def test_layout_inputs_built():
    inputs = build_layout_inputs(_project())
    assert len(inputs) == 1
    ctx, room = inputs[0]
    assert room.room_id == "corr"
    assert room.length_m == 48
    assert ctx.building_height_m == 30.0
    assert ctx.required_jets_override == 2   # из fire.streams


def test_layout_maps_purpose():
    from app.calc.fire_normative import FireBuildingKind
    p = _project()
    p.building.purpose = BuildingPurpose.RESIDENTIAL
    ctx, _ = build_layout_inputs(p)[0]
    assert ctx.building_kind == FireBuildingKind.RESIDENTIAL


def test_layout_requires_height():
    p = _project()
    p.building.fire_height_m = None
    with pytest.raises(ValueError, match="height_m"):
        build_layout_inputs(p)


def test_layout_requires_streams():
    p = _project()
    p.fire.streams = 0
    with pytest.raises(ValueError, match="streams"):
        build_layout_inputs(p)


def test_layout_empty_rooms_raises():
    p = _project()
    p.fire_rooms = []
    with pytest.raises(ValueError, match="пуст"):
        build_layout_inputs(p)


# ── network ──────────────────────────────────────────────────────────────────

def test_network_built():
    net = build_network(_project())
    # 4 узла магистрали + 2 вершины стояков
    assert len(net.nodes) == 6
    # 4 участка кольца + 2 стояка
    assert len(net.segments) == 6
    assert len(net.cabinets) == 2
    assert net.validate() == []
    assert next(s for s in net.segments if s.diameter_mm == 100).inner_diameter_mm == 105.0
    assert next(s for s in net.segments if s.diameter_mm == 50).inner_diameter_mm == 53.0


def test_network_is_ring():
    net = build_network(_project())
    assert net.is_acyclic() is False   # кольцевая магистраль


def test_network_preserves_repair_section_links():
    p = _project()
    p.fire_network.segments[0].repair_section_id = "РС-1"
    p.fire_network.risers[0].repair_section_id = "РС-1"
    net = build_network(p)
    assert net.segments[0].repair_section_id == "РС-1"
    assert net.cabinets[0].repair_section_id == "РС-1"


def test_network_cabinet_params_from_fire():
    p = _project()
    p.fire.nozzle_dn = 50
    p.fire.hose_length_m = 20
    net = build_network(p)
    cab = net.cabinets[0]
    assert cab.dn == 50 and cab.hose_m == 20
    assert cab.riser_id == "СТ-1"


def test_network_riser_elevation():
    net = build_network(_project())
    top = net.nodes["СТ-1_top"]
    assert top.elevation_m == 27.5


def test_network_missing_source_raises():
    p = _project()
    p.fire_network.source_node = ""
    with pytest.raises(ValueError, match="source_node"):
        build_network(p)


def test_network_bad_attach_raises():
    p = _project()
    p.fire_network.risers[0].attach_node = "NOPE"
    with pytest.raises(ValueError, match="NOPE"):
        build_network(p)


def test_network_no_risers_raises():
    p = _project()
    p.fire_network.risers = []
    with pytest.raises(ValueError, match="стояков"):
        build_network(p)


# ── предикаты наличия геометрии ──────────────────────────────────────────────

def test_geometry_predicates():
    p = _project()
    assert project_has_layout_geometry(p)
    assert project_has_network_geometry(p)
    p2 = Project()
    assert not project_has_layout_geometry(p2)
    assert not project_has_network_geometry(p2)


# ── one-click через оркестратор ──────────────────────────────────────────────

def test_one_click_full_pipeline(tmp_path):
    from app.pz.ios2_orchestrator import design_ios2
    p = _project()
    p.document = DocumentInfo(cipher="ТЕСТ-ИОС2", object_name="Объект",
                              organization="Орг")
    from app.pz.project import PumpSystem, FlowsData
    p.pumps = PumpSystem(required=True)
    p.flows = FlowsData()
    b = design_ios2(p, output_dir=str(tmp_path))
    # геометрия построена автоматически
    joined = " ".join(b.status)
    assert "layout_inputs построены" in joined
    assert "network построена" in joined
    # полный расчёт прошёл — кольцо через Кросса
    assert b.project.fire.pk_total > 0
    assert b.project.fire.required_head_m is not None
    # никаких skip-предупреждений
    assert not any("skipped" in w for w in b.warnings)
    # все четыре документа
    assert b.pz_pdf and b.spec_pdf and b.scheme_pdf and b.hydraulic_pdf


def test_explicit_args_have_priority(tmp_path):
    # явно переданный network важнее спецификации проекта
    from app.pz.ios2_orchestrator import design_ios2
    from app.pz.geometry_builder import build_network
    p = _project()
    p.document = DocumentInfo(cipher="Т", object_name="О", organization="Орг")
    from app.pz.project import PumpSystem, FlowsData
    p.pumps = PumpSystem(required=True); p.flows = FlowsData()
    explicit = build_network(p)
    explicit.source.available_head_m = 999.0   # маркер
    b = design_ios2(p, output_dir=str(tmp_path), network=explicit)
    # использована явная сеть (напор 999 → насос не нужен)
    assert b.project.fire.needs_pump is False
    # и в status НЕТ пометки про построение network из спеки
    assert not any("network построена" in s for s in b.status)
