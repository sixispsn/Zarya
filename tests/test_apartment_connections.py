from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from app.pz import apartment_connections as module
from app.pz.spec import build_water_specification, format_spec_qty
from tests.test_apartment_accessories import samara
from tests.test_apartment_products import project


def rows(p, system='В1'):
    return module.apartment_connection_rows(p, system, lambda: 1)


def by_key(items, key):
    return next(r for r in items if r.component_ids[0].endswith('-connection-' + key))


@pytest.mark.parametrize('system', ['В1', 'Т3'])
def test_samara_exact_counts_current_geometry_and_no_duplicate_kits(samara, system):
    before = deepcopy(asdict(samara))
    result = rows(samara, system)
    assert len(result) == 6
    for key in ('in', 'out'):
        row = by_key(result, key)
        assert row.qty == 143 and row.type_mark == 'PE-X Ø20×2 × евроконус 3/4 ВР'
        assert row.catalogue_id and row.code == 'VT.4410.NE.20'
        assert '6 мес.' in row.note and 'Кандидат' in row.note
        adapter = by_key(result, key + '-adapter')
        assert adapter.qty == 143 and adapter.code == 'VTr.580.NE.040E'
        assert adapter.type_mark == 'Евроконус 3/4 НР × G1/2 НР'
        assert 'не монтажная длина' in adapter.note
    assert by_key(result, 'valve-filter').qty == 143
    assert by_key(result, 'filter-regulator').qty == 98
    assert sum(r.qty for r in result if r.code == 'VTr.582.N.0004') == 241
    assert all(format_spec_qty(r.qty, r.unit) == str(r.qty) for r in result)
    assert not any('meter-kit' in r.component_ids[0] for r in result)
    all_rows = [r for s in build_water_specification(samara).sections for r in s.rows]
    assert all(r in all_rows or any(x.component_ids == r.component_ids and x.qty == r.qty
                                  for x in all_rows) for r in result)
    assert asdict(samara) == before


def test_no_rds_no_extra_nipples_and_no_kit_doubled(samara):
    samara.water_regulation_design = None
    result = rows(samara)
    assert len(result) == 5 and sum(r.qty for r in result if r.code == 'VTr.582.N.0004') == 143
    all_rows = [r for s in build_water_specification(samara).sections for r in s.rows]
    kits = [r for r in all_rows if r.component_ids == ('apartment-v1-meter-kit',)]
    assert len(kits) == 1 and kits[0].qty == 143


def test_unknown_counts_are_not_apartment_or_average_guesses(samara):
    samara.apartment_water_units = replace(samara.apartment_water_units, mode='unspecified')
    assert all(r.qty is None for r in rows(samara))
    samara.apartment_water_units = replace(samara.apartment_water_units,
        mode='explicit_counts', cold_count=200, hot_count=210)
    for system, n in [('В1', 200), ('Т3', 210)]:
        result = rows(samara, system)
        assert by_key(result, 'valve-filter').qty == n
        assert by_key(result, 'filter-regulator').qty is None


def test_unknown_rd_plan_is_not_zero_fittings(samara):
    samara.water_regulation_design = {'kind': 'unknown'}
    row = by_key(rows(samara), 'filter-regulator')
    assert row.qty is None and not row.code


def test_unknown_or_changed_hot_geometry_never_borrows_cold(samara):
    samara.t3_sections = []
    assert 'Dн×s уточнить' in by_key(rows(samara, 'Т3'), 'in').type_mark
    assert 'PE-X Ø20×2' in by_key(rows(samara, 'В1'), 'in').type_mark


def test_pipe_change_updates_requirement_without_auto_assigning_brand(samara):
    from app.pz.water_pipe_binding import PipeBinding, DrawingPipe
    # Binding already validates current Dн/s/dвн; no nearest-size substitution.
    binding = PipeBinding('apartment', DrawingPipe('PE-X 20×2,8', 'pex',20,2.8), ('changed',))
    old = module.bind_v1_pipes
    try:
        module.bind_v1_pipes = lambda p: {'apartment': binding}
        row = by_key(rows(samara), 'in')
        assert row.type_mark == 'PE-X Ø20×2,8 × G1/2 НР' and not row.catalogue_id
    finally:
        module.bind_v1_pipes = old


