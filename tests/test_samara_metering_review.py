"""Frozen Samara uses the ordinary model-proposal layer, not historic blanks."""
from dataclasses import replace
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

import pytest

from app.intake import samara_study
from app.intake.studio_metering import catalogue_proposal
from app.intake.yaml_io import dump_request, load_request
from app.pz.metering_detail import build_metering_detail_pages
from app.pz.spec import build_water_specification


@pytest.fixture(scope='module')
def sample():
    d = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(d, None)
    with TemporaryDirectory() as folder:
        b, fingerprint = samara_study.build(d, folder)
    return d, b.project, fingerprint


def test_same_proposal_inputs_and_no_hydraulic_change(sample):
    d, p, fingerprint = sample
    req, _, result, _ = samara_study.inputs(d)
    frozen = samara_study.load_case()['payload']
    base = load_request(frozen['request_yaml'])
    assert req.metering_detail == catalogue_proposal(base.metering_detail, dimensioned=True)
    assert req.metering_detail.mounting.enabled
    assert req.metering_detail.mounting.scale == base.metering_detail.mounting.scale
    assert load_request(dump_request(req)).metering_detail == req.metering_detail
    assert replace(req, metering_detail=base.metering_detail,
                   apartment_water_units=base.apartment_water_units,
                   wastewater_presentation=base.wastewater_presentation) == base
    assert result == frozen['result'] and fingerprint == d['study']['snapshot']
    assert [r.dn for r in p.meters.rows] == [50, 32, 32]
    assert [r.h_a for r in p.meters.rows] == [1.451, 3.479, 4.703]
    assert [r.q_min_passport_m3h for r in p.meters.rows] == [.45, .12, .12]
    assert all(r.q_min_hourly_m3h is None and r.ok_v is None for r in p.meters.rows)
    assert all(r.product['id'] and r.product['automatic'] for r in p.meters.rows)
    pages = build_metering_detail_pages(p)
    assert any('data-meter-mounting="true"' in svg for svg in pages)
    # The hot node includes the already-added maintenance/continuation sheets.
    # Check the actual independent subassembly, not the historical page count.
    from app.pz.metering_hot_node import hot_detail_contents
    hot_pages = hot_detail_contents(p)
    assert sum('data-meter-hot-node="true"' in svg for svg in pages) == len(hot_pages)
    assert (p.pumps.q_design_m3h, p.pumps.h_design_m) == pytest.approx((11.466, 50.25))
    assert not d['project_calculation']['can_release']


def test_model_counts_not_drawing_symbols_or_doubled_connection_kits(sample):
    _, p, _ = sample
    spec = build_water_specification(p)
    vu = next(s for s in spec.sections if s.title == 'В1 — Водомерный узел')
    hot = next(s for s in spec.sections if s.title.startswith('ВУ-Г.'))
    meters = [r for s in (vu, hot) for r in s.rows if r.name.startswith('Счётчик воды')]
    assert [r.qty for r in meters] == [2, 1, 1]
    assert meters[-1].component_ids == ('hot:meter',)
    assert all(r.catalogue_id and r.type_mark and r.manufacturer for r in meters)
    assert '1 на узел × 2 узлов' in meters[0].quantity_source
    kit = next(r for r in vu.rows if r.name.startswith('Присоединительный комплект'))
    assert kit.qty == 2 and kit.unit == 'компл.' and '1 комплект на узел × 2' in kit.quantity_source
    assert all(r.qty is None for r in vu.rows if r.unit == 'м')
    estimates = [r for s in spec.sections for r in s.rows if r.quantity_basis == 'area_estimate']
    assert estimates and all('Оценка по площади' in r.quantity_note for r in estimates)
    assert not any(r.quantity_basis == 'metering_scheme' for r in estimates)
    text = ' '.join(' '.join(ET.fromstring(svg).itertext()) for svg in build_metering_detail_pages(p))
    assert all(r.product['model'] in text for r in p.meters.rows)
    assert '0,450' in text and '0,120' in text
    assert 'минимальный расчётный часовой расход и его основание' in text


@pytest.mark.parametrize('hot', [False, True])
def test_control_marks_stay_outside_adjacent_service_branches(sample, hot):
    from app.pz.metering_hot_node import hot_meter_view
    from app.pz.metering_layout import build_metering_layout, layout_contents, _symbol_half_height
    p = hot_meter_view(sample[1]) if hot else sample[1]
    layout = build_metering_layout(p)
    root = ET.fromstring('<svg>' + layout_contents(p)[0] + '</svg>')
    for number in (1, 2):
        cock = layout.part(f'control_cock_{number}')
        cap = layout.part(f'control_cap_{number}')
        marks = []
        for part in (cock, cap):
            group = root.find(f'.//*[@data-vu-component="{part.id}"]')
            marks.append(next(t for t in group.iter('text') if t.text == part.mark))
        assert marks[0].attrib['x'] == marks[1].attrib['x']
        assert float(marks[1].attrib['y']) - float(marks[0].attrib['y']) >= 5.5
        envelope = max(_symbol_half_height(part, layout.scale) for part in (cock, cap))
        x = float(marks[0].attrib['x'])
        if number == 1:
            assert all(m.attrib['text-anchor'] == 'end' for m in marks)
            assert x <= cock.center[0] - envelope - 3
        else:
            assert all(m.attrib['text-anchor'] == 'start' for m in marks)
            assert x >= cock.center[0] + envelope + 3
            if cock.length_mm is not None:
                assert x >= cock.center[0] + 18  # clear the dimension number
    assert build_metering_layout(p) == layout
