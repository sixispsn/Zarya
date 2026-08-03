from app.pz.aux_schemes import build_metering_scheme_svg, build_pump_zone_scheme_svg
from app.pz.project import (
    BuildingFlags, FireSystem, MeterRow, MetersSystem, Project, WaterSource,
)
from app.pz.scheme import build_scheme


def _project():
    project = Project()
    project.building = BuildingFlags(
        floors_above=12, height_m=36, zones=2, apartments=240,
    )
    project.source = WaterSource(
        inputs_count=2, hws_heater_in_scope=True, h_tepl_m=3.0,
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
    assert "Ввод водопровода 2x" in build_scheme(project).svg
    meter_svg = build_metering_scheme_svg(project)
    assert "Ввод 1 · 100% Q" in meter_svg
    assert "Ввод 2 · 100% Q" in meter_svg
    assert "задвижка с электроприводом" in meter_svg


def test_pump_zone_scheme_contains_zones_heater_t3_and_t4():
    svg = build_pump_zone_scheme_svg(_project())
    assert "Зона 1" in svg and "Зона 2" in svg
    assert "Водонагреватель / теплообменник" in svg
    assert "Т3 · подача ГВС" in svg
    assert "Т4 · циркуляция" in svg
