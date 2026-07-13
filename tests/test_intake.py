# -*- coding: utf-8 -*-
"""Тесты слоя ввода: RequestDTO → ProjectBuilder → Project (→ design_ios2)."""
import pytest

from app.intake.request_dto import (
    IOS2Request, DocumentRequest, RoomRequest, NetworkRequest,
    MainRunRequest, RiserRequest,
)
from app.intake.project_builder import build_project, RequestValidationError
from app.pz.project import BuildingPurpose


def _req(**overrides):
    base = dict(
        document=DocumentRequest(cipher="Т-ИОС2", object_name="Объект",
                                 organization="Орг"),
        building_type="residential", floors=16, building_height_m=48.0,
        streams=2,
        rooms=[RoomRequest("Коридор", 42.0, 2.4, 3.0)],
        network=NetworkRequest(
            runs=[MainRunRequest("К1", "К2", 36), MainRunRequest("К2", "К3", 15),
                  MainRunRequest("К3", "К4", 36), MainRunRequest("К4", "К1", 15)],
            risers=[RiserRequest("СТ-1", "К1", 46.5, 45.6),
                    RiserRequest("СТ-2", "К2", 46.5, 45.6)],
            source_node="К1", available_head_m=32.0),
    )
    base.update(overrides)
    return IOS2Request(**base)


# ── валидация намерения ──────────────────────────────────────────────────────

def test_valid_request_passes():
    assert _req().validate() == []


def test_bad_building_type():
    assert any("building_type" in p for p in _req(building_type="жилое").validate())


def test_bad_streams():
    assert any("streams" in p for p in _req(streams=3).validate())


def test_missing_cipher():
    r = _req(document=DocumentRequest(cipher="", object_name="X", organization="Y"))
    assert any("cipher" in p for p in r.validate())


def test_riser_at_unknown_node():
    r = _req()
    r.network.risers[0].at_node = "НЕТ"
    assert any("НЕТ" in p for p in r.validate())


def test_source_not_in_runs():
    r = _req()
    r.network.source_node = "К99"
    assert any("К99" in p for p in r.validate())


def test_validation_collects_all_problems():
    bad = IOS2Request(document=DocumentRequest("", "", ""),
                      building_type="x", floors=0, building_height_m=-1)
    assert len(bad.validate()) >= 4   # все проблемы разом, не первая


# ── Builder: маппинг намерения в модель ──────────────────────────────────────

def test_builder_raises_on_invalid():
    with pytest.raises(RequestValidationError):
        build_project(_req(building_type="жилое"))


def test_builder_maps_building_type():
    p = build_project(_req())
    assert p.building.purpose == BuildingPurpose.RESIDENTIAL
    assert p.building.floors_above == 16
    assert p.building.height_m == 48.0


def test_builder_fills_fire_system():
    p = build_project(_req())
    assert p.fire.streams == 2
    assert p.fire.q_total == pytest.approx(5.2)
    assert p.fire.nozzle_dn == 50


def test_builder_streams_none_stays_zero():
    # streams не задан → 0 (honest: билдер геометрии потребует явно)
    p = build_project(_req(streams=None))
    assert p.fire.streams == 0


def test_builder_builds_rooms():
    p = build_project(_req())
    assert len(p.fire_rooms) == 1
    assert p.fire_rooms[0].length_m == 42.0


def test_builder_builds_network_from_runs():
    p = build_project(_req())
    net = p.fire_network
    # узлы собраны из участков
    assert {n.node_id for n in net.nodes} == {"К1", "К2", "К3", "К4"}
    assert len(net.segments) == 4
    assert len(net.risers) == 2
    assert net.source_node == "К1"


def test_builder_node_elevations():
    r = _req()
    r.network.node_elevations = {"К2": -1.5}
    p = build_project(r)
    k2 = next(n for n in p.fire_network.nodes if n.node_id == "К2")
    assert k2.elevation_m == -1.5


def test_builder_no_network():
    p = build_project(_req(network=None))
    assert p.fire_network is None


# ── сквозная цепочка: намерение → комплект ───────────────────────────────────

def test_end_to_end_dto_to_pdfs(tmp_path):
    from app.pz.ios2_orchestrator import design_ios2
    project = build_project(_req())
    b = design_ios2(project, output_dir=str(tmp_path))
    assert b.project.fire.pk_total > 0
    assert b.project.fire.needs_pump is True     # 32 м на 16 этажей не хватит
    assert b.pz_pdf and b.spec_pdf and b.scheme_pdf and b.hydraulic_pdf
    assert not any("skipped" in w for w in b.warnings)


# ── валидация связности сети (заход: до расчёта, человеческим языком) ────────

def test_disconnected_main_caught():
    r = _req()
    r.network.runs = [MainRunRequest("К1", "К2", 30), MainRunRequest("К3", "К4", 30)]
    r.network.risers = [RiserRequest("СТ-1", "К1", 46.5, 45.6)]
    probs = r.validate()
    assert any("разорвана" in p and "К3" in p for p in probs)


def test_riser_on_unreachable_node_caught():
    r = _req()
    r.network.runs = [MainRunRequest("К1", "К2", 30), MainRunRequest("К3", "К4", 30)]
    r.network.risers = [RiserRequest("СТ-X", "К3", 46.5, 45.6)]
    probs = r.validate()
    assert any("СТ-X" in p and "не дойдёт" in p for p in probs)


def test_duplicate_run_caught():
    r = _req()
    r.network.runs = list(r.network.runs) + [MainRunRequest("К2", "К1", 99)]
    # К1-К2 уже есть (в любом направлении — та же пара)
    assert any("дублирующиеся" in p for p in r.validate())


def test_duplicate_riser_names_caught():
    r = _req()
    r.network.risers = [RiserRequest("СТ-1", "К1", 46.5, 45.6),
                        RiserRequest("СТ-1", "К2", 46.5, 45.6)]
    assert any("повторяются" in p for p in r.validate())


def test_connected_ring_passes():
    assert _req().validate() == []   # базовое кольцо связно — чисто
