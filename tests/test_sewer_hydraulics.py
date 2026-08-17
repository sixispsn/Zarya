from math import pi

import pytest

from app.calc.sewer_hydraulics import (
    SewerHydraulicInput,
    calculate_sewer_hydraulics,
    circular_partial_geometry,
    is_polymer,
)


def test_half_full_circle_uses_exact_wetted_geometry():
    geometry = circular_partial_geometry(100.0, 0.5)
    assert geometry.area_m2 == pytest.approx(pi * 0.05**2 / 2.0)
    assert geometry.wetted_perimeter_m == pytest.approx(pi * 0.05)
    assert geometry.hydraulic_radius_m == pytest.approx(0.025)


def test_polymer_detection_does_not_treat_copper_as_pe():
    assert is_polymer("ПП")
    assert is_polymer("polypropylene")
    assert not is_polymer("copper")


def test_chezy_manning_solves_demo_main_and_self_cleaning_rule():
    result = calculate_sewer_hydraulics(SewerHydraulicInput(
        section_id="К1-М1",
        design_flow_lps=2.758,
        inner_diameter_mm=103.2,
        slope_per_mille=10.0,
        material="ПП",
        manning_n=0.011,
        roughness_source="паспорт выбранной трубы",
    ))
    assert result.fill_ratio == pytest.approx(0.4493, abs=0.0001)
    assert result.velocity_mps == pytest.approx(0.757, abs=0.001)
    assert result.self_cleaning_value == pytest.approx(0.507, abs=0.001)
    assert result.self_cleaning_k == 0.5
    assert result.status == "verified"


def test_hydraulic_calculation_rejects_hidden_roughness_source():
    with pytest.raises(ValueError, match="шероховатости нужен источник"):
        calculate_sewer_hydraulics(SewerHydraulicInput(
            section_id="К1-1",
            design_flow_lps=1.0,
            inner_diameter_mm=100.0,
            slope_per_mille=10.0,
            material="ПП",
            manning_n=0.011,
            roughness_source="",
        ))


def test_oversized_low_fill_pipe_fails_self_cleaning_even_if_it_carries_flow():
    result = calculate_sewer_hydraulics(SewerHydraulicInput(
        section_id="К1-НЕВЕРНЫЙ",
        design_flow_lps=2.758,
        inner_diameter_mm=150.2,
        slope_per_mille=8.0,
        material="ПП",
        manning_n=0.011,
        roughness_source="паспорт выбранной трубы",
    ))
    assert result.maximum_capacity_lps > result.design_flow_lps
    assert result.status == "fail"
    assert result.minimum_fill_ok is False
    assert result.velocity_ok is False
    assert result.self_cleaning_ok is False
