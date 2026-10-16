"""Golden СП 30, 8.28: один k_l для участков, вводов и сводной ПЗ."""

from dataclasses import replace

import pytest

from app.calc.pumps import PumpInput, calculate_pump
from app.calc.v1_hydraulics import (
    V1InletInput, V1NetworkSectionInput, V1NodeInput, V1SectionInput,
    apply_v1_inlets, calculate_v1_hydraulics, calculate_v1_network,
)
from app.calc.water_local_losses import local_loss_factor, with_fire_topology
from app.pz.project import WaterSource
from app.pz.rules import calc_required_head


CASES = [
    ("domestic", .30, 55.10),
    ("combined", .20, 54.40),
    ("industrial", .20, 54.40),
    ("industrial_fire", .15, 54.05),
    ("fire", .10, 53.70),
]


@pytest.mark.parametrize("kind,factor,expected", CASES)
def test_formula_15_golden_and_legacy_pump_aggregate(kind, factor, expected):
    head = calc_required_head(WaterSource(
        network_kind=kind, h_geom_m=25, il_dict_m=5, il_vvod_m=2,
        h_pr_m=20, h_vod_m=1, guaranteed_head_m=10,
    ))
    assert head.km == factor
    assert head.h_required_m == expected
    # Ни отметки, ни 20 м, ни счётчик не умножены на коэффициент.
    assert head.h_losses_dynamic_m == round(7 * (1 + factor) + 1, 2)
    assert dict(head.components)[next(k for k, _ in head.components if "Hlввод" in k)] == round(2 * (1 + factor), 2)
    pump = calculate_pump(PumpInput(
        q_design_m3h=5, h_geom_manual=head.h_geom_m,
        h_losses=head.h_losses_dynamic_m, h_pr=head.h_pr_m, h_gar=10,
    ))
    # L02: ядро не округляет баланс до отображения на листе.
    assert pump.h_required == pytest.approx(head.h_pump_m)


@pytest.mark.parametrize("kind,factor,_", CASES)
def test_section_and_inlet_losses_use_same_factor(kind, factor, _):
    sections = [
        V1SectionInput("input", 10, 35, 1, .01, role="input"),
        V1SectionInput("internal", 20, 35, 1, .01),
    ]
    result = calculate_v1_hydraulics(sections, network_kind=kind)
    assert result.network_kind == kind
    for row in result.sections:
        assert row.local_loss_factor == factor
        assert row.total_loss_m == pytest.approx(row.linear_loss_m * (1 + factor), abs=.001)
    # Готовые результаты не получают вторую надбавку в ПЗ.
    head = calc_required_head(WaterSource(
        network_kind=kind, h_geom_m=25, h_il_m=result.internal_loss_m,
        h_vvod_m=result.input_loss_m, h_vod_m=1, h_pr_m=20,
    ))
    assert head.h_required_m == round(46 + result.total_loss_m, 2)


@pytest.mark.parametrize("kind,factor,_", CASES)
def test_tree_and_its_explicit_inlets_keep_network_kind(kind, factor, _):
    result = calculate_v1_network(
        [V1NodeInput("S", 0), V1NodeInput("A", 10, direct_demand_lps=.5),
         V1NodeInput("idle", 1)],
        [V1NetworkSectionInput("SA", "S", "A", 20, 35, .01),
         V1NetworkSectionInput("S-idle", "S", "idle", 10, 35, .01)],
        "S", network_kind=kind,
    )
    result = apply_v1_inlets(result, [V1InletInput("input", 10, 20, 15, 40, .01)])
    assert result.network_kind == kind
    assert all(row.local_loss_factor == factor for row in result.sections)
    assert result.input_loss_m == result.sections[0].total_loss_m


@pytest.mark.parametrize("kind,factor,_", CASES)
def test_ring_normal_and_failure_paths_use_same_factor(kind, factor, _):
    result = calculate_v1_network(
        [V1NodeInput("S", 0), V1NodeInput("A", 5, direct_demand_lps=.4),
         V1NodeInput("B", 10), V1NodeInput("C", 15, direct_demand_lps=.6)],
        [V1NetworkSectionInput("SA", "S", "A", 20, 40, .01),
         V1NetworkSectionInput("AB", "A", "B", 20, 32, .01),
         V1NetworkSectionInput("BC", "B", "C", 20, 32, .01),
         V1NetworkSectionInput("CS", "C", "S", 20, 40, .01)],
        "S", network_kind=kind,
    )
    assert result.ring_converged and len(result.ring_scenarios) == 4
    assert all(row.local_loss_factor == factor for row in result.sections + result.ring_normal_sections)


@pytest.mark.parametrize("supplied", [.1, .2, .15, 0, -1, float("nan"), float("inf"), True])
def test_arbitrary_or_conflicting_manual_percentage_is_rejected(supplied):
    with pytest.raises(ValueError, match="8.28"):
        local_loss_factor("domestic", supplied)


def test_unknown_network_never_silently_becomes_domestic():
    with pytest.raises(ValueError, match="Неизвестный тип сети"):
        calc_required_head(WaterSource(network_kind="typo"))


