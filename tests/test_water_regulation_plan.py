from copy import deepcopy
from dataclasses import asdict
from xml.etree import ElementTree as ET

import pytest

from app.intake import samara_study
from app.data.booster_controls import booster_control
from app.pz.project import Project
from app.pz.water_regulation_plan import branch_regulation_plan
from app.pz.water_control_review import review_water_control
from app.pz.scheme import build_scheme
from app.pz.hws_building_drafting import build_hws_section
from app.pz.spec import build_water_specification
from app.pz.generator import generate_pz_html, generate_pump_selection_html
from app.pz.water_station_drafting import build_pump_zone_scheme_pages


@pytest.fixture
def project(tmp_path):
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    return samara_study.build(draft,tmp_path,render=False)[0].project


def test_catalogue_vfd_is_not_the_highrise_requirement_flag(project):
    assert not project.normative.frequency_drive_required
    assert booster_control(project.pumps).drive == 'Aikon PD ES'
    assert booster_control(project.fire_pumps) is None
    assert 'Частотное управление предусмотрено' in generate_pump_selection_html(project)
    station = build_pump_zone_scheme_pages(project)[0]
    assert 'data-component="PT-master"' in station and 'data-component="PT-reserve-master"' in station
    project.pumps.model = 'CNP / Aikon PBS CDM999-1'
    assert booster_control(project.pumps) is None


def test_principle_intent_is_opt_in_and_read_only(project):
    before = deepcopy(asdict(project))
    plan = branch_regulation_plan(project)
    assert plan.state == 'principle'
    assert plan.floors == tuple(range(1,12))
    assert plan.systems == ('В1','Т3') and plan.reference_head_m == 80.25
    assert not plan.shows('Т4',1) and not plan.shows('В1',16)
    assert asdict(project) == before
    assert branch_regulation_plan(Project()).state == 'not_specified'
    project.water_regulation_design = None
    assert branch_regulation_plan(project).state == 'not_specified'


@pytest.mark.parametrize('change', ['stale','offset','levels','upper','purpose','catalogue','zones'])
def test_invalid_intent_is_not_presented_as_a_complete_pressure_solution(project,change):
    if change == 'stale': project.source.h_il_hot_m += 1
    if change == 'offset': project.water_regulation_design['fixture_offset_m'] = float('nan')
    if change == 'levels': del project.building.floor_elevations_m[5]
    if change == 'upper': project.building.floor_elevations_m[16] = 50
    if change == 'purpose': project.water_regulation_design['basis'] = ''
    if change == 'catalogue': project.pumps.model = 'Unknown'
    if change == 'zones': project.building.zones = 2
    plan = branch_regulation_plan(project)
    assert plan.state == 'needs_data' and plan.issue
    assert not plan.floors


def test_45m_boundary_is_exclusive_and_uses_target_not_full_speed_shutoff(project):
    # Henv=80.25, zsource=-2.195, fixture offset=1, thus zfloor=32.055 at 45 m.
    project.building.floor_elevations_m[11] = 32.055
    assert 11 not in branch_regulation_plan(project).floors
    project.building.floor_elevations_m[11] -= .001
    assert 11 in branch_regulation_plan(project).floors
    project.pumps.curve[0] = (0,200)
    assert 16 not in branch_regulation_plan(project).floors


def test_sheets_put_prvs_only_on_planned_apartment_branches(project):
    cold = ET.fromstring(build_scheme(project).svg)
    hot = ET.fromstring(build_hws_section(project,3,3))
    for tree,system in ((cold,'В1'),(hot,'Т3')):
        valves = [e for e in tree.iter() if e.get('data-pressure-regulator') == 'stage-p']
        assert valves and {e.get('data-floor') for e in valves} == {'1','2','3'}
        assert all(e.get('data-system') == system for e in valves)
        assert all(e.get('data-floor') != '16' for e in valves)
    branches = [e for e in hot.iter() if e.get('data-component') == 't3-apartment']
    assert sum(len([e for e in b.iter() if e.get('data-pressure-regulator')]) for b in branches) == 3
    project.water_regulation_design = None
    assert 'data-pressure-regulator="stage-p"' not in build_scheme(project).svg
    assert 'data-pressure-regulator' not in build_hws_section(project,3,3)


def test_spec_and_pz_bind_same_intent_without_fake_quantities_or_extra_cabinet(project):
    before = deepcopy(asdict(project))
    for highrise_flag in (False,True):
        project.normative.frequency_drive_required = highrise_flag
        spec = build_water_specification(project)
        cold = next(s for s in spec.sections if s.title.startswith('В1'))
        hot = next(s for s in spec.sections if s.title.startswith('Т3'))
        for section,system in ((cold,'В1'),(hot,'Т3')):
            rd = [r for r in section.rows if r.name.startswith('Регулятор давления квартирного')]
            assert len(rd) == 1 and system in rd[0].name
            assert rd[0].qty == 98 and '1–11' in rd[0].note
            assert section.rows.index(rd[0]) < next(i for i,r in enumerate(section.rows)
                                                    if r.name.startswith('Труба'))
        assert any('частотное управление Aikon PD ES' in r.name for r in cold.rows)
        assert not any('Шкаф управления повысительной' in r.name for r in cold.rows)
    project.normative.frequency_drive_required = before['normative']['frequency_drive_required']
    html = generate_pz_html(project)
    for phrase in ('Частотное управление предусмотрено','1–11','не на транзите',
                   'Потери РД на нижних ветвях не приняты равными нулю'):
        assert phrase in html
    assert review_water_control(project).rows[-1].excess_head_m == 0
    assert asdict(project) == before
