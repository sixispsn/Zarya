"""Residential paper-space water section, separate from hydraulic calculations."""
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
from xml.etree import ElementTree as ET
import re

import pymupdf
import pytest

from app.pz.building_cutaway import representative_floors
from app.pz.generator import generate_scheme_result, generate_scheme_pdf
from app.pz.project import BuildingPurpose, HwsType, Stage
from app.pz.residential_concept_section import ResidentialConceptSection
from app.pz.water_building_section import (
    AXES, LEFT, RIGHT, build_water_section, can_draw_water_section,
    water_section_model, water_section_edges,
)
from app.pz.water_station_drafting import build_pump_zone_scheme_pages
from tests.test_water_pipe_binding import source_project


def project(floors=16, basement=True):
    p = source_project()
    p.fire.required = False
    p.building.floors_above = floors
    p.building.floors_below = int(basement)
    p.building.floor_elevations_m = {i:(i-1)*3.3 for i in range(1,floors+1)}
    if basement:
        p.building.floor_elevations_m[-1] = -3.1
    p.sewage.roof_relative_elevation_m = floors*3.3
    p.sewage.roof_kind = 'flat_non_accessible'
    p.pumps.required = False
    return p


def tagged(root, attribute):
    return [e for e in root.iter() if e.get(attribute) is not None]


@pytest.mark.parametrize('floors', [1,2,3,4,9,16,25,200])
@pytest.mark.parametrize('basement', [True,False])
def test_floor_model_is_shared_with_sewer_no_mutation_or_floating_flow_arrows(floors,basement):
    p = project(floors,basement)
    original = deepcopy(asdict(p))
    m = water_section_model(p)
    sewer = ResidentialConceptSection(floors,3.3,'basement',-3.1,'flat_non_accessible',
                                     'internal','residential_full_bath')
    assert m.floors == representative_floors(floors) == sewer.shown_floors
    assert (m.basement_y is not None) == basement
    svg = build_water_section(p).svg
    root = ET.fromstring(svg)
    mains = dict(m.main_ys)
    assert root.get('data-takeoff-eligible') == 'false'
    slabs = {e.get('data-section-slab'):e for e in tagged(root,'data-section-slab')}
    assert set(slabs) == {*(f'water-floor-{f}' for f in m.floors),
                          *(['water-base'] if basement else [])}
    for f,y in zip(m.floors,m.floor_ys):
        slab = slabs[f'water-floor-{f}']
        assert float(list(slab)[0].get('y')) == y
        assert tagged(slab,'data-slab-hatch')
    for arrow in tagged(root,'data-x'):
        if arrow.get('data-component') != 'water-riser-arrow':
            continue
        system = arrow.get('data-system')
        y = float(arrow.get('data-y'))
        end = m.floor_ys[-1] - (18 if system == 'В1' else 44)
        assert end < y < mains[system], (system,y,end,mains)
    # Every branch has a real junction on its own riser; no false top crossing.
    for pipe in tagged(root,'data-pipe'):
        if pipe.get('data-pipe','').startswith('Т3-apartment-'):
            top = pipe.get('data-pipe').endswith(f'-{m.floors[-1]}')
            assert (' A2,2 ' in pipe.get('d')) == (not top)
    assert asdict(p) == original


@pytest.mark.parametrize('kind,systems',[(HwsType.CENTRAL,('В1','Т3','Т4')),
                                      (HwsType.LOCAL,('В1',)),(HwsType.NONE,('В1',))])
def test_separate_networks_current_hws_scope_and_no_water_draw_from_t4(kind,systems):
    p = project(2)
    p.building.hws_type = kind
    m = water_section_model(p)
    assert m.systems == systems
    edges,terminals = water_section_edges(p,m)
    assert not any(a.startswith('Т4:') and 'apartment' in b for a,b in edges)
    assert not any(a.startswith('В1:') != b.startswith('В1:') for a,b in edges)
    assert len(terminals) == (5 if kind == HwsType.CENTRAL else 2)
    root = ET.fromstring(build_water_section(p).svg)
    assert {e.get('data-system') for e in tagged(root,'data-pipe')} == set(systems)
    assert all(e.get('data-scope') in ('representative','principle') for e in tagged(root,'data-pipe'))


