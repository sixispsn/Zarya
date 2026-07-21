import math

import pytest

from app.calc.v1_hydraulics import (
    V1InletInput, V1NetworkSectionInput, V1NodeInput, V1SectionInput,
    apply_v1_inlets, audit_v1_pressures, calculate_v1_hydraulics,
    calculate_v1_network, velocity_mps,
)
from app.calc.v1_stage_p import calculate_v1_stage_p


def test_darcy_weisbach_section_and_formula_15():
    section = V1SectionInput(
        section_id="1-2", length_m=20.0, inner_diameter_mm=35.0,
        flow_lps=1.0, roughness_mm=0.01,
    )
    result = calculate_v1_hydraulics([section])
    row = result.sections[0]
    expected_velocity = 0.001 / (math.pi * 0.035 ** 2 / 4)
    assert row.velocity_mps == pytest.approx(expected_velocity, abs=0.001)
    assert row.reynolds > 20_000
    assert row.friction_factor > 0
    assert row.total_loss_m == pytest.approx(row.linear_loss_m * 1.3, abs=0.002)
    assert result.internal_loss_m == row.total_loss_m
    assert result.input_loss_m == 0


def test_stage_p_checks_only_inlet_and_uses_exact_pipe_geometry():
    result = calculate_v1_stage_p(1.426, 2)
    inlet, riser, branch = result.rows
    assert inlet.flow_lps == 1.426  # каждый ввод несёт 100%, расход не делится на два
    assert (inlet.outer_mm, inlet.wall_mm, inlet.inner_mm) == (60.0, 3.5, 53.0)
    assert inlet.velocity_mps == pytest.approx(velocity_mps(1.426, 53.0), abs=0.001)
    assert inlet.velocity_ok is True
    assert (riser.outer_mm, riser.wall_mm, riser.inner_mm) == (32.0, 3.0, 26.0)
    assert (branch.outer_mm, branch.wall_mm, branch.inner_mm) == (20.0, 2.0, 16.0)
    assert riser.flow_lps is None and riser.velocity_mps is None
    assert branch.flow_lps is None and branch.velocity_mps is None


def test_internal_and_input_losses_are_separated():
    result = calculate_v1_hydraulics([
        V1SectionInput("Ввод", 12, 40, 1.2, 0.1, role="input"),
        V1SectionInput("М1", 18, 35, 1.0, 0.01, role="internal"),
        V1SectionInput("Ст1", 30, 28, 0.5, 0.01, role="internal"),
    ])
    assert result.input_loss_m == result.sections[0].total_loss_m
    assert result.internal_loss_m == pytest.approx(
        result.sections[1].total_loss_m + result.sections[2].total_loss_m, abs=0.001)
    assert result.total_loss_m == pytest.approx(
        result.internal_loss_m + result.input_loss_m, abs=0.001)


def test_velocity_limit_audit():
    result = calculate_v1_hydraulics([
        V1SectionInput("узкий", 10, 20, 1.0, 0.01, velocity_limit_mps=1.5),
    ])
    assert result.all_velocities_ok is False
    assert result.sections[0].velocity_ok is False


def test_network_distributes_subtree_flows_and_selects_dictating_node():
    result = calculate_v1_network(
        nodes=[
            V1NodeInput("Ввод", 0.0),
            V1NodeInput("Тройник", 1.0),
            V1NodeInput("Кв-1", 12.0, [("residential_central_hw", 40)]),
            V1NodeInput("Кв-2", 30.0, [("residential_central_hw", 60)]),
        ],
        sections=[
            V1NetworkSectionInput("Ввод-Т", "Ввод", "Тройник", 12, 40, 0.1,
                                  role="input"),
            V1NetworkSectionInput("Т-К1", "Тройник", "Кв-1", 18, 32, 0.01),
            V1NetworkSectionInput("Т-К2", "Тройник", "Кв-2", 35, 32, 0.01),
        ],
        source_node="Ввод",
    )
    by_id = {s.section_id: s for s in result.sections}
    assert by_id["Ввод-Т"].flow_lps == result.source_flow_lps
    assert by_id["Ввод-Т"].flow_lps > by_id["Т-К1"].flow_lps
    assert by_id["Ввод-Т"].flow_lps > by_id["Т-К2"].flow_lps
    # Вероятностный максимум общего поддерева не равен сумме максимумов ветвей.
    assert by_id["Ввод-Т"].flow_lps < (
        by_id["Т-К1"].flow_lps + by_id["Т-К2"].flow_lps)
    assert result.dictating_node_id == "Кв-2"
    assert result.dictating_path == ["Ввод-Т", "Т-К2"]
    assert result.input_loss_m == by_id["Ввод-Т"].total_loss_m
    assert result.internal_loss_m == by_id["Т-К2"].total_loss_m
    dictating = next(x for x in result.node_checks if x.node_id == "Кв-2")
    assert dictating.h_pr_m == 20.0
    assert dictating.required_before_common_m == pytest.approx(
        dictating.h_geom_m + dictating.internal_loss_m
        + dictating.input_loss_m + 20.0, abs=0.001)


