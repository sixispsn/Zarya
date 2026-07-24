# -*- coding: utf-8 -*-
"""Тесты app/pz/ios2_orchestrator.py — pipeline coordinator, два режима."""
import os
import pytest

from app.pz.project import (
    Project, DocumentInfo, BuildingFlags, BuildingPurpose, FireSystem,
    PumpSystem, FlowsData,
)
from app.pz.ios2_orchestrator import design_ios2, IOS2DesignBundle


def _project():
    p = Project()
    p.document = DocumentInfo(cipher="2026-14-ИОС2", object_name="Жилой дом",
                              object_part="Корпус 1", organization="ООО «Заря»",
                              developer_name="Иванов", gip_name="Сидоров")
    p.building = BuildingFlags(purpose=BuildingPurpose.RESIDENTIAL, floors_above=14, zones=2)
    p.fire = FireSystem(required=True, streams=2, q_per_stream=2.6, q_total=5.2,
                        nozzle_dn=50, hose_length_m=20)
    p.pumps = PumpSystem(required=True)
    p.flows = FlowsData()
    return p


def _calc_inputs():
    from app.calc.fire_normative import (
        FireNormativeContext, FireBuildingKind, FireSpaceKind)
    from app.calc.fire_layout import RectangularRoom
    from app.calc.fire_models import PlacementMode
    from app.calc.fire_hydraulics import (
        FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode,
        HydraulicSource, SourceKind)
    ctx = FireNormativeContext(
        building_kind=FireBuildingKind.RESIDENTIAL, space_kind=FireSpaceKind.CORRIDOR,
        room_height_m=3.0, room_width_m=12.0, building_height_m=42.0,
        placement_mode=PlacementMode.TWO_OPPOSITE_SIDES, required_jets_override=2)
    room = RectangularRoom("corridor_1", 48.0, 12.0, 3.0)
    net = FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "fork": HydraulicNode("fork", 0.0),
               "a": HydraulicNode("a", 27.5), "b": HydraulicNode("b", 27.5)},
        segments=[PipeSegment("mag", "src", "fork", length_m=30, A=0.00246, equiv_length_m=8, diameter_mm=65),
                  PipeSegment("rA", "fork", "a", length_m=27.5, A=0.011, equiv_length_m=4, diameter_mm=50),
                  PipeSegment("rB", "fork", "b", length_m=27.5, A=0.011, equiv_length_m=4, diameter_mm=50)],
        cabinets=[FireCabinetNode("PK-A", "a", riser_id="R1"),
                  FireCabinetNode("PK-B", "b", riser_id="R2")],
        source=HydraulicSource("src", kind=SourceKind.CITY_MAIN, available_head_m=30.0))
    return [(ctx, room)], net


# ── режим 2: только документы ────────────────────────────────────────────────

def test_mode2_builds_documents_only(tmp_path):
    b = design_ios2(_project(), output_dir=str(tmp_path))
    assert isinstance(b, IOS2DesignBundle)
    assert b.pz_pdf and os.path.exists(b.pz_pdf)
    assert b.v1_calculation_pdf and os.path.exists(b.v1_calculation_pdf)
    assert b.spec_pdf and os.path.exists(b.spec_pdf)
    # гидролист НЕ собран (нет отчёта)
    assert b.hydraulic_pdf is None


def test_mode2_warns_about_skipped(tmp_path):
    b = design_ios2(_project(), output_dir=str(tmp_path))
    joined = " ".join(b.warnings)
    assert "fire_layout skipped" in joined
    assert "fire_hydraulics skipped" in joined
    assert "pre-filled project.fire" in joined


def test_mode2_does_not_invent_pk_total(tmp_path):
    p = _project()
    p.fire = FireSystem(required=True, pk_total=0)  # не заполнено
    b = design_ios2(p, output_dir=str(tmp_path))
    # оркестратор НЕ придумал pk_total — как было 0, так и осталось
    assert b.project.fire.pk_total == 0


def test_mode2_no_hydraulic_result(tmp_path):
    b = design_ios2(_project(), output_dir=str(tmp_path))
    assert b.fire_hydraulic_result is None
    assert b.diameter_audit is None