@pytest.mark.parametrize('change', ['fire','zones','hot_zones','public','stage_r','regulators','irrigation','reuse'])
def test_explicit_unhandled_topology_keeps_old_renderer(change,monkeypatch):
    p = project()
    if change == 'fire': p.fire.required = True
    elif change == 'zones': p.building.zones = 2
    elif change == 'hot_zones': p.hws_stage_p = replace(p.hws_stage_p,enabled=True,zones=2)
    elif change == 'public': p.building.purpose = BuildingPurpose.PUBLIC
    elif change == 'stage_r': p.document.stage = Stage.R
    elif change == 'irrigation': p.flows.irrigation_m3_day = 1
    elif change == 'reuse': p.rainwater_reuse = replace(p.rainwater_reuse,enabled=True)
    else: p.v1_hydraulic_result = SimpleNamespace(zone_regulators=[SimpleNamespace(required=True)])
    assert not can_draw_water_section(p)
    import app.pz.generator as generator
    sentinel = SimpleNamespace(warnings=[])
    monkeypatch.setattr(generator,'build_scheme',lambda *args:sentinel)
    assert generate_scheme_result(p) is sentinel


def test_custom_legacy_layout_parameters_are_not_ignored(monkeypatch):
    from app.pz.scheme import SchemeParams
    import app.pz.generator as generator
    seen = []
    monkeypatch.setattr(generator,'build_scheme',lambda p,params:seen.append(params))
    custom = SchemeParams()
    generate_scheme_result(project(),custom)
    assert seen == [custom]


def test_explicit_elevations_survive_unknown_marks_not_guessed():
    p = project(9)
    p.building.floor_elevations_m[2] = 4.1
    p.building.floor_elevations_m[9] = 29.8
    p.sewage.roof_relative_elevation_m = 35
    p.source.elev_fixture_m = 30.8
    p.source.lowest_fixture_elevation_m = 1
    p.source.lowest_fixture_basis = 'Учебное допущение'
    assert water_section_model(p).elevations == (0,4.1,29.8)
    svg = build_water_section(p).svg
    assert 'data-source-elevation-m="29.8"' in svg
    assert '+30,80' in svg and '+1,00' in svg
    del p.building.floor_elevations_m[2]
    p.sewage.roof_relative_elevation_m = None
    p.sewage.roof_kind = 'complex'
    result = build_water_section(p)
    assert '2 этаж: по АР' in result.svg
    assert 'Верхняя граница условная' in result.svg
    assert any('Геометрия кровли не задана' in w for w in result.warnings)
    assert 'data-source-elevation-m="3.3"' not in result.svg


@pytest.mark.parametrize('bad', [float('nan'),float('inf'),True,'3'])
def test_invalid_mark_cannot_reach_pdf(bad):
    p = project()
    p.building.floor_elevations_m[2] = bad
    with pytest.raises(ValueError): build_water_section(p)


def test_current_pipe_binding_not_generic_sizes_and_missing_t4_not_t3():
    p = project(2)
    svg = build_water_section(p).svg
    for value in ('Ø110×6,6','Ø76×3,5','Ø48×3,5','Ø20×2'):
        assert value in svg
    assert 'Т4: размер не определён' in svg
    p.v1_sections[2].inner_diameter_mm = 39
    result = build_water_section(p)
    assert 'Ø48×3,5' not in result.svg
    assert any('стояк' in w for w in result.warnings)
    assert 'Ø32' not in result.svg


def test_inlet_crosses_outer_wall_and_split_detail_does_not_duplicate_hws_section():
    p = project(16)
    p.source.inputs_count = 2
    root = ET.fromstring(build_water_section(p).svg)
    inlet = next(e for e in tagged(root,'data-pipe') if e.get('data-pipe') == 'water-inlet')
    points = [tuple(map(float,pair)) for pair in re.findall(r'([\d.]+),([\d.]+)',inlet.get('d'))]
    assert points[0][0] < LEFT < points[1][0] and points[0][1] == points[1][1]
    assert 'всего 2' in ''.join(root.itertext())
    assert len(build_pump_zone_scheme_pages(p)) == 3
    separate = build_pump_zone_scheme_pages(p,include_building_section=False)
    assert len(separate) == 2
    assert 'data-hws-mode' in separate[1]