def test_network_auto_selects_smallest_diameter_by_velocity_and_specific_loss():
    result = calculate_v1_network(
        [V1NodeInput("S", 0), V1NodeInput(
            "A", 10, [("residential_central_hw", 100)])],
        [V1NetworkSectionInput(
            "S-A", "S", "A", 20, None, 0.01,
            candidate_inner_diameters_mm=[40, 25, 32],
            max_specific_loss_m_per_m=0.03,
        )],
        "S",
    )
    section = result.sections[0]
    assert section.inner_diameter_mm == 32
    assert section.diameter_selection == "auto"
    assert section.velocity_mps <= section.velocity_limit_mps
    assert section.specific_loss_m_per_m <= 0.03


def test_network_auto_diameter_rejects_insufficient_series():
    with pytest.raises(ValueError, match="сортамент до 20 мм не обеспечивает"):
        calculate_v1_network(
            [V1NodeInput("S", 0), V1NodeInput("A", 1, direct_demand_lps=1.0)],
            [V1NetworkSectionInput(
                "S-A", "S", "A", 10, None, 0.01,
                candidate_inner_diameters_mm=[15, 20],
                max_specific_loss_m_per_m=0.03,
            )],
            "S",
        )


def test_two_inlets_each_carry_full_flow_and_worst_available_head_dictates():
    internal = calculate_v1_network(
        [V1NodeInput("S", 0), V1NodeInput("A", 12, direct_demand_lps=1.0)],
        [V1NetworkSectionInput("S-A", "S", "A", 25, 35, 0.01)],
        "S",
    )
    result = apply_v1_inlets(internal, [
        V1InletInput("Ввод-1", 30, 42, 20, 40, 0.1),
        V1InletInput("Ввод-2", 24, 38, 35, 32, 0.1),
    ])

    assert len(result.inlet_checks) == 2
    assert all(x.flow_lps == result.source_flow_lps for x in result.inlet_checks)
    assert result.all_inlets_100_percent_ok is True
    assert result.dictating_inlet_id == "Ввод-2"
    dictating = next(x for x in result.inlet_checks if x.inlet_id == "Ввод-2")
    assert result.input_loss_m == dictating.loss_m
    assert result.dictating_path == ["Ввод-2", "S-A"]
    assert {x.role for x in result.sections[:2]} == {"input"}


def test_explicit_inlets_reject_input_role_inside_network_tree():
    internal = calculate_v1_network(
        [V1NodeInput("S", 0), V1NodeInput("A", 1, direct_demand_lps=0.2)],
        [V1NetworkSectionInput("S-A", "S", "A", 5, 25, 0.01, role="input")],
        "S",
    )
    with pytest.raises(ValueError, match="должны иметь role=internal"):
        apply_v1_inlets(
            internal,
            [V1InletInput("Ввод-1", 20, 30, 10, 32, 0.1)],
        )


