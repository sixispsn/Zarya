"""Missing inputs must expose an incomplete schedule, not remove its rows."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.intake.project_builder import build_project
from app.intake.studio_intake import build_handoff_request
from app.pz.spec import build_water_specification
from app.pz.spec_quantity_review import water_spec_quantity_review
from tests.test_spec_materials import _demo_project
from tests.test_studio_apartment_meters import draft
from tests.test_water_pipe_binding import source_project
from tests.test_apartment_accessories import samara
from tests.test_studio import client, new, answer


def v1_rows(p):
    return build_water_specification(p).sections[0].rows


@pytest.mark.parametrize('factory', [_demo_project, source_project])
@pytest.mark.parametrize('area', [0, None])
def test_no_area_keeps_pipe_support_and_insulation_requirements(factory, area):
    p = factory()
    with_area = [r for r in v1_rows(p) if r.quantity_basis == 'area_estimate']
    assert len(with_area) == 8
    p.building.total_area_m2 = area
    before = deepcopy(asdict(p))
    pending = [r for r in v1_rows(p) if r.quantity_basis == 'needs_area']
    assert len(pending) == 8
    assert [(r.name, r.type_mark, r.unit) for r in pending] == [
        (r.name, r.type_mark, r.unit) for r in with_area]
    assert all(r.qty is None for r in pending)
    assert asdict(p) == before
    spec = build_water_specification(p)
    assert 'оценка 0 м' not in spec.note and 'площади 0 м²' not in spec.note
    report = water_spec_quantity_review(p)
    action = next(a for a in report['actions'] if a['id'] == 'area')
    assert action['fields'] == ['building_area_m2'] and 'не обмер' in action['note']


def test_area_add_remove_does_not_change_any_engineering_calculation():
    p = build_project(build_handoff_request(draft(building_area_m2=800)))
    before = deepcopy(asdict(p))
    filled = v1_rows(p)
    p.building.total_area_m2 = 0
    pending = v1_rows(p)
    assert sum(r.quantity_basis == 'needs_area' for r in pending) == 8
    p.building.total_area_m2 = 800
    assert v1_rows(p) == filled
    assert asdict(p) == before


def test_missing_pipe_geometry_does_not_remove_supports_and_insulation():
    p = source_project()
    p.v1_sections = [s for s in p.v1_sections if s.section_id != 'В1-Стояк']
    found = v1_rows(p)
    for title in ('Трубы В1 — стояки', 'Крепления труб В1 — стояки', 'Теплоизоляция В1 — стояки'):
        row = next(r for r in found if r.name == title)
        assert row.qty is None and 'нет согласованных' in row.note


def test_unheated_without_area_keeps_protection_requirement_without_power_guess():
    p = _demo_project()
    p.building.total_area_m2 = 0
    p.building.unheated_zones = True
    row = next(r for r in v1_rows(p) if r.component_ids == ('v1-freeze-protection',))
    assert row.qty is None and '16' not in row.type_mark
    assert 'мощность' in row.note


def test_samara_partial_sealing_is_not_the_whole_building(samara):
    before = deepcopy(asdict(samara))
    row = next(r for r in v1_rows(samara) if 'заделки зазоров' in r.name)
    assert row.qty is None and 'Частичный объём 2,4 дм³' in row.note
    assert 'только вводы' in row.note and 'проходок стояков' in row.note
    assert asdict(samara) == before
    # Existing 49 unknowns plus 7 for the independently drawn hot assembly.
    assert water_spec_quantity_review(samara)['counts']['missing'] == 56


def test_known_risers_keep_existing_volume_formula_and_unknown_mass():
    p = _demo_project()
    row = next(r for r in v1_rows(p) if 'заделки зазоров' in r.name)
    assert row.qty is None and '13,9 дм³' in row.note and 'Частичный' not in row.note
    p.building.floors_above = 0
    row = next(r for r in v1_rows(p) if 'заделки зазоров' in r.name)
    assert 'Частичный' in row.note


def test_ordinary_http_without_area_then_existing_field_recalculates_estimates(client):
    state = new(client)
    answers = {k: r['value'] for k, r in draft()['answers'].items()}
    response = client.post('/studio/api/calculate', json={'revision': state['revision'], 'answers': answers})
    assert response.status_code == 200, response.text
    state = response.json()
    first = state['project_calculation']
    assert first['can_preview']
    assert any(a['id'] == 'area' for a in first['spec_quantity_review']['actions'])
    state = answer(client, state, 'building_area_m2', 800)
    assert state['project_calculation'] is None and state['preview'] is None
    response = client.post('/studio/api/calculate', json={'revision': state['revision']})
    assert response.status_code == 200, response.text
    second = response.json()['project_calculation']
    a, b = first['spec_quantity_review'], second['spec_quantity_review']
    assert a['counts']['positions'] == b['counts']['positions']
    assert a['counts']['missing'] - b['counts']['missing'] == 8
    assert b['counts']['estimated'] - a['counts']['estimated'] == 8
    assert not any(a['id'] == 'area' for a in b['actions'])
    for key in ('flows', 'head', 'meters', 'pumps'):
        assert first[key] == second[key]
