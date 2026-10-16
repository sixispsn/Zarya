from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET

import pytest

from app.intake import samara_study
from app.pz.hws_presentation import hws_pipe_items, hws_principle
from app.pz.hws_building_drafting import build_hws_section, section_floors, can_draw_hws_section
from app.pz.spec import build_specification
from app.pz.project import BuildingPurpose, HwsType
from app.pz.generator import generate_pz_html
from app.pz.water_station_drafting import build_pump_zone_scheme_pages


@pytest.fixture
def project(tmp_path):
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    return samara_study.build(draft,tmp_path,render=False)[0].project


def hws_rows(project):
    return next(s.rows for s in build_specification(project,scope='water').sections
                if s.title.startswith('Т3-Т4'))


def test_shared_geometry_and_ids_no_guess_of_t4_or_building_quantities(project):
    before = deepcopy(asdict(project))
    rows = hws_rows(project)
    svg = build_hws_section(project,3,3)
    assert asdict(project) == before
    ids = {e.get('data-component') for e in ET.fromstring(svg).iter()}
    for item in hws_pipe_items(project):
        assert item.key in ids
        row = next(r for r in rows if r.component_ids == (item.key,))
        assert row.qty is None
        if item.binding.pipe:
            assert item.binding.label in row.name
    assert next(r for r in rows if r.component_ids == ('t4-network',)).type_mark == 'Материал и размер по расчёту Т4'
    assert not any('25×2,3' in r.type_mark for r in rows)


def test_unknown_riser_count_not_one_and_cold_inputs_not_hot_sleeves(project):
    rows = hws_rows(project)
    for key in ('circulation-pump-pending','circulation-balance','t3-riser-valve','t4-riser-valve','hws-sleeves','hws-supports'):
        assert next(r for r in rows if r.component_ids == (key,)).qty is None
    project.building.risers_t3 = 8
    project.building.risers_t4 = 4
    rows = hws_rows(project)
    assert next(r for r in rows if r.component_ids == ('circulation-balance',)).qty is None
    assert next(r for r in rows if r.component_ids == ('t3-riser-valve',)).qty == 8
    assert not any('ввод через стену' in r.note for r in rows)


def test_insulation_uses_current_outer_diameter_but_no_estimated_length(project):
    items = hws_pipe_items(project)
    assert [i.binding.pipe.outer_mm for i in items[:3]] == [76,48,20]
    assert items[0].binding.pipe.dn == 65
    assert items[0].binding.pipe.inner_mm == 69
    assert items[0].insulation_mm == 60
    assert items[1].insulation_mm == 60
    assert items[2].insulation_mm is None and items[3].insulation_mm is None
    rows = hws_rows(project)
    for i in items[:2]:
        row = next(r for r in rows if r.component_ids == ('insulation-'+i.key,))
        assert row.qty is None
        if i.insulation_mm is not None:
            assert f'δ{i.insulation_mm} мм' in row.type_mark
        else:
            assert 'толщина требует данных' in row.type_mark


def test_area_total_retained_as_unallocated_estimate_not_procurement_quantity(project):
    result = build_specification(project,scope='water')
    assert '2407.5 м сохранена справочно' in result.note
    assert all(r.qty is None for r in hws_rows(project) if r.unit == 'м')


def test_section_levels_compression_and_shared_cut_of_pipes_and_walls(project):
    assert section_floors(project) == (1,2,3,16)
    svg = build_hws_section(project,3,3)
    root = ET.fromstring(svg)
    assert 'Этажи 4-15 (12 шт.) опущены' in svg
    assert 'data-source-elevation-m="45.0"' in svg
    assert 'data-source-elevation-m="-3.25"' in svg
    geometry = next(e for e in root if e.get('clip-path'))
    assert any(e.get('data-pipe') == 'building-t3-riser' for e in geometry.iter())
    assert any(e.get('data-floor') == '1' for e in geometry.iter())
    breaks = [e for e in root if e.get('data-floor-break')]
    assert len(breaks) == 2
    assert all('M90,' in e.get('d') and 'H490' in e.get('d') for e in breaks)
    assert svg.count('data-representative-floor=') == 4


