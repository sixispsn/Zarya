import math

import pytest

from app.calc.v1_hydraulics import V1SectionInput, calculate_v1_hydraulics


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