def test_incompatible_end_keeps_one_requirement_not_an_incomplete_kit(samara, monkeypatch):
    old = module.apartment_product_proposal(samara, 'В1')
    positions = tuple(replace(p, product=replace(p.product, connection_standard='eurocone'))
                      if p.kind == 'check' else p for p in old.positions)
    monkeypatch.setattr(module, 'apartment_product_proposal', lambda *a: replace(old, positions=positions))
    result = rows(samara)
    assert not by_key(result, 'out').code
    assert not any(r.component_ids[0].endswith('-out-adapter') for r in result)
    assert by_key(result, 'in').code == 'VT.4410.NE.20'


@pytest.mark.parametrize('change', ['thread', 'sex', 'standard', 'absent', 'source', 'duplicate'])
def test_port_matching_never_inserts_fitting_by_dn_alone(monkeypatch, change):
    from app.data import metering_products
    p = project(apartment_units_mode='one_per_apartment')
    prop = module.apartment_product_proposal(p, 'В1')
    parts = {r.kind:r.product for r in prop.positions}
    left, right = parts['valve'], parts['filter']
    assert module._joint(left, right)[0] == 'nipple'
    if change == 'thread': right = replace(right, thread='3/4')
    elif change == 'sex':
        right = replace(right, connection_sex='male')
        assert module._joint(left,right) == ('direct',None)
        return
    elif change == 'standard': right = replace(right, connection_standard='eurocone')
    elif change == 'absent': right = None
    elif change == 'source':
        cat = metering_products.get_metering_catalogue()
        monkeypatch.setattr(metering_products, 'get_metering_catalogue', lambda: replace(cat,sources={}))
    else: monkeypatch.setattr(module, 'NIPPLES', module.NIPPLES + (module.NIPPLES[0],))
    assert module._joint(left,right) == ('unresolved',None)


def test_dn20_supported_without_guessing_other_sizes():
    p = project(apartment_units_mode='one_per_apartment', apartment_design_residents=100)
    row = by_key(rows(p), 'valve-filter')
    assert row.code == 'VTr.582.N.0005' and 'G3/4' in row.type_mark
    p.apartment_water_units = replace(p.apartment_water_units, design_residents=300)
    row = by_key(rows(p), 'valve-filter')
    assert not row.code and row.qty == 8


def test_no_new_rows_outside_supported_apartment_composition():
    p = project()
    p.meters.has_apartment_meters = False
    assert rows(p) == []
    p.meters.has_apartment_meters = True
    p.consumer_groups.append(('cafe', 20))
    assert rows(p) == []


def test_sources_do_not_claim_validated_installation_dimensions():
    assert all(n.dimensions_status == 'conflict' for n in module.NIPPLES)
    assert all(not hasattr(n, 'length_mm') for n in module.NIPPLES)


def test_pdf_retains_table_heads_and_no_orphan_note_tail(samara, tmp_path):
    from app.pz.generator import generate_spec_pdf
    import pymupdf
    path = tmp_path / 'connections.pdf'
    generate_spec_pdf(samara, str(path))
    with pymupdf.open(path) as pdf:
        # Catalogue notes can grow; page count alone is not layout correctness.
        # Every actual overflow page must keep its header and usable body.
        # Measured row pagination (14.10) removed the former 6-row/page limit.
        # Exercise continuation pages without pinning the obsolete 20+ pages.
        assert len(pdf) > 1
        for p in pdf:
            text = p.get_text()
            assert 'Поз.' in text and 'Поставщик' in text
            # Body text remains above the lower title block at y=277 mm.
            for block in p.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    for span in line['spans']:
                        if 'присоединение ×' in span['text'] or 'Источники каталога:' in span['text']:
                            assert span['bbox'][3] < 277 * 72 / 25.4
        assert 'Источники каталога:' in pdf[-1].get_text()
