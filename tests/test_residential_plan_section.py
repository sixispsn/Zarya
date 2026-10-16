"""The delivery is a connected section, not another annotated plan image."""
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfReader
import pytest

from app.architecture.residential_plan_study import load_plan_study
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine
from app.pz.residential_plan_section import (
    audit_plan_section_svg, build_plan_section_svg, fixture_paths,
    floor_templates, generate_plan_section_pdf, section_bays,
)


@pytest.fixture
def study():
    return load_plan_study(Path(__file__).parents[1]/"demo/residential_second_layout.study.json")


def test_every_fixture_reaches_its_own_section_outlet(study):
    paths = fixture_paths(study, floor_templates(study))
    assert len(paths) == 32
    for source, path in paths.items():
        stack, floor, *_ = source.split(':')
        route = next(r for r in study.routes if stack in r.ordered_stacks)
        assert path[-1] == route.outlet
        assert f"{stack}:{floor}" in path
        assert stack+":base:riser_in" in path
        assert len(path) == len(set(path))


def test_section_preserves_cleanouts_axes_unknowns_and_no_k2(study):
    svg = build_plan_section_svg(study)
    assert not audit_plan_section_svg(study, svg)
    root = ET.fromstring(svg)
    assert root.get('data-fixture-paths') == '32'
    assert len([r for r in root.iter() if r.get('data-floor-fixture')]) == 32
    assert len([r for r in root.iter() if r.get('data-floor-boundary')]) == 2
    assert len([r for r in root.iter() if r.get('data-lower-connection') == 'elbow-wye-cleanout']) == 2
    assert len([r for r in root.iter() if r.get('data-lower-connection') == 'elbow-wye-through']) == 2
    assert not any(r.get('data-k2-stack') or r.get('data-slope') for r in root.iter())
    assert all(r.get('data-text-height-mm') == '3.5' for r in root.iter() if r.get('data-unbound-slope'))
    assert 'схема бытовой канализации' in svg
    assert {b.stack for b in section_bays(study)} == {g.stack for g in study.groups}


@pytest.mark.parametrize('damage', ['apartment', 'riser', 'axis', 'cap', 'revision', 'grade', 'outlet', 'release', 'raster'])
def test_export_guard_detects_lost_graphic_elements(study, damage):
    root = ET.fromstring(build_plan_section_svg(study))
    def first(key):
        return next(r for r in root.iter() if r.get(key) is not None)
    if damage in ('apartment', 'riser', 'revision', 'grade', 'outlet'):
        key = {'apartment': 'data-section-apartment', 'riser': 'data-section-riser',
               'revision': 'data-riser-revision', 'grade': 'data-unbound-slope',
               'outlet': 'data-section-outlet'}[damage]
        first(key).attrib.pop(key)
    elif damage == 'axis':
        first('data-section-lower').set('data-axis-x', '99')
    elif damage == 'cap':
        first('data-lower-connection').set('data-accessible-capped-end', 'false')
    elif damage == 'release':
        root.set('data-release-ready', 'true')
    else:
        ET.SubElement(root, 'image')
    assert audit_plan_section_svg(study, ET.tostring(root, encoding='unicode'))


def test_pdf_is_one_vector_a2_section_with_explicit_data_gaps(study, tmp_path):
    path = generate_plan_section_pdf(tmp_path/'section.pdf', study)
    pages = PdfReader(path).pages
    assert len(pages) == 1
    page = pages[0]
    assert float(page.mediabox.width)*25.4/72 == pytest.approx(594)
    assert float(page.mediabox.height)*25.4/72 == pytest.approx(420)
    assert not page.images
    text = page.extract_text()
    for title in ('Принципиальная схема', 'Санузел', 'Кухня', 'Прочистка', 'Выпуск',
                  'Ревизия', 'н/д', 'Исходные данные требуют дополнения'):
        assert title in text
    for inherited in ('3,30', '6,60', '-3,10', '20 жителей', '0,020', '0,030', '\ufffd'):
        assert inherited not in text


@pytest.mark.parametrize('offsets', [(), (0,), (-4,), (float('nan'),), (float('inf'),)])
def test_short_leader_offsets_are_validated(offsets):
    with pytest.raises(ValueError, match='horizontal offsets'):
        LeaderLayoutEngine(bounds=LeaderBounds(0, 0, 10, 10), units_per_mm=1, horizontal_offsets_mm=offsets)
