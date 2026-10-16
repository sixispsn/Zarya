"""Whole-document regressions: product layout, PZ identity and readable pages."""
from copy import deepcopy
from dataclasses import asdict
from math import dist
from xml.etree import ElementTree as ET

import pytest

from app.pz.generator import generate_pz_html
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_layout import build_metering_layout, layout_contents, _control_mark_positions, _vertical_mark_positions
from app.pz.metering_maintenance import audit_metering_maintenance
from app.pz.metering_presentation import metering_presentation
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_spec import build_metering_spec_section
from scripts.preview_metering_service_matrix import CASES, review_case


@pytest.mark.parametrize('orientation,filter_layout,title', CASES)
@pytest.mark.parametrize('bypass', [False, True])
def test_three_real_studio_layouts_reach_full_document(orientation,filter_layout,title,bypass,tmp_path):
    p = review_case(tmp_path,orientation,filter_layout)
    p.meters.has_bypass = bypass
    p.meters.single_input_bypass_note = bypass
    if not bypass:
        p.metering_detail.catalogue_items.pop('bypass_valve')
        p.metering_detail.bypass_dn = None
    before = deepcopy(asdict(p))
    state = drawing_state(p)
    selection = resolve_metering_products(p,state.meter,bypass=bypass,electric_bypass=False)
    chain = build_metering_chain(p.metering_detail,state,selection)
    layout = build_metering_layout(p)
    assert not layout.issues and layout.parts
    assert not selection.errors
    rows = build_metering_spec_section(p).rows
    owned = [ident for row in rows for ident in row.component_ids]
    assert len(owned)==len(set(owned))==len(chain.nodes)
    assert set(owned)=={part.id for part in layout.parts}
    for part in layout.parts:
        if part.length_mm is not None:
            assert dist(part.points[0],part.points[-1])*layout.scale == pytest.approx(part.length_mm)
    for body in layout_contents(p):
        root = ET.fromstring('<svg>'+body+'</svg>')
        assert all(float(t.get('y',0))<236 for t in root.findall('.//text'))  # stamp starts at 237 mm
    all_pages = build_metering_detail_pages(p)
    assert any('data-vu-component="outlet_valve"' in page for page in all_pages)
    assert any('data-maintenance-target="meter"' in page for page in all_pages)
    if orientation == 'vertical_down':
        assert layout.part('filter').catalogue_id == 'valtec-vt192-dn15'
        assert 'Продолжение условий' in layout_contents(p)[0]
        assert 'Проверка малых расходов' in ''.join(layout_contents(p)[1:])
    report = audit_metering_maintenance(p)
    assert not report['safe_to_remove'] and not report['all_design_checks_passed']
    assert not report['hydraulic_calculation_changed']
    assert asdict(p)==before


def test_pz_service_positions_match_spec_and_do_not_leak_to_old_mode(tmp_path):
    p = review_case(tmp_path,'vertical_up','valtec_vt386')
    before = deepcopy(asdict(p))
    wording = metering_presentation(p)
    assert 'поз. 1.3' in wording['service'] and 'поз. 4.3, 4.4' in wording['service']
    html = generate_pz_html(p)
    assert wording['service'] in html and wording['inlet'] in html
    assert asdict(p)==before
    p.metering_detail.maintenance_layout='existing'
    assert not metering_presentation(p)['service']
    assert 'В сервисной компоновке' not in generate_pz_html(p)


def test_pz_inlet_uses_inlet_row_not_cold_branch(tmp_path):
    from app.intake import samara_study
    d=dict(revision=0,answers={},documents=[])
    samara_study.initialize(d,None)
    p=samara_study.build(d,tmp_path)[0].project
    assert p.meters.cold_meter_dn==50  # the current inlet summary was already correct
    # A stale convenience field must not override the actual inlet selection.
    p.meters.cold_meter_dn=32
    text=metering_presentation(p)['inlet']
    assert 'узлов — 2' in text and 'DN50 на каждом вводе' in text
    assert 'DN32' not in text
    assert text in generate_pz_html(p)


def test_unknown_inlet_does_not_borrow_branch_or_room(tmp_path):
    p=review_case(tmp_path,'vertical_up','valtec_vt386')
    p.meters.selection_error='Не пройдена проверка'
    p.metering_detail.room_number=p.metering_detail.room_name=''
    text=metering_presentation(p)['inlet']
    assert 'водомер не определён' in text and 'архитектурным данным' in text
    assert 'DN15' not in text and 'подвал' not in text


def test_horizontal_service_marks_do_not_point_to_next_branch(tmp_path):
    p=review_case(tmp_path,'horizontal_dial_up','valtec_vt386')
    layout=build_metering_layout(p)
    marks=_control_mark_positions(layout,_vertical_mark_positions(layout))
    assert marks['control_cock_2'][0] < layout.part('maintenance_cock_out').center[0]-4
    assert marks['maintenance_cock_out'][0] > layout.part('maintenance_cock_out').center[0]
    assert marks['maintenance_cock_in'][0] < layout.part('maintenance_cock_in').center[0]
