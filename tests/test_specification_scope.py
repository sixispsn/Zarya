"""A section-specific export must not evaluate or count the other section."""
from dataclasses import asdict
from pathlib import Path

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request
from app.pz.generator import generate_spec_html, generate_wastewater_spec_html
from app.pz.spec import build_specification, build_water_specification, build_wastewater_specification


@pytest.fixture
def project():
    return build_project(load_request(Path('demo/demo_project.yaml').read_text()))


def rows(spec):
    return [r for section in spec.sections for r in section.rows]


@pytest.mark.parametrize('scope,builder', [
    ('water', build_water_specification), ('wastewater', build_wastewater_specification),
])
def test_selected_output_preserves_quantities_and_does_not_mutate_project(project, scope, builder):
    before = asdict(project)
    full = build_specification(project)
    expected = [s for s in full.sections if (s.division == 'Водоотведение') == (scope == 'wastewater')]
    selected = builder(project)
    assert [s.title for s in selected.sections] == [s.title for s in expected]
    def quantities(sections):
        return [(r.name, r.type_mark, r.unit, r.qty, r.quantity_basis) for s in sections for r in s.rows]
    assert quantities(selected.sections) == quantities(expected)
    positions = [r.pos for r in rows(selected) if r.pos is not None]
    assert positions == list(range(1, len(positions) + 1))
    assert asdict(project) == before


def test_ios2_export_has_no_k1_k2_section_even_with_invalid_sewer_input(project):
    project.sewage.pipes = [object()]
    project.sewage.elements = [object()]
    html = generate_spec_html(project)
    assert 'В1 —' in html and 'Т3-Т4 —' in html
    assert 'Водоотведение' not in html and 'К1 —' not in html and 'К2 —' not in html


def test_ios3_export_does_not_run_water_pipe_or_fixture_calculations(project, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('water pipe/insulation calculation entered IOS3')
    monkeypatch.setattr('app.pz.spec.pipe_size', unexpected)
    monkeypatch.setattr('app.pz.spec.calculate_insulation', unexpected)
    project.fixtures = [object()]
    html = generate_wastewater_spec_html(project)
    assert 'К1 —' in html and 'К2 —' in html
    assert 'В1 —' not in html and 'Т3-Т4 —' not in html
    assert 'Оценка по площади, не обмер трасс' not in html
    assert 'Метраж по площади здания не применяется' in html


def test_area_estimates_are_visible_on_each_affected_quantity(project):
    spec = build_water_specification(project)
    v1 = next(s for s in spec.sections if s.title.startswith('В1'))
    affected = [r for r in v1.rows if r.name.startswith(('Труба ', 'то же Ду', 'Трубки теплоизоляционные',
                                                       'то же толщ.', 'Крепление скользящее', 'Хомут трубный'))]
    assert affected
    assert all(r.quantity_basis == 'area_estimate' for r in affected)
    assert all('не обмер трасс' in r.quantity_note for r in affected)
    assert 'Оценка по площади, не обмер трасс' in generate_spec_html(project)
    assert all(r.quantity_basis != 'area_estimate' for s in spec.sections if s.title.startswith('В2') for r in s.rows)


def test_source_quantities_are_not_certified_as_measured_or_confirmed(project):
    spec = build_wastewater_specification(project)
    pipes = [r for r in rows(spec) if r.unit == 'м']
    assert pipes and all(r.quantity_basis == 'source_rows' for r in pipes)
    assert 'само по себе не подтверждает' in spec.note
    assert all('По заданным' in r.quantity_note for r in pipes)


def test_unknown_scope_fails_instead_of_silently_exporting_everything(project):
    with pytest.raises(ValueError, match='scope'):
        build_specification(project, scope='ios4')