def test_pressure_audit_checks_minimum_maximum_and_splits_zones():
    hydraulic = calculate_v1_network(
        [V1NodeInput("S", 0),
         V1NodeInput("Низ", 5, direct_demand_lps=0.3),
         V1NodeInput("Верх", 60, direct_demand_lps=0.3)],
        [V1NetworkSectionInput("S-L", "S", "Низ", 10, 32, 0.01),
         V1NetworkSectionInput("S-H", "S", "Верх", 70, 32, 0.01)],
        "S",
    )
    dictating = next(x for x in hydraulic.node_checks
                     if x.node_id == hydraulic.dictating_node_id)
    result = audit_v1_pressures(
        hydraulic,
        required_source_head_m=dictating.required_before_common_m + 5,
        common_dynamic_loss_m=5,
        static_source_head_m=100,
    )
    by_node = {x.node_id: x for x in result.pressure_checks}
    assert by_node["Верх"].dynamic_head_m == pytest.approx(20, abs=0.002)
    assert by_node["Верх"].minimum_ok is True
    assert by_node["Низ"].static_head_m == 95
    assert by_node["Низ"].maximum_ok is False
    assert by_node["Верх"].maximum_ok is True
    assert result.all_minimum_pressures_ok is True
    assert result.all_maximum_pressures_ok is False
    assert len(result.pressure_zones) == 2
    assert all(zone.valid for zone in result.pressure_zones)
    regulators = {x.zone_id: x for x in result.zone_regulators}
    assert regulators["Зона 1"].section_id == "S-L"
    assert regulators["Зона 1"].required is True
    assert regulators["Зона 1"].topology_feasible is True
    assert regulators["Зона 1"].outlet_setpoint_m is not None
    assert regulators["Зона 1"].hydraulic_reserve_available is True
    assert regulators["Зона 1"].required_kv_m3h is not None
    assert regulators["Зона 2"].section_id == "S-H"
    assert regulators["Зона 2"].required is False


def test_zone_regulator_requires_separate_branch_for_pass_through_riser():
    hydraulic = calculate_v1_network(
        [V1NodeInput("S", 0),
         V1NodeInput("Низ", 5, direct_demand_lps=0.3),
         V1NodeInput("Верх", 60, direct_demand_lps=0.3)],
        [V1NetworkSectionInput("S-L", "S", "Низ", 10, 32, 0.01),
         V1NetworkSectionInput("L-H", "Низ", "Верх", 55, 32, 0.01)],
        "S",
    )
    dictating = next(x for x in hydraulic.node_checks
                     if x.node_id == hydraulic.dictating_node_id)
    result = audit_v1_pressures(
        hydraulic,
        required_source_head_m=dictating.required_before_common_m + 5,
        common_dynamic_loss_m=5,
        static_source_head_m=100,
    )
    assert len(result.pressure_zones) == 2
    low = next(x for x in result.zone_regulators if x.zone_id == "Зона 1")
    high = next(x for x in result.zone_regulators if x.zone_id == "Зона 2")
    assert low.required is True
    assert low.topology_feasible is False
    assert "разделение трасс" in low.note
    assert high.section_id == "L-H"
    assert high.topology_feasible is True


def test_network_rejects_disconnected_nodes():
    with pytest.raises(ValueError, match="не достижимы"):
        calculate_v1_network(
            [V1NodeInput("S", 0), V1NodeInput("A", 1, direct_demand_lps=0.2),
             V1NodeInput("X", 1), V1NodeInput("Y", 1, direct_demand_lps=0.2)],
            [V1NetworkSectionInput("S-A", "S", "A", 5, 20, 0.01),
             V1NetworkSectionInput("X-Y", "X", "Y", 5, 20, 0.01)],
            "S",
        )


