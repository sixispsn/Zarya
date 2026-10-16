from dataclasses import replace

import pytest

from app.data import apartment_filters as evidence
from app.pz import apartment_products as module
from tests.test_apartment_products import project


@pytest.mark.parametrize('system', ['В1', 'Т3'])
def test_reviewed_quality_preference_not_catalogue_order(monkeypatch, system):
    catalogue = module.get_metering_catalogue()
    for products in (dict(catalogue.products), dict(reversed(list(catalogue.products.items())))):
        monkeypatch.setattr(module, 'get_metering_catalogue', lambda: replace(catalogue, products=products))
        position = next(p for p in module.apartment_product_proposal(project(), system).positions
                        if p.kind == 'filter')
        assert position.product.id == 'valtec-vt386-dn15'
        assert set(position.candidates) == {'valtec-vt386-dn15', 'valtec-vt192-dn15'}
        assert '300 мкм' in position.reason and 'PN16' in position.reason
        assert 'требуют проверки' in position.reason


@pytest.mark.parametrize('change', ['stale', 'unknown', 'dimensions', 'mounting', 'temperature'])
def test_quality_cannot_override_missing_evidence_or_compatibility(monkeypatch, change):
    catalogue = module.get_metering_catalogue()
    products, sources = dict(catalogue.products), dict(catalogue.sources)
    preferred = products['valtec-vt386-dn15']
    if change == 'stale':
        sources['vt386-0625'] = dict(sources['vt386-0625'], sha256='changed')
    elif change == 'unknown':
        products['unreviewed'] = replace(preferred, id='unreviewed')
    elif change == 'dimensions':
        products[preferred.id] = replace(preferred, dimension_status='conflict')
    elif change == 'mounting':
        products[preferred.id] = replace(preferred, installation={'allowed': ('vertical_up',)})
    else:
        products[preferred.id] = replace(preferred, temperature_c=(1, 40))
    monkeypatch.setattr(module, 'get_metering_catalogue',
                        lambda: replace(catalogue, products=products, sources=sources))
    position = next(p for p in module.apartment_product_proposal(project(), 'Т3').positions
                    if p.kind == 'filter')
    if change in ('stale', 'unknown'):
        assert position.product is None
    else:
        assert position.product.id == 'valtec-vt192-dn15'


def test_both_filter_passports_remain_usable_for_prv_screening():
    catalogue = module.get_metering_catalogue()
    for model, mesh in (('vt192', 500), ('vt386', 300)):
        product = catalogue.products[f'valtec-{model}-dn15']
        assert evidence.filter_evidence(product, catalogue).mesh_microns == mesh
    assert evidence.filter_evidence(None, catalogue) is None


def test_two_missing_hashes_are_not_proof(monkeypatch):
    catalogue = module.get_metering_catalogue()
    monkeypatch.setattr(evidence, 'SOURCE_HASHES', {})
    assert evidence.filter_evidence(catalogue.products['valtec-vt386-dn15'],
                                    replace(catalogue, sources={})) is None