def test_small_building_no_compression_missing_levels_not_guessed(project):
    project.building.floors_above = 3
    project.building.floor_elevations_m.pop(2)
    svg = build_hws_section(project,3,3)
    assert 'hws-break-clip' not in svg
    assert '2 этаж: по АР' in svg
    assert 'data-source-elevation-m="3.0"' not in svg
    project.building.zones = 2
    assert not can_draw_hws_section(project)


def test_external_source_omits_local_circulation_pump_and_cold_feed(project):
    project.source.hws_heater_in_scope = False
    keys = {key for r in hws_rows(project) for key in r.component_ids}
    assert 'circulation-pump-pending' not in keys
    assert 'cold-to-heater' not in keys


def test_unknown_nominal_diameter_never_reaches_thermal_tables(project,monkeypatch):
    import app.pz.hws_presentation as binding
    calculate = binding.calculate_insulation
    seen = []
    def checked(params, hot, cold):
        seen.extend(pipe.dn for pipe in hot)
        assert all(pipe.dn > 0 for pipe in hot)
        return calculate(params,hot,cold)
    monkeypatch.setattr(binding,'calculate_insulation',checked)
    project.t3_sections = [replace(s, material='Стальная 77x3,5', inner_diameter_mm=70)
                          if s.section_id == 'Т3-Магистраль' else s for s in project.t3_sections]
    binding.hws_pipe_items(project)
    assert seen == [40]


def test_exact_main_insulation_on_drawing_and_spec_survives_size_change(project):
    before = deepcopy(asdict(project))
    svg = build_hws_section(project,3,3)
    assert 'Ø76×3,5; DN65' in svg
    assert 'Изоляция δ60 мм' in svg
    row = next(r for r in hws_rows(project) if r.component_ids == ('insulation-t3-main',))
    assert 'Ø76×3,5; δ60 мм' in row.type_mark
    assert 'DN65' in row.note and row.qty is None
    assert asdict(project) == before
    # Current geometry wins over any previously calculated presentation.
    # Inconsistent declared series is not silently changed to a welded one.
    project.t3_sections = [replace(s, material='Стальная ВГП 76x3,5')
                          if s.section_id == 'Т3-Магистраль' else s for s in project.t3_sections]
    assert hws_pipe_items(project)[0].insulation_mm is None
    assert 'Изоляция: уточнить DN' in build_hws_section(project,3,3)


def test_exported_pdf_really_cuts_risers_and_room_walls(project):
    import cairosvg
    import pymupdf
    svg = build_hws_section(project,3,3)
    root = ET.fromstring(svg)
    edges = {e.get('data-floor-break'): float(e.get('d').split(' H')[0].split(',')[1])
             for e in root if e.get('data-floor-break')}
    middle = (edges['upper'] + edges['lower'])/2
    pdf = pymupdf.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()),filetype='pdf')
    mm = 72/25.4
    for x in (100,285,315,342,360,480):
        clip = pymupdf.Rect((x-.4)*mm,(middle-2)*mm,(x+.4)*mm,(middle+2)*mm)
        pix = pdf[0].get_pixmap(matrix=pymupdf.Matrix(3,3),clip=clip,colorspace=pymupdf.csGRAY)
        assert min(pix.samples) > 245, f'uncut line at x={x} mm'
    slab = next(e for e in root.iter() if e.get('data-section-slab') ==
                f'hws-floor-{project.building.floors_above}')
    y = float(list(slab)[0].get('y'))
    clip = pymupdf.Rect(115*mm,(y+.3)*mm,128*mm,(y+2.7)*mm)
    pix = pdf[0].get_pixmap(matrix=pymupdf.Matrix(3,3),clip=clip,colorspace=pymupdf.csGRAY)
    assert min(pix.samples) < 160, 'top floor hatch was removed by the break clip'