def test_single_ring_is_balanced_and_all_single_section_outages_are_checked():
    result = calculate_v1_network(
        [V1NodeInput("S", 0),
         V1NodeInput("A", 5, direct_demand_lps=0.4),
         V1NodeInput("B", 10),
         V1NodeInput("C", 15, direct_demand_lps=0.6)],
        [V1NetworkSectionInput("SA", "S", "A", 20, 40, 0.01),
         V1NetworkSectionInput("AB", "A", "B", 20, 32, 0.01),
         V1NetworkSectionInput("BC", "B", "C", 20, 32, 0.01),
         V1NetworkSectionInput("CS", "C", "S", 20, 40, 0.01)],
        "S",
    )

    assert result.topology_kind == "single_ring"
    assert result.ring_converged is True
    assert result.ring_residual_m < 0.0001
    assert len(result.ring_section_ids) == 4
    assert len(result.ring_scenarios) == 4
    assert {x.disabled_section_id for x in result.ring_scenarios} == {
        "SA", "AB", "BC", "CS"}
    assert result.dictating_outage_section_id == max(
        result.ring_scenarios, key=lambda x: x.required_before_common_m
    ).disabled_section_id
    normal = {x.section_id: x for x in result.ring_normal_sections}
    assert normal["SA"].flow_lps + normal["CS"].flow_lps == pytest.approx(1.0, abs=0.002)
    assert (normal["CS"].from_node, normal["CS"].to_node) == ("S", "C")
    assert (normal["BC"].from_node, normal["BC"].to_node) == ("B", "C")
    assert (normal["AB"].from_node, normal["AB"].to_node) == ("A", "B")
    assert all(x.flow_lps >= 0 for x in result.ring_normal_sections)


def test_ring_rejects_more_than_one_independent_cycle():
    with pytest.raises(ValueError, match="многокольцевая"):
        calculate_v1_network(
            [V1NodeInput("S", 0), V1NodeInput("A", 1, direct_demand_lps=0.2),
             V1NodeInput("B", 1), V1NodeInput("C", 1)],
            [V1NetworkSectionInput("SA", "S", "A", 5, 25, 0.01),
             V1NetworkSectionInput("AB", "A", "B", 5, 25, 0.01),
             V1NetworkSectionInput("BS", "B", "S", 5, 25, 0.01),
             V1NetworkSectionInput("AC", "A", "C", 5, 25, 0.01),
             V1NetworkSectionInput("CS", "C", "S", 5, 25, 0.01)],
            "S",
        )


@pytest.mark.parametrize("field,value", [
    ("length_m", 0), ("inner_diameter_mm", 0), ("flow_lps", 0),
    ("roughness_mm", -0.1), ("velocity_limit_mps", 0),
])
def test_invalid_section_rejected(field, value):
    data = dict(section_id="1", length_m=10, inner_diameter_mm=25,
                flow_lps=0.5, roughness_mm=0.01, velocity_limit_mps=1.5)
    data[field] = value
    with pytest.raises(ValueError):
        calculate_v1_hydraulics([V1SectionInput(**data)])


def test_orchestrator_puts_v1_losses_into_required_head(tmp_path):
    from app.intake.project_builder import build_project
    from app.intake.request_dto import (
        ConsumerGroupRequest, DocumentRequest, IOS2Request, SourceDataRequest,
        V1SectionRequest,
    )
    from app.pz.ios2_orchestrator import design_ios2

    request = IOS2Request(
        document=DocumentRequest(cipher="В1", object_name="Проверка", organization="Заря"),
        building_type="residential", floors=9, building_height_m=27,
        streams=2,
        consumers=[ConsumerGroupRequest("residential_central_hw", 100)],
        source_data=SourceDataRequest(guaranteed_head_m=30, h_geom_m=25),
        v1_sections=[
            V1SectionRequest("Ввод", 10, 40, 0.7, 0.1, role="input"),
            V1SectionRequest("М1", 20, 35, 0.7, 0.01),
            V1SectionRequest("Ст1", 25, 28, 0.4, 0.01),
        ],
    )
    bundle = design_ios2(build_project(request), output_dir=str(tmp_path))
    result = bundle.project.v1_hydraulic_result
    assert result is not None
    assert bundle.project.source.h_il_m == result.internal_loss_m
    assert bundle.project.source.h_vvod_m == result.input_loss_m
    assert any("v1_hydraulics:" in status for status in bundle.status)


