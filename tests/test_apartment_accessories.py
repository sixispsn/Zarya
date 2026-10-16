from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from app.data import apartment_regulators as catalogue
from app.data import apartment_filters as filters
from app.intake import samara_study
from app.pz import apartment_products as products
from app.pz.spec import build_water_specification
from app.pz.water_apartment_assembly import apartment_spec_rows
from tests.test_apartment_products import project


@pytest.fixture
def samara(tmp_path):
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    return samara_study.build(draft, tmp_path, render=False)[0].project


@pytest.mark.parametrize('system', ['В1', 'Т3'])
@pytest.mark.parametrize('residents,dn,thread,pipe', [(3,15,'3/4','1/2'), (100,20,'1','3/4')])
def test_kit_tracks_current_meter_not_house_size(system,residents,dn,thread,pipe):
    p = project(apartment_units_mode='one_per_apartment', apartment_design_residents=residents)
    kit = products.apartment_connection_kit(p, system)
    assert kit.kit.meter_ids == (kit.meter.id,)
    assert kit.kit.meter_thread == thread and kit.kit.pipe_thread == pipe
    rows = apartment_spec_rows(p, system, lambda: 1)
    r = rows[-1]
    assert r.catalogue_id.endswith(f'-dn{dn}') and r.qty == 8 and r.unit == 'компл.'
    assert r.component_ids[0].endswith('-meter-kit')
    assert 'повторно не закупать' in r.note
    assert 'присоединения учтены отдельно' in rows[2].note


@pytest.mark.parametrize('change', ['thread','meter','status','duplicate','missing'])
def test_no_incompatible_or_ambiguous_kit(monkeypatch,change):
    cat = products.get_metering_catalogue()
    kits = dict(cat.connection_kits)
    key = 'decast-vskm90-kit-dn15'
    kit = kits[key]
    if change == 'thread': kits[key] = replace(kit, pipe_thread='3/4')
    elif change == 'meter': kits[key] = replace(kit, meter_ids=('some-other-meter',))
    elif change == 'status': kits[key] = replace(kit, status='conflict')
    elif change == 'missing': del kits[key]
    else: kits['duplicate'] = replace(kit, id='duplicate')
    monkeypatch.setattr(products, 'get_metering_catalogue', lambda: replace(cat,connection_kits=kits))
    p = project(apartment_units_mode='one_per_apartment')
    assert products.apartment_connection_kit(p, 'В1').kit is None
    # The need for a kit does not disappear just because catalogue matching fails.
    row = apartment_spec_rows(p, 'В1', lambda: 1)[-1]
    assert row.qty == 8 and not row.catalogue_id and row.type_mark == 'по подбору'


def test_samara_counts_read_only_and_no_invented_regulator_setting(samara):
    before = deepcopy(asdict(samara))
    rows = [r for s in build_water_specification(samara).sections for r in s.rows]
    for system, prefix in [('В1','v1'), ('Т3','t3')]:
        kit = next(r for r in rows if r.component_ids == (f'apartment-{prefix}-meter-kit',))
        rd = next(r for r in rows if r.component_ids == (f'apartment-{prefix}-regulator',))
        assert kit.qty == 143 and rd.qty == 98
        assert rd.code == 'OR.224.G.04' and 'Кандидат' in rd.note
        candidate = products.apartment_regulator_proposal(samara, system)
        assert candidate.status == 'candidate' and candidate.setting_bar is None
        assert candidate.product.dn == 15 and candidate.product.static_regulation
        assert candidate.product.setting_range_bar == (1,7)
    assert asdict(samara) == before
    samara.water_regulation_design = None
    assert products.apartment_regulator_proposal(samara,'В1') is None
    assert not any('regulator' in k for s in build_water_specification(samara).sections for r in s.rows for k in r.component_ids)


@pytest.mark.parametrize('change', ['temperature','nan','mesh','filter_source','thread','duplicate','withdrawn','no_static','dn'])
def test_unsuitable_rd_is_not_silently_substituted(samara,monkeypatch,change):
    if change == 'temperature': samara.insulation.gvs_water_temp = 81
    elif change == 'nan': samara.insulation.gvs_water_temp = float('nan')
    elif change == 'mesh':
        # Both compatible filters violate the regulator's <=500 µm condition.
        monkeypatch.setattr(filters,'FILTERS', {k:replace(v,mesh_microns=800)
                                               for k,v in filters.FILTERS.items()})
    elif change == 'filter_source': monkeypatch.setattr(filters,'SOURCE_HASHES', {})
    elif change == 'dn': samara.apartment_water_units = replace(samara.apartment_water_units, design_residents=300)
    else:
        rd = catalogue.PRODUCTS[0]
        if change == 'thread': new = replace(rd, thread='3/4')
        elif change == 'withdrawn': new = replace(rd, status='withdrawn')
        elif change == 'no_static': new = replace(rd, static_regulation=False)
        else: new = replace(rd, id='duplicate')
        monkeypatch.setattr(catalogue,'PRODUCTS', (rd,new) if change == 'duplicate' else (new,))
    result = products.apartment_regulator_proposal(samara,'Т3')
    assert result.product is None and result.setting_bar is None
    if change == 'nan':
        # The independent insulation calculation rejects an invalid temperature.
        with pytest.raises(ValueError):
            build_water_specification(samara)
        return
    row = next(r for s in build_water_specification(samara).sections for r in s.rows
               if r.component_ids == ('apartment-t3-regulator',))
    assert row.qty == 98 and not row.catalogue_id and 'по подбору' in row.type_mark


def test_rd_dn20_is_not_forced_to_dn15_and_old_model_not_in_catalog(samara):
    samara.apartment_water_units = replace(samara.apartment_water_units, design_residents=100)
    found = products.apartment_regulator_proposal(samara,'В1')
    assert found.product.dn == 20 and found.product.article == 'OR.224.G.05'
    assert all(p.model != 'VT.085.N' for p in catalogue.PRODUCTS)


def test_unknown_quantity_stays_unknown_and_no_meter_means_no_kit():
    p = project()
    assert apartment_spec_rows(p,'В1',lambda:1)[-1].qty is None
    p.meters.has_apartment_meters = False
    assert len(apartment_spec_rows(p,'В1',lambda:1)) == 3
    assert products.apartment_connection_kit(p,'В1').kit is None
