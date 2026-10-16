from dataclasses import replace

import pytest

from app.data import apartment_pipe_connections as module
from app.pz.water_pipe_binding import DrawingPipe

PIPE = DrawingPipe('PE-X 20×2', 'pex', 20, 2)
PORT = module.ConnectionPort('G', '1/2', 'female')


def test_two_mating_interfaces_and_no_installation_or_hydraulic_claim():
    result = module.propose_pipe_end(PIPE, PORT, 60)
    assert result.fitting.article == 'VT.4410.NE.20'
    assert result.adapter.article == 'VTr.580.NE.040E'
    assert result.fitting.port.mates(result.adapter.fitting_port)
    assert result.adapter.equipment_port.mates(PORT)
    assert result.status == 'candidate' and not result.installation_complete
    assert result.fitting.pn_bar == 10 and result.fitting.retightening_months == 6
    assert result.adapter.dimensions_status == 'conflict'
    assert not hasattr(result.adapter, 'length_mm')
    assert not hasattr(result, 'hydraulic_loss_m')


@pytest.mark.parametrize('pipe', [None, replace(PIPE, wall_mm=2.8),
    replace(PIPE, outer_mm=16), replace(PIPE, family='pe'),
    replace(PIPE, material='PE-X/Al/PE-X 20×2'),
    replace(PIPE, material='Металлополимерная PE-X 20×2'),
    replace(PIPE, material='PE-X с алюминиевой оболочкой 20×2')])
def test_unsupported_geometry_or_material_cannot_reuse_20x2(pipe):
    assert module.propose_pipe_end(pipe, PORT, 60) is None


@pytest.mark.parametrize('port', [None, replace(PORT, sex='male'),
    replace(PORT, thread='3/4'), replace(PORT, standard='eurocone'),
    replace(PORT, standard='R')])
def test_equipment_port_is_not_matched_by_dn_alone(port):
    assert module.propose_pipe_end(PIPE, port, 60) is None


@pytest.mark.parametrize('temperature', [None, float('nan'), float('inf'), 111, -21, True])
def test_temperature_is_a_screen_not_a_default(temperature):
    assert module.propose_pipe_end(PIPE, PORT, temperature) is None


@pytest.mark.parametrize('change', ['plain_thread', 'male_union', 'duplicate_fitting', 'duplicate_adapter', 'source'])
def test_incomplete_ambiguous_or_unproven_chain_has_no_candidate(monkeypatch, change):
    if change in ('plain_thread', 'male_union'):
        port = replace(module.ADAPTERS[0].fitting_port, standard='G') if change == 'plain_thread' else replace(
            module.ADAPTERS[0].fitting_port, sex='female')
        monkeypatch.setattr(module, 'ADAPTERS', (replace(module.ADAPTERS[0], fitting_port=port),))
    elif change == 'duplicate_fitting':
        monkeypatch.setattr(module, 'FITTINGS', module.FITTINGS * 2)
    elif change == 'duplicate_adapter':
        monkeypatch.setattr(module, 'ADAPTERS', module.ADAPTERS * 2)
    else:
        from app.data import metering_products
        cat = metering_products.get_metering_catalogue()
        monkeypatch.setattr(metering_products, 'get_metering_catalogue', lambda: replace(cat, sources={}))
    assert module.propose_pipe_end(PIPE, PORT, 60) is None
