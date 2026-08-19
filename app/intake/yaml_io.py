# -*- coding: utf-8 -*-
"""
app/intake/yaml_io.py — YAML-вход/выход проекта (второй потребитель Builder'а).

    project.yaml  ──load_request──▶  IOS2Request  ──build_project──▶  Project
    IOS2Request   ──dump_request──▶  project.yaml   (сохранение/обмен/git)

YAML — человекочитаемое зеркало IOS2Request в терминах проектировщика.
Парсер НЕ знает Project (как и форма): собирает намерение, Builder делает
остальное. Этот же формат — основа персистентности проектов.

Пример файла:

    document:
      cipher: 2026-089-ИОС2
      object_name: Многоквартирный жилой дом, 16 этажей
      organization: ООО «ПроектСервис»
    building:
      type: residential
      floors: 16
      height_m: 48
      zones: 2
    fire:
      streams: 2
    rooms:
      - name: Коридор тип. этажа
        length_m: 42
        width_m: 2.4
        height_m: 3.0
        kind: corridor
        placement: two_opposite_sides
    network:
      source: {node: К1, kind: city_main, available_head_m: 32}
      runs:
        - {from: К1, to: К2, length_m: 36, dn: 100, equiv_length_m: 6}
      risers:
        - {name: СТ-В2-1, at: К1, height_m: 46.5, cabinet_elevation_m: 45.6}
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml

from app.intake.request_dto import (
    IOS2Request, DocumentRequest, RoomRequest, NetworkRequest,
    MainRunRequest, RiserRequest, SourceDataRequest, ConsumerGroupRequest,
    SewageRiserRequest, SewerPipeRequest, SewerElementRequest,
    SewerDischargeEventRequest,
)


class YamlFormatError(ValueError):
    """Файл не является валидным YAML-проектом Зари (структурные проблемы)."""
    def __init__(self, problems: List[str]):
        super().__init__("файл проекта не разобран:\n  - " + "\n  - ".join(problems))
        self.problems = problems


# ── YAML → IOS2Request ───────────────────────────────────────────────────────

def load_request(text: str) -> IOS2Request:
    """Разбирает YAML-текст проекта в IOS2Request.

    Структурные ошибки (не тот тип, нет секции) → YamlFormatError со списком.
    Смысловая валидация значений — как всегда, в req.validate()/Builder.
    """
    problems: List[str] = []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise YamlFormatError([f"синтаксис YAML: {e}"])
    if not isinstance(data, dict):
        raise YamlFormatError(["корень файла должен быть словарём (mapping)"])

    def sect(name: str, required: bool = True) -> Dict[str, Any]:
        s = data.get(name)
        if s is None:
            if required:
                problems.append(f"нет секции '{name}'")
            return {}
        if not isinstance(s, dict):
            problems.append(f"секция '{name}' должна быть словарём")
            return {}
        return s

    doc = sect("document")
    bld = sect("building")
    fire = sect("fire", required=False)
    source_data_s = sect("source_data", required=False)
    insulation_s = sect("insulation", required=False)
    sewage_s = sect("sewage", required=False)
    storm_s = sect("storm", required=False)
    catering_s = sect("catering", required=False)
    net_s = sect("network", required=False)
    rooms_s = data.get("rooms", [])
    if rooms_s is not None and not isinstance(rooms_s, list):
        problems.append("'rooms' должна быть списком")
        rooms_s = []

    if problems:
        raise YamlFormatError(problems)

    document = DocumentRequest(
        cipher=str(doc.get("cipher", "")),
        object_name=str(doc.get("object_name", "")),
        organization=str(doc.get("organization", "")),
        object_address=str(doc.get("object_address", "") or doc.get("address", "")),
        object_part=str(doc.get("object_part", "") or doc.get("part", "")),
        stage=str(doc.get("stage", "П")),
        developer=str(doc.get("developer", "")),
        inspector=str(doc.get("inspector", "")),
        dept_head=str(doc.get("dept_head", "")),
        gip=str(doc.get("gip", "")),
        norm_control=str(doc.get("norm_control", "")))

    rooms: List[RoomRequest] = []
    for i, r in enumerate(rooms_s or []):
        if not isinstance(r, dict):
            raise YamlFormatError([f"rooms[{i}] должен быть словарём"])
        rooms.append(RoomRequest(
            name=str(r.get("name", f"room_{i+1}")),
            length_m=float(r.get("length_m", 0)),
            width_m=float(r.get("width_m", 0)),
            height_m=float(r.get("height_m", 0)),
            space_kind=str(r.get("kind", r.get("space_kind", "corridor"))),
            placement=str(r.get("placement", "two_opposite_sides"))))

    network: Optional[NetworkRequest] = None
    if net_s:
        src = net_s.get("source", {}) or {}
        if not isinstance(src, dict):
            raise YamlFormatError(["network.source должен быть словарём"])
        runs_s = net_s.get("runs", []) or []
        risers_s = net_s.get("risers", []) or []
        if not isinstance(runs_s, list) or not isinstance(risers_s, list):
            raise YamlFormatError(["network.runs и network.risers должны быть списками"])
        runs = [MainRunRequest(
                    from_node=str(r.get("from", "")), to_node=str(r.get("to", "")),
                    length_m=float(r.get("length_m", 0)),
                    dn=int(r.get("dn", 100)),
                    equiv_length_m=float(r.get("equiv_length_m", 0)),
                    A=float(r.get("A", 0.0023)),
                    repair_section_id=str(r.get("repair_section_id", "")))
                for r in runs_s if isinstance(r, dict)]
        risers = [RiserRequest(
                      name=str(r.get("name", f"СТ-{i+1}")),
                      at_node=str(r.get("at", r.get("at_node", ""))),
                      height_m=float(r.get("height_m", 0)),
                      cabinet_elevation_m=float(r.get("cabinet_elevation_m", 0)),
                      dn=int(r.get("dn", 65)),
                      equiv_length_m=float(r.get("equiv_length_m", 0)),
                      A=float(r.get("A", 0.011)),
                      repair_section_id=str(r.get("repair_section_id", "")))
                  for i, r in enumerate(risers_s) if isinstance(r, dict)]
        network = NetworkRequest(
            runs=runs, risers=risers,
            source_node=str(src.get("node", "")),
            source_kind=str(src.get("kind", "city_main")),
            available_head_m=(float(src["available_head_m"])
                              if src.get("available_head_m") is not None else None),
            water_level_m=(float(src["water_level_m"])
                           if src.get("water_level_m") is not None else None),
            suction_head_loss_m=float(src.get("suction_head_loss_m", 0)),
            second_source_node=str((net_s.get("source2") or {}).get("node", "")),
            second_available_head_m=(float((net_s.get("source2") or {})["available_head_m"])
                                     if (net_s.get("source2") or {}).get("available_head_m")
                                     is not None else None),
            node_elevations={str(k): float(v) for k, v in
                             (net_s.get("node_elevations") or {}).items()})

    fire_streams = fire.get("streams")
    source_data = None
    if source_data_s:
        sd = source_data_s
        def optional_float(name):
            return float(sd[name]) if sd.get(name) is not None else None
        source_data = SourceDataRequest(
            customer=str(sd.get("customer", "")),
            designer_org=str(sd.get("designer_org", "")),
            basis=str(sd.get("basis", "")),
            design_stage=str(sd.get("design_stage", "Проектная документация (П)")),
            source_description=str(sd.get("source_description", "")),
            water_protection_note=str(sd.get("water_protection_note", "")),
            reserve_water_note=str(sd.get("reserve_water_note", "")),
            tu_org=str(sd.get("tu_org", "")), tu_number=str(sd.get("tu_number", "")),
            tu_date=str(sd.get("tu_date", "")),
            connection_point=str(sd.get("connection_point", "")),
            guaranteed_head_m=optional_float("guaranteed_head_m"),
            maximum_head_m=optional_float("maximum_head_m"),
            tu_limit_q_day=optional_float("tu_limit_q_day"),
            tu_fire_outdoor_l_s=optional_float("tu_fire_outdoor_l_s"),
            water_main_dn=int(sd.get("water_main_dn", 0)),
            elev_header_m=optional_float("elev_header_m"),
            elev_fixture_m=optional_float("elev_fixture_m"),
            h_geom_m=optional_float("h_geom_m"), il_dict_m=optional_float("il_dict_m"),
            h_il_m=optional_float("h_il_m"), network_kind=str(sd.get("network_kind", "domestic")),
            h_pr_m=float(sd.get("h_pr_m", 20.0)), h_tepl_m=float(sd.get("h_tepl_m", 0.0)),
            h_apartment_c_meter_m=optional_float("h_apartment_c_meter_m"),
            h_apartment_h_meter_m=optional_float("h_apartment_h_meter_m"),
            hws_heater_in_scope=bool(sd.get("hws_heater_in_scope", False)),
            il_vvod_m=optional_float("il_vvod_m"), h_vvod_m=optional_float("h_vvod_m"),
            water_use_period_h=float(sd.get("water_use_period_h", 24.0)),
            inputs_count=int(sd.get("inputs_count", 1)),
            npsh_available_m=optional_float("npsh_available_m"),
        )
    consumers = [ConsumerGroupRequest(
                    str(x.get("code", "")), int(x.get("count", 0)),
                    str(x.get("name", "")))
                 for x in (data.get("consumers") or []) if isinstance(x, dict)]
    sewage_risers = [
        SewageRiserRequest(
            riser_id=str(x.get("id", x.get("riser_id", ""))),
            design_flow_lps=float(x.get("design_flow_lps", 0)),
            material=str(x.get("material", "pp")),
            ventilation=str(x.get("ventilation", "ventilated")),
            riser_dn_mm=int(x.get("riser_dn_mm", 110)),
            branch_dn_mm=int(x.get("branch_dn_mm", 110)),
            branch_angle_deg=float(x.get("branch_angle_deg", 87.5)),
            has_toilet=bool(x.get("has_toilet", True)),
            working_height_m=(
                float(x["working_height_m"])
                if x.get("working_height_m") is not None else None
            ),
            inner_diameter_mm=(
                float(x["inner_diameter_mm"])
                if x.get("inner_diameter_mm") is not None else None
            ),
            branch_inner_diameter_mm=(
                float(x["branch_inner_diameter_mm"])
                if x.get("branch_inner_diameter_mm") is not None else None
            ),
            minimum_trap_seal_mm=(
                float(x["minimum_trap_seal_mm"])
                if x.get("minimum_trap_seal_mm") is not None else None
            ),
            pressure_input_source=str(x.get("pressure_input_source", "")),
            air_valve_free_area_mm2=(
                float(x["air_valve_free_area_mm2"])
                if x.get("air_valve_free_area_mm2") is not None else None
            ),
            air_valve_source=str(x.get("air_valve_source", "")),
        )
        for x in (sewage_s.get("risers") or [])
        if isinstance(x, dict)
    ]
    sewer_pipes = [
        SewerPipeRequest(
            system=str(x.get("system", "K1")),
            section_id=str(x.get("id", x.get("section_id", ""))),
            purpose=str(x.get("purpose", "")),
            material=str(x.get("material", "")),
            standard=str(x.get("standard", "")),
            outer_diameter_mm=float(x.get("outer_diameter_mm", 0)),
            wall_thickness_mm=float(x.get("wall_thickness_mm", 0)),
            length_m=float(x.get("length_m", 0)),
            calculation_length_m=(
                float(x["calculation_length_m"])
                if x.get("calculation_length_m") is not None else None
            ),
            nominal_diameter_mm=(
                int(x["nominal_diameter_mm"])
                if x.get("nominal_diameter_mm") is not None else None
            ),
            design_flow_lps=(
                float(x["design_flow_lps"])
                if x.get("design_flow_lps") is not None else None
            ),
            manning_n=(
                float(x["manning_n"])
                if x.get("manning_n") is not None else None
            ),
            hydraulic_source=str(x.get("hydraulic_source", "")),
            critical_velocity_mps=(
                float(x["critical_velocity_mps"])
                if x.get("critical_velocity_mps") is not None else None
            ),
            critical_velocity_source=str(
                x.get("critical_velocity_source", "")
            ),
            critical_fill_ratio=(
                float(x["critical_fill_ratio"])
                if x.get("critical_fill_ratio") is not None else None
            ),
            slope_per_mille=(
                float(x["slope_per_mille"])
                if x.get("slope_per_mille") is not None else None
            ),
            fill_ratio=(
                float(x["fill_ratio"])
                if x.get("fill_ratio") is not None else None
            ),
            from_node=str(x.get("from_node", "")),
            to_node=str(x.get("to_node", "")),
            room=str(x.get("room", "")),
            elevation_start_m=(
                float(x["elevation_start_m"])
                if x.get("elevation_start_m") is not None else None
            ),
            elevation_end_m=(
                float(x["elevation_end_m"])
                if x.get("elevation_end_m") is not None else None
            ),
            absolute_elevation_start_m=(
                float(x["absolute_elevation_start_m"])
                if x.get("absolute_elevation_start_m") is not None else None
            ),
            absolute_elevation_end_m=(
                float(x["absolute_elevation_end_m"])
                if x.get("absolute_elevation_end_m") is not None else None
            ),
            insulated=bool(x.get("insulated", False)),
        )
        for x in (sewage_s.get("pipes") or [])
        if isinstance(x, dict)
    ]
    sewer_elements = [
        SewerElementRequest(
            element_id=str(x.get("id", x.get("element_id", ""))),
            system=str(x.get("system", "K1")),
            kind=str(x.get("kind", "other")),
            name=str(x.get("name", "")),
            quantity=int(x.get("quantity", 1)),
            typical_quantity=(
                int(x["typical_quantity"])
                if x.get("typical_quantity") is not None else None
            ),
            floor_from=int(x.get("floor_from", 1)),
            floor_to=(
                int(x["floor_to"])
                if x.get("floor_to") is not None else None
            ),
            room_number=str(x.get("room_number", "")),
            room_name=str(x.get("room_name", "")),
            elevation_m=(
                float(x["elevation_m"])
                if x.get("elevation_m") is not None else None
            ),
            dn_mm=(int(x["dn_mm"]) if x.get("dn_mm") is not None else None),
            slope_per_mille=(
                float(x["slope_per_mille"])
                if x.get("slope_per_mille") is not None else None
            ),
            section_id=str(x.get("section_id", "")),
            connects_to=str(x.get("connects_to", "")),
            type_mark=str(x.get("type_mark", "")),
            standard=str(x.get("standard", "")),
            manufacturer=str(x.get("manufacturer", "по проекту")),
            unit=str(x.get("unit", "шт.")),
            include_in_spec=bool(x.get("include_in_spec", True)),
            note=str(x.get("note", "")),
            layout_column=int(x.get("layout_column", 0)),
            service_direction=str(x.get("service_direction", "")),
            service_fitting=str(x.get("service_fitting", "")),
            accessible=bool(x.get("accessible", True)),
            service_chainage_m=(
                float(x["service_chainage_m"])
                if x.get("service_chainage_m") is not None else None
            ),
        )
        for x in (sewage_s.get("elements") or [])
        if isinstance(x, dict)
    ]
    sewer_discharge_events = [
        SewerDischargeEventRequest(
            event_id=str(x.get("id", x.get("event_id", ""))),
            fixture_id=str(x.get("fixture_id", "")),
            floor=int(x.get("floor", 1)),
            instance_no=int(x.get("instance_no", 1)),
            start_seconds=float(x.get("start_seconds", 0)),
            duration_seconds=float(x.get("duration_seconds", 0)),
            flow_lps=float(x.get("flow_lps", 0)),
            source=str(x.get("source", "")),
            suspended_solids_mg_l=(
                float(x["suspended_solids_mg_l"])
                if x.get("suspended_solids_mg_l") is not None else None
            ),
            suspended_solids_source=str(
                x.get("suspended_solids_source", "")
            ),
        )
        for x in (sewage_s.get("discharge_events") or [])
        if isinstance(x, dict)
    ]
    return IOS2Request(
        document=document,
        building_type=str(bld.get("type", "residential")),
        floors=int(bld.get("floors", 0)),
        building_height_m=float(bld.get("height_m", 0)),
        total_area_m2=float(bld.get("total_area_m2", 0)),
        hws_type=str(bld.get("hws_type", "central")),
        risers_v1=int(bld.get("risers_v1", 0)),
        risers_t3=int(bld.get("risers_t3", 0)),
        risers_t4=int(bld.get("risers_t4", 0)),
        apartments=int(bld.get("apartments", 0)),
        owner_groups_count=int(bld.get("owner_groups_count", 1)),
        insulation_location=str(insulation_s.get("location", "room_hot")),
        insulation_t_room_manual=float(insulation_s.get("t_room_manual", 5.0)),
        insulation_humidity=int(insulation_s.get("humidity", 60)),
        insulation_hvs_water_temp=float(insulation_s.get("hvs_water_temp", 10.0)),
        insulation_gvs_water_temp=float(insulation_s.get("gvs_water_temp", 60.0)),
        fire_mode=str(fire.get("mode", "auto")),
        fire_height_m=(
            float(fire["height_m"])
            if fire.get("height_m") is not None else None
        ),
        fire_category=str(fire.get("category", "")),
        fire_hall_seats=(
            int(fire["hall_seats"])
            if fire.get("hall_seats") is not None else None
        ),
        fire_area_m2=(
            float(fire["area_m2"])
            if fire.get("area_m2") is not None else None
        ),
        # Наличие геометрии в YAML/импорте уже является явным действием.
        # Wizard передаёт отдельный checkbox и не пользуется этим fallback.
        fire_geometry_confirmed=bool(
            fire.get("geometry_confirmed", bool(rooms or network is not None))
        ),
        streams=(int(fire_streams) if fire_streams is not None else None),
        q_per_stream_lps=float(fire.get("q_per_stream_lps", 2.6)),
        hose_length_m=int(fire.get("hose_length_m", 20)),
        cabinet_dn=int(fire.get("cabinet_dn", 50)),
        nozzle_mm=int(fire.get("nozzle_mm", 13)),
        compact_jet_m=int(fire.get("compact_jet_m", 12)),
        fire_topology=str(fire.get("topology", "auto")),
        fire_topology_basis=str(fire.get("topology_basis", "")),
        fire_branch_electric_valves=bool(fire.get("branch_electric_valves", False)),
        roof_type=str(storm_s.get("roof_type", "not_set")),
        storm_city=str(storm_s.get("city", "")),
        storm_roof_area_m2=float(storm_s.get("roof_area_m2", 0)),
        storm_walls_area_m2=float(storm_s.get("walls_area_m2", 0)),
        storm_period_years=int(storm_s.get("period_years", 1)),
        storm_roof_sections=int(storm_s.get("roof_sections", 0)),
        storm_funnels_count=int(storm_s.get("funnels_count", 0)),
        storm_sectional_residential_single_funnel=bool(
            storm_s.get("sectional_residential_single_funnel", False)
        ),
        storm_max_funnel_spacing_m=(
            float(storm_s["max_funnel_spacing_m"])
            if storm_s.get("max_funnel_spacing_m") is not None else None
        ),
        storm_selected_funnel_capacity_lps=(
            float(storm_s["selected_funnel_capacity_lps"])
            if storm_s.get("selected_funnel_capacity_lps") is not None else None
        ),
        storm_max_funnel_flow_lps=(
            float(storm_s["max_funnel_flow_lps"])
            if storm_s.get("max_funnel_flow_lps") is not None else None
        ),
        storm_risers_count=int(storm_s.get("risers_count", 0)),
        storm_selected_riser_dn_mm=int(
            storm_s.get("selected_riser_dn_mm", 0)
        ),
        storm_max_riser_flow_lps=(
            float(storm_s["max_riser_flow_lps"])
            if storm_s.get("max_riser_flow_lps") is not None else None
        ),
        storm_funnels_on_different_levels=bool(
            storm_s.get("funnels_on_different_levels", False)
        ),
        storm_design_m3_day=(
            float(storm_s["design_m3_day"])
            if storm_s.get("design_m3_day") is not None else None
        ),
        storm_annual_m3=(
            float(storm_s["annual_m3"])
            if storm_s.get("annual_m3") is not None else None
        ),
        storm_melt_m3h=(
            float(storm_s["melt_m3h"])
            if storm_s.get("melt_m3h") is not None else None
        ),
        storm_melt_m3_day=(
            float(storm_s["melt_m3_day"])
            if storm_s.get("melt_m3_day") is not None else None
        ),
        storm_melt_m3_year=(
            float(storm_s["melt_m3_year"])
            if storm_s.get("melt_m3_year") is not None else None
        ),
        storm_treatment_volume_m3=(
            float(storm_s["treatment_volume_m3"])
            if storm_s.get("treatment_volume_m3") is not None else None
        ),
        storm_storage_volume_m3=(
            float(storm_s["storage_volume_m3"])
            if storm_s.get("storage_volume_m3") is not None else None
        ),
        sewage_max_fixture_lps=float(sewage_s.get("max_fixture_lps", 1.6)),
        sewage_risers=sewage_risers,
        sewer_pipes=sewer_pipes,
        sewer_elements=sewer_elements,
        sewer_discharge_events=sewer_discharge_events,
        sewer_transient_step_seconds=(
            float(sewage_s["transient_step_seconds"])
            if sewage_s.get("transient_step_seconds") is not None else None
        ),
        sewer_transient_duration_seconds=(
            float(sewage_s["transient_duration_seconds"])
            if sewage_s.get("transient_duration_seconds") is not None else None
        ),
        sewage_outlets_count=int(sewage_s.get("outlets_count", 0)),
        wastewater_design_assignment_ref=str(
            sewage_s.get("design_assignment_ref", "")
        ),
        wastewater_survey_ref=str(sewage_s.get("survey_ref", "")),
        wastewater_service_life_years=(
            int(sewage_s["service_life_years"])
            if sewage_s.get("service_life_years") is not None else None
        ),
        wastewater_overhaul_period_years=(
            int(sewage_s["overhaul_period_years"])
            if sewage_s.get("overhaul_period_years") is not None else None
        ),
        wastewater_disposal_mode=str(sewage_s.get("disposal_mode", "not_set")),
        wastewater_tu_org=str(sewage_s.get("tu_org", "")),
        wastewater_tu_number=str(sewage_s.get("tu_number", "")),
        wastewater_tu_date=str(sewage_s.get("tu_date", "")),
        wastewater_discharge_standard_ref=str(
            sewage_s.get("discharge_standard_ref", "")
        ),
        wastewater_water_body_characteristics_note=str(
            sewage_s.get("water_body_characteristics_note", "")
        ),
        wastewater_existing_network_type=str(
            sewage_s.get("existing_network_type", "")
        ),
        wastewater_existing_network_material=str(
            sewage_s.get("existing_network_material", "")
        ),
        wastewater_existing_network_standard=str(
            sewage_s.get("existing_network_standard", "")
        ),
        wastewater_existing_network_outer_diameter_mm=(
            float(sewage_s["existing_network_outer_diameter_mm"])
            if sewage_s.get("existing_network_outer_diameter_mm") is not None else None
        ),
        wastewater_existing_network_wall_thickness_mm=(
            float(sewage_s["existing_network_wall_thickness_mm"])
            if sewage_s.get("existing_network_wall_thickness_mm") is not None else None
        ),
        wastewater_discharge_point_k1=str(
            sewage_s.get("discharge_point_k1", "")
        ),
        wastewater_discharge_point_k2=str(
            sewage_s.get("discharge_point_k2", "")
        ),
        wastewater_discharge_point_k3=str(
            sewage_s.get("discharge_point_k3", "")
        ),
        wastewater_k1_min_hourly_m3h=(
            float(sewage_s["k1_min_hourly_m3h"])
            if sewage_s.get("k1_min_hourly_m3h") is not None else None
        ),
        wastewater_k3_max_hourly_m3h=(
            float(sewage_s["k3_max_hourly_m3h"])
            if sewage_s.get("k3_max_hourly_m3h") is not None else None
        ),
        wastewater_k3_min_hourly_m3h=(
            float(sewage_s["k3_min_hourly_m3h"])
            if sewage_s.get("k3_min_hourly_m3h") is not None else None
        ),
        wastewater_quality_indicators_note=str(
            sewage_s.get("quality_indicators_note", "")
        ),
        wastewater_laying_method=str(sewage_s.get("laying_method", "")),
        wastewater_fire_barrier_note=str(
            sewage_s.get("fire_barrier_note", "")
        ),
        wastewater_deformation_joint_note=str(
            sewage_s.get("deformation_joint_note", "")
        ),
        wastewater_waste_handling_note=str(
            sewage_s.get("waste_handling_note", "")
        ),
        wastewater_external_network_in_scope=bool(
            sewage_s.get("external_network_in_scope", False)
        ),
        wastewater_external_network_design_note=str(
            sewage_s.get("external_network_design_note", "")
        ),
        wastewater_external_scheme_source=str(
            sewage_s.get("external_scheme_source", "")
        ),
        wastewater_site_plan_source=str(sewage_s.get("site_plan_source", "")),
        wastewater_pump_required=bool(sewage_s.get("pump_required", False)),
        wastewater_pump_location=str(sewage_s.get("pump_location", "")),
        wastewater_pump_model=str(sewage_s.get("pump_model", "")),
        wastewater_pump_q_m3h=(
            float(sewage_s["pump_q_m3h"])
            if sewage_s.get("pump_q_m3h") is not None else None
        ),
        wastewater_pump_head_m=(
            float(sewage_s["pump_head_m"])
            if sewage_s.get("pump_head_m") is not None else None
        ),
        wastewater_pump_power_kw=(
            float(sewage_s["pump_power_kw"])
            if sewage_s.get("pump_power_kw") is not None else None
        ),
        wastewater_pump_reserve_note=str(
            sewage_s.get("pump_reserve_note", "")
        ),
        wastewater_pump_power_category=str(
            sewage_s.get("pump_power_category", "")
        ),
        wastewater_pump_automation_note=str(
            sewage_s.get("pump_automation_note", "")
        ),
        wastewater_treatment_required=bool(
            sewage_s.get("treatment_required", False)
        ),
        wastewater_treatment_location=str(
            sewage_s.get("treatment_location", "")
        ),
        wastewater_treatment_type=str(sewage_s.get("treatment_type", "")),
        wastewater_treatment_capacity_lps=(
            float(sewage_s["treatment_capacity_lps"])
            if sewage_s.get("treatment_capacity_lps") is not None else None
        ),
        wastewater_treatment_capacity_m3_day=(
            float(sewage_s["treatment_capacity_m3_day"])
            if sewage_s.get("treatment_capacity_m3_day") is not None else None
        ),
        wastewater_treatment_technology=str(
            sewage_s.get("treatment_technology", "")
        ),
        catering_type=str(catering_s.get("type", "none")),
        catering_seats=int(catering_s.get("seats", 0)),
        catering_conditional_dishes=int(catering_s.get("conditional_dishes", 0)),
        school_grease_by_assignment=bool(
            catering_s.get("school_grease_by_assignment", False)
        ),
        zones=int(bld.get("zones", 1)),
        rooms=rooms, network=network, source_data=source_data, consumers=consumers)


def load_request_file(path: str) -> IOS2Request:
    with open(path, encoding="utf-8") as f:
        return load_request(f.read())


# ── IOS2Request → YAML ───────────────────────────────────────────────────────

def dump_request(req: IOS2Request) -> str:
    """Сериализует намерение обратно в YAML (сохранение/обмен/git).
    Гарантия: load_request(dump_request(x)) эквивалентен x (round-trip)."""
    d = req.document
    data: Dict[str, Any] = {
        "document": {
            "cipher": d.cipher, "object_name": d.object_name,
            "organization": d.organization,
            **({"object_address": d.object_address} if d.object_address else {}),
            **({"object_part": d.object_part} if d.object_part else {}),
            "stage": d.stage,
            **({"developer": d.developer} if d.developer else {}),
            **({"inspector": d.inspector} if d.inspector else {}),
            **({"dept_head": d.dept_head} if d.dept_head else {}),
            **({"gip": d.gip} if d.gip else {}),
            **({"norm_control": d.norm_control} if d.norm_control else {}),
        },
        "building": {
            "type": req.building_type, "floors": req.floors,
            "height_m": req.building_height_m, "zones": req.zones,
            "hws_type": req.hws_type,
            "total_area_m2": req.total_area_m2,
            "risers_v1": req.risers_v1,
            "risers_t3": req.risers_t3,
            "risers_t4": req.risers_t4,
            "apartments": req.apartments,
            "owner_groups_count": req.owner_groups_count,
        },
        "fire": {
            "mode": req.fire_mode,
            **({"height_m": req.fire_height_m} if req.fire_height_m is not None else {}),
            **({"category": req.fire_category} if req.fire_category else {}),
            **({"hall_seats": req.fire_hall_seats}
               if req.fire_hall_seats is not None else {}),
            **({"area_m2": req.fire_area_m2}
               if req.fire_area_m2 is not None else {}),
            "geometry_confirmed": req.fire_geometry_confirmed,
            **({"streams": req.streams} if req.streams is not None else {}),
            "q_per_stream_lps": req.q_per_stream_lps,
            "hose_length_m": req.hose_length_m,
            "cabinet_dn": req.cabinet_dn,
            "nozzle_mm": req.nozzle_mm,
            "compact_jet_m": req.compact_jet_m,
            "topology": req.fire_topology,
            **({"topology_basis": req.fire_topology_basis}
               if req.fire_topology_basis else {}),
            "branch_electric_valves": req.fire_branch_electric_valves,
        },
        "insulation": {
            "location": req.insulation_location,
            "t_room_manual": req.insulation_t_room_manual,
            "humidity": req.insulation_humidity,
            "hvs_water_temp": req.insulation_hvs_water_temp,
            "gvs_water_temp": req.insulation_gvs_water_temp,
        },
        "storm": {
            "roof_type": req.roof_type,
            "city": req.storm_city,
            "roof_area_m2": req.storm_roof_area_m2,
            "walls_area_m2": req.storm_walls_area_m2,
            "period_years": req.storm_period_years,
            "roof_sections": req.storm_roof_sections,
            "funnels_count": req.storm_funnels_count,
            "sectional_residential_single_funnel":
                req.storm_sectional_residential_single_funnel,
            "max_funnel_spacing_m": req.storm_max_funnel_spacing_m,
            "selected_funnel_capacity_lps":
                req.storm_selected_funnel_capacity_lps,
            "max_funnel_flow_lps": req.storm_max_funnel_flow_lps,
            "risers_count": req.storm_risers_count,
            "selected_riser_dn_mm": req.storm_selected_riser_dn_mm,
            "max_riser_flow_lps": req.storm_max_riser_flow_lps,
            "funnels_on_different_levels":
                req.storm_funnels_on_different_levels,
            "design_m3_day": req.storm_design_m3_day,
            "annual_m3": req.storm_annual_m3,
            "melt_m3h": req.storm_melt_m3h,
            "melt_m3_day": req.storm_melt_m3_day,
            "melt_m3_year": req.storm_melt_m3_year,
            "treatment_volume_m3": req.storm_treatment_volume_m3,
            "storage_volume_m3": req.storm_storage_volume_m3,
        },
        "sewage": {
            "max_fixture_lps": req.sewage_max_fixture_lps,
            "outlets_count": req.sewage_outlets_count,
            "risers": [{
                "id": x.riser_id,
                "design_flow_lps": x.design_flow_lps,
                "material": x.material,
                "ventilation": x.ventilation,
                "riser_dn_mm": x.riser_dn_mm,
                "branch_dn_mm": x.branch_dn_mm,
                "branch_angle_deg": x.branch_angle_deg,
                "has_toilet": x.has_toilet,
                "working_height_m": x.working_height_m,
                "inner_diameter_mm": x.inner_diameter_mm,
                "branch_inner_diameter_mm": x.branch_inner_diameter_mm,
                "minimum_trap_seal_mm": x.minimum_trap_seal_mm,
                "pressure_input_source": x.pressure_input_source,
                "air_valve_free_area_mm2": x.air_valve_free_area_mm2,
                "air_valve_source": x.air_valve_source,
            } for x in req.sewage_risers],
            "pipes": [{
                "system": x.system,
                "id": x.section_id,
                "purpose": x.purpose,
                "material": x.material,
                "standard": x.standard,
                "outer_diameter_mm": x.outer_diameter_mm,
                "wall_thickness_mm": x.wall_thickness_mm,
                "length_m": x.length_m,
                **({"calculation_length_m": x.calculation_length_m}
                   if x.calculation_length_m is not None else {}),
                **({"nominal_diameter_mm": x.nominal_diameter_mm}
                   if x.nominal_diameter_mm is not None else {}),
                **({"design_flow_lps": x.design_flow_lps}
                   if x.design_flow_lps is not None else {}),
                **({"manning_n": x.manning_n}
                   if x.manning_n is not None else {}),
                **({"hydraulic_source": x.hydraulic_source}
                   if x.hydraulic_source else {}),
                **({"critical_velocity_mps": x.critical_velocity_mps}
                   if x.critical_velocity_mps is not None else {}),
                **({"critical_velocity_source": x.critical_velocity_source}
                   if x.critical_velocity_source else {}),
                **({"critical_fill_ratio": x.critical_fill_ratio}
                   if x.critical_fill_ratio is not None else {}),
                **({"slope_per_mille": x.slope_per_mille}
                   if x.slope_per_mille is not None else {}),
                **({"fill_ratio": x.fill_ratio}
                   if x.fill_ratio is not None else {}),
                **({"from_node": x.from_node} if x.from_node else {}),
                **({"to_node": x.to_node} if x.to_node else {}),
                **({"room": x.room} if x.room else {}),
                **({"elevation_start_m": x.elevation_start_m}
                   if x.elevation_start_m is not None else {}),
                **({"elevation_end_m": x.elevation_end_m}
                   if x.elevation_end_m is not None else {}),
                **({"absolute_elevation_start_m": x.absolute_elevation_start_m}
                   if x.absolute_elevation_start_m is not None else {}),
                **({"absolute_elevation_end_m": x.absolute_elevation_end_m}
                   if x.absolute_elevation_end_m is not None else {}),
                "insulated": x.insulated,
            } for x in req.sewer_pipes],
            "elements": [{
                "id": x.element_id,
                "system": x.system,
                "kind": x.kind,
                "name": x.name,
                "quantity": x.quantity,
                **({"typical_quantity": x.typical_quantity}
                   if x.typical_quantity is not None else {}),
                "floor_from": x.floor_from,
                **({"floor_to": x.floor_to} if x.floor_to is not None else {}),
                **({"room_number": x.room_number} if x.room_number else {}),
                **({"room_name": x.room_name} if x.room_name else {}),
                **({"elevation_m": x.elevation_m}
                   if x.elevation_m is not None else {}),
                **({"dn_mm": x.dn_mm} if x.dn_mm is not None else {}),
                **({"slope_per_mille": x.slope_per_mille}
                   if x.slope_per_mille is not None else {}),
                **({"section_id": x.section_id} if x.section_id else {}),
                **({"connects_to": x.connects_to} if x.connects_to else {}),
                **({"type_mark": x.type_mark} if x.type_mark else {}),
                **({"standard": x.standard} if x.standard else {}),
                "manufacturer": x.manufacturer,
                "unit": x.unit,
                "include_in_spec": x.include_in_spec,
                **({"note": x.note} if x.note else {}),
                **({"layout_column": x.layout_column}
                   if x.layout_column else {}),
                **({"service_direction": x.service_direction}
                   if x.service_direction else {}),
                **({"service_fitting": x.service_fitting}
                   if x.service_fitting else {}),
                "accessible": x.accessible,
                **({"service_chainage_m": x.service_chainage_m}
                   if x.service_chainage_m is not None else {}),
            } for x in req.sewer_elements],
            "transient_step_seconds": req.sewer_transient_step_seconds,
            "transient_duration_seconds": req.sewer_transient_duration_seconds,
            "discharge_events": [{
                "id": x.event_id,
                "fixture_id": x.fixture_id,
                "floor": x.floor,
                "instance_no": x.instance_no,
                "start_seconds": x.start_seconds,
                "duration_seconds": x.duration_seconds,
                "flow_lps": x.flow_lps,
                "source": x.source,
                **({"suspended_solids_mg_l": x.suspended_solids_mg_l}
                   if x.suspended_solids_mg_l is not None else {}),
                **({"suspended_solids_source": x.suspended_solids_source}
                   if x.suspended_solids_source else {}),
            } for x in req.sewer_discharge_events],
            "design_assignment_ref": req.wastewater_design_assignment_ref,
            "survey_ref": req.wastewater_survey_ref,
            "service_life_years": req.wastewater_service_life_years,
            "overhaul_period_years": req.wastewater_overhaul_period_years,
            "disposal_mode": req.wastewater_disposal_mode,
            "tu_org": req.wastewater_tu_org,
            "tu_number": req.wastewater_tu_number,
            "tu_date": req.wastewater_tu_date,
            "discharge_standard_ref": req.wastewater_discharge_standard_ref,
            "water_body_characteristics_note": req.wastewater_water_body_characteristics_note,
            "existing_network_type": req.wastewater_existing_network_type,
            "existing_network_material": req.wastewater_existing_network_material,
            "existing_network_standard": req.wastewater_existing_network_standard,
            "existing_network_outer_diameter_mm": req.wastewater_existing_network_outer_diameter_mm,
            "existing_network_wall_thickness_mm": req.wastewater_existing_network_wall_thickness_mm,
            "discharge_point_k1": req.wastewater_discharge_point_k1,
            "discharge_point_k2": req.wastewater_discharge_point_k2,
            "discharge_point_k3": req.wastewater_discharge_point_k3,
            "k1_min_hourly_m3h": req.wastewater_k1_min_hourly_m3h,
            "k3_max_hourly_m3h": req.wastewater_k3_max_hourly_m3h,
            "k3_min_hourly_m3h": req.wastewater_k3_min_hourly_m3h,
            "quality_indicators_note": req.wastewater_quality_indicators_note,
            "laying_method": req.wastewater_laying_method,
            "fire_barrier_note": req.wastewater_fire_barrier_note,
            "deformation_joint_note": req.wastewater_deformation_joint_note,
            "waste_handling_note": req.wastewater_waste_handling_note,
            "external_network_in_scope": req.wastewater_external_network_in_scope,
            "external_network_design_note": req.wastewater_external_network_design_note,
            "external_scheme_source": req.wastewater_external_scheme_source,
            "site_plan_source": req.wastewater_site_plan_source,
            "pump_required": req.wastewater_pump_required,
            "pump_location": req.wastewater_pump_location,
            "pump_model": req.wastewater_pump_model,
            "pump_q_m3h": req.wastewater_pump_q_m3h,
            "pump_head_m": req.wastewater_pump_head_m,
            "pump_power_kw": req.wastewater_pump_power_kw,
            "pump_reserve_note": req.wastewater_pump_reserve_note,
            "pump_power_category": req.wastewater_pump_power_category,
            "pump_automation_note": req.wastewater_pump_automation_note,
            "treatment_required": req.wastewater_treatment_required,
            "treatment_location": req.wastewater_treatment_location,
            "treatment_type": req.wastewater_treatment_type,
            "treatment_capacity_lps": req.wastewater_treatment_capacity_lps,
            "treatment_capacity_m3_day": req.wastewater_treatment_capacity_m3_day,
            "treatment_technology": req.wastewater_treatment_technology,
        },
        "catering": {
            "type": req.catering_type,
            "seats": req.catering_seats,
            "conditional_dishes": req.catering_conditional_dishes,
            "school_grease_by_assignment": req.school_grease_by_assignment,
        },
    }
    if req.source_data is not None:
        sd = req.source_data
        data["source_data"] = {
            key: value for key, value in vars(sd).items()
            if value not in (None, "")
        }
    if req.consumers:
        data["consumers"] = [{
            **({"name": x.name} if x.name else {}),
            "code": x.code,
            "count": x.count,
        } for x in req.consumers]
    if req.rooms:
        data["rooms"] = [{
            "name": r.name, "length_m": r.length_m, "width_m": r.width_m,
            "height_m": r.height_m, "kind": r.space_kind, "placement": r.placement,
        } for r in req.rooms]
    if req.network is not None:
        n = req.network
        src: Dict[str, Any] = {"node": n.source_node, "kind": n.source_kind}
        if n.available_head_m is not None:
            src["available_head_m"] = n.available_head_m
        if n.water_level_m is not None:
            src["water_level_m"] = n.water_level_m
        if n.suction_head_loss_m:
            src["suction_head_loss_m"] = n.suction_head_loss_m
        s2: Dict[str, Any] = {}
        if n.second_source_node:
            s2 = {"node": n.second_source_node}
            if n.second_available_head_m is not None:
                s2["available_head_m"] = n.second_available_head_m
        data["network"] = {
            "source": src,
            **({"source2": s2} if s2 else {}),
            "runs": [{"from": r.from_node, "to": r.to_node, "length_m": r.length_m,
                      "dn": r.dn, "equiv_length_m": r.equiv_length_m, "A": r.A,
                      **({"repair_section_id": r.repair_section_id}
                         if r.repair_section_id else {})}
                     for r in n.runs],
            "risers": [{"name": r.name, "at": r.at_node, "height_m": r.height_m,
                        "cabinet_elevation_m": r.cabinet_elevation_m,
                        "dn": r.dn, "equiv_length_m": r.equiv_length_m, "A": r.A,
                        **({"repair_section_id": r.repair_section_id}
                           if r.repair_section_id else {})}
                       for r in n.risers],
            **({"node_elevations": n.node_elevations} if n.node_elevations else {}),
        }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)


def dump_request_file(req: IOS2Request, path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump_request(req))
    return path
