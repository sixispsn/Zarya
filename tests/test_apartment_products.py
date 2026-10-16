"""Current apartment sizing → product proposals, without rewriting hydraulics."""
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
import yaml

from app.intake.project_builder import build_project
from app.intake.studio_intake import answer_field, build_handoff_request
from app.intake.yaml_io import dump_request, load_request, YamlFormatError
from app.calc.apartment_meters import estimate_apartment_meters
from app.pz import apartment_products as module
from app.pz.apartment_products import apartment_product_proposal as proposal
from app.pz.spec import build_water_specification
from app.pz.water_apartment_assembly import apartment_spec_rows
from tests.test_studio_apartment_meters import draft
from tests import test_studio as studio_tests

client = studio_tests.client


def project(**values):
    return build_project(build_handoff_request(draft(**values)))


@pytest.mark.parametrize('system,key', [('В1','h_apartment_c_meter_m'), ('Т3','h_apartment_h_meter_m')])
@pytest.mark.parametrize('occupants,dn', [(3,15), (100,20), (300,32)])
def test_current_inputs_use_same_approved_estimator_not_fixed_dn15(system,key,occupants,dn):
    p = project(apartment_design_residents=occupants)
    before = deepcopy(asdict(p))
    found = proposal(p,system)
    reference = estimate_apartment_meters(dict(residents=20,apartments=8,
        consumer_code='residential_full_bath', hws_type='central', apartment_design_residents=occupants))
    assert found.dn == reference['rows'][key]['dn'] == dn
    assert found.reference_loss_m == reference['rows'][key]['loss_m']
    assert found.flow_lps == reference['rows'][key]['flow_lps']
    assert found.status == 'preliminary'
    assert asdict(p) == before
    meter = next(x.product for x in found.positions if x.kind=='meter')
    assert meter.dn == dn and meter.remote_readout
    for part in found.positions:
        if part.product and part.kind != 'meter':
            assert part.product.thread == meter.kit_pipe_thread
            assert part.product.connection_sex == 'female'
    if dn == 32:
        # The expanded catalogue has two valid manual valves. Never silently
        # choose one by catalogue order just to keep an old golden green.
        valve = next(x for x in found.positions if x.kind == 'valve')
        assert valve.product is None
        assert set(valve.candidates) == {'valtec-vt214-dn32', 'ld47-vv-m02-dn32'}
        assert all(x.product and x.product.dn == dn for x in found.positions if x.kind != 'valve')
    else:
        assert all(x.product and x.product.dn == dn for x in found.positions)


def test_mean_and_manual_occupancy_survive_yaml_and_input_changes():
    d = draft()
    def make():
        req = build_handoff_request(d)
        assert load_request(dump_request(req)) == req
        return build_project(load_request(dump_request(req)))
    assert proposal(make(),'В1').design_residents == 2.5
    answer_field(d,'apartment_design_residents',3)
    assert proposal(make(),'В1').design_residents == 3
    answer_field(d,'residents',40)
    assert proposal(make(),'В1').design_residents == 3
    answer_field(d,'apartment_design_residents',None)
    assert proposal(make(),'В1').design_residents == 5


def test_manual_head_losses_never_replaced_by_product_proposal():
    p = project(h_apartment_c_meter_m=1.25,h_apartment_h_meter_m=2.75)
    before = deepcopy(asdict(p))
    spec = build_water_specification(p)
    assert (p.source.h_apartment_c_meter_m,p.source.h_apartment_h_meter_m)==(1.25,2.75)
    assert asdict(p) == before
    assert 'Ручные потери в балансе напора сохранены' in spec.note
    assert 'не паспортное h(Q)' in spec.note


def test_temperature_screening_and_qn_duration_not_mistaken_for_approval():
    p = project(apartment_design_residents=100)
    hot = proposal(p,'Т3')
    assert 'выше Qn' in next(x.reason for x in hot.positions if x.kind=='meter')
    p.insulation.gvs_water_temp=105
    hot = proposal(p,'Т3')
    assert next(x.product for x in hot.positions if x.kind=='meter')
    assert next(x.product for x in hot.positions if x.kind=='check') is None
    p.insulation.gvs_water_temp=150
    assert all(x.product is None for x in proposal(p,'Т3').positions)


@pytest.mark.parametrize('change', ['no_apartments','unreconciled','no_meter','local','mixed','unknown_catalog_dn'])
def test_no_fabricated_success(change):
    from app.pz.project import HwsType
    p = project()
    if change == 'no_apartments': p.building.apartments=0
    elif change == 'unreconciled': p.building.residents=21
    elif change == 'no_meter': p.meters.has_apartment_meters=False
    elif change == 'local': p.building.hws_type=HwsType.LOCAL
    elif change == 'mixed': p.consumer_groups.append(('cafe',20))
    else: p.apartment_water_units=replace(p.apartment_water_units,design_residents=50000)
    found = proposal(p,'В1')
    if change == 'unknown_catalog_dn':
        assert found.dn == 250 and all(x.product is None for x in found.positions)
        assert all(not x.catalogue_id for x in apartment_spec_rows(p,'В1',lambda:1))
    else:
        assert found is None


@pytest.mark.parametrize('change', ['conflict','wrong_thread','duplicate','too_little_flow','no_remote'])
def test_incompatible_or_ambiguous_products_are_not_auto_accepted(monkeypatch,change):
    catalog=module.get_metering_catalogue()
    products=dict(catalog.products)
    meter=products['decast-vskm90-dg-dn15']
    check=products['itap-europa100-g-dn15']
    if change=='conflict': products[check.id]=replace(check,dimension_status='conflict')
    elif change=='wrong_thread': products[check.id]=replace(check,thread='3/4')
    elif change=='duplicate': products['another-check']=replace(check,id='another-check')
    elif change=='too_little_flow': products[meter.id]=replace(meter,flows_m3h={'qmax':.1})
    else: products[meter.id]=replace(meter,remote_readout=False)
    monkeypatch.setattr(module,'get_metering_catalogue',lambda:replace(catalog,products=products))
    found=proposal(project(),'В1')
    assert next(x for x in found.positions if x.kind=='check').product is None
    assert all(x.product is None or x.product.dimension_status=='verified' for x in found.positions)
    # Quarantined VALTEC VT.161 never replaces the missing verified check valve.
    assert all(not x.product or not x.product.id.startswith('valtec-vt161') for x in found.positions)


@pytest.mark.parametrize('bad', [0,-1,1.5,True,'3',float('nan'),1_000_001])
def test_manual_occupancy_validation_in_yaml(bad):
    data=yaml.safe_load(dump_request(build_handoff_request(draft())))
    data['apartment_water_units']={'design_residents':bad}
    with pytest.raises(YamlFormatError): load_request(yaml.safe_dump(data,allow_unicode=True))


def test_ordinary_http_persists_design_occupancy_and_revokes_derived_documents(client):
    state=studio_tests.new(client)
    answers={k:r['value'] for k,r in draft(apartment_design_residents=3)['answers'].items()}
    response=client.post('/studio/api/calculate',json={'revision':state['revision'],'answers':answers})
    assert response.status_code==200, response.text
    state=response.json()
    restored=client.get('/studio/api/draft').json()
    assert next(x for x in restored['fields'] if x['key']=='apartment_design_residents')['value']==3
    state=studio_tests.answer(client,state,'apartment_design_residents',6)
    assert all(state[k] is None for k in ('project_calculation','preview','package'))
