"""Review rebuild must not quietly alter calculations or hide missing items."""
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from tests.test_water_station_drafting import samara
from scripts.review_samara_water_documents import (
    assert_unique_owners, assert_variant_scope, audit_model,
)


def variant(project):
    result = deepcopy(project)
    result.metering_detail.inlet_metering_mode = 'common'
    result.metering_detail.common_topology = 'gost_g1'
    result.document.object_part = 'Вариант общего ВУ. Проверка компоновки'
    return result


def test_current_samara_common_review_is_read_only(samara):
    original = deepcopy(asdict(samara))
    project = variant(samara)
    assert_variant_scope(samara, project)
    report = audit_model(project)
    assert report['building_sections'] == 1
    assert report['characteristic_fixture_symbols'] == 24
    assert report['pump']['q_m3h'] == pytest.approx(11.466)
    assert report['pump']['reserve'] == 1
    assert not report['station_review']['hydraulic_capacity_confirmed']
    assert asdict(samara) == original
    assert_variant_scope(samara, project)


@pytest.mark.parametrize('change', ['head', 'flow', 'inlet', 'meter_mode'])
def test_review_does_not_accept_hidden_input_or_calculation_changes(samara, change):
    project = variant(samara)
    if change == 'head':
        project.pumps.h_design_m += 1
    elif change == 'flow':
        project.pumps.q_design_m3h *= 2
    elif change == 'inlet':
        project.source.guaranteed_head_m += 1
    else:
        project.metering_detail.inlet_metering_mode = 'per_inlet'
    with pytest.raises(AssertionError, match='вне согласованной'):
        assert_variant_scope(samara, project)


@pytest.mark.parametrize('ids, required', [
    ([('pump',), ('pump',)], {'pump'}),
    ([('pump',)], {'pump', 'drain'}),
    ([('pump', 'pump')], {'pump'}),
])
def test_spec_audit_detects_duplicate_or_missing_owners(ids, required):
    with pytest.raises(AssertionError):
        assert_unique_owners([SimpleNamespace(component_ids=value) for value in ids], required)


def test_spec_audit_accepts_grouped_factory_supply_once():
    result = assert_unique_owners([
        SimpleNamespace(component_ids=('pump1', 'pump2', 'factory_valve')),
        SimpleNamespace(component_ids=('external_drain',)),
    ], {'pump1', 'pump2', 'external_drain'})
    assert result['pump2'] == 1