def test_15_percent_label_is_not_rounded_to_20_percent():
    result = calc_required_head(WaterSource(network_kind="industrial_fire", il_dict_m=5, il_vvod_m=2))
    assert sum("(1+0,15)" in name for name, _ in result.components) == 2


def test_production_purpose_is_preserved_when_fire_topology_changes():
    assert with_fire_topology("industrial", combined=True) == "industrial_fire"
    assert with_fire_topology("industrial_fire", combined=False) == "industrial"
    assert with_fire_topology("domestic", combined=True) == "combined"
    assert with_fire_topology("combined", combined=False) == "domestic"


def _project():
    from app.intake.project_builder import build_project
    from app.intake.request_dto import (
        ConsumerGroupRequest, DocumentRequest, IOS2Request, SourceDataRequest,
        V1SectionRequest, RoomRequest,
    )
    return build_project(IOS2Request(
        document=DocumentRequest("KL", "Проверка", "Заря"),
        building_type="residential", floors=12, building_height_m=36,
        fire_height_m=36, rooms=[RoomRequest("Коридор", 12, 2, 3)],
        fire_topology="combined", hws_type="none",
        consumers=[ConsumerGroupRequest("residential_central_hw", 100)],
        source_data=SourceDataRequest(
            guaranteed_head_m=5, h_geom_m=34, h_il_m=999, h_vvod_m=999,
        ),
        v1_sections=[
            V1SectionRequest("input", 10, 40, .7, .01, role="input"),
            V1SectionRequest("internal", 20, 35, .7, .01),
        ],
    ))


def test_orchestrator_passes_combined_kind_and_does_not_count_locals_twice(tmp_path):
    from app.pz.ios2_orchestrator import design_ios2
    from app.pz.generator import generate_pz_html
    p = design_ios2(_project(), output_dir=str(tmp_path), render_documents=False).project
    assert p.source.network_kind == "combined"
    assert all(r.local_loss_factor == .2 for r in p.v1_hydraulic_result.sections)
    assert p.source.h_il_m == p.v1_hydraulic_result.internal_loss_m
    assert p.source.h_vvod_m == p.v1_hydraulic_result.input_loss_m
    head = p.head_paths.cold.head
    assert head.h_required_m == round(34 + 20 + p.source.h_il_m + p.source.h_vvod_m + p.head_paths.cold.meter_loss_m, 2)
    # ПЗ сохраняет расчётную таблицу и фактический коэффициент.
    html = generate_pz_html(p)
    assert "Гидравлический расчёт диктующего направления В1" in html
    assert "0,20" in html


def test_failed_current_hydraulics_cannot_reuse_old_ready_losses(tmp_path):
    from app.pz.ios2_orchestrator import design_ios2
    p = _project()
    p.v1_sections[0] = replace(p.v1_sections[0], local_loss_factor=.3)
    bundle = design_ios2(p, output_dir=str(tmp_path), render_documents=False)
    p = bundle.project
    assert any("8.28" in warning for warning in bundle.warnings)
    assert p.source.h_il_m is None and p.source.h_vvod_m is None
    assert p.v1_hydraulic_result is None
    assert p.head_paths.cold.head.h_required_m is None
    assert not p.head_paths.complete
    assert not p.pumps.required


def test_orchestrator_network_and_inlets_receive_combined_coefficient(tmp_path):
    from app.pz.ios2_orchestrator import design_ios2
    from app.pz.project import V1NetworkSpec, V1NodeSpec, V1NetworkSectionSpec, V1InletSpec
    p = _project()
    p.v1_sections = []
    p.v1_network = V1NetworkSpec(
        "S", [V1NodeSpec("S", 0), V1NodeSpec("A", 34, direct_demand_lps=.7)],
        [V1NetworkSectionSpec("SA", "S", "A", 20, 35, .01)],
        [V1InletSpec("input", 5, 10, 10, 40, .01)],
    )
    p = design_ios2(p, output_dir=str(tmp_path), render_documents=False).project
    assert p.source.network_kind == "combined"
    assert p.v1_hydraulic_result.network_kind == "combined"
    assert all(r.local_loss_factor == .2 for r in p.v1_hydraulic_result.sections)
    assert p.source.h_vvod_m < 999 and p.source.h_il_m < 999


def test_failed_network_does_not_fall_back_to_old_losses_or_sections(tmp_path):
    from app.pz.ios2_orchestrator import design_ios2
    from app.pz.project import V1NetworkSpec, V1NodeSpec, V1NetworkSectionSpec
    p = _project()
    p.v1_network = V1NetworkSpec(
        "S", [V1NodeSpec("S", 0), V1NodeSpec("A", 34, direct_demand_lps=.7)],
        [V1NetworkSectionSpec("SA", "S", "A", 20, 35, .01, local_loss_factor=.3)],
    )
    bundle = design_ios2(p, output_dir=str(tmp_path), render_documents=False)
    assert any("8.28" in warning for warning in bundle.warnings)
    assert bundle.project.v1_hydraulic_result is None
    assert bundle.project.head_paths.cold.head.h_required_m is None
    assert not bundle.project.pumps.required
