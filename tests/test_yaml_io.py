# -*- coding: utf-8 -*-
"""Тесты app/intake/yaml_io.py — YAML как второй потребитель Builder'а."""
import pytest

from app.intake.yaml_io import (
    load_request, dump_request, YamlFormatError,
)
from app.intake.project_builder import build_project, RequestValidationError

GOOD = """
document:
  cipher: Т-ИОС2
  object_name: Объект
  organization: Орг
building: {type: residential, floors: 16, height_m: 48}
fire: {height_m: 48, category: residential_f13, streams: 2, geometry_confirmed: true}
rooms:
  - {name: Коридор, length_m: 42, width_m: 2.4, height_m: 3.0}
network:
  source: {node: К1, kind: city_main, available_head_m: 32}
  runs:
    - {from: К1, to: К2, length_m: 36}
    - {from: К2, to: К3, length_m: 15}
    - {from: К3, to: К4, length_m: 36}
    - {from: К4, to: К1, length_m: 15}
  risers:
    - {name: СТ-1, at: К1, height_m: 46.5, cabinet_elevation_m: 45.6}
    - {name: СТ-2, at: К2, height_m: 46.5, cabinet_elevation_m: 45.6}
"""


def test_load_basic():
    req = load_request(GOOD)
    assert req.document.cipher == "Т-ИОС2"
    assert req.building_type == "residential"
    assert req.floors == 16
    assert req.streams == 2
    assert len(req.rooms) == 1
    assert len(req.network.runs) == 4
    assert req.network.available_head_m == 32.0


def test_roundtrip_identity():
    req = load_request(GOOD)
    assert load_request(dump_request(req)) == req


def test_roundtrip_preserves_optional_fields():
    y = GOOD + "\n"
    req = load_request(y)
    req.network.node_elevations = {"К2": -1.5}
    req2 = load_request(dump_request(req))
    assert req2.network.node_elevations == {"К2": -1.5}


def test_roundtrip_preserves_explicit_fire_category_and_inputs():
    req = load_request(GOOD)
    req.fire_category = "theatre_f21"
    req.fire_hall_seats = 450
    req.fire_area_m2 = 1800
    req2 = load_request(dump_request(req))
    assert req2.fire_category == "theatre_f21"
    assert req2.fire_hall_seats == 450
    assert req2.fire_area_m2 == 1800
    assert req2.fire_geometry_confirmed is True


def test_roundtrip_preserves_topology_hws_and_head_path_inputs():
    from app.intake.request_dto import SourceDataRequest

    req = load_request(GOOD)
    req.hws_type = "local"
    req.fire_topology = "pre_meter_branch"
    req.fire_topology_basis = "ТУ СКС, п. 7"
    req.fire_branch_electric_valves = True
    req.source_data = SourceDataRequest(
        inputs_count=2,
        h_tepl_m=3.0,
        h_apartment_c_meter_m=0.4,
        h_apartment_h_meter_m=0.5,
        hws_heater_in_scope=True,
    )
    assert load_request(dump_request(req)) == req


def test_roundtrip_preserves_sp54_118_253_inputs():
    from app.intake.request_dto import SewageRiserRequest, SewerPipeRequest

    req = load_request(GOOD)
    req.apartments = 240
    req.owner_groups_count = 3
    req.roof_type = "flat"
    req.storm_city = "moscow"
    req.storm_roof_area_m2 = 1200
    req.storm_walls_area_m2 = 80
    req.storm_period_years = 5
    req.catering_type = "raw"
    req.catering_seats = 200
    req.catering_conditional_dishes = 1500
    req.school_grease_by_assignment = True
    req.sewage_risers = [SewageRiserRequest(
        "К1-Ст1", 3.5, "pp", "ventilated", 110, 110, 87.5, True,
    )]
    req.sewer_pipes = [SewerPipeRequest(
        "K1", "К1-М1", "горизонтальная сеть", "ПП", "ТУ изготовителя", 110, 3.4, 48,
        slope_per_mille=20.0, fill_ratio=0.55,
        from_node="К1-Ст1", to_node="К1-Вып1", room="техподполье",
        elevation_start_m=-0.40, elevation_end_m=-1.36,
    )]
    req.sewage_outlets_count = 2
    req.wastewater_design_assignment_ref = "Задание, раздел 6"
    req.wastewater_survey_ref = "ИГИ, том 2"
    req.wastewater_service_life_years = 50
    req.wastewater_overhaul_period_years = 25
    req.wastewater_disposal_mode = "centralized"
    req.wastewater_tu_org = "Водоканал"
    req.wastewater_tu_number = "123-К"
    req.wastewater_tu_date = "01.08.2026"
    req.wastewater_discharge_standard_ref = "НДС № 7 от 01.08.2026"
    req.wastewater_water_body_characteristics_note = "категория и режим по ИЭИ"
    req.wastewater_existing_network_type = "раздельная"
    req.wastewater_existing_network_material = "ПЭ"
    req.wastewater_existing_network_standard = "ГОСТ 18599-2001"
    req.wastewater_existing_network_outer_diameter_mm = 200
    req.wastewater_existing_network_wall_thickness_mm = 11.9
    req.wastewater_discharge_point_k1 = "КК-1"
    req.wastewater_k1_min_hourly_m3h = 0.12
    req.wastewater_quality_indicators_note = "по условиям подключения"
    req.wastewater_laying_method = "в шахтах и под потолком"
    req.wastewater_fire_barrier_note = "противопожарные муфты"
    req.wastewater_deformation_joint_note = "пересечения отсутствуют"
    req.wastewater_external_network_design_note = "решения по ИГИ и ГП"
    req.storm_roof_sections = 2
    req.storm_funnels_count = 4
    req.storm_max_funnel_spacing_m = 40
    req.storm_selected_funnel_capacity_lps = 12
    req.storm_max_funnel_flow_lps = 10
    req.storm_risers_count = 2
    req.storm_selected_riser_dn_mm = 100
    req.storm_max_riser_flow_lps = 10
    assert load_request(dump_request(req)) == req