# ── режим 2 с готовым отчётом ────────────────────────────────────────────────

def test_mode2_with_prebuilt_report(tmp_path):
    _, net = _calc_inputs()
    from app.calc.fire_hydraulics import solve_fire_hydraulics_scenario, NetworkMode
    from app.calc.diameter_audit import audit_sections
    from app.calc.fire_hydraulic_report import build_hydraulic_report
    r = solve_fire_hydraulics_scenario(net, 2, mode=NetworkMode.PURE_FIRE)
    audit = audit_sections(r.dictating_scenario.sections, NetworkMode.PURE_FIRE,
                           dn_by_segment={"mag": 65, "rA": 50, "rB": 50})
    report = build_hydraulic_report(r, audit)
    # передаём готовый отчёт без network → гидролист собирается
    b = design_ios2(_project(), output_dir=str(tmp_path), hydraulic_report=report)
    assert b.hydraulic_pdf and os.path.exists(b.hydraulic_pdf)


# ── режим 1: полный расчёт ───────────────────────────────────────────────────

def test_mode1_full_calculation(tmp_path):
    layout_inputs, net = _calc_inputs()
    b = design_ios2(_project(), output_dir=str(tmp_path),
                    layout_inputs=layout_inputs, network=net, required_jets=2,
                    dn_by_segment={"mag": 65, "rA": 50, "rB": 50})
    # все четыре документа
    assert b.pz_pdf and b.spec_pdf and b.scheme_pdf and b.hydraulic_pdf
    assert all(os.path.exists(x) for x in (b.pz_pdf, b.spec_pdf, b.scheme_pdf, b.hydraulic_pdf))


def test_mode1_enriches_fire_system(tmp_path):
    layout_inputs, net = _calc_inputs()
    b = design_ios2(_project(), output_dir=str(tmp_path),
                    layout_inputs=layout_inputs, network=net, required_jets=2)
    # pk_total из геометрии, напор/насос из гидравлики
    assert b.project.fire.pk_total > 0
    assert b.project.fire.needs_pump is True
    assert b.project.fire.required_head_m is not None


def test_mode1_produces_intermediate_results(tmp_path):
    layout_inputs, net = _calc_inputs()
    b = design_ios2(_project(), output_dir=str(tmp_path),
                    layout_inputs=layout_inputs, network=net, required_jets=2,
                    dn_by_segment={"mag": 65, "rA": 50, "rB": 50})
    # промежуточные результаты доступны для инспекции (швы видны)
    assert b.fire_layout_results is not None
    assert b.fire_hydraulic_result is not None
    assert b.diameter_audit is not None
    assert b.hydraulic_report is not None


def test_mode1_no_warnings_when_complete(tmp_path):
    layout_inputs, net = _calc_inputs()
    b = design_ios2(_project(), output_dir=str(tmp_path),
                    layout_inputs=layout_inputs, network=net, required_jets=2,
                    dn_by_segment={"mag": 65, "rA": 50, "rB": 50})
    # полный прогон — не должно быть warnings про пропуски
    skip_warns = [w for w in b.warnings if "skipped" in w]
    assert skip_warns == []


def test_mode1_status_records_each_step(tmp_path):
    layout_inputs, net = _calc_inputs()
    b = design_ios2(_project(), output_dir=str(tmp_path),
                    layout_inputs=layout_inputs, network=net, required_jets=2)
    joined = " ".join(b.status)
    assert "ГОСТ Р 21.619-2023" in joined
    assert "п. 5.1.21" in joined
    assert "fire_layout" in joined
    assert "fire_hydraulics" in joined
    assert "enrich_fire" in joined


# ── только гидравлика без layout ─────────────────────────────────────────────

def test_only_network_no_layout(tmp_path):
    _, net = _calc_inputs()
    b = design_ios2(_project(), output_dir=str(tmp_path), network=net, required_jets=2,
                    dn_by_segment={"mag": 65, "rA": 50, "rB": 50})
    # гидравлика посчитана, layout пропущен
    assert b.fire_hydraulic_result is not None
    assert b.fire_layout_results is None
    assert any("fire_layout skipped" in w for w in b.warnings)
    assert b.hydraulic_pdf is not None   # гидролист есть
