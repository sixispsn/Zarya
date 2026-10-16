"""Position 3.2 must occupy the catalogue L/scale, not merely reserve it."""
from copy import deepcopy
from dataclasses import asdict, replace
from math import dist
import re
from xml.etree import ElementTree as ET

import pytest

from app.pz.metering_layout import build_metering_layout, layout_contents, _part_svg, _gauge_cock_dimension_notes
from app.pz.metering_vertical_drawing import _ink
from app.pz.metering_spec import build_metering_spec_section
from tests.test_metering_service import example
from scripts.preview_metering_vertical_reference import review_project


@pytest.mark.parametrize('scale',[5,10,20])
@pytest.mark.parametrize('axis',['horizontal_dial_up','vertical_up','vertical_down'])
def test_cock_ink_and_endpoint_span_are_both_scaled(axis,scale,tmp_path):
    p=review_project(tmp_path); d=p.metering_detail
    d.mounting.scale=scale
    d.assembly_orientation=d.meter_mounting=axis
    d.meter_orientations={k:axis for k in d.meter_orientations}
    # A generic vertical test must not rotate a horizontal-only filter.
    d.catalogue_items.pop('filter',None)
    if axis=='vertical_down':
        d.filter_inline_family=''
    before=deepcopy(asdict(p))
    layout=build_metering_layout(p)
    assert not layout.issues
    part=layout.part('gauge_cock')
    assert part.mark=='3.2' and part.length_mm==75
    assert dist(*part.points)*scale==pytest.approx(75)
    ink=_part_svg(part,scale) if axis=='horizontal_dial_up' else _ink(part,scale)
    root=ET.fromstring('<svg>'+ink+'</svg>')
    scaled=root.find('.//g[@data-vu-scaled-symbol="gauge_cock"]')
    assert scaled is not None
    symbol=scaled.find('.//g[@data-vu-ugo="ball-cock"]')
    assert symbol is not None
    # The two triangle bases are the actual symbol ends. No short glyph
    # plus long pipe tails, and no pipe through the white symbol interior.
    xs=[float(re.match(r'M(-?[\d.]+)',e.get('d')).group(1)) for e in symbol.findall('path')]
    assert (max(xs)-min(xs))*scale==pytest.approx(75,abs=.003)
    assert not scaled.findall('.//line')
    svg=''.join(layout_contents(p))
    assert 'L=75 мм по паспорту' in svg and '75,1' in svg
    assert 'L не принят: паспорт 75' not in svg
    spec=build_metering_spec_section(p)
    row=next(r for r in spec.rows if 'gauge_cock' in r.component_ids)
    assert row.diagram_pos=='3.2' and row.qty==1 and row.catalogue_id==part.catalogue_id
    assert asdict(p)==before


def test_missing_cock_length_cannot_be_mistaken_for_a_scaled_drawing():
    layout=build_metering_layout(example())
    unknown=replace(layout.part('gauge_cock'),length_mm=None,dimension_basis='unknown',catalogue_id='')
    layout=replace(layout,parts=tuple(unknown if p.id=='gauge_cock' else p for p in layout.parts))
    assert 'Поз. 3.2: УГО крана манометра вне масштаба' in _gauge_cock_dimension_notes(layout)[0]
    assert 'data-vu-scaled-symbol="gauge_cock"' not in _part_svg(unknown,layout.scale)


def test_review_cock_dimension_and_position_have_separate_lanes(tmp_path):
    p=review_project(tmp_path)
    root=ET.fromstring('<svg>'+layout_contents(p)[0]+'</svg>')
    mark=root.find('.//g[@data-horizontal-mark="gauge_cock"]/text')
    dimension=root.find('.//g[@data-body-dimension="gauge_cock"]/text')
    assert mark.text=='3.2' and dimension.text=='75'
    assert abs(float(mark.get('y'))-float(dimension.get('y'))) > 5
    gauge_mark=root.find('.//g[@data-horizontal-mark="gauge"]/text')
    layout=build_metering_layout(p)
    gauge=layout.part('gauge')
    assert float(gauge_mark.get('y')) > gauge.points[0][1]+gauge.gauge_diameter_mm/(2*layout.scale)+3.5
