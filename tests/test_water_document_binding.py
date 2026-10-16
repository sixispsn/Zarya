from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from app.intake import samara_study
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request
from app.pz.generator import generate_pz_html
from app.pz.project import BuildingPurpose, HwsType
from app.pz.scheme import build_scheme
from app.pz.water_document_binding import water_material_context, water_pressure_presentation
from app.pz.water_station_drafting import build_pump_zone_scheme_pages
from app.pz.spec import build_specification


@pytest.fixture
def project(tmp_path):
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    return samara_study.build(draft,tmp_path,render=False)[0].project


def test_materials_and_pressure_are_read_only_and_match_current_path(project):
    before = deepcopy(asdict(project))
    context = water_material_context(project)
    for group in ('cold_rows','hot_rows'):
        riser = next(r for r in context[group] if r.role == 'Стояк')
        apartment = next(r for r in context[group] if r.role == 'Квартирная подводка')
        assert 'Стальная 48' in riser.material and riser.size == 'Ø48×3,5'
        assert riser.inner_mm == 41
        assert 'PE-X 20' in apartment.material and apartment.size == 'Ø20×2'
    assert water_pressure_presentation(project).state == 'static_only'
    html = generate_pz_html(project)
    assert 'стояки и поквартирная разводка — сшитый полиэтилен' not in html
    assert 'data-pipe-key="В1-riser"' in html
    assert 'data-pipe-key="Т3-riser"' in html
    assert 'data-pipe-key="Т4-network"' in html
    assert 'Выполнена только предварительная статическая проверка В1' in html
    assert asdict(project) == before


@pytest.mark.parametrize('role,index', [('main',1),('riser',2)])
def test_inconsistent_material_size_does_not_revert_to_generic_description(project,role,index):
    project.t3_sections[index] = replace(project.t3_sections[index],inner_diameter_mm=1)
    row = next(r for r in water_material_context(project)['hot_rows'] if r.key == 'Т3-'+role)
    assert row.material == 'Требует уточнения'
    assert row.inner_mm is None
    spec = build_specification(project,scope='water')
    hot = next(s for s in spec.sections if s.title.startswith('Т3-Т4'))
    row = next(r for r in hot.rows if r.component_ids == ('t3-'+role,))
    assert row.type_mark == 'Материал и размер по расчёту Т3'


@pytest.mark.parametrize('kind', [HwsType.NONE,HwsType.LOCAL])
def test_no_stale_t3_or_fabricated_shared_t4_for_local_or_absent_hws(project,kind):
    project.building.hws_type = kind
    assert not water_material_context(project)['hot_bound']
    html = generate_pz_html(project)
    assert 'data-pipe-key="Т3-riser"' not in html
    assert 'data-pipe-key="Т4-network"' not in html
    if kind == HwsType.NONE:
        assert 'Магистрали горячего водоснабжения —' not in html


def test_no_sections_keep_explicit_generic_material_choices():
    p = build_project(load_request(Path('demo/demo_project.yaml').read_text()))
    p.v1_network = None; p.v1_sections = []; p.t3_sections = []
    p.materials.cold_distribution = 'Материал пользователя'
    html = generate_pz_html(p)
    assert 'Материал пользователя' in html and 'id="water-materials"' not in html


@pytest.mark.parametrize('kind',[BuildingPurpose.RESIDENTIAL,BuildingPurpose.PUBLIC])
def test_building_zone_count_alone_does_not_certify_pressure(project,kind):
    project.building.purpose = kind
    project.building.zones = 2
    html = generate_pz_html(project)
    assert 'data-water-pressure="not_checked"' in html
    assert 'давление в каждой зоне поддерживается' not in html


@pytest.mark.parametrize('checks,state',[
    ([], 'static_only'),
    ([(True,None)], 'partial'),
    ([(False,None)], 'outside_limits'),
    ([(True,False)], 'outside_limits'),
    ([(True,True),(True,None)], 'partial'),
    ([(True,True)], 'checked_nodes'),
])
def test_pressure_view_does_not_equate_missing_checks_with_success(project,checks,state):
    project.v1_hydraulic_result = replace(project.v1_hydraulic_result,
        pressure_checks=[SimpleNamespace(minimum_ok=a,maximum_ok=b) for a,b in checks])
    assert water_pressure_presentation(project).state == state


def test_no_regulator_is_drawn_from_building_height_or_pump_head(project):
    state = water_pressure_presentation(project)
    drawing = build_scheme(project)
    text = ' '.join(ET.fromstring(drawing.svg).itertext())
    station = build_pump_zone_scheme_pages(project)[0]
    for line in state.drawing_lines:
        assert line in text and line in station
    assert 'РД-В1-' not in text
    assert state.text in drawing.warnings


def test_diameter_updates_propagate_without_altering_calculation(project):
    project.t3_sections[2] = replace(project.t3_sections[2],material='Стальная 60×3',inner_diameter_mm=54)
    before = deepcopy(asdict(project))
    html = generate_pz_html(project)
    context = water_material_context(project)
    assert next(r for r in context['hot_rows'] if r.key == 'Т3-riser').size == 'Ø60×3'
    assert 'Ø60×3' in html
    assert asdict(project) == before


def test_rendered_head_rows_and_material_intro_stay_with_their_values(project,tmp_path):
    from pypdf import PdfReader
    from app.pz.generator import generate_pz_pdf

    path = tmp_path / 'water-text.pdf'
    generate_pz_pdf(project,str(path))
    texts = [' '.join(p.extract_text().split()) for p in PdfReader(path).pages]
    # Both paths and their computed heads must stay in the same small table.
    # Previously the T3 label moved to the next page, leaving its numbers behind.
    head_page = next(t for t in texts if 'Расчётная трасса' in t)
    for calculation_path in project.head_paths.paths:
        assert calculation_path.label in head_page
        assert f'{calculation_path.head.h_required_m:.2f}'.replace('.',',') in head_page
    material_page = next(t for t in texts if 'Материалы и размеры характерных' in t)
    assert 'В1-Подвод' in material_page and 'Т3-Квартира' in material_page
