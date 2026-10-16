from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET

import pytest

from app.intake import samara_study
from app.pz.water_station_drafting import build_pump_zone_scheme_pages, station_counts
from app.pz.water_pipe_binding import bind_t3_pipes
from app.pz.project import HwsType, PumpSystem


@pytest.fixture
def samara(tmp_path):
    # Use the current signed-input adapter, including the reviewed K1/quantity inputs.
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    return samara_study.build(draft,tmp_path,render=False)[0].project


def _pipes(svg):
    return {e.get('data-pipe'): e for e in ET.fromstring(svg).iter() if e.get('data-pipe')}


def test_drawing_does_not_modify_project_or_working_point(samara):
    before = deepcopy(asdict(samara))
    pages = build_pump_zone_scheme_pages(samara)
    assert len(pages) == 3
    assert asdict(samara) == before
    assert '11,466' in pages[0] and '50,25' in pages[0]
    assert '14,78' in pages[0] and '58,22' in pages[0]
    assert '29,56' not in pages[0]


def test_standalone_station_uses_same_fixture_cutaway_as_main_water_sheet(samara):
    from app.pz.generator import generate_scheme_result
    from app.pz.spec import build_specification
    before=deepcopy(asdict(samara))
    specification=asdict(build_specification(samara,scope='water'))
    domestic=deepcopy(samara)
    domestic.fire.required=False
    domestic.fire_pumps.required=False
    main=ET.fromstring(generate_scheme_result(domestic).svg)
    pages=build_pump_zone_scheme_pages(samara,include_review=True)
    section=ET.fromstring(pages[2])
    assert section.get('data-residential-water-section')=='approval'
    stamp=next(e for e in section.iter() if e.get('data-title-block')=='form-3')
    assert stamp.get('data-sheet-no')=='3'
    assert stamp.get('data-sheet-total')==str(len(pages))
    assert 'К горячим приборам' not in pages[2]
    def fixtures(root):
        return [ET.tostring(e,encoding='unicode') for e in root.iter()
                if e.get('data-fragment-component')=='fixture']
    assert fixtures(main)==fixtures(section)
    assert len(fixtures(section))==24
    assert not any('data-residential-water-section' in s for s in
                   build_pump_zone_scheme_pages(samara,include_building_section=False))
    assert asdict(samara)==before
    assert asdict(build_specification(samara,scope='water'))==specification


@pytest.mark.parametrize('change',['profile','schedule','fire'])
def test_standalone_does_not_invent_fixture_profile_or_hide_unhandled_fire(samara,change):
    if change=='profile': samara.consumer_groups=[('residential_no_bath',350)]
    elif change=='schedule': samara.fixtures=[object()]
    else:
        samara.fire.required=True
        samara.fire_pumps.station_design={}
        samara.fire_pumps.pressure_review={}
    assert not any('data-residential-water-section' in s for s in build_pump_zone_scheme_pages(samara))


def test_reserve_pump_parallel_not_series(samara):
    pipes = _pipes(build_pump_zone_scheme_pages(samara)[0])
    for name in ('Н1','Н2'):
        assert pipes[name].get('data-from') == 'suction'
        assert pipes[name].get('data-to') == 'discharge'
    assert 'резервный; остановлен' in build_pump_zone_scheme_pages(samara)[0]


def test_service_points_and_leaders_do_not_cross_their_own_detail(samara):
    pages = build_pump_zone_scheme_pages(samara)
    assert 'data-component="station-air"' in pages[0]
    assert 'data-component="station-drain"' in pages[0]
    for page in pages:
        for element in ET.fromstring(page).iter():
            if element.get('data-leader-id'):
                # The oblique approach remains outside the shelf text on
                # either side, including short factory service callouts.
                target = float(element.get('data-target-x'))
                knee = float(element.get('data-knee-x'))
                if target < knee:
                    assert knee < float(element.get('data-text-box-x1'))
                else:
                    assert knee > float(element.get('data-text-box-x2'))


def test_unknown_counts_are_not_silently_one_plus_one():
    assert station_counts(PumpSystem(count_note='подбор позже')) is None
    assert station_counts(PumpSystem(count_note='1 рабочий + 1 резервный')) == (1,1)
    assert station_counts(PumpSystem(working_units=2,reserve_units=1)) == (2,1)


def test_stale_working_point_not_printed_as_verified(samara):
    samara.pumps.wp_h += 5
    svg = build_pump_zone_scheme_pages(samara)[0]
    assert 'Пересечение не подтверждено' in svg
    assert 'Оценочно: Q=' not in svg


