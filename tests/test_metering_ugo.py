"""VU symbol regression: Appendix Г appearance must not alter body dimensions."""
from copy import deepcopy
from dataclasses import asdict, replace
import math
import xml.etree.ElementTree as ET

import pytest

from app.pz.metering_detail import _assembly, drawing_state
from app.pz.metering_layout import (
    _dimension_offset, _part_svg, _symbol_half_height, build_metering_layout, layout_contents,
)
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_ugo import connector, gauge, is_ball_cock, shutoff
from scripts.preview_metering_detail import catalogue_review_project


def example():
    p = catalogue_review_project()
    p.metering_detail.inline_joint_selection_mode = 'catalogue_proposal'
    p.metering_detail.service_selection_mode = 'catalogue_proposal'
    return p


def root(svg):
    return ET.fromstring('<svg>'+svg+'</svg>')


def test_general_shutoff_is_not_a_boxed_throttling_valve_or_gate():
    r = root(shutoff(10,20))
    paths = list(r.iter('path'))
    assert len(paths) == 2 and all(p.get('fill') == 'white' for p in paths)
    assert not list(r.iter('rect')) and not list(r.iter('line'))
    assert not list(r.iter('circle'))


@pytest.mark.parametrize('ident,expected', [
    ('valtec-vt214-dn15',True), ('valtec-vt214-dn32',True),
    ('valtec-vt214-dn50',True), ('valtec-vt806-0404',True),
    ('valtec-vt192-dn32',False), ('unknown',False), ('',False),
])
def test_ball_cock_type_comes_from_selected_product(ident,expected):
    assert is_ball_cock(ident) is expected


def test_ball_cock_has_open_circle_and_check_flows_white_to_black():
    r = root(shutoff(10,20,ball=True))
    assert next(r.iter('circle')).get('fill') == 'white'
    assert not list(r.iter('rect'))
    check = list(root(shutoff(10,20,check=True)).iter('path'))
    assert check[0].get('fill') == 'white' and check[0].get('d').startswith('M7.2 ')
    assert check[1].get('fill') == 'black' and check[1].get('d').startswith('M12.8 ')


@pytest.mark.parametrize('radius',[3.5,4,10])
def test_pressure_gauge_keeps_diameter_and_has_an_arrowhead(radius):
    r = root(gauge(10,20,radius=radius))
    assert float(next(r.iter('circle')).get('r')) == radius
    assert len(list(r.iter('path'))) == 2
    assert r.find('.//path[@data-gauge-arrowhead="true"]').get('fill') == 'black'


@pytest.mark.parametrize('scale',[5,10,20])
def test_all_body_dimensions_and_quantities_survive_symbol_rendering(scale):
    p = example(); p.metering_detail.mounting.scale = scale
    before = deepcopy(asdict(p))
    layout = build_metering_layout(p)
    spec = build_metering_spec_section(p)
    for part in layout.parts:
        svg = _part_svg(part,scale)
        r = root(svg)
        element = r.find('.//g[@data-vu-component]')
        assert element.get('data-body-length-mm') == (str(part.length_mm) if part.length_mm is not None else '')
        assert 'data-body-envelope' not in svg
        if part.kind in ('shutoff','strainer','check','gauge','meter','reducer_reduce','reducer_expand'):
            # Only the meter itself, not the catalogue envelopes, is rectangular.
            assert len(list(r.iter('rect'))) == (1 if part.kind == 'meter' else 0)
        if part.length_mm is not None:
            assert math.dist(part.points[0],part.points[-1])*scale == pytest.approx(part.length_mm)
            if part.points[0][1] == part.points[-1][1] or part.kind == 'shutoff':
                # Numerical size stays on the drawing, not only in the model.
                assert f'{part.length_mm:g}'.replace('.',',') in ''.join(r.itertext())
    text = ''.join(layout_contents(p))
    assert 'data-gauge-arrowhead="true"' in text
    assert text.count('data-vu-ugo="ball-cock"') == 7
    assert build_metering_layout(p) == layout
    assert build_metering_spec_section(p) == spec
    assert asdict(p) == before


def test_unknown_vertical_shutoff_keeps_its_axis_without_inventing_a_length():
    part = build_metering_layout(example()).part('control_cock_1')
    part = replace(part,length_mm=None,catalogue_id='')
    svg = _part_svg(part,5)
    assert 'rotate(90,' in svg and 'data-body-length-mm=""' in svg
    assert 'data-vu-ugo="shutoff"' in svg


