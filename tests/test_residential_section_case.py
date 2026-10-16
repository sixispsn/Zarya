"""Third residential case: connected K1/K2, low underfloor and shared roof fan."""
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from fontTools.ttLib import TTFont
from pypdf import PdfReader
import pytest

from app.architecture.residential_section_case import load_residential_section_case
from app.pz.drafting_font import DRAFTING_FONT_PATH
from app.pz.leader_layout import _text_width
from app.pz.residential_case_section import (
    BAYS, K2_AXES, audit_residential_case_svg, build_residential_case_svg,
    generate_residential_case_pdf, ordinate,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def case():
    return load_residential_section_case(ROOT/'demo/residential_3floors_accessible_roof.json')


def node_binary():
    node = os.environ.get('NODE_BINARY') or shutil.which('node')
    if not node:
        pytest.fail('Node is mandatory for actual legacy parity, set NODE_BINARY')
    return node


def rows(root, key):
    return [e for e in root.iter() if e.get(key) is not None]


def test_architecture_is_derived_from_floor_to_floor_and_clear_underfloor(case):
    assert case.floor_levels == {1: 0, 2: 3.5, 3: 7}
    assert case.roof_m == 10.5
    assert case.ceiling_m == -.3
    assert case.subfloor_m == case.outlet_invert_m == -1.8
    assert ordinate(case.subfloor_m)-ordinate(case.ceiling_m) == 30
    assert not case.release_ready


def test_all_appliances_and_funnels_reach_separate_outlets(case):
    paths = case.drainage_paths()
    assert len(paths) == 50
    assert sum(source.startswith('K1') for source in paths) == 48
    for source, path in paths.items():
        assert path[-1] == source[:2]+':outlet'
        assert len(set(path)) == len(path)
        assert all(node.startswith(source[:2]) for node in path)
    for system, collector in (('K1', case.k1), ('K2', case.k2)):
        for i, assembly in enumerate(collector.nodes()):
            assert assembly.system == system
            assert (assembly.service_path is not None) == (i == 0)
            assert not assembly.validate()


def test_shared_fan_is_above_roof_not_apartment_ceiling(case):
    graph = case.fan_graph()
    assert {n.source_id for n in graph.nodes if n.role == 'riser_port'} == {b.stack for b in BAYS}
    collectors = [n for n in graph.nodes if n.role == 'collector_join']
    assert len(collectors) == 4
    assert all(n.level_m > case.roof_m for n in collectors)
    assert all(a.level_m < b.level_m for a, b in zip(collectors, collectors[1:]))
    endings = [n for n in graph.nodes if n.role == 'open_end']
    assert len(endings) == 1 and endings[0].level_m-case.roof_m == 3
    checks = {c.code: c.status for c in case.fan_audit().checks}
    assert checks['FAN-FOUR'] == checks['FAN-HEIGHT'] == 'verified'
    assert checks['FAN-OPENINGS'] == checks['FAN-UV'] == 'pending'


@pytest.mark.parametrize('changes', [
    dict(outlet_invert_m=-2), dict(subfloor_clear_m=0), dict(slab_m=3.5),
    dict(fan_start_m=10.4), dict(fan_height_m=2.99), dict(fan_stations=(0, 4, 8)),
    dict(fan_stations=(0, 4, 4, 8)), dict(fan_stations=(0, 4, 8, float('nan'))),
    dict(fan_placement='apartment_ceiling'), dict(fan_terminal_riser='K2-1'),
    dict(catchments=(150,)), dict(catchments=(150, 151)), dict(catchments=()),
    dict(catchments=(150, float('nan'))), dict(authority=''), dict(residents=0),
])
def test_missing_or_conflicting_inputs_are_not_silently_fixed(case, changes):
    with pytest.raises(ValueError):
        replace(case, **changes).validate()


def test_missing_horizontal_service_access_blocks_case(case):
    with pytest.raises(ValueError, match='interval'):
        replace(case, k1=replace(case.k1, revisions=())).validate()


def test_profile_cannot_silently_diverge_from_catalogue_bore(case):
    other_profile = replace(case.k1.profile, wall_thickness_mm=4)
    with pytest.raises(ValueError, match='actual bore'):
        replace(case, k1=replace(case.k1, profile=other_profile)).validate()


def test_other_floor_count_requires_sheet_layout_not_clipping(case):
    with pytest.raises(ValueError, match='composition'):
        build_residential_case_svg(replace(case, floors=2))


def test_this_case_matches_executed_legacy(case):
    case.verify_legacy(node_binary(), ROOT)
    water, rain = case.calculate()
    assert (water.total.q_sec, water.total.q_hr, water.sewage_flow) == (.899, 1.746, 2.5)
    assert (rain.q_total_l_per_s, rain.f_calculated_m2) == (6.422, 300)


def test_legacy_mismatch_stops_pdf_export(case, monkeypatch, tmp_path):
    reference = {'cases': [{'flow_lps': 999, 'q5': 214.07, 'area': 300}],
                 'residents': [{'total_lps': .899, 'hourly_m3': 1.746, 'sewage_lps': 2.5}]}
    monkeypatch.setattr('app.architecture.residential_section_case.subprocess.run',
                        lambda *a, **k: SimpleNamespace(stdout=json.dumps(reference)))
    output = tmp_path/'must-not-exist.pdf'
    with pytest.raises(ValueError, match='legacy mismatch'):
        generate_residential_case_pdf(output, case, node='unused', root=ROOT)
    assert not output.exists()


def test_drawing_keeps_all_axes_maintenance_and_separate_networks(case):
    svg = build_residential_case_svg(case)
    assert not audit_residential_case_svg(case, svg)
    r = ET.fromstring(svg)
    assert len(rows(r, 'data-section-apartment')) == 12
    assert len(rows(r, 'data-floor-fixture')) == 48
    assert len(rows(r, 'data-riser-revision')) == 10  # K1 on 1 & 3, K2 on 1.
    assert len(rows(r, 'data-main-revision')) == 2
    assert len(rows(r, 'data-section-slope')) == 27
    assert len(rows(r, 'data-nonconnecting-crossing')) == 2
    assert {float(e.get('data-crossing-x')) for e in rows(r, 'data-nonconnecting-crossing')} == set(K2_AXES)
    for e in rows(r, 'data-section-outlet'):
        collector = case.k1 if e.get('data-section-outlet').startswith('K1') else case.k2
        assert float(e.get('data-axis-level-m')) == pytest.approx(-1.8+collector.pipe.inner_diameter_mm/2000)
    assert len([e for e in rows(r, 'data-lower-connection') if e.get('data-accessible-capped-end') == 'true']) == 2


@pytest.mark.parametrize('damage', ['riser', 'apartment', 'revision', 'slope', 'slope-value', 'slope-size',
                                   'axis', 'cap', 'fan', 'outlet', 'release', 'raster'])
def test_damaged_sheet_cannot_be_exported(case, damage):
    r = ET.fromstring(build_residential_case_svg(case))
    key = {'riser':'data-section-riser', 'apartment':'data-section-apartment', 'revision':'data-riser-revision',
           'slope':'data-section-slope', 'fan':'data-fan-open-end', 'outlet':'data-section-outlet'}.get(damage)
    if key:
        rows(r, key)[0].attrib.pop(key)
    elif damage in ('slope-value', 'slope-size'):
        rows(r, 'data-section-slope')[0].set('data-slope' if damage == 'slope-value' else 'data-text-height-mm', '99')
    elif damage == 'axis':
        rows(r, 'data-section-lower')[0].set('data-axis-x', '1')
    elif damage == 'cap':
        rows(r, 'data-lower-connection')[0].set('data-accessible-capped-end', 'false')
    elif damage == 'release':
        r.set('data-release-ready', 'true')
    else:
        ET.SubElement(r, 'image')
    assert audit_residential_case_svg(case, ET.tostring(r, encoding='unicode'))


def test_letters_fit_leaders_and_font_has_every_nonvector_character(case):
    root = ET.fromstring(build_residential_case_svg(case))
    cmap = TTFont(DRAFTING_FONT_PATH).getBestCmap()
    missing = {c for e in root.iter() if e.tag.endswith('text') for c in (e.text or '') if not c.isspace() and ord(c) not in cmap}
    assert not missing
    assert len(rows(root, 'data-vector-diameter-sign')) > 30
    for leader in rows(root, 'data-leader-id'):
        assert leader.get('data-text-height-mm') == '3.5'
        assert float(leader.get('data-line-width-mm')) == .25
        width = abs(float(leader.get('data-knee-x'))-float(leader.get('data-shelf-outer-x')))
        for text in rows(leader, 'data-leader-title')+rows(leader, 'data-leader-detail'):
            assert _text_width(text.text, float(text.get('font-size')))+1 <= width


def test_main_labels_do_not_erase_revisions_or_cleanout_caption(case):
    r = ET.fromstring(build_residential_case_svg(case))
    def translate(element):
        return tuple(float(v) for v in re.search(r'translate\(([-.\d]+) ([-.\d]+)\)', element.get('transform')).groups())
    labels = [e for e in rows(r, 'data-pipe-line-id') if re.fullmatch(r'K[12]-main-\d', e.get('data-pipe-line-id'))]
    for revision in rows(r, 'data-main-revision'):
        symbol = next(e for e in revision if e.get('transform'))
        x, y = translate(symbol)
        for label in labels:
            xx, yy = translate(label)
            mask = rows(label, 'data-pipe-label-mask')[0]
            assert abs(y-yy) > float(mask.get('height'))/2+1 or abs(x-xx) > float(mask.get('width'))/2+2
    for leader in rows(r, 'data-leader-id'):
        if leader.get('data-leader-id') not in ('K1-start-cleanout', 'K2-start-cleanout'):
            continue
        for text in rows(leader, 'data-leader-title')+rows(leader, 'data-leader-detail'):
            x, y, size = float(text.get('x')), float(text.get('y')), float(text.get('font-size'))
            right = x+_text_width(text.text, size)
            for label in labels:
                xx, yy = translate(label)
                mask = rows(label, 'data-pipe-label-mask')[0]
                hw, hh = float(mask.get('width'))/2, float(mask.get('height'))/2
                assert right < xx-hw or x > xx+hw or y+1 < yy-hh or y-size > yy+hh


def test_pdf_is_one_vector_a2_with_disclosed_assumptions(case, tmp_path):
    output = generate_residential_case_pdf(tmp_path/'third.pdf', case, node=node_binary(), root=ROOT)
    pages = PdfReader(output).pages
    assert len(pages) == 1
    p = pages[0]
    assert not p.images
    assert float(p.mediabox.width)*25.4/72 == pytest.approx(594)
    assert float(p.mediabox.height)*25.4/72 == pytest.approx(420)
    text = p.extract_text()
    for expected in ('Принципиальная схема', '3 этажа', '12 квартир', 'Неотапливаемое', 'Техподполье',
                     '3000', '-1,800', 'Квартира 12', '6,422', '2,500', 'Исходные решения требуют подтверждения'):
        assert re.sub(r'\s', '', expected) in re.sub(r'\s', '', text)
    assert '\ufffd' not in text