def test_orchestrator_uses_network_dictating_node_for_required_head(tmp_path):
    from app.intake.project_builder import build_project
    from app.intake.request_dto import (
        ConsumerGroupRequest, DocumentRequest, IOS2Request, SourceDataRequest,
        V1NetworkRequest, V1NetworkSectionRequest, V1NodeRequest,
    )
    from app.pz.ios2_orchestrator import design_ios2

    request = IOS2Request(
        document=DocumentRequest(cipher="В1-АВТО", object_name="Проверка", organization="Заря"),
        building_type="residential", floors=9, building_height_m=27,
        streams=2,
        source_data=SourceDataRequest(guaranteed_head_m=30, maximum_head_m=35),
        v1_network=V1NetworkRequest(
            source_node="Ввод",
            nodes=[
                V1NodeRequest("Ввод", 0),
                V1NodeRequest("Этаж-3", 9, [ConsumerGroupRequest(
                    "residential_central_hw", 30)]),
                V1NodeRequest("Этаж-9", 27, [ConsumerGroupRequest(
                    "residential_central_hw", 70)]),
            ],
            sections=[
                V1NetworkSectionRequest("1", "Ввод", "Этаж-3", 15, 40, 0.1,
                                        role="input"),
                V1NetworkSectionRequest(
                    "2", "Этаж-3", "Этаж-9", 25, None, 0.01,
                    candidate_inner_diameters_mm=[25, 32, 40],
                    max_specific_loss_m_per_m=0.03,
                ),
            ],
        ),
    )
    bundle = design_ios2(build_project(request), output_dir=str(tmp_path))
    result = bundle.project.v1_hydraulic_result
    assert result.dictating_node_id == "Этаж-9"
    assert bundle.project.source.elev_header_m == 0
    assert bundle.project.source.elev_fixture_m == 27
    assert bundle.project.source.h_pr_m == 20
    assert bundle.project.source.h_il_m == result.internal_loss_m
    assert bundle.project.source.h_vvod_m == result.input_loss_m
    assert next(s for s in result.sections if s.section_id == "2").diameter_selection == "auto"
    assert next(s for s in result.sections if s.section_id == "2").inner_diameter_mm == 32
    assert result.pressure_checks
    assert result.all_minimum_pressures_ok is True
    assert result.all_maximum_pressures_ok is False
    assert result.pressure_zones
    assert result.zone_regulators
    assert any(status.startswith("head: H_тр=") for status in bundle.status)
    assert any("диктующий узел Этаж-9" in status for status in bundle.status)
    assert any("превышен максимальный статический напор" in warning
               for warning in bundle.warnings)
    from app.pz.generator import generate_scheme_svg
    scheme = generate_scheme_svg(bundle.project)
    assert "отдельная НС" in scheme
    assert "РД-В1-1" not in scheme


def test_orchestrator_checks_two_inlets_and_uses_dictating_tu(tmp_path):
    from app.intake.project_builder import build_project
    from app.intake.request_dto import (
        DocumentRequest, IOS2Request, SourceDataRequest, V1InletRequest,
        V1NetworkRequest, V1NetworkSectionRequest, V1NodeRequest,
    )
    from app.pz.ios2_orchestrator import design_ios2

    request = IOS2Request(
        document=DocumentRequest(
            cipher="В1-2ВВ", object_name="Проверка двух вводов", organization="Заря"),
        building_type="residential", floors=9, building_height_m=27,
        streams=2,
        source_data=SourceDataRequest(guaranteed_head_m=99, maximum_head_m=100),
        v1_network=V1NetworkRequest(
            source_node="Коллектор",
            nodes=[
                V1NodeRequest("Коллектор", 0),
                V1NodeRequest("Этаж-9", 27, direct_demand_lps=1.0),
            ],
            sections=[
                V1NetworkSectionRequest(
                    "М1", "Коллектор", "Этаж-9", 35, 35, 0.01),
            ],
            inlets=[
                V1InletRequest("Ввод-1", 31, 43, 20, 40, 0.1),
                V1InletRequest("Ввод-2", 25, 39, 35, 32, 0.1),
            ],
        ),
    )
    bundle = design_ios2(build_project(request), output_dir=str(tmp_path))
    result = bundle.project.v1_hydraulic_result

    assert result.dictating_inlet_id == "Ввод-2"
    assert len(result.inlet_checks) == 2
    assert all(x.flow_lps == result.source_flow_lps for x in result.inlet_checks)
    assert bundle.project.source.inputs_count == 2
    assert bundle.project.source.guaranteed_head_m == 25
    assert bundle.project.source.maximum_head_m == 43
    assert any("проверено вводов 2 при 100% расходе" in x for x in bundle.status)
    assert any("диктующий ввод Ввод-2" in x for x in bundle.status)
