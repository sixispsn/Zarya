from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET

import pytest

from app.pz.aux_schemes import build_metering_scheme_svg, build_pump_zone_scheme_svg
from app.pz.project import (
    BuildingFlags,
    FireSystem,
    MeterRow,
    MetersSystem,
    Project,
    WaterSource,
)
from app.pz.scheme import build_scheme
from app.pz.water_station_drafting import build_pump_zone_scheme_pages


def _pipes(svg):
    return {
        e.get("data-pipe"): e for e in ET.fromstring(svg).iter() if e.get("data-pipe")
    }


def _project():
    project = Project()
    project.building = BuildingFlags(
        floors_above=12,
        height_m=36,
        zones=2,
        apartments=240,
    )
    project.source = WaterSource(
        inputs_count=2,
        hws_heater_in_scope=True,
        h_tepl_m=3.0,
    )
    project.fire = FireSystem(
        required=True,
        network_topology="pre_meter_branch",
        topology_basis="ТУ СКС",
        branch_electric_valves=True,
    )
    project.meters = MetersSystem(
        inputs_count=2,
        rows=[MeterRow(label="Счётчик ХВС", dn=40, h_a=0.5)],
    )
    return project


def test_input_count_is_same_in_main_and_metering_schemes():
    project = _project()
    assert "Вводы В1 (2 шт.)" in build_scheme(project).svg
    meter_svg = build_metering_scheme_svg(project)
    assert 'data-inlet="1"' in meter_svg
    assert 'data-inlet="2"' in meter_svg
    assert "задвижка с электроприводом" in meter_svg


@pytest.mark.parametrize("zones", [2, 3, 12])
@pytest.mark.parametrize("pump_required", [False, True])
def test_pump_zone_scheme_does_not_invent_connections_between_zones(
    zones, pump_required
):
    project = _project()
    project.building.zones = zones
    project.pumps.required = pump_required
    before = deepcopy(asdict(project))
    pages = build_pump_zone_scheme_pages(project)
    svg = build_pump_zone_scheme_svg(project)
    # Compatibility preview is the station sheet, not the separate HWS sheet.
    assert svg == pages[0]
    assert f"Всего зон: {zones}" in svg
    assert "Распределение по зонам не задано" in svg
    assert "Требуется схема присоединений" in svg
    pipes = _pipes(svg)
    assert pipes["station-discharge"].get("data-to") == "split"
    assert not {"cold-branch", "heater-branch"} & pipes.keys()
    assert not any(e.get("data-from") == "split" for e in pipes.values())
    components = {e.get("data-component") for e in ET.fromstring(svg).iter()}
    assert not {"meter-cold", "meter-heater"} & components
    assert len(pages) == 2
    assert "Зональная схема требует данных" in pages[1]
    assert "требуется дополнение топологии" in pages[1]
    assert not _pipes(pages[1])  # No invented shared T3/T4 loop.
    assert asdict(project) == before


@pytest.mark.parametrize("cold_zones,hot_zones", [(1, 1), (1, 2), (2, 1), (2, 2)])
def test_explicit_hws_zones_do_not_reconfigure_station(cold_zones, hot_zones):
    project = _project()
    project.building.zones = cold_zones
    # Hold the document composition fixed too: otherwise adding/removing a
    # building section legitimately changes the total in the station stamp.
    base_station = build_pump_zone_scheme_pages(
        project, include_building_section=False
    )[0]
    project.hws_stage_p = replace(project.hws_stage_p, enabled=True, zones=hot_zones)
    before = deepcopy(asdict(project))
    pages = build_pump_zone_scheme_pages(project, include_building_section=False)
    assert len(pages) == 2
    assert pages[0] == base_station
    cold, hot = _pipes(pages[0]), _pipes(pages[1])
    assert ("cold-branch" in cold) == (cold_zones == 1)
    assert ("heater-branch" in cold) == (cold_zones == 1)
    if cold_zones == 1:
        assert cold["cold-branch"].get("data-to") == "cold-zone-1"
        assert cold["heater-branch"].get("data-to") == "heater-meter-out"
    if hot_zones == 1:
        assert hot["t4-return"].get("data-to") == "return-join"
        assert hot["representative-circulation"].get("data-scope") == "representative"
    else:
        assert "Объединять зоны в один условный контур" in pages[1]
        assert not hot
    assert asdict(project) == before


def test_pump_zone_uses_a3_physical_units_and_shared_frame():
    svg = ET.fromstring(build_pump_zone_scheme_svg(_project()))
    assert svg.get("viewBox") == "0 0 420 297"
    assert svg.get("width") == "420mm"
    assert any(e.get("data-drawing-frame") == "spds-form-3" for e in svg.iter())
    assert not any(e.get("rx") for e in svg.iter())
