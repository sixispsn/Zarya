# -*- coding: utf-8 -*-
"""Тесты моста подбора насоса и его интеграции в ПЗ."""
from app.pz.pump_bridge import compute_pump, head_components


def test_zero_flow_no_pump():
    ps, h = compute_pump(q_design_m3h=0, floors=12)
    assert ps.required is False and h == 0.0


def test_pump_selected_with_working_point():
    ps, h_req = compute_pump(q_design_m3h=6.57, floors=12, h_gar_m=26.0)
    assert ps.required is True
    assert ps.model
    assert ps.wp_q > 0 and ps.wp_h > 0
    assert ps.power_kw > 0
    assert h_req > 0


def test_pump_curve_is_tuples():
    ps, _ = compute_pump(q_design_m3h=6.57, floors=12)
    assert ps.curve
    assert all(len(pt) == 2 for pt in ps.curve)


def test_pump_has_system_curve():
    ps, _ = compute_pump(q_design_m3h=6.57, floors=12)
    assert ps.k_sys > 0
    assert ps.h_stat > 0


def test_head_components_sum():
    hc = head_components(q_design_m3h=6.57, floors=12, h_losses_m=8.0,
                         h_pr_m=20.0, h_gar_m=26.0)
    assert abs(hc["h_required_m"] - (hc["h_geom_m"] + hc["h_losses_m"] + hc["h_pr_m"]
                                     - hc["h_gar_m"])) < 0.5


def _request():
    from app.intake.request_dto import (IOS2Request, DocumentRequest, RoomRequest,
        NetworkRequest, MainRunRequest, RiserRequest, ConsumerGroupRequest)
    return IOS2Request(
        document=DocumentRequest(cipher="Т", object_name="О", organization="Орг"),
        building_type="residential", floors=12, building_height_m=36.0, streams=2,
        rooms=[RoomRequest("Коридор", 24, 2.4, 3.0)],
        consumers=[ConsumerGroupRequest("residential_central_hw", 260)],
        network=NetworkRequest(
            runs=[MainRunRequest("У1", "У2", 22), MainRunRequest("У2", "У3", 12),
                  MainRunRequest("У3", "У4", 22), MainRunRequest("У4", "У1", 12)],
            risers=[RiserRequest("Ст-1", "У1", 35, 33.5),
                    RiserRequest("Ст-2", "У3", 35, 33.5)],
            source_node="У1", available_head_m=30.0))


def test_orchestrator_fills_pump_and_head(tmp_path):
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    bundle = design_ios2(build_project(_request()), output_dir=str(tmp_path))
    assert bundle.project.pumps.required is True
    assert bundle.project.pumps.model
    assert bundle.project.pumps.wp_q > 0
    assert any("pump:" in status for status in bundle.status)


def test_pz_shows_pump_not_placeholder(tmp_path):
    import re
    from pypdf import PdfReader
    from app.intake.project_builder import build_project
    from app.pz.generator import _pump_chart_svg
    from app.pz.ios2_orchestrator import design_ios2
    bundle = design_ios2(build_project(_request()), output_dir=str(tmp_path))
    pz = re.sub(r"\s+", " ", "".join(
        page.extract_text() for page in PdfReader(bundle.pz_pdf).pages))
    assert "МОДЕЛЬ НАСОСА" not in pz
    assert "CR" in pz
    assert "<svg" in _pump_chart_svg(bundle.project)
