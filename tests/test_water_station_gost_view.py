"""GOST station presentation: exact catalogue identity, no invented datums."""
from copy import deepcopy
from dataclasses import asdict
from xml.etree import ElementTree as ET

import pytest

from tests.test_water_station_drafting import samara
from tests.test_water_station_review import common
from app.data.booster_geometry import booster_geometry
from app.pz.water_station_drafting import build_pump_zone_scheme_pages
from app.pz.water_station_review import station_counts, connected_network, review_station


def test_source_backed_pbs_ports_not_external_pipe_sizing(common):
    ref = booster_geometry(common.pumps,station_counts(common.pumps))
    assert (ref['connection_dn'],ref['bare_pump_nozzle_dn'],ref['p2_motor_kw']) == (80,50,4)
    assert ref['p1_input_kw'] is None
    before = deepcopy(asdict(common))
    svg = build_pump_zone_scheme_pages(common)[0]
    assert 'DN80*' in svg and 'DN50' in svg
    assert 'P1 потребляемая: не подтверждена' in svg
    assert 'P2 двигателя одного насоса: 4,00 кВт' in svg
    assert asdict(common) == before
    assert next(x for x in review_station(common)['hydraulic'] if x['id']=='new_losses')['value']=='Не подтверждены'


@pytest.mark.parametrize('model',['CNP / Aikon PBS CDM15-5 extra','CNP / Aikon PBS CDM15-7','Wilo PBS CDM15-5'])
def test_stale_or_similar_selection_does_not_inherit_passport(common,model):
    common.pumps.model = model
    assert booster_geometry(common.pumps,(1,1)) is None
    svg = build_pump_zone_scheme_pages(common)[0]
    assert 'DN80*' not in svg and 'P2 двигателя одного насоса: 4,00' not in svg
    assert 'data-regulated="true"' not in svg


def test_unknown_count_not_given_two_pump_connection(common):
    assert booster_geometry(common.pumps,None) is None
    assert booster_geometry(common.pumps,(3,1)) is None


def test_vertical_parallel_pump_branches_and_gost_symbols(common):
    root = ET.fromstring(build_pump_zone_scheme_pages(common)[0])
    pipes = {e.get('data-pipe'):e for e in root.iter() if e.get('data-pipe')}
    assert pipes['Н1'].get('d') == 'M160,175 L160,95'
    assert pipes['Н2'].get('d') == 'M215,175 L215,95'
    symbols = [e for e in root.iter() if e.get('data-ugo')=='pump-general']
    assert len(symbols)==2 and all(e.get('data-regulated')=='true' for e in symbols)
    assert len([e for e in root.iter() if e.get('data-ugo')=='closed-pressure-tank'])==1
    assert all(e.get('data-from')=='suction' and e.get('data-to')=='discharge' for e in (pipes['Н1'],pipes['Н2']))


def test_factory_tank_bound_to_graph_and_one_spec_owner(common):
    from app.pz.spec import build_specification
    net = connected_network(common)
    assert next(n for n in net.nodes if n.id=='station_tank').kind=='source'
    assert any(e.a=='station_discharge' and e.b=='station_tank_valve' for e in net.links)
    rows = [r for s in build_specification(common).sections for r in s.rows]
    for key in ('station_tank','station_tank_valve'):
        owners = [r for r in rows if key in r.component_ids]
        assert len(owners)==1 and 'station_assembly' in owners[0].component_ids
        assert '12 л' in owners[0].note


def test_actual_architectural_datums_are_not_basement_or_catalogue_height(common):
    missing = build_pump_zone_scheme_pages(common)[0]
    assert 'Пол насосной: отметка не задана' in missing
    assert 'Ось всасывания: отметка не задана' in missing
    assert 'data-level-mark="station-floor"' not in missing
    common.source.station_room_number='Н-01'
    common.source.station_floor_elevation_m=-2.75
    common.source.station_suction_elevation_m=-2.50
    before=deepcopy(asdict(common))
    svg=build_pump_zone_scheme_pages(common)[0]
    assert 'Помещение № Н-01' in svg
    assert 'data-source-elevation-m="-2.75"' in svg
    assert 'data-source-elevation-m="-2.5"' in svg
    assert '-3,25' not in svg  # whole-basement datum is not copied
    assert asdict(common)==before


def test_studio_to_yaml_builder_and_drawing_without_assistant():
    from tests.test_studio_apartment_meters import draft
    from app.intake.studio_intake import build_handoff_request
    from app.intake.studio_project import calculate_project
    from app.intake.yaml_io import dump_request,load_request
    from app.intake.project_builder import build_project
    base = draft()
    entered=draft(station_room_number='Н-02',station_floor_elevation_m=-2.8,station_suction_elevation_m=-2.6)
    before, after=calculate_project(base),calculate_project(entered)
    assert before['head']==after['head'] and before['flows']==after['flows']
    req=build_handoff_request(entered)
    restored=load_request(dump_request(req))
    assert restored.source_data==req.source_data
    project=build_project(restored)
    svg=build_pump_zone_scheme_pages(project)[0]
    assert 'data-source-elevation-m="-2.8"' in svg and 'Помещение № Н-02' in svg
    assert project.source.station_suction_elevation_m==-2.6


@pytest.mark.parametrize('key,value', [('station_floor_elevation_m','nan'),
    ('station_suction_elevation_m',True),('station_floor_elevation_m',1001),('station_room_number','x'*41)])
def test_invalid_drawing_inputs_rejected(key,value):
    from app.intake.studio_intake import validate_value,IntakeError
    with pytest.raises(IntakeError): validate_value(key,value)


@pytest.mark.parametrize('key', ['station_floor_elevation_m','station_suction_elevation_m'])
@pytest.mark.parametrize('value', [True,'not a level'])
def test_yaml_does_not_turn_boolean_into_elevation(key,value):
    import yaml
    from app.intake.studio_intake import build_handoff_request
    from app.intake.yaml_io import dump_request,load_request,YamlFormatError
    from tests.test_studio_apartment_meters import draft
    data=yaml.safe_load(dump_request(build_handoff_request(draft())))
    data['source_data'][key]=value
    with pytest.raises(YamlFormatError):
        load_request(yaml.safe_dump(data,allow_unicode=True))


def test_station_annotations_do_not_overlap_title_block(common):
    import cairosvg,pymupdf
    svg=build_pump_zone_scheme_pages(common)[0]
    with pymupdf.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()),filetype='pdf') as doc:
        for block in doc[0].get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                text=''.join(span['text'] for span in line['spans'])
                if text.startswith(('1. DN','2. Q/H','3. PI','4. Отметки','5. Т1/Т2','См. лист','PBS:')):
                    # Check the full rendered line, not its first text span:
                    # Cairo may split a sentence into separate word runs.
                    x0,y0,x1,y1=[v*25.4/72 for v in line['bbox']]
                    assert x1 < 225 or y1 < 232
        text=doc[0].get_text()
        assert 'См. лист обслуживания.' in text
