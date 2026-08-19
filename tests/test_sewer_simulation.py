import pytest

from app.calc.sewer_hydraulics import (
    SewerHydraulicInput,
    calculate_sewer_hydraulics,
)
from app.calc.sewer_simulation import (
    PipeSection,
    PipeSectionConfig,
    PipeStatus,
    SedimentCalibration,
    base_critical_velocity_mps,
)


def _pipe(*, diameter_mm=103.2, slope=10.0, critical_velocity=0.6):
    return PipeSection(PipeSectionConfig(
        section_id="К1-М1",
        length_m=12.0,
        inner_diameter_mm=diameter_mm,
        slope_per_mille=slope,
        material="ПП",
        manning_n=0.011,
        roughness_source="паспорт выбранной трубы",
        critical_velocity_mps=critical_velocity,
        critical_velocity_source="исходное правило пользователя",
        critical_fill_ratio=0.8,
    ))


def test_clean_pipe_matches_existing_chezy_manning_solver():
    pipe = _pipe()
    dynamic = pipe.calculate_hydraulics(2.758)
    existing = calculate_sewer_hydraulics(SewerHydraulicInput(
        section_id="К1-М1",
        design_flow_lps=2.758,
        inner_diameter_mm=103.2,
        slope_per_mille=10.0,
        material="ПП",
        manning_n=0.011,
        roughness_source="паспорт выбранной трубы",
    ))
    assert dynamic.fill_ratio_h_d == pytest.approx(existing.fill_ratio, abs=0.0001)
    assert dynamic.velocity_mps == pytest.approx(existing.velocity_mps, abs=0.001)
    assert dynamic.status is PipeStatus.NORMAL


def test_low_velocity_deposits_suspended_solids_and_reduces_live_section():
    pipe = _pipe()
    hydraulic = pipe.calculate_hydraulics(0.1)
    before_area = pipe.available_cross_section_m2
    assert PipeStatus.SILTING in hydraulic.active_flags

    result = pipe.apply_sediment_step(
        dt_seconds=3600.0,
        inflow_lps=0.1,
        hydraulic_state=hydraulic,
        calibration=SedimentCalibration(
            suspended_solids_mg_l=300.0,
            sediment_bulk_density_kg_m3=1200.0,
            capture_efficiency_at_zero_velocity=0.8,
            velocity_deficit_exponent=1.0,
            source="испытательный сценарий",
        ),
    )

    assert result.deposited_mass_kg > 0
    assert result.sediment_increment_mm > 0
    assert pipe.available_cross_section_m2 < before_area


def test_no_deposition_when_velocity_is_not_below_critical():
    pipe = _pipe()
    hydraulic = pipe.calculate_hydraulics(2.758)
    result = pipe.apply_sediment_step(
        dt_seconds=60.0,
        inflow_lps=2.758,
        hydraulic_state=hydraulic,
        calibration=SedimentCalibration(
            suspended_solids_mg_l=300.0,
            sediment_bulk_density_kg_m3=1200.0,
            capture_efficiency_at_zero_velocity=0.8,
            velocity_deficit_exponent=1.0,
            source="испытательный сценарий",
        ),
    )
    assert result.deposited_mass_kg == 0
    assert result.sediment_increment_mm == 0


def test_capacity_excess_is_critical_but_not_called_flooding_without_storage_balance():
    pipe = _pipe()
    capacity = pipe.calculate_hydraulics(1.0).maximum_gravity_capacity_lps
    overloaded = pipe.calculate_hydraulics(capacity * 1.01)
    assert overloaded.capacity_exceeded
    assert overloaded.status is PipeStatus.CRITICAL_FILL
    assert PipeStatus.FLOODING not in overloaded.active_flags


def test_user_base_velocity_table_does_not_interpolate_missing_diameters():
    assert base_critical_velocity_mps(103.2) == 0.6
    assert base_critical_velocity_mps(160.0) == 0.7
    assert base_critical_velocity_mps(50.0) is None
    assert base_critical_velocity_mps(125.0) is None


def test_sediment_model_requires_traceable_calibration():
    with pytest.raises(ValueError, match="источник или калибровка"):
        SedimentCalibration(
            suspended_solids_mg_l=300.0,
            sediment_bulk_density_kg_m3=1200.0,
            capture_efficiency_at_zero_velocity=0.8,
            velocity_deficit_exponent=1.0,
            source="",
        )


def test_sediment_step_rejects_hydraulics_for_another_flow():
    pipe = _pipe()
    hydraulic = pipe.calculate_hydraulics(0.1)
    with pytest.raises(ValueError, match="расход шага не совпадает"):
        pipe.apply_sediment_step(
            dt_seconds=60.0,
            inflow_lps=0.2,
            hydraulic_state=hydraulic,
            calibration=SedimentCalibration(
                suspended_solids_mg_l=300.0,
                sediment_bulk_density_kg_m3=1200.0,
                capture_efficiency_at_zero_velocity=0.8,
                velocity_deficit_exponent=1.0,
                source="испытательный сценарий",
            ),
        )