def test_circulation_returns_after_meter_and_cold_check(samara):
    svg = build_pump_zone_scheme_pages(samara)[1]
    pipes = _pipes(svg)
    assert pipes['cold-to-heater'].get('data-to') == 'return-join'
    assert pipes['t4-return'].get('data-to') == 'return-join'
    assert pipes['mixed-heater-feed'].get('data-from') == 'return-join'
    assert pipes['mixed-heater-feed'].get('data-to') == 'heater-in'
    assert 'data-component="meter-heater"' not in svg
    assert pipes['cold-to-heater'].get('d').endswith('115,150')
    assert pipes['t4-return'].get('d').endswith('115,150')
    assert pipes['mixed-heater-feed'].get('d').startswith('M115,150')


def test_hot_pipe_sizes_bound_separately_and_no_invented_t4(samara):
    sizes = bind_t3_pipes(samara)
    assert sizes['main'].pipe.outer_mm == 76
    assert sizes['riser'].pipe.outer_mm == 48
    assert sizes['apartment'].pipe.outer_mm == 20
    samara.v1_sections.clear()
    assert bind_t3_pipes(samara) == sizes
    svg = build_pump_zone_scheme_pages(samara)[1]
    assert 'Q/H не определены' in svg and 'DN, Kv не заданы' in svg
    assert 'data-selection="pending"' in svg
    assert '0,5 л/с' not in svg


def test_hot_pipe_unknown_and_conflicting_geometry_not_replaced(samara):
    samara.t3_sections[1] = replace(samara.t3_sections[1],inner_diameter_mm=1)
    assert bind_t3_pipes(samara)['main'].pipe is None
    assert bind_t3_pipes(samara)['feed'].pipe is not None


def test_missing_and_local_hot_water_no_fictitious_shared_loop(samara):
    samara.building.hws_type = HwsType.NONE
    pages = build_pump_zone_scheme_pages(samara)
    assert len(pages) == 1 and 'heater-branch' not in pages[0]
    samara.building.hws_type = HwsType.LOCAL
    pages = build_pump_zone_scheme_pages(samara)
    assert 'Общая циркуляционная сеть Т4 автоматически не добавляется' in pages[1]
    assert 't4-return' not in pages[1]


def test_external_hot_water_no_fictitious_heater_or_circulation_pump(samara):
    samara.source.hws_heater_in_scope = False
    pages = build_pump_zone_scheme_pages(samara)
    assert 'heater-branch' not in pages[0]
    assert 'external-t3' in pages[1] and 'external-t4' in pages[1]
    assert 'heater-interface' not in pages[1]
    assert 'circulation-pump-pending' not in pages[1]


def test_no_pump_has_continuous_direct_route(samara):
    samara.pumps.required = False
    pipes = _pipes(build_pump_zone_scheme_pages(samara)[0])
    assert pipes['without-booster'].get('data-from') == 'suction'
    assert 'Н1' not in pipes and 'Н2' not in pipes


def test_levels_use_same_display_rounding_as_v1_not_suction_guess(samara):
    svg = build_pump_zone_scheme_pages(samara)[0]
    assert '-2,20' in svg and '-3,25' not in svg
    assert 'Ось всасывания: отметка не задана' in svg
    assert 'data-source-elevation-m="-2.195"' in svg


def test_multiple_zones_do_not_become_one_common_hws_loop(samara):
    samara.building.zones = 12
    pages = build_pump_zone_scheme_pages(samara)
    assert 'Всего зон: 12' in pages[0]
    assert 'требуется дополнение топологии' in pages[1]
    assert 't4-return' not in pages[1]


def test_pdf_pages_frames_fonts_and_bookmarks(samara,tmp_path):
    from app.pz.generator import generate_pump_zone_scheme_pdf
    import pymupdf
    from pypdf import PdfReader
    path = tmp_path/'station.pdf'
    generate_pump_zone_scheme_pdf(samara,str(path))
    reader = PdfReader(path)
    assert len(reader.pages) == 6 and len(reader.outline) == 6
    pdf = pymupdf.open(path)
    for index, page in enumerate(pdf):
        width, height = (594,420) if index == 2 else (420,297)
        assert page.rect.width / 72 * 25.4 == pytest.approx(width,.01)
        assert page.rect.height / 72 * 25.4 == pytest.approx(height,.01)
        fonts = page.get_fonts()
        assert fonts and all('OpenGOST' in font[3] for font in fonts)
        assert '\ufffd' not in page.get_text()
