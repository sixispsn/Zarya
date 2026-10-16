"""Approval fragment: paper geometry, original water UGO and no calculation writes."""
from copy import deepcopy
from dataclasses import asdict
import re
from xml.etree import ElementTree as ET

import cairosvg
import pymupdf
import pytest

from app.pz.water_floor_fragment import (
    APARTMENT_Y, BASEMENT, CENTRE, CUT, FLOOR, LEFT, MAIN, RIGHT,
    build_water_floor_fragment, water_fixture,
)
from tests.test_water_pipe_binding import source_project


def project():
    p = source_project()
    p.building.floors_below = 1
    p.building.floor_elevations_m = {1:0.,-1:-3.25}
    p.source.inputs_count = 2
    return p


def render(p=None):
    return build_water_floor_fragment(p or project(),profile='residential_full_bath')


def tagged(root,name):
    return [e for e in root.iter() if e.get(name) is not None]


def points(element):
    return [tuple(map(float,p.split(','))) for p in element.get('d').replace('M','').split(' L')]


def test_fragment_is_read_only_and_not_a_full_project_or_quantity_network():
    p = project()
    before = deepcopy(asdict(p))
    result = render(p)
    root = ET.fromstring(result.svg)
    assert asdict(p) == before
    assert root.get('data-release-ready') == root.get('data-takeoff-eligible') == 'false'
    assert root.get('data-water-floor-fragment') == 'approval-only'
    assert root.get('width') == '420mm' and root.get('height') == '297mm'
    assert len(tagged(root,'data-title-block')) == 1
    assert len(tagged(root,'data-section-slab')) == 2
    assert 'Показан один характерный ввод; по исходным вводов: 2' in result.svg
    assert 'Т3/Т4 и В2 в этот фрагмент не входят' in result.svg
    assert any('не распознаны' in w for w in result.warnings)


@pytest.mark.parametrize('kind',['sink','basin','bath','wc'])
@pytest.mark.parametrize('mirrored',[False,True])
def test_canonical_water_symbol_port_meets_its_connector(kind,mirrored):
    x = 99 if not mirrored else 2*CENTRE-99
    glyph = water_fixture(kind,x,APARTMENT_Y,mirrored=mirrored)
    assert glyph.port == (x,APARTMENT_Y-2)
    root = ET.fromstring('<g>'+glyph.svg+'</g>')
    lines = list(root.iter('line'))
    if kind != 'wc':
        assert float(lines[-1].get('x2')) == pytest.approx(glyph.port[0])
        assert float(lines[-1].get('y2')) == pytest.approx(glyph.port[1])
    else:
        body = root.find('g')
        cx,top,sx,sy = map(float,re.findall(r'[-\d.]+',body.get('transform')))
        assert float(lines[-1].get('x2'))*sx+cx == pytest.approx(glyph.port[0])
        assert float(lines[-1].get('y2'))*sy+top == pytest.approx(glyph.port[1])


def test_floor_has_eight_connected_fixture_symbols_not_two_generic_taps():
    root = ET.fromstring(render().svg)
    fixtures = [e for e in tagged(root,'data-fragment-component') if e.get('data-fragment-component') == 'fixture']
    pipes = {e.get('data-pipe'):e for e in tagged(root,'data-pipe')}
    assert len(fixtures) == 8
    for fixture in fixtures:
        side,kind = fixture.get('data-side'),fixture.get('data-kind')
        port = float(fixture.get('data-port-x')),float(fixture.get('data-port-y'))
        connector = points(pipes[f'feed-{side}-{kind}'])
        assert connector == [(port[0],APARTMENT_Y),port]
        assert pipes[f'feed-{side}-{kind}'].get('data-from') == f'{side}-apartment'
    for side,riser in [('left',191),('right',277)]:
        assert points(pipes[f'{side}-riser']) == [(riser,MAIN),(riser,CUT)]
        assert points(pipes[f'{side}-apartment-feed'])[0] == (riser,79)
        assert MAIN > FLOOR
    assert set(e.get('data-system') for e in pipes.values()) == {'В1'}


def test_sizes_and_unknowns_come_from_existing_binding_not_template():
    svg = render().svg
    assert all(label in svg for label in ('Ø110×6,6','Ø76×3,5','Ø48×3,5','Ø20×2'))
    p = project()
    p.v1_sections[2].inner_diameter_mm = 40
    result = render(p)
    assert 'Ø48×3,5' not in result.svg
    assert 'Ø по расчёту' in result.svg
    assert any('стояк' in w for w in result.warnings)
    assert 'data-fragment-component="apartment-regulator"' not in svg


