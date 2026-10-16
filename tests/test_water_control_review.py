from copy import deepcopy
from dataclasses import asdict

import pytest

from app.intake import samara_study
from app.pz.project import Project
from app.pz.water_control_review import review_water_control
from app.pz.water_static_review import review_water_static_pressure
from app.pz.generator import generate_pz_html


@pytest.fixture
def project(tmp_path):
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    return samara_study.build(draft,tmp_path,render=False)[0].project


def test_design_balance_does_not_assign_a_controller_or_valves(project):
    before = deepcopy(asdict(project))
    r = review_water_control(project)
    assert not r.issues and r.reference_head_m == 80.25 and r.governing_code == 'T3'
    cold, hot = r.rows
    assert cold.required_head_m == 75.63
    assert cold.excess_head_m == pytest.approx(4.62)
    assert cold.residual_head_m == pytest.approx(24.62)
    assert hot.excess_head_m == 0 and hot.residual_head_m == 20
    assert asdict(project) == before
    html = generate_pz_html(project)
    for phrase in ('99,805','4,62','не назначаются уставкой датчика',
                   'Учебное допущение','Частотное управление само по себе'):
        assert phrase in html


@pytest.mark.parametrize('invalid', ['stale','no_paths','zones','pump','pending'])
def test_incomplete_or_stale_calculation_is_not_a_control_target(project,invalid):
    if invalid == 'stale': project.source.h_il_hot_m = 5
    if invalid == 'no_paths': project.head_paths = None
    if invalid == 'zones': project.building.zones = 2
    if invalid == 'pump': project.pumps.q_design_m3h *= 2
    if invalid == 'pending': project.document.review_head_pending = True
    r = review_water_control(project)
    assert not r.rows and r.issues


def test_missing_shutoff_curve_does_not_hide_valid_design_balance(project):
    project.pumps.curve = project.pumps.curve[1:]
    assert not review_water_static_pressure(project).rows
    assert review_water_control(project).rows


def test_samara_lower_fixture_is_not_a_default_for_other_projects():
    assert Project().source.lowest_fixture_elevation_m is None
    assert not Project().source.lowest_fixture_basis


@pytest.mark.parametrize('value,basis', [(float('nan'),'АР'), (47,'АР'), (1,'')])
def test_invalid_lowest_fixture_is_never_certified(project,value,basis):
    project.source.lowest_fixture_elevation_m = value
    project.source.lowest_fixture_basis = basis
    r = review_water_static_pressure(project)
    assert not any(x.kind == 'lowest_fixture' for x in r.rows)
    assert r.issues