def test_final_pdf_physical_frame_hatches_and_full_width_break(tmp_path):
    p = project(16)
    svg = generate_scheme_result(p).svg
    root = ET.fromstring(svg)
    m = water_section_model(p)
    breaks = tagged(root,'data-floor-break')
    assert len(breaks) == 2
    assert all(f'M{LEFT-10:g},' in e.get('d') and f'H{RIGHT+10:g}' in e.get('d') for e in breaks)
    geometry = next(e for e in root if e.get('clip-path'))
    assert {e.get('data-pipe') for e in tagged(geometry,'data-pipe')} >= {'water-v1-riser','water-t3-riser','water-t4'}
    path = tmp_path/'section.pdf'
    generate_scheme_pdf(p,str(path))
    mm=72/25.4
    with pymupdf.open(path) as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        assert page.rect.width/mm == pytest.approx(594,abs=.01)
        assert page.rect.height/mm == pytest.approx(420,abs=.01)
        # Diameter is the existing vector symbol, not a missing font glyph.
        assert tagged(root,'data-vector-diameter-sign')
        assert '110×6,6' in page.get_text() and '\ufffd' not in page.get_text()
        middle = sum(m.break_edges)/2
        for x in (LEFT,280,*AXES.values(),369,RIGHT):
            clip=pymupdf.Rect((x-.4)*mm,(middle-2)*mm,(x+.4)*mm,(middle+2)*mm)
            pix=page.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=clip,colorspace=pymupdf.csGRAY)
            assert min(pix.samples)>245
            # All pipes/walls meet both knife-cut edges, no extra gaps.
            for y in (m.break_edges[0]-1,m.break_edges[1]+1):
                clip=pymupdf.Rect((x-.4)*mm,(y-.3)*mm,(x+.4)*mm,(y+.3)*mm)
                pix=page.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=clip,colorspace=pymupdf.csGRAY)
                assert min(pix.samples)<180
        for floor,y in zip(m.floors,m.floor_ys):
            pix=page.get_pixmap(matrix=pymupdf.Matrix(3,3),
                clip=pymupdf.Rect(115*mm,(y+.3)*mm,128*mm,(y+2.7)*mm),colorspace=pymupdf.csGRAY)
            assert min(pix.samples)<160
        border=tagged(root,'data-sheet-border')[0]
        assert tuple(float(border.get(k)) for k in ('x','y','width','height')) == (20,5,569,410)


def test_real_samara_package_preserves_v2_and_uses_one_water_cutaway(tmp_path):
    from app.intake import samara_study
    draft = dict(revision=0,answers={},documents=[])
    samara_study.initialize(draft,None)
    bundle,fingerprint = samara_study.build(draft,tmp_path,render=True)
    assert fingerprint == draft['study']['snapshot']
    assert bundle.project.fire.required and bundle.project.fire_pumps.station_design
    assert bundle.water_package_pdf and bundle.scheme_pdf and bundle.pump_zone_scheme_pdf
    assert not any('scheme skipped' in warning for warning in bundle.warnings)
    assert any('Принципиальная схема воды: Характерный разрез' in w for w in bundle.warnings)
    with pymupdf.open(bundle.scheme_pdf) as pdf:
        assert len(pdf) == 1
        assert pdf[0].rect.width*25.4/72 == pytest.approx(594,abs=.01)
        assert 'В1, Т3, Т4. Принципиальная схема здания' in pdf[0].get_text()
    with pymupdf.open(bundle.pump_zone_scheme_pdf) as pdf:
        # Two schemes plus the three existing station audit sheets. Neither
        # the old HWS fragment nor a second residential cutaway is included.
        assert len(pdf) == 5
        assert all('Принципиальная схема здания' not in p.get_text() for p in pdf)
        assert all('К горячим приборам' not in p.get_text() for p in pdf)
