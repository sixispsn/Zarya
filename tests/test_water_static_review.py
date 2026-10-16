from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from app.calc.v1_hydraulics import static_head_at_elevation
from app.intake import samara_study
from app.pz.generator import generate_pz_html
from app.pz.scheme import build_scheme
from app.pz.water_document_binding import water_pressure_presentation
from app.pz.water_static_review import review_water_static_pressure


@pytest.fixture
def project(tmp_path):
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    return samara_study.build(draft,tmp_path,render=False)[0].project


def test_samara_static_scenario_uses_known_levels_not_invented_lower_fixture(project):
    before = deepcopy(asdict(project))
    r = review_water_static_pressure(project)
    assert not r.issues and len(r.rows) == 18
    assert r.external_max_m == 35 and r.pump_zero_head_m == 68
    assert r.source_head_m == 103 and r.source_elevation_m == -2.195
    first = r.rows[0]
    assert first.kind == 'floor' and first.elevation_m == 0
    assert first.head_m == pytest.approx(100.805)
    assert first.limit_m is None and first.exceeds is None
    fixture = next(x for x in r.rows if x.kind == 'fixture')
    assert fixture.kind == 'fixture' and fixture.elevation_m == 46
    assert fixture.head_m == pytest.approx(54.805)
    assert fixture.exceeds is True and r.has_exceedance
    assert len([x for x in r.rows if x.kind == 'fixture']) == 1
    lower = r.rows[-1]
    assert lower.kind == 'lowest_fixture' and lower.elevation_m == 1
    assert lower.head_m == pytest.approx(99.805) and lower.exceeds
    assert 'Учебное допущение' in project.source.lowest_fixture_basis
    assert asdict(project) == before


def test_shared_static_balance_matches_existing_equation_and_does_not_clamp():
    for head,z0,z in [(103,-2.195,0),(103,-2.195,46),(5,0,10),(0,0,0)]:
        assert static_head_at_elevation(head,z0,z) == head-(z-z0)
    assert static_head_at_elevation(5,0,10) == -5
    for bad in (float('nan'),float('inf')):
        with pytest.raises(ValueError):
            static_head_at_elevation(30,0,bad)


@pytest.mark.parametrize('field,value',[
    ('maximum_head_m',None),('maximum_head_m',float('nan')),
    ('maximum_head_m',29),('elev_header_m',None),('elev_header_m',float('inf')),
])
def test_invalid_source_never_becomes_success(project,field,value):
    setattr(project.source,field,value)
    r = review_water_static_pressure(project)
    assert not r.rows and r.issues
    assert water_pressure_presentation(project).state == 'not_checked'


def test_pump_curve_without_zero_does_not_use_maximum_as_shutoff(project):
    project.pumps.curve = project.pumps.curve[1:]
    r = review_water_static_pressure(project)
    assert not r.rows
    assert any('Q=0' in s for s in r.issues)


def test_stale_pump_or_incomplete_head_cannot_certify_static_review(project):
    project.pumps.q_design_m3h *= 2
    r = review_water_static_pressure(project)
    assert not r.rows and any('текущим Q/H' in x for x in r.issues)
    project.source.h_geom_m = None
    project.source.elev_fixture_m = None
    project.head_paths = None
    assert not review_water_static_pressure(project).rows


@pytest.mark.parametrize('field,value',[
    ('guaranteed_head_m',25),('h_il_hot_m',10),('elev_fixture_m',47),
])
def test_changed_inputs_do_not_reuse_saved_head(project,field,value):
    setattr(project.source,field,value)
    r = review_water_static_pressure(project)
    assert not r.rows and any('после расчёта' in s for s in r.issues)


def test_no_new_regulator_or_building_quantities_from_static_screen(project):
    project.pumps.reserve_units = 99
    r = review_water_static_pressure(project)
    assert r.source_head_m == 103
    state = water_pressure_presentation(project)
    assert state.state == 'static_only'
    assert not project.v1_hydraulic_result.zone_regulators
    svg = ' '.join(ET.fromstring(build_scheme(project).svg).itertext())
    assert all(s in svg for s in state.drawing_lines)
    assert 'РД-В1-' not in svg
    html = generate_pz_html(project)
    for text in ('54,805','100,805','не штатный режим частотного регулирования',
                 'не является напором у нижнего прибора','Резервный насос дополнительно не учитывается'):
        assert text in html


def test_reference_levels_are_never_generated_from_height(project):
    project.building.floor_elevations_m = {1:0,3:6.25}
    r = review_water_static_pressure(project)
    assert len(r.rows) == 4
    assert r.rows[1].head_m == pytest.approx(94.555)
    assert all(row.elevation_m != 3 for row in r.rows)


def test_multizone_unbound_network_is_not_treated_as_single_riser(project):
    project.building.zones = 2
    r = review_water_static_pressure(project)
    assert not r.rows and r.issues
    project.building.zones = 1
    project.v1_network = SimpleNamespace()
    assert not review_water_static_pressure(project).rows


def test_separate_fire_or_process_network_is_not_certified_by_domestic_limit(project):
    project.source.network_kind = 'fire'
    assert not review_water_static_pressure(project).rows


def test_no_booster_means_only_explicit_maximum_network_head():
    from app.pz.project import HwsType, Project
    p = Project()
    p.building.hws_type = HwsType.NONE
    p.building.floors_above = 2
    p.building.floor_elevations_m = {1:0,2:3}
    p.source.maximum_head_m = 40
    p.source.guaranteed_head_m = 35
    p.source.elev_header_m = -2
    p.source.elev_fixture_m = 4
    p.source.h_il_m = 1
    p.source.h_vod_m = 1
    p.source.h_vvod_m = 1
    r = review_water_static_pressure(p)
    assert not r.issues and r.source_head_m == 40
    assert r.pump_zero_head_m is None and not r.has_exceedance
    assert r.rows[-1].head_m == 34
    assert water_pressure_presentation(p).state == 'static_only'


def test_floor_warning_is_not_a_fixture_limit_result(project):
    # Existing actual node audit takes precedence; this view does not overwrite it.
    project.v1_hydraulic_result = replace(project.v1_hydraulic_result,
        pressure_checks=[SimpleNamespace(minimum_ok=True,maximum_ok=True)])
    state = water_pressure_presentation(project)
    assert state.state == 'checked_nodes' and state.static_review is None