@pytest.mark.parametrize('purpose', [BuildingPurpose.RESIDENTIAL, BuildingPurpose.PUBLIC])
@pytest.mark.parametrize('kind,heater,mode', [
    (HwsType.CENTRAL, True, 'central_local'),
    (HwsType.CENTRAL, False, 'central_external'),
    (HwsType.LOCAL, True, 'local'),  # stale central-heater flag is ignored
    (HwsType.NONE, True, 'none'),
])
def test_pz_spec_and_schemes_share_hws_scope(project,purpose,kind,heater,mode):
    project.building.purpose = purpose
    project.building.hws_type = kind
    project.source.hws_heater_in_scope = heater
    before = deepcopy(asdict(project))
    view = hws_principle(project)
    html = generate_pz_html(project)
    sheets = build_pump_zone_scheme_pages(project)
    spec = build_specification(project,scope='water')
    hot = [s for s in spec.sections if s.division == 'Водоснабжение горячее']
    ids = {key for s in hot for r in s.rows for key in r.component_ids}
    assert view.mode == mode and f'data-hws-mode="{mode}"' in html
    if not view.local_circulation_pump:
        assert 'Учёт горячей воды — в ИТП' not in html
        assert 'Учёт горячей воды для нужд ГВС — в ИТП' not in html
        assert 'Прибор учета горячей воды размещается в ИТП' not in html
    if view.central:
        assert 'data-hws-circulation="principle-only"' in html
        assert 'должны быть дополнены для выпуска' in html
        assert f'data-hws-mode="{mode}"' in sheets[1]
        assert f'data-hws-mode="{mode}"' in sheets[2]
        assert 'circulation-balance' in ids
        assert ('circulation-pump-pending' in ids) == heater
        if not heater:
            assert 'НЦ: Q/H не заданы' not in sheets[2]
            if 'data-residential-water-section' in sheets[2]:
                assert 'Условия возврата - по ТУ' in sheets[2]
                assert 'data-pipe="cold-to-hws"' not in sheets[2]
            else:
                assert 'Т4: возврат по ТУ' in sheets[2]
            assert 'Водонагреватель и циркуляционный насос в границах данного раздела не назначены' in html
    else:
        assert not {'circulation-balance','circulation-pump-pending','t4-network'} & ids
        assert all('data-pipe="t4-return"' not in s for s in sheets)
        assert 'data-hws-circulation="principle-only"' not in html
        if kind == HwsType.NONE:
            assert not hot and len(sheets) == 1
        else:
            assert ids == {'local-hws-heaters','local-hws-pipes','local-hws-fittings'}
    assert asdict(project) == before


def test_missing_t3_path_cannot_enable_fabricated_t4_sizes_or_lengths(project):
    from app.pz.water_service_assemblies import WaterServiceLayout
    project.t3_sections = []
    project.building.risers_t4 = 4
    project.building.water_service_layout = WaterServiceLayout(balance_mode='riser_returns')
    rows = hws_rows(project)
    balance = next(r for r in rows if r.component_ids == ('circulation-balance',))
    assert balance.qty == 4 and balance.type_mark == 'DN, Kv и настройка по расчёту'
    assert not any('DN20' in r.type_mark or 'Ду20' in r.type_mark for r in rows)
    assert all(r.qty is None for r in rows if r.unit == 'м')
    assert 'Размер и толщина после задания труб Т4' in next(
        r.type_mark for r in rows if r.component_ids == ('insulation-t4-network',))


def test_known_riser_counts_and_t3_assumption_basis_are_not_lost(project):
    project.building.risers_t3 = 8
    project.building.risers_t4 = 4
    svg = build_hws_section(project,3,3)
    assert 'Т3: 8; Т4: 4' in svg
    html = generate_pz_html(project)
    assert 'не результат расчёта кольца Т4' in html
    assert 'гипотетические входные расходы циркуляции' in html
    assert 'Расчёт водоразбора Т3 и заданные для него qcir не заменяют расчёт циркуляции Т4' in html


def test_local_heaters_in_multiple_zones_do_not_trigger_shared_circulation(project):
    project.building.hws_type = HwsType.LOCAL
    project.building.zones = 2
    pages = build_pump_zone_scheme_pages(project)
    assert 'Местные водонагреватели' in pages[1]
    assert 'ГВС разделяется на зоны' not in pages[1]
