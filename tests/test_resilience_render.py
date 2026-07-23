# -*- coding: utf-8 -*-
"""Тесты листа живучести: рендер + встройка в оркестратор."""
import os
import pytest

from app.pz.project import Project, DocumentInfo
from app.calc.ring_hydraulics import analyze_ring_resilience
from app.pz.generator import generate_resilience_html, generate_resilience_pdf


def _net(available=70.0):
    from app.calc.fire_hydraulics import (
        FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode,
        HydraulicSource, SourceKind)
    net = FireNetwork(
        nodes={"К1": HydraulicNode("К1", 0.0), "К2": HydraulicNode("К2", 0.0),
               "К3": HydraulicNode("К3", 0.0), "К4": HydraulicNode("К4", 0.0),
               "t1": HydraulicNode("t1", 45.6), "t3": HydraulicNode("t3", 45.6)},
        segments=[
            PipeSegment("М1", "К1", "К2", length_m=36, A=0.0023, equiv_length_m=6, diameter_mm=100),
            PipeSegment("М2", "К2", "К3", length_m=15, A=0.0023, equiv_length_m=4, diameter_mm=100),
            PipeSegment("М3", "К3", "К4", length_m=36, A=0.0023, equiv_length_m=6, diameter_mm=100),
            PipeSegment("М4", "К4", "К1", length_m=15, A=0.0023, equiv_length_m=4, diameter_mm=100),
            PipeSegment("с1", "К1", "t1", length_m=46.5, A=0.011, equiv_length_m=6, diameter_mm=65),
            PipeSegment("с3", "К3", "t3", length_m=46.5, A=0.011, equiv_length_m=6, diameter_mm=65)],
        cabinets=[FireCabinetNode("ПК-1", "t1", riser_id="R1"),
                  FireCabinetNode("ПК-3", "t3", riser_id="R3")],
        source=HydraulicSource("К1", kind=SourceKind.CITY_MAIN, available_head_m=available))
    for seg in net.segments[:4]:
        seg.repair_section_id = f"РС-{seg.segment_id}"
    for cabinet, seg in zip(net.cabinets, net.segments[:2]):
        cabinet.repair_section_id = seg.repair_section_id
    return net


def _proj():
    p = Project()
    p.document = DocumentInfo(cipher="Т-ИОС2", object_name="Объект",
                              organization="Орг")
    return p


def test_html_has_all_blocks():
    rep = analyze_ring_resilience(_net(), 2)
    html = generate_resilience_html(_proj(), rep)
    for token in ("живучести", "Штатный режим", "Худший случай", "Заключение",
                  "Т-ИОС2.ЖВ"):
        assert token in html


def test_html_positive_verdict():
    rep = analyze_ring_resilience(_net(70.0), 2)
    html = generate_resilience_html(_proj(), rep)
    assert "сохраняет работоспособность" in html


def test_html_negative_verdict():
    rep = analyze_ring_resilience(_net(60.0), 2)
    html = generate_resilience_html(_proj(), rep)
    assert "не подтверждает работоспособность" in html


def test_pdf_is_a4(tmp_path):
    from pypdf import PdfReader
    rep = analyze_ring_resilience(_net(), 2)
    out = str(tmp_path / "r.pdf")
    generate_resilience_pdf(_proj(), rep, out)
    box = PdfReader(out).pages[0].mediabox
    assert abs(float(box.width) / 72 * 25.4 - 210) < 2
    assert abs(float(box.height) / 72 * 25.4 - 297) < 2


def test_orchestrator_includes_resilience(tmp_path):
    from app.intake.request_dto import (IOS2Request, DocumentRequest, RoomRequest,
                                        NetworkRequest, MainRunRequest, RiserRequest)
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    req = IOS2Request(
        document=DocumentRequest(cipher="Т", object_name="О", organization="Орг"),
        building_type="residential", floors=16, building_height_m=48.0,
        fire_height_m=48.0, streams=2,
        rooms=[RoomRequest("Коридор", 42, 2.4, 3.0)],
        network=NetworkRequest(
            runs=[MainRunRequest("К1", "К2", 36), MainRunRequest("К2", "К3", 15),
                  MainRunRequest("К3", "К4", 36), MainRunRequest("К4", "К1", 15)],
            risers=[RiserRequest("СТ-1", "К1", 46.5, 45.6),
                    RiserRequest("СТ-2", "К2", 46.5, 45.6)],
            source_node="К1", available_head_m=70.0))
    b = design_ios2(build_project(req), output_dir=str(tmp_path))
    assert b.resilience_report is not None
    assert b.resilience_pdf and os.path.exists(b.resilience_pdf)
    assert any("ring_resilience" in s for s in b.status)


def test_orchestrator_no_resilience_for_tree(tmp_path):
    # дерево (не кольцо) → живучесть не считается, лист не генерится
    from app.intake.request_dto import (IOS2Request, DocumentRequest, RoomRequest,
                                        NetworkRequest, MainRunRequest, RiserRequest)
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    req = IOS2Request(
        document=DocumentRequest(cipher="Т", object_name="О", organization="Орг"),
        building_type="residential", floors=16, building_height_m=48.0,
        fire_height_m=48.0, streams=2,
        rooms=[RoomRequest("Коридор", 42, 2.4, 3.0)],
        network=NetworkRequest(
            runs=[MainRunRequest("К1", "К2", 36), MainRunRequest("К2", "К3", 15)],
            risers=[RiserRequest("СТ-1", "К2", 46.5, 45.6),
                    RiserRequest("СТ-2", "К3", 46.5, 45.6)],
            source_node="К1", available_head_m=70.0))
    b = design_ios2(build_project(req), output_dir=str(tmp_path))
    assert b.resilience_report is None
    assert b.resilience_pdf is None
