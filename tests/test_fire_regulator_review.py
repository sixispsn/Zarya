from dataclasses import replace

import pytest

from app.calc.fire_regulator_review import BAR_TO_M, screen_regulator, setpoint_window
from app.data.fire_regulators import CANDIDATES, get_candidate


def screen(candidate=None, **overrides):
    duty = dict(application='standalone_vpv', flow_range_m3h=(9.48, 9.50),
                setting_bar=2.1, minimum_available_drop_bar=.536,
                maximum_inlet_pressure_bar=12.61)
    duty.update(overrides)
    return screen_regulator(candidate or CANDIDATES[0], **duty)


def test_actual_ridan_requires_passport_drop_not_kv_loss():
    c = get_candidate('ridan-c101-082X6100RL')
    assert c.minimum_drop_bar == (1.5, 1.5)
    assert c.kv_m3h == 65
    result = screen(c)
    assert result.status == 'outside_documented_limits'
    assert 'insufficient_control_drop' in result.failures
    assert not result.selection_confirmed


def test_aup_exclusion_is_not_misrepresented_as_standalone_vpv_ban():
    assert 'application_excluded_by_manufacturer' not in screen().failures
    assert 'fire_application_confirmation' in screen().missing
    assert 'application_excluded_by_manufacturer' in screen(
        application='automatic_water_foam_fire').failures


def test_exact_minimum_drop_boundary_included_but_not_final_selection():
    out = screen(minimum_available_drop_bar=1.5)
    assert 'insufficient_control_drop' not in out.failures
    assert out.status == 'needs_manufacturer_data'
    assert not out.selection_confirmed


def test_family_minimum_is_not_silently_lowest_value():
    c = get_candidate('asta-r01-02-dn50-family')
    out = screen(c)
    assert not out.failures
    assert 'exact_minimum_drop_for_configuration' in out.missing
    assert 'flow_range' in out.missing
    assert not out.selection_confirmed
    assert 'insufficient_control_drop' in screen(c, minimum_available_drop_bar=.49).failures


def test_fire_marketing_and_pn_are_not_characteristics():
    c = get_candidate('pvo-rkm60-dn50-family')
    out = screen(c)
    assert 'fire_application_confirmation' not in out.missing
    assert 'minimum_control_drop' in out.missing
    assert not out.selection_confirmed
    assert 'inlet_above_documented_limit' in screen(c, maximum_inlet_pressure_bar=16.1).failures
    assert 'maximum_inlet_at_design_temperature' in screen().missing


@pytest.mark.parametrize('key,value,code', [
    ('flow_range_m3h', (.4, 9.5), 'flow_outside_documented_range'),
    ('flow_range_m3h', (9.5, 45.1), 'flow_outside_documented_range'),
    ('setting_bar', 8.1, 'setting_outside_documented_range'),
    ('maximum_inlet_pressure_bar', 16.1, 'inlet_above_nominal_pressure'),
])
def test_bounds(key, value, code):
    assert code in screen(**{key: value}).failures


def test_relief_valve_cannot_be_used_as_inline_reducer():
    assert 'not_a_downstream_pressure_reducer' in screen(
        replace(CANDIDATES[0], function='pressure_relief')).failures


@pytest.mark.parametrize('changes', [
    {'minimum_available_drop_bar': float('nan')},
    {'minimum_available_drop_bar': -1},
    {'flow_range_m3h': (10, 9)},
    {'maximum_inlet_pressure_bar': float('inf')},
    {'setting_bar': 0},
    {'application': 'unknown'},
])
def test_invalid_duty_is_error(changes):
    with pytest.raises(ValueError):
        screen(**changes)


def test_source_and_catalog_range_validation():
    with pytest.raises(ValueError):
        screen(replace(CANDIDATES[0], source_url=''))
    with pytest.raises(ValueError):
        screen(replace(CANDIDATES[0], minimum_drop_bar=(1.5, .5)))


def window(**overrides):
    args = dict(required_dynamic_head_m=74.51, available_inlet_head_m=79.975,
        allowed_static_head_m=95.543, minimum_control_drop_bar=1.5,
        no_flow_extra_bar=0, lower_error_bar=0, upper_error_bar=0)
    args.update(overrides)
    return setpoint_window(**args)


def test_common_ridan_consumes_more_than_available_pressure_budget():
    out = window()
    assert out.dynamic_ceiling_head_m == pytest.approx(79.975 - 1.5 * BAR_TO_M)
    assert out.maximum_setting_head_m < out.minimum_setting_head_m
    assert not out.feasible


def test_no_flow_one_bar_and_accuracy_are_not_ignored():
    out = window(available_inlet_head_m=120, minimum_control_drop_bar=.5,
                 no_flow_extra_bar=1, lower_error_bar=.1, upper_error_bar=.2)
    assert out.minimum_setting_head_m == pytest.approx(74.51 + .1 * BAR_TO_M)
    assert out.static_ceiling_head_m == pytest.approx(95.543 - 1.2 * BAR_TO_M)
    assert out.maximum_setting_head_m == out.static_ceiling_head_m
    assert out.feasible


def test_setpoint_exact_boundary():
    out = window(required_dynamic_head_m=80, available_inlet_head_m=80 + BAR_TO_M,
                 allowed_static_head_m=80, minimum_control_drop_bar=1)
    assert out.feasible
    assert out.minimum_setting_head_m == pytest.approx(out.maximum_setting_head_m)


@pytest.mark.parametrize('key', ['required_dynamic_head_m', 'available_inlet_head_m',
    'allowed_static_head_m', 'minimum_control_drop_bar', 'no_flow_extra_bar',
    'lower_error_bar', 'upper_error_bar'])
def test_no_unphysical_setpoint_inputs(key):
    with pytest.raises(ValueError):
        window(**{key: float('nan')})
    with pytest.raises(ValueError):
        window(**{key: -1})