def test_ordinary_principle_sheet_uses_same_gauge_arrow_and_capped_controls():
    p = example()
    svg = _assembly(p,drawing_state(p))
    r = root(svg)
    assert r.find('.//path[@data-gauge-arrowhead="true"]') is not None
    controls = r.findall('.//g[@data-control-cock]')
    assert len(controls) == 2
    for element in controls:
        assert element.get('data-capped') == 'true'
        assert element.find('.//g[@data-vu-ugo="ball-cock"]') is not None


@pytest.mark.parametrize('scale',[5,10,20])
def test_actual_rendered_ugo_spans_catalogue_length_not_a_small_icon_with_pipe_tails(scale):
    """Measure PDF vector geometry, independently of model and dimension text."""
    import cairosvg
    import pymupdf

    p = example(); p.metering_detail.mounting.scale = scale
    layout = build_metering_layout(p)
    measured = set()
    for part in layout.parts:
        if part.length_mm is None:
            continue
        r = root(_part_svg(part,scale))
        body = r.find('.//g[@data-vu-scaled-symbol]')
        assert body is not None, part.id
        # The group excludes dimension lines and labels; those must not make
        # a short symbol appear to have the correct physical width.
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
               'viewBox="0 0 420 297">'+ET.tostring(body,encoding='unicode')+'</svg>')
        with pymupdf.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()),filetype='pdf') as doc:
            boxes = [path['rect'] for path in doc[0].get_drawings()]
            assert boxes
            # Rect unions omit zero-area line bounds; keep nipple/cap strokes.
            bounds = pymupdf.Rect(min(b.x0 for b in boxes),min(b.y0 for b in boxes),
                                  max(b.x1 for b in boxes),max(b.y1 for b in boxes))
        horizontal = part.points[0][1] == part.points[-1][1]
        actual = (bounds.width if horizontal else bounds.height)*25.4/72
        assert actual == pytest.approx(part.length_mm/scale,abs=.002), part.id
        # A spanning underlay line would let the old small UGO pass the bbox
        # test. Closed UGO must have no such line, nor nonzero extension tails.
        if part.kind in ('meter','shutoff','check','strainer','reducer_reduce','reducer_expand'):
            tails = [e for e in body.findall('line') if e.get('y1') == e.get('y2')]
            assert all(e.get('x1') == e.get('x2') for e in tails), part.id
            if part.kind == 'meter':
                rect = body.find('rect')
                assert float(rect.get('width')) == pytest.approx(part.length_mm/scale)
        measured.add(part.kind)
    assert {'meter','shutoff','check','strainer','nipple','plug','reducer_reduce','reducer_expand'} <= measured


@pytest.mark.parametrize('scale',[5,10,20])
def test_dimension_and_mark_are_outside_scaled_meter_body(scale):
    p = example(); p.metering_detail.mounting.scale = scale
    part = build_metering_layout(p).part('meter')
    r = root(_part_svg(part,scale))
    assert float(r.find('.//rect').get('width')) == pytest.approx(260/scale)
    half = _symbol_half_height(part,scale)
    assert _dimension_offset(part,scale) >= half+8
    texts = list(r.iter('text'))
    dimension = next(e for e in texts if ''.join(e.itertext()) == '260')
    mark = next(e for e in texts if ''.join(e.itertext()) == '7')
    assert float(dimension.get('y'))-3.5 > part.center[1]+half
    assert float(mark.get('y')) < part.center[1]-half


def test_all_links_are_docked_or_connected_by_a_solid_line_not_empty_gaps():
    p = example()
    layout = build_metering_layout(p)
    r = root(layout_contents(p)[0])
    links = r.findall('.//g[@data-vu-link]')
    assert {e.get('data-vu-link') for e in links} == {p.before+'>'+p.after for p in layout.links}
    by_id = {p.before+'>'+p.after:p for p in layout.links}
    for element in links:
        a,b = by_id[element.get('data-vu-link')].points
        if a == b:
            assert len(element) == 0 and element.get('data-link-ink') == 'docked'
        else:
            assert element.get('data-link-ink') == 'solid'
            line = element.find('line')
            assert (float(line.get('x1')),float(line.get('y1'))) == pytest.approx(a)
            assert (float(line.get('x2')),float(line.get('y2'))) == pytest.approx(b)
            assert float(line.get('stroke-width')) == .6
            assert line.get('stroke-dasharray') is None
    assert all(e.get('data-mounting-unresolved') == 'true' for e in links)
    assert not list(r.findall('.//*[@stroke-dasharray]'))
    assert layout.overall_length_mm is None