def test_roundtrip_preserves_consumer_functional_names():
    from app.intake.request_dto import ConsumerGroupRequest
    req = load_request(GOOD)
    req.consumers = [
        ConsumerGroupRequest("residential_central_hw", 480, "Жилая часть"),
        ConsumerGroupRequest("sport_pool", 120, "Спортивный комплекс"),
    ]
    assert load_request(dump_request(req)).consumers == req.consumers


def test_roundtrip_preserves_repair_sections():
    req = load_request(GOOD)
    req.network.runs[0].repair_section_id = "РС-1"
    req.network.risers[0].repair_section_id = "РС-1"
    req2 = load_request(dump_request(req))
    assert req2.network.runs[0].repair_section_id == "РС-1"
    assert req2.network.risers[0].repair_section_id == "РС-1"


def test_bad_yaml_syntax():
    with pytest.raises(YamlFormatError, match="синтаксис"):
        load_request("document: [unclosed")


def test_root_not_mapping():
    with pytest.raises(YamlFormatError, match="словарём"):
        load_request("- just\n- a list\n")


def test_missing_document_section():
    with pytest.raises(YamlFormatError, match="document"):
        load_request("building: {type: residential, floors: 5, height_m: 15}")


def test_rooms_not_list():
    with pytest.raises(YamlFormatError, match="списком"):
        load_request(GOOD.replace("rooms:\n  - {name: Коридор, length_m: 42, "
                                  "width_m: 2.4, height_m: 3.0}",
                                  "rooms: {oops: 1}"))


def test_semantic_errors_deferred_to_builder():
    # структурно валидный YAML, но с плохими значениями → ловит Builder, не парсер
    bad_values = GOOD.replace("floors: 16", "floors: 0")
    req = load_request(bad_values)          # парсер пропускает
    with pytest.raises(RequestValidationError):
        build_project(req)                  # Builder ловит


def test_full_chain_yaml_to_project():
    req = load_request(GOOD)
    p = build_project(req)
    assert p.fire.streams == 2
    assert p.fire_network is not None
    assert len(p.fire_network.risers) == 2


def test_streams_absent_means_none():
    y = GOOD.replace(
        "fire: {height_m: 48, category: residential_f13, streams: 2, geometry_confirmed: true}",
        "fire: {height_m: 48, category: residential_f13, geometry_confirmed: true}",
    )
    req = load_request(y)
    assert req.streams is None


def test_fire_height_is_not_silently_copied_from_building_height():
    y = GOOD.replace("height_m: 48, category:", "category:")
    req = load_request(y)
    assert req.fire_height_m is None
    assert any("fire_height_m" in problem for problem in req.validate())


def test_demo_yaml_is_valid_complete_and_roundtrips():
    from pathlib import Path
    raw = Path("demo/demo_project.yaml").read_text(encoding="utf-8")
    req = load_request(raw)
    assert req.validate() == []
    assert req.source_data.tu_number == "DEMO-ТУ-01"
    assert req.source_data.maximum_head_m == 45.0
    assert req.consumers[0].count == 480
    assert req.total_area_m2 == 14400.0
    assert (req.risers_v1, req.risers_t3, req.risers_t4) == (8, 8, 8)
    assert req.insulation_humidity == 60
    assert all(x.repair_section_id for x in req.network.runs)
    assert load_request(dump_request(req)) == req
