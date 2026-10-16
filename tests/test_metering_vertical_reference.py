"""User's vertical symbol, current VT.386 passport, and ordinary Studio path."""
from copy import deepcopy
from dataclasses import asdict, replace
from math import dist
import re
from xml.etree import ElementTree as ET

import pytest

from app.data.metering_products import get_metering_catalogue
from app.intake.studio_intake import answer_field
from app.intake.studio_project import calculate_project
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_hot_node import hot_meter_view
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_orientation import check_product_orientation
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_vertical_drawing import _ink
from tests.test_studio_apartment_meters import draft
from tests.test_studio_metering_nodes import project
from tests import test_studio as studio_tests

client = studio_tests.client


@pytest.mark.parametrize('dn,length,height', [(15,56,62),(20,58,67),(25,84,91)])
def test_vt386_current_passport_not_old_album(dn, length, height):
    p = get_metering_catalogue().products[f'valtec-vt386-dn{dn}']
    assert p.body_length_mm == length
    assert p.dimensions_mm['B_overall'] == height
    assert 'B_above_axis' not in p.dimensions_mm
    assert p.source_ids == ('vt386-0625',)
    assert p.pn_bar == 16 and p.temperature_c == (1,110)
    assert p.connection_sex == 'female' and p.connection_standard == 'G'
    assert p.country_of_manufacture == 'unknown'
    assert not p.flows_m3h  # Geometry evidence doesn't become a hydraulic algorithm.
    for axis in ('horizontal_dial_up','vertical_up'):
        assert check_product_orientation(p, axis).allowed is True
    assert check_product_orientation(p, 'vertical_down').allowed is False


@pytest.mark.parametrize('axis', ['horizontal_dial_up','vertical_up'])
@pytest.mark.parametrize('residents,dn,length', [(20,15,56),(100,20,58),(200,25,84)])
def test_studio_inline_family_has_one_filter_no_extra_elbows(axis, residents, dn, length, tmp_path):
    d = draft(residents=residents, apartments=residents//2, vu_orientation=axis,
              vu_hot_orientation='horizontal_dial_up', vu_filter_layout='valtec_vt386',
              vu_drawing_scale='10')
    p = project(d, tmp_path); before = deepcopy(asdict(p))
    layout = build_metering_layout(p)
    assert layout.parts and not layout.issues
    filt = layout.part('filter')
    assert filt.catalogue_id == f'valtec-vt386-dn{dn}'
    assert dist(filt.points[0],filt.points[-1])*layout.scale == pytest.approx(length)
    assert not any(part.kind == 'elbow90' for part in layout.parts)
    rows = build_metering_spec_section(p).rows
    assert sum('filter' in r.component_ids for r in rows) == 1
    assert next(r for r in rows if 'filter' in r.component_ids).catalogue_id == filt.catalogue_id
    assert p.metering_detail.catalogue_items == {}  # Derived IDs not sticky.
    assert not hot_meter_view(p).metering_detail.filter_inline_family
    assert asdict(p) == before


@pytest.mark.parametrize('axis', ['vertical_up','vertical_down'])
@pytest.mark.parametrize('scale', [5,10,20])
def test_meter_symbol_not_mirrored_and_keeps_axial_catalogue_length(axis, scale, tmp_path):
    p = project(draft(vu_orientation=axis, vu_drawing_scale=str(scale)), tmp_path)
    layout = build_metering_layout(p)
    part = layout.part('meter')
    root = ET.fromstring('<svg>'+_ink(part,scale)+'</svg>')
    assert not any(el.get('transform') for el in root.iter())
    symbol = root.find('.//g[@data-vu-ugo="vertical-meter"]')
    box = symbol.find('rect')
    x,y,w,h = (float(box.get(k)) for k in ('x','y','width','height'))
    assert h*scale == pytest.approx(part.length_mm)
    fill = symbol.find('path[@data-meter-filled-half="upper-left"]')
    coordinates = [float(n) for n in re.findall(r'-?\d+(?:\.\d+)?',fill.get('d'))]
    assert coordinates == pytest.approx([x,y,x+w,y,x,y+h],abs=.0011)
    assert 'data-body-dimension="meter"' in layout_contents(p)[0]
    # Missing L may have only a symbolic icon, not a nominal catalogue size.
    unknown = ET.fromstring('<svg>'+_ink(replace(part,length_mm=None,catalogue_id=''),scale)+'</svg>')
    assert float(unknown.find('.//g[@data-vu-ugo="vertical-meter"]/rect').get('height')) == 3


@pytest.mark.parametrize('mode', ['down','dn','origin','manual','magnetic','pressure','temperature','turn'])
def test_inline_filter_conflict_blocks_instead_of_substituting(mode, tmp_path):
    d = draft(vu_orientation='vertical_up', vu_filter_layout='valtec_vt386')
    if mode == 'down': answer_field(d,'vu_orientation','vertical_down')
    if mode == 'dn': answer_field(d,'residents',500)
    if mode == 'origin': answer_field(d,'russian_equipment_only','yes')
    p = project(d,tmp_path)
    if mode == 'manual': p.metering_detail.catalogue_items['filter'] = 'valtec-vt192-dn15'
    if mode == 'magnetic': p.metering_detail.enhancements['magnetic_filter'] = 'vodopribor_fmf_replace'
    if mode == 'pressure': p.metering_detail.design_pressure_bar = 17
    if mode == 'temperature': p.metering_detail.water_temperature_c = 111
    if mode == 'turn': p.metering_detail.fitting_items['filter_turn_in'] = 'valtec-vtr090-dn15'
    layout = build_metering_layout(p)
    assert not layout.parts and layout.issues


def test_option_removal_and_hydraulic_results_unchanged(tmp_path):
    d = draft(vu_orientation='vertical_up')
    before = calculate_project(d)
    answer_field(d,'vu_filter_layout','valtec_vt386')
    after = calculate_project(d)
    for key in ('flows','head','hydraulics','hot_hydraulics','pumps','fire','meters'):
        assert before[key] == after[key]
    answer_field(d,'vu_filter_layout','inline')
    p = project(d,tmp_path)
    assert not p.metering_detail.filter_inline_family
    assert not build_metering_layout(p).part('filter').catalogue_id
    assert MeteringDetailData(filter_inline_family='unknown').validate()
    assert MeteringDetailData(filter_inline_family='valtec_vt386',
                             filter_offset_family='valtec_vt192_vtr090').validate()


def test_http_vt386_choice_survives_reload(client):
    state = studio_tests.new(client)
    d = draft(vu_orientation='vertical_up', vu_filter_layout='valtec_vt386')
    response = client.post('/studio/api/calculate',json={'revision':state['revision'],
        'answers':{k:v['value'] for k,v in d['answers'].items()}})
    assert response.status_code == 200
    layout = response.json()['project_calculation']['metering_layout']
    assert layout['drawing_available'] and layout['filter_layout'] == 'valtec_vt386'
    assert layout['orientation'] == 'vertical_up'
    saved = studio_tests.values(client.get('/studio/api/draft').json())
    assert saved['vu_filter_layout']['value'] == 'valtec_vt386'


def test_review_pdf_content_has_diameters_and_filter_condition(tmp_path):
    from scripts.preview_metering_vertical_reference import review_project
    p = review_project(tmp_path)
    svg = layout_contents(p)[0]
    assert 'Вход В1 · DN15' in svg and 'Выход В1 · DN15' in svg
    assert 'Обводная · DN15' in svg
    assert 'VT.386: пробка вниз' in svg