def test_cut_hatching_elevations_and_wall_crossing():
    root = ET.fromstring(render().svg)
    cut = next(e for e in tagged(root,'data-fragment-component') if e.get('data-fragment-component') == 'full-width-cut')
    assert float(cut.get('data-left')) == LEFT-10
    assert float(cut.get('data-right')) == RIGHT+10
    assert len(tagged(root,'data-slab-hatch')) > 40
    levels = {e.get('data-component'):float(e.get('data-source-elevation-m'))
              for e in tagged(root,'data-source-elevation-m')}
    assert levels == {'v1-fragment-floor':0,'v1-fragment-base':-3.25,'inlet-axis':-2.195}
    pipe = next(e for e in tagged(root,'data-pipe') if e.get('data-pipe') == 'inlet-fragment')
    a,b = points(pipe)
    assert a[0] < LEFT < LEFT+2 < b[0]
    assert a[1] == b[1] == pytest.approx(FLOOR+(BASEMENT-FLOOR)*2.195/3.25,abs=.001)


def test_leaders_keep_shelf_arrow_and_vector_diameter_instead_of_missing_glyph():
    root = ET.fromstring(render().svg)
    leaders = tagged(root,'data-leader-id')
    assert len(leaders) == 3
    boxes = []
    for leader in leaders:
        assert leader.get('data-shelf-horizontal') == 'true'
        assert len(tagged(leader,'data-leader-arrow')) == 1
        assert leader.get('data-text-height-mm') == '3.5'
        boxes.append(tuple(float(leader.get('data-text-box-'+part)) for part in ('x1','y1','x2','y2')))
        if leader.get('data-leader-id').endswith('riser'):
            assert len(tagged(leader,'data-vector-diameter-sign')) == 1
    assert not any('Ø' in (t.text or '') for t in root.iter('{http://www.w3.org/2000/svg}text'))
    for i,a in enumerate(boxes):
        for b in boxes[i+1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


@pytest.mark.parametrize('field', ['profile','basement','level','inlet','zones','floors','inputs'])
def test_inapplicable_fragment_stops_instead_of_inventing_data(field):
    p = project()
    profile = 'residential_full_bath'
    if field == 'profile': profile = 'unknown'
    elif field == 'basement': p.building.floors_below = 0
    elif field == 'level': p.building.floor_elevations_m.pop(-1)
    elif field == 'inlet': p.metering_detail.inlet_elevation_m = float('nan')
    elif field == 'zones': p.building.zones = 2
    elif field == 'floors': p.building.floors_above = 1
    elif field == 'inputs': p.source.inputs_count = 0
    with pytest.raises(ValueError): build_water_floor_fragment(p,profile=profile)


def test_final_vector_pdf_a3_fonts_and_content_fit_frame():
    data = cairosvg.svg2pdf(bytestring=render().svg.encode('utf-8'))
    doc = pymupdf.open(stream=data,filetype='pdf')
    assert len(doc) == 1
    page = doc[0]
    assert page.rect.width == pytest.approx(420*72/25.4,abs=.01)
    assert page.rect.height == pytest.approx(297*72/25.4,abs=.01)
    assert not page.get_images()
    assert any('OpenGOST' in f[3] for f in page.get_fonts())
    safe = pymupdf.Rect(20*72/25.4,5*72/25.4,415*72/25.4,292*72/25.4)
    # GOST additional columns 20-22 are outside the main frame, on the
    # filing margin; format designation (26) is below its bottom edge.
    inventory = pymupdf.Rect(8*72/25.4,207*72/25.4,13*72/25.4,292*72/25.4)
    paper_format = pymupdf.Rect(390*72/25.4,292*72/25.4,415*72/25.4,297*72/25.4)
    for word in page.get_text('words'):
        rect = pymupdf.Rect(word[:4])
        assert (safe.contains(rect) or
                (word[4] in {'Взам.', 'инв.', '№', 'Подп.', 'и', 'дата', 'Инв.', 'подл.', '№подл.'}
                 and inventory.contains(rect)) or
                (word[4] in {'Формат', 'А3'} and paper_format.contains(rect))), word
    assert '\ufffd' not in page.get_text()
