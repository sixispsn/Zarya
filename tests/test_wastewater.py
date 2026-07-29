import pytest

from app.calc.sewage import (
    SewageRiserInput,
    calculate_sewage_system,
    check_sewage_riser,
)
from app.calc.storm import (
    StormInput,
    StormNetworkInput,
    assess_storm_network,
    calculate_storm,
)
from app.data.sewage_tables import get_riser_capacity


@pytest.mark.parametrize(
    "material,ventilation,riser_dn,branch_dn,angle,expected,table",
    [
        ("pvc", "ventilated", 110, 50, 45.0, 8.22, "К.1"),
        ("pp", "ventilated", 110, 110, 87.5, 3.60, "К.2"),
        ("cast_iron_socket", "ventilated", 150, 100, 60.0, 12.80, "К.3"),
        ("sml", "ventilated", 125, 50, 87.5, 7.91, "К.4"),
        ("pp", "vacuum_valve", 110, 50, 60.0, 5.98, "К.8"),
    ],
)
def test_appendix_k_golden_values(
    material,
    ventilation,
    riser_dn,
    branch_dn,
    angle,
    expected,
    table,
):
    row = get_riser_capacity(
        material=material,
        ventilation=ventilation,
        riser_dn_mm=riser_dn,
        branch_dn_mm=branch_dn,
        branch_angle_deg=angle,
    )
    assert row is not None
    assert row.capacity_lps == expected
    assert row.table == table


def test_appendix_k_does_not_interpolate_unknown_node():
    assert get_riser_capacity(
        material="pp",
        ventilation="ventilated",
        riser_dn_mm=100,
        branch_dn_mm=50,
        branch_angle_deg=45.0,
    ) is None


def test_k1_riser_check_uses_explicit_flow_and_exact_table():
    result = calculate_sewage_system(
        2.4,
        1.6,
        [SewageRiserInput(
            "К1-Ст1",
            3.5,
            "pp",
            "ventilated",
            110,
            110,
            87.5,
            True,
        )],
    )
    assert result.total.q_sewage_lps == 4.0
    assert result.risers[0].capacity_lps == 3.6
    assert result.risers[0].status == "verified"
    assert result.risers[0].reserve_lps == 0.1


def test_unventilated_riser_is_stage_r_without_height_interpolation():
    result = check_sewage_riser(SewageRiserInput(
        "К1-Ст1",
        1.0,
        "pp",
        "unventilated",
        110,
        110,
        87.5,
        True,
        30.0,
    ))
    assert result.capacity_lps is None
    assert result.status == "stage_r"
    assert "интерполяция" in result.note


def test_k1_rejects_riser_flow_above_whole_system_flow():
    result = calculate_sewage_system(
        1.0,
        1.6,
        [SewageRiserInput(
            "К1-Ст1", 3.0, "pp", "ventilated", 110, 50, 60.0, True,
        )],
    )
    assert result.total.q_sewage_lps == 2.6
    assert result.risers[0].status == "fail"
    assert "превышает общий" in result.risers[0].note


def _storm_result():
    return calculate_storm(StormInput(
        city_code="moscow",
        roof_area_m2=1200,
        walls_area_m2=100,
        period_years=1,
    ))


def test_k2_network_checks_explicit_passport_and_table_values():
    result = assess_storm_network(
        _storm_result(),
        StormNetworkInput(
            roof_type="flat",
            roof_sections=2,
            funnels_count=4,
            max_funnel_spacing_m=40,
            selected_funnel_capacity_lps=12,
            max_funnel_flow_lps=10,
            risers_count=2,
            selected_riser_dn_mm=100,
            max_riser_flow_lps=14,
            funnels_on_different_levels=True,
        ),
    )
    assert result.minimum_funnels == 4
    assert result.funnels_count_ok
    assert result.funnel_capacity_ok
    assert result.aggregate_funnel_capacity_lps == 48
    assert result.aggregate_funnel_capacity_ok
    assert result.base_riser_capacity_lps == 20
    assert result.effective_riser_capacity_lps == 14
    assert result.riser_capacity_ok
    assert result.aggregate_riser_capacity_lps == 28
    assert result.aggregate_riser_capacity_ok
    assert result.status == "verified"


def test_k2_network_never_divides_total_flow_when_loads_missing():
    result = assess_storm_network(
        _storm_result(),
        StormNetworkInput(
            roof_type="flat",
            roof_sections=1,
            funnels_count=2,
            risers_count=2,
            selected_riser_dn_mm=100,
        ),
    )
    assert result.max_funnel_flow_lps is None
    assert result.max_riser_flow_lps is None
    assert result.funnel_capacity_ok is None
    assert result.riser_capacity_ok is None
    assert result.status == "stage_r"
    assert any("автоматически не делится" in note for note in result.notes)
