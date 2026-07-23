# -*- coding: utf-8 -*-
"""Тесты моста расходов В1 и его интеграции в ПЗ."""
import pytest

from app.pz.demand_bridge import compute_flows
from app.pz.project import FlowsData


def test_empty_groups_zero_flows():
    f = compute_flows([])
    assert f.q_day_tot == 0.0


def test_residential_computes_nonzero():
    f = compute_flows([("residential_central_hw", 260)])
    assert f.q_day_tot > 0
    assert f.q_sec_tot > 0
    assert f.q_day_c > 0 and f.q_day_h > 0        # ХВС и ГВС раздельно
    assert f.heat_max_kw > 0                       # тепло на ГВС


def test_cold_hot_sum_consistency():
    f = compute_flows([("residential_central_hw", 260)])
    # суточный: холодная + горячая ≈ общий (в пределах округления)
    assert abs((f.q_day_c + f.q_day_h) - f.q_day_tot) < 1.0


def test_alpha_not_arithmetic_sum():
    # удвоение жителей НЕ удваивает секундный расход (α срезает пик)
    f1 = compute_flows([("residential_central_hw", 100)])
    f2 = compute_flows([("residential_central_hw", 200)])
    assert f2.q_sec_tot < 2 * f1.q_sec_tot         # вероятностный метод


def test_zero_count_ignored():
    assert compute_flows([("residential_central_hw", 0)]).q_day_tot == 0.0


def test_orchestrator_fills_flows(tmp_path):
    from app.intake.request_dto import (IOS2Request, DocumentRequest, RoomRequest,
        NetworkRequest, MainRunRequest, RiserRequest, ConsumerGroupRequest)
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    req = IOS2Request(
        document=DocumentRequest(cipher="Т", object_name="О", organization="Орг"),
        building_type="residential", floors=12, building_height_m=36.0,
        fire_height_m=36.0, streams=2,
        rooms=[RoomRequest("Коридор", 24, 2.4, 3.0)],
        consumers=[ConsumerGroupRequest("residential_central_hw", 260)],
        network=NetworkRequest(
            runs=[MainRunRequest("У1","У2",22), MainRunRequest("У2","У3",12),
                  MainRunRequest("У3","У4",22), MainRunRequest("У4","У1",12)],
            risers=[RiserRequest("Ст-1","У1",35,33.5), RiserRequest("Ст-2","У3",35,33.5)],
            source_node="У1", available_head_m=30.0))
    b = design_ios2(build_project(req), output_dir=str(tmp_path))
    assert b.project.flows.q_day_tot > 0            # не нули!
    assert any("water_demand" in s for s in b.status)


def test_orchestrator_warns_without_consumers(tmp_path):
    from app.intake.request_dto import (IOS2Request, DocumentRequest, RoomRequest,
        NetworkRequest, MainRunRequest, RiserRequest)
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    req = IOS2Request(
        document=DocumentRequest(cipher="Т", object_name="О", organization="Орг"),
        building_type="residential", floors=12, building_height_m=36.0,
        fire_height_m=36.0, streams=2,
        rooms=[RoomRequest("Коридор", 24, 2.4, 3.0)],
        network=NetworkRequest(
            runs=[MainRunRequest("У1","У2",22), MainRunRequest("У2","У3",12),
                  MainRunRequest("У3","У4",22), MainRunRequest("У4","У1",12)],
            risers=[RiserRequest("Ст-1","У1",35,33.5), RiserRequest("Ст-2","У3",35,33.5)],
            source_node="У1", available_head_m=30.0))
    b = design_ios2(build_project(req), output_dir=str(tmp_path))
    assert any("группы потребителей не заданы" in w for w in b.warnings)