@pytest.mark.parametrize('ident', ['joint_valve_before__filter', 'outlet_thread'])
def test_nipples_use_two_open_threaded_ends_not_flange_ticks(ident):
    part = build_metering_layout(example()).part(ident)
    r = root(_part_svg(part,5))
    body = r.find('.//g[@data-vu-ugo="threaded-fitting"]')
    assert body is not None
    ports = body.findall('g[@data-vu-port="coupling-thread"]')
    assert len(ports) == 2
    for port in ports:
        lines = port.findall('line')
        assert len(lines) == 2
        assert all(e.get('y1') == e.get('y2') for e in lines)
        assert not any(e.get('x1') == e.get('x2') for e in lines)


@pytest.mark.parametrize('ident,pipe_left', [
    ('outlet_connector',False), ('connection_meter_valve_out_connector',False),
    ('connection_bypass_valve_out_connector',False),
    ('connection_inlet_valve_in_connector',True), ('connection_filter_in_connector',True),
    ('connection_bypass_valve_in_connector',True),
])
def test_combined_connector_orientation_comes_from_connection_role(ident,pipe_left):
    part = replace(build_metering_layout(example()).part('outlet_connector'),id=ident)
    r = root(_part_svg(part,5))
    body = r.find('.//g[@data-vu-ugo="thread-socket-fitting"]')
    socket = body.find('g[@data-vu-port="socket"]')
    thread = body.find('g[@data-vu-port="coupling-thread"]')
    assert socket.get('data-port-side') == ('left' if pipe_left else 'right')
    assert thread.get('data-port-side') == ('right' if pipe_left else 'left')
    assert ' A' in socket.find('path').get('d')


def test_unknown_connector_does_not_receive_an_invented_connection_type():
    assert connector(0,10,0,catalogue_id='unknown') is None


@pytest.mark.parametrize('scale',[5,10,20])
def test_connected_control_dimensions_and_marks_clear_the_meter_kit(scale):
    p=example(); p.metering_detail.mounting.scale=scale
    layout=build_metering_layout(p)
    r=root(layout_contents(p)[0])
    for number in (1,2):
        cock=layout.part(f'control_cock_{number}')
        cap=layout.part(f'control_cap_{number}')
        assert cock.points[0][1] >= cock.center[1]-cock.length_mm/scale/2
        assert cock.points[0][1] >= 161
        body=r.find(f'.//g[@data-vu-component="{cock.id}"]')
        end=r.find(f'.//g[@data-vu-component="{cap.id}"]')
        mark=next(e for e in body.iter('text') if ''.join(e.itertext())=='4.1')
        capmark=next(e for e in end.iter('text') if ''.join(e.itertext())=='4.2')
        dimension=next(e for e in body.iter('text') if ''.join(e.itertext())=='47,5')
        # Dimensions remain right-hand. Marks sit outside the pair; at small
        # scales the first pair moves below captions, not across them.
        assert float(dimension.get('x')) > cock.center[0]
        if number == 2:
            assert float(mark.get('x')) > float(dimension.get('x'))+3
        else:
            from app.pz.metering_detail import _label_width
            assert mark.get('text-anchor') == 'end'
            assert float(mark.get('x')) < cock.center[0]-3
            for label in (mark, capmark):
                left = float(label.get('x'))-_label_width(label.text, 3.5)
                right = float(label.get('x'))
                baseline = float(label.get('y'))
                for caption in r.find('.//g[@data-protected-meter-kit="true"]').iter('text'):
                    cx, cy = float(caption.get('x')), float(caption.get('y'))
                    half = _label_width(caption.text, 3.5)/2
                    assert (right <= cx-half-2 or left >= cx+half+2
                            or abs(baseline-cy) >= 5.5)
        assert float(capmark.get('y'))-float(mark.get('y')) >= 5.5-1e-6
