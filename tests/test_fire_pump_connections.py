"""Stage-P connections follow actual DN, not inferred mounting dimensions."""
from copy import deepcopy

import pytest

from app.data.fire_pump_geometry import connection_review
from app.intake.studio_fire_pipework import from_model
from app.pz.fire_principle_scheme import Sheet, build_station_sheet
from app.pz.fire_review_binding import spec_rows
from tests.test_fire_principle_scheme import elements
from tests.test_fire_review_binding import bundle, passing_model
from tests.test_studio_fire_location import located_model


@pytest.fixture(scope='module')
def accepted(tmp_path_factory):
    return bundle(located_model(), tmp_path_factory.mktemp('pump-connections')).project


def test_four_installed_reducers_same_positions_in_sheet_and_spec(accepted):
    before = deepcopy(accepted)
    svg = build_station_sheet(accepted)
    drawn = {e.attrib['data-component']:e for e in elements(svg,'data-component')}
    rows = [r for r in spec_rows(accepted) if r['id'].startswith(('ПВ','ПД'))]
    assert len(rows) == 2 and sum(r['qty'] for r in rows) == 4
    assert all(r['unit']=='шт.' and type(r['qty']) is int and 'DN100×65' in r['mark'] for r in rows)
    for row in rows:
        assert 'учёт потерь' in row['note'] and 'требуют увязки' in row['note']
        for ident in row['id'].split('/'):
            shape = next(iter(drawn[ident]))
            assert shape.attrib['fill'] == 'white'
            assert {int(shape.attrib['data-dn-left']), int(shape.attrib['data-dn-right'])} == {65,100}
    assert next(iter(drawn['ПВ1'])).attrib['d'] == 'M182,76 V80 L188,78 Z'
    assert next(iter(drawn['ПД1'])).attrib['d'] == 'M220,76 V80 L214,78 Z'
    assert 'ПВ, ПД: переходы к патрубкам насоса' in svg
    assert accepted == before


def test_render_and_spec_do_not_invent_or_add_hydraulic_losses(accepted):
    model = deepcopy(accepted.fire_station_model_input)
    original = from_model(model).audit(accepted.fire_pumps.wp_q)
    original_result = deepcopy(accepted.fire_pumps.pressure_review)
    build_station_sheet(accepted)
    spec_rows(accepted)
    assert from_model(model).audit(accepted.fire_pumps.wp_q) == original
    assert accepted.fire_pumps.pressure_review == original_result
    geometry = connection_review(model, accepted.fire_pumps.model)
    assert geometry['product_verified'] is False and geometry['selected_pn'] is None
    assert all(not {'zeta','length_m','mass_kg','product_id'} & row.keys() for row in geometry['transitions'])


@pytest.mark.parametrize('sides', [('suction',), ('discharge',), ('suction','discharge')])
def test_equal_nozzles_do_not_add_unnecessary_transitions(sides):
    m = located_model()
    for row in m['pipework']['elements']:
        if any(row['role'].startswith(side+'_') and not row['role'].endswith('header') for side in sides):
            row['dn'] = 65
    ref = connection_review(m, 'CNP CDM32-3')
    assert {r['side'] for r in ref['transitions']} == {'suction','discharge'}-set(sides)
    # These are pump-port reducers, not reducers at the collectors.
    assert all(r['branch_dn'] == 100 for r in ref['transitions'])


def test_unknown_geometry_or_branch_diameter_is_not_substituted():
    assert connection_review(located_model(), 'Unknown pump') is None
    assert connection_review(passing_model(), 'CNP CDM32-3')['transitions'] == []


@pytest.mark.parametrize('left,right,start', [(100,65,'M7,8 V12 L13,10'), (50,65,'M13,8 V12 L7,10')])
def test_wedge_flat_side_faces_large_dn(left,right,start):
    s = Sheet(None,'test',1,1)
    s.transition('P',10,10,left,right)
    assert start in s.parts[-1]
