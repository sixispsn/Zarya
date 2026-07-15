import pytest

from app.calc.sewage import calculate_domestic_sewage
from app.calc.water_demand import ConsumerGroup, calculate_water_demand


def test_formula_5_with_wc_max_discharge():
    result = calculate_domestic_sewage(1.499, 1.6)
    assert result.q_sewage_lps == 3.099


def test_fixture_discharge_is_explicit_not_hardcoded():
    result = calculate_domestic_sewage(1.499, 0.8)
    assert result.q_sewage_lps == 2.299


def test_water_demand_passes_explicit_q0s():
    result = calculate_water_demand(
        [ConsumerGroup(code="office", count=480)],
        sewage_max_fixture_lps=0.8,
    )
    assert result.sewage_fixture_discharge == 0.8
    assert result.sewage_flow == 2.299


@pytest.mark.parametrize("q_water,q_fixture", [(-0.1, 1.6), (1.0, -0.1)])
def test_negative_inputs_rejected(q_water, q_fixture):
    with pytest.raises(ValueError):
        calculate_domestic_sewage(q_water, q_fixture)
