import math

import pytest

from app.calc.v1_hydraulics import (
    V1NetworkSectionInput, V1NodeInput, V1SectionInput,
    calculate_v1_hydraulics, calculate_v1_network,
)


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


def test_network_rejects_disconnected_nodes():
    with pytest.raises(ValueError, match="не достижимы"):
        calculate_v1_network(
            [V1NodeInput("S", 0), V1NodeInput("A", 1, direct_demand_lps=0.2),
             V1NodeInput("X", 1), V1NodeInput("Y", 1, direct_demand_lps=0.2)],
            [V1NetworkSectionInput("S-A", "S", "A", 5, 20, 0.01),
             V1NetworkSectionInput("X-Y", "X", "Y", 5, 20, 0.01)],
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
        source_data=SourceDataRequest(guaranteed_head_m=30),
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
    assert any(status.startswith("head: H_тр=") for status in bundle.status)
    assert any("диктующий узел Этаж-9" in status for status in bundle.status)
