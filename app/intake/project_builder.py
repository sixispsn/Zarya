# -*- coding: utf-8 -*-
"""
app/intake/project_builder.py — Project Builder (слой 2 цепочки ввода).

ЕДИНСТВЕННОЕ место, где из намерения (IOS2Request) рождается Project.
Все входы (Wizard, YAML, Excel, IFC, REST, CLI) собирают IOS2Request,
Builder делает остальное. UI и форматы не знают модель Project вообще.

Builder:
  • маппит термины проектировщика в модель (residential → BuildingPurpose...);
  • разворачивает namespace сети (runs/risers → FireNetworkSpec);
  • НЕ считает (расчёт — в design_ios2) и НЕ выдумывает (чего нет — ошибка).
"""
from __future__ import annotations

from typing import List
from dataclasses import asdict
from app.calc.meter_verification import validate_meter_minimum_checks

from app.intake.project_intent import IntentLike, unwrap_project_intent
from app.intake.fire_applicability import calculate_request_fire
from app.pz.project import (
    Project, DocumentInfo, BuildingFlags, BuildingPurpose, FireSystem,
    PumpSystem, FlowsData, FireRoomSpec, FireNetworkSpec,
    MainNodeSpec, MainSegmentSpec, RiserSpec, V1SectionSpec,
    V1NodeSpec, V1NetworkSectionSpec, V1NetworkSpec, V1InletSpec,
    InsulationDesign, SewageRiserSpec, SewerPipeSpec, SewerElementSpec,
    SewerDischargeEventSpec, SewerFixtureSafetySpec,
    SewerBoundaryLevelSpec, SewerFirstManholeSpec,
    SewerInternalNodeSpec,
    HwsType,
)
from app.pz.normative import derive_requirements, decide_grease_trap, decide_storm_system


class RequestValidationError(ValueError):
    """Намерение не прошло валидацию — список проблем в args[0]."""
    def __init__(self, problems: List[str]):
        super().__init__("вход не пригоден для сборки Project:\n  - " +
                         "\n  - ".join(problems))
        self.problems = problems


_BUILDING_MAP = {
    "residential": BuildingPurpose.RESIDENTIAL,
    "public": BuildingPurpose.PUBLIC,
    "industrial": BuildingPurpose.INDUSTRIAL,
}


def _network_has_cycle(runs) -> bool:
    """Определить кольцевую разводку по явному неориентированному графу."""
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for run in runs:
        left = find(run.from_node)
        right = find(run.to_node)
        if left == right:
            return True
        parent[left] = right
    return False

def build_project(intent: IntentLike) -> Project:
    """ProjectIntent/IOS2Request → Project без изменения рабочего маппинга."""
    req = unwrap_project_intent(intent)
    problems = req.validate()
    if problems:
        raise RequestValidationError(problems)

    p = Project()
    from copy import deepcopy
    p.suction_check = deepcopy(req.suction_check)
    p.hws_stage_p = req.hws_stage_p  # immutable inputs; results are never persisted

    d = req.document
    p.document = DocumentInfo(
        cipher=d.cipher, object_name=d.object_name, object_address=d.object_address,
        object_part=d.object_part, stage=d.stage, organization=d.organization,
        developer_name=d.developer, inspector_name=d.inspector,
        dept_head_name=d.dept_head, gip_name=d.gip, norm_control_name=d.norm_control,
        sheet_no="1", sheet_total="1")

    p.building = BuildingFlags(
        purpose=_BUILDING_MAP[req.building_type],
        floors_above=req.floors, height_m=req.building_height_m,
        floors_below=req.floors_below,
        residents=req.residents,
        seismicity=req.seismicity, permafrost=req.permafrost,
        basement_clear_height_m=req.basement_clear_height_m,
        floor_elevations_m=dict(req.floor_elevations_m),
        apartments_by_floor=dict(req.apartments_by_floor),
        fire_height_m=req.fire_height_m, zones=req.zones,
        apartments=req.apartments,
        hws_type=HwsType(req.hws_type),
        total_area_m2=req.total_area_m2, risers_v1=req.risers_v1,
        risers_t3=req.risers_t3, risers_t4=req.risers_t4,
        v1_sectional_valves_count=req.v1_sectional_valves_count,
        v1_sectional_valves_basis=req.v1_sectional_valves_basis,
        water_service_layout=req.water_service_layout)
    p.insulation = InsulationDesign(
        location=req.insulation_location,
        t_room_manual=req.insulation_t_room_manual,
        humidity=req.insulation_humidity,
        hvs_water_temp=req.insulation_hvs_water_temp,
        gvs_water_temp=req.insulation_gvs_water_temp,
    )

    from app.pz.project import WaterSource
    sd = req.source_data
    p.apartment_water_units = req.apartment_water_units
    if req.metering_detail is not None:
        from dataclasses import replace
        from copy import deepcopy
        p.metering_detail = replace(req.metering_detail,
                                   mounting=deepcopy(req.metering_detail.mounting),
                                   enhancements=dict(req.metering_detail.enhancements),
                                   catalogue_items=dict(req.metering_detail.catalogue_items),
                                   meter_products=dict(req.metering_detail.meter_products),
                                   meter_orientations=dict(req.metering_detail.meter_orientations),
                                   connection_items=dict(req.metering_detail.connection_items),
                                   connection_thread_items=dict(req.metering_detail.connection_thread_items),
                                   reducer_items=dict(req.metering_detail.reducer_items),
                                   fitting_items=dict(req.metering_detail.fitting_items),
                                   pipe_sections=dict(req.metering_detail.pipe_sections))
    if sd is not None:
        p.source = WaterSource(
            description=(sd.source_description or sd.tu_org),
            water_protection_note=sd.water_protection_note,
            reserve_water_note=sd.reserve_water_note,
            connection_point=sd.connection_point,
            tu_number=sd.tu_number, tu_date=sd.tu_date,
            tu_org=sd.tu_org,
            guaranteed_head_m=sd.guaranteed_head_m,
            maximum_head_m=sd.maximum_head_m,
            pressure_note=sd.apartment_meter_basis,
            tu_limit_q_day=sd.tu_limit_q_day,
            tu_fire_outdoor_l_s=sd.tu_fire_outdoor_l_s,
            elev_header_m=sd.elev_header_m, elev_fixture_m=sd.elev_fixture_m,
            lowest_fixture_elevation_m=sd.lowest_fixture_elevation_m,
            lowest_fixture_basis=sd.lowest_fixture_basis,
            h_geom_m=sd.h_geom_m, il_dict_m=sd.il_dict_m, h_il_m=sd.h_il_m,
            internal_losses_scope=sd.internal_losses_scope, h_il_hot_m=sd.h_il_hot_m,
            network_kind=sd.network_kind, h_pr_m=sd.h_pr_m,
            h_tepl_m=sd.h_tepl_m, il_vvod_m=sd.il_vvod_m,
            h_apartment_c_meter_m=sd.h_apartment_c_meter_m,
            h_apartment_h_meter_m=sd.h_apartment_h_meter_m,
            hws_heater_in_scope=sd.hws_heater_in_scope,
            h_vvod_m=sd.h_vvod_m, water_use_period_h=sd.water_use_period_h,
            meter_minimum_checks={k: asdict(v) for k, v in validate_meter_minimum_checks(sd.meter_minimum_checks).items()},
            inputs_count=sd.inputs_count, npsh_available_m=sd.npsh_available_m,
            station_room_number=sd.station_room_number,
            station_floor_elevation_m=sd.station_floor_elevation_m,
            station_suction_elevation_m=sd.station_suction_elevation_m)

    if req.fire_mode == "not_required":
        p.fire = FireSystem(
            required=False,
            determination_mode="not_required",
            normative_note="ВПВ не требуется — решение подтверждено проектировщиком.",
            nozzle_dn=req.cabinet_dn,
            hose_length_m=req.hose_length_m,
            network_topology=req.fire_topology,
            topology_basis=req.fire_topology_basis,
            branch_electric_valves=req.fire_branch_electric_valves,
        )
    elif req.fire_mode == "manual":
        streams = int(req.streams or 0)
        p.fire = FireSystem(
            required=True,
            determination_mode="manual",
            normative_note="Параметры ВПВ заданы проектировщиком вручную.",
            streams=streams,
            q_per_stream=req.q_per_stream_lps,
            q_total=round(streams * req.q_per_stream_lps, 3),
            nozzle_dn=req.cabinet_dn,
            hose_length_m=req.hose_length_m,
            network_topology=req.fire_topology,
            topology_basis=req.fire_topology_basis,
            branch_electric_valves=req.fire_branch_electric_valves,
        )
    else:
        from app.pz.flows_bridge import fire_from_calc
        fire_result = calculate_request_fire(req)
        p.fire = fire_from_calc(
            fire_result,
            nozzle_dn=req.cabinet_dn,
            hose_length_m=req.hose_length_m,
        )
        p.fire.determination_mode = "auto"
        p.fire.normative_note = fire_result.message
        p.fire.network_topology = req.fire_topology
        p.fire.topology_basis = req.fire_topology_basis
        p.fire.branch_electric_valves = req.fire_branch_electric_valves

    # One table-7.3 key for the intake/PZ and hydraulic cabinets. This is data
    # binding, not a change to the legacy table or its flow/head calculation.
    p.fire.nozzle_mm = req.nozzle_mm

    # Без ВПВ система В1 не может оставаться «объединённой В1+В2».
    # Нормализуем старые анкеты, в которых combined был скрытым UI-дефолтом.
    from app.calc.water_local_losses import with_fire_topology
    if not p.fire.required and p.source.network_kind in {"combined", "industrial_fire"}:
        p.source.network_kind = with_fire_topology(p.source.network_kind, combined=False)
    elif p.fire.required:
        p.source.network_kind = with_fire_topology(
            p.source.network_kind, combined=p.fire.network_topology == "combined",
        )

    p.pumps = PumpSystem(required=req.needs_booster_pumps)
    p.flows = FlowsData()

    # Помещения/сеть В2 разворачиваются только если ВПВ действительно требуется.
    p.fire_rooms = [
        FireRoomSpec(r.name, length_m=r.length_m, width_m=r.width_m,
                     height_m=r.height_m, space_kind=r.space_kind,
                     placement_mode=r.placement)
        for r in req.rooms
    ] if p.fire.required else []

    # Common-station data is explicit and independent of the example project.
    fire_network = req.network
    if req.fire_station_model is not None and p.fire.required:
        from app.intake.studio_fire_station import parse_model
        parsed = parse_model(req.fire_station_model)
        fire_network = parsed.network
        p.fire_station_input = parsed.station
        p.fire_station_model_input = parsed.model

    # сеть В2: узлы собираются из участков (namespace runs), отметки из карты
    if fire_network is not None and p.fire.required:
        n = fire_network
        p.fire.ring_distribution = _network_has_cycle(n.runs)
        node_ids = sorted({x for r in n.runs for x in (r.from_node, r.to_node)})
        nodes = [MainNodeSpec(nid, float(n.node_elevations.get(nid, 0.0)))
                 for nid in node_ids]
        segments = [
            MainSegmentSpec(f"М{i+1}", r.from_node, r.to_node, length_m=r.length_m,
                            A=r.A, dn=r.dn, equiv_length_m=r.equiv_length_m,
                            repair_section_id=r.repair_section_id)
            for i, r in enumerate(n.runs)]
        risers = [
            RiserSpec(r.name, r.at_node, length_m=r.height_m,
                      cabinet_elevation_m=r.cabinet_elevation_m, A=r.A,
                      dn=r.dn, equiv_length_m=r.equiv_length_m,
                      jet_m=req.compact_jet_m,
                      repair_section_id=r.repair_section_id)
            for r in n.risers]
        p.fire_network = FireNetworkSpec(
            nodes=nodes, segments=segments, risers=risers,
            source_node=n.source_node, source_kind=n.source_kind,
            available_head_m=n.available_head_m, water_level_m=n.water_level_m,
            suction_head_loss_m=n.suction_head_loss_m,
            second_source_node=n.second_source_node,
            second_available_head_m=n.second_available_head_m)

    p.consumer_groups = [(g.code, g.count) for g in req.consumers]
    p.consumer_details = [(g.name, g.code, g.count) for g in req.consumers]
    p.v1_sections = [V1SectionSpec(**vars(s)) for s in req.v1_sections]
    p.t3_sections = list(req.t3_sections)
    if req.v1_network is not None:
        p.v1_network = V1NetworkSpec(
            source_node=req.v1_network.source_node,
            nodes=[V1NodeSpec(
                node_id=n.node_id,
                elevation_m=n.elevation_m,
                consumer_groups=[(g.code, g.count) for g in n.consumers],
                direct_demand_lps=n.direct_demand_lps,
                h_pr_m=n.h_pr_m,
                max_static_head_m=n.max_static_head_m,
            ) for n in req.v1_network.nodes],
            sections=[V1NetworkSectionSpec(**vars(s)) for s in req.v1_network.sections],
            inlets=[V1InletSpec(**vars(x)) for x in req.v1_network.inlets],
        )
        if req.v1_network.inlets:
            p.source.inputs_count = len(req.v1_network.inlets)
        # Топология является источником состава потребителей для общего расхода:
        # это исключает расхождение расхода водомера и корневого участка сети.
        counts = {}
        for node in req.v1_network.nodes:
            for group in node.consumers:
                counts[group.code] = counts.get(group.code, 0) + group.count
        if counts:
            p.consumer_groups = list(counts.items())
    p.sewage_max_fixture_lps = req.sewage_max_fixture_lps
    p.sewage.risers = [SewageRiserSpec(**vars(row)) for row in req.sewage_risers]
    p.sewage.pipes = [SewerPipeSpec(**vars(row)) for row in req.sewer_pipes]
    p.sewage.elements = [SewerElementSpec(**vars(row)) for row in req.sewer_elements]
    p.sewage.discharge_events = [
        SewerDischargeEventSpec(**vars(row))
        for row in req.sewer_discharge_events
    ]
    p.sewage.fixture_safety_inputs = [
        SewerFixtureSafetySpec(**vars(row))
        for row in req.sewer_fixture_safety_inputs
    ]
    p.sewage.first_manholes = [
        SewerFirstManholeSpec(
            manhole_id=row.manhole_id,
            outlet_section_id=row.outlet_section_id,
            invert_absolute_elevation_m=row.invert_absolute_elevation_m,
            levels=[
                SewerBoundaryLevelSpec(**vars(point))
                for point in row.levels
            ],
            source=row.source,
        )
        for row in req.sewer_first_manholes
    ]
    p.sewage.internal_nodes = [
        SewerInternalNodeSpec(
            node_id=row.node_id,
            downstream_section_id=row.downstream_section_id,
            upstream_section_ids=list(row.upstream_section_ids),
            invert_absolute_elevation_m=row.invert_absolute_elevation_m,
            overflow_absolute_elevation_m=row.overflow_absolute_elevation_m,
            storage_volume_m3=row.storage_volume_m3,
            overflow_location=row.overflow_location,
            source=row.source,
        )
        for row in req.sewer_internal_nodes
    ]
    p.sewage.transient_step_seconds = req.sewer_transient_step_seconds
    p.sewage.transient_duration_seconds = req.sewer_transient_duration_seconds
    p.sewage.outlets_count = req.sewage_outlets_count
    p.sewage.basement_floor_elevation_m = (
        req.wastewater_basement_floor_elevation_m
    )
    p.sewage.floor_height_m = req.wastewater_floor_height_m
    p.sewage.presentation = req.wastewater_presentation
    p.sewage.outlet_plan_side = req.wastewater_outlet_plan_side
    p.sewage.first_manhole_cover_relative_elevation_m = (
        req.wastewater_first_manhole_cover_relative_elevation_m
    )
    p.sewage.pipe_series_id = req.wastewater_pipe_series_id
    p.sewage.ground_relative_elevation_m = req.wastewater_ground_relative_elevation_m
    p.sewage.frost_depth_m = req.wastewater_frost_depth_m
    p.sewage.roof_kind = req.wastewater_roof_kind
    p.sewage.fan_ventilation = req.wastewater_fan_ventilation
    p.sewage.fan_geometry = req.wastewater_fan_geometry
    p.sewage.roof_relative_elevation_m = req.wastewater_roof_relative_elevation_m
    p.sewage.design_assignment_ref = req.wastewater_design_assignment_ref
    p.sewage.survey_ref = req.wastewater_survey_ref
    p.sewage.service_life_years = req.wastewater_service_life_years
    p.sewage.overhaul_period_years = req.wastewater_overhaul_period_years
    p.sewage.disposal_mode = req.wastewater_disposal_mode
    p.sewage.connection_tu_org = req.wastewater_tu_org
    p.sewage.connection_tu_number = req.wastewater_tu_number
    p.sewage.connection_tu_date = req.wastewater_tu_date
    p.sewage.discharge_standard_ref = req.wastewater_discharge_standard_ref
    p.sewage.water_body_characteristics_note = (
        req.wastewater_water_body_characteristics_note
    )
    p.sewage.existing_network_type = req.wastewater_existing_network_type
    p.sewage.existing_network_material = req.wastewater_existing_network_material
    p.sewage.existing_network_standard = req.wastewater_existing_network_standard
    p.sewage.existing_network_outer_diameter_mm = (
        req.wastewater_existing_network_outer_diameter_mm
    )
    p.sewage.existing_network_wall_thickness_mm = (
        req.wastewater_existing_network_wall_thickness_mm
    )
    p.sewage.discharge_point_k1 = req.wastewater_discharge_point_k1
    p.sewage.discharge_point_k2 = req.wastewater_discharge_point_k2
    p.sewage.discharge_point_k3 = req.wastewater_discharge_point_k3
    p.sewage.k1_min_hourly_m3h = req.wastewater_k1_min_hourly_m3h
    p.sewage.k3_max_hourly_m3h = req.wastewater_k3_max_hourly_m3h
    p.sewage.k3_min_hourly_m3h = req.wastewater_k3_min_hourly_m3h
    p.sewage.quality_indicators_note = req.wastewater_quality_indicators_note
    p.sewage.laying_method = req.wastewater_laying_method
    p.sewage.fire_barrier_note = req.wastewater_fire_barrier_note
    p.sewage.deformation_joint_note = req.wastewater_deformation_joint_note
    p.sewage.waste_handling_note = req.wastewater_waste_handling_note
    p.sewage.external_network_in_scope = req.wastewater_external_network_in_scope
    p.sewage.external_network_design_note = (
        req.wastewater_external_network_design_note
    )
    p.sewage.external_scheme_source = req.wastewater_external_scheme_source
    p.sewage.site_plan_source = req.wastewater_site_plan_source
    p.sewage.pump_required = req.wastewater_pump_required
    p.sewage.pump_location = req.wastewater_pump_location
    p.sewage.pump_model = req.wastewater_pump_model
    p.sewage.pump_q_m3h = req.wastewater_pump_q_m3h
    p.sewage.pump_head_m = req.wastewater_pump_head_m
    p.sewage.pump_power_kw = req.wastewater_pump_power_kw
    p.sewage.pump_reserve_note = req.wastewater_pump_reserve_note
    p.sewage.pump_power_category = req.wastewater_pump_power_category
    p.sewage.pump_automation_note = req.wastewater_pump_automation_note
    p.sewage.pump_system = req.wastewater_pump_system
    p.sewage.pump_mode = req.wastewater_pump_mode
    p.sewage.pump_fixture_count = req.wastewater_pump_fixture_count
    p.sewage.pump_static_head_m = req.wastewater_pump_static_head_m
    p.sewage.pump_dynamic_loss_m = req.wastewater_pump_dynamic_loss_m
    p.sewage.pump_curve = list(req.wastewater_pump_curve)
    p.sewage.pump_curve_source = req.wastewater_pump_curve_source
    p.sewage.pump_hydraulic_source = req.wastewater_pump_hydraulic_source
    p.sewage.pump_working_units = req.wastewater_pump_working_units
    p.sewage.pump_reserve_units = req.wastewater_pump_reserve_units
    p.sewage.pump_discharge_node = req.wastewater_pump_discharge_node
    p.sewage.pump_receiver_useful_volume_m3 = (
        req.wastewater_pump_receiver_useful_volume_m3
    )
    p.sewage.pump_emergency_volume_m3 = (
        req.wastewater_pump_emergency_volume_m3
    )
    p.sewage.pump_emergency_runtime_min = (
        req.wastewater_pump_emergency_runtime_min
    )
    p.sewage.pump_emergency_note = req.wastewater_pump_emergency_note
    p.sewage.treatment_required = req.wastewater_treatment_required
    p.sewage.treatment_location = req.wastewater_treatment_location
    p.sewage.treatment_type = req.wastewater_treatment_type
    p.sewage.treatment_capacity_lps = req.wastewater_treatment_capacity_lps
    p.sewage.treatment_capacity_m3_day = (
        req.wastewater_treatment_capacity_m3_day
    )
    p.sewage.treatment_technology = req.wastewater_treatment_technology
    p.storm_city = req.storm_city
    from copy import deepcopy
    p.rainwater_reuse = deepcopy(req.rainwater_reuse)
    p.wastewater_service = deepcopy(req.wastewater_service)
    p.storm = decide_storm_system(req.roof_type, req.floors)
    p.storm.city_code = req.storm_city
    p.storm.roof_area_m2 = req.storm_roof_area_m2
    p.storm.walls_area_m2 = req.storm_walls_area_m2
    p.storm.period_years = req.storm_period_years
    p.storm.roof_sections = req.storm_roof_sections
    p.storm.funnels_count = req.storm_funnels_count
    p.storm.sectional_residential_single_funnel = (
        req.storm_sectional_residential_single_funnel
    )
    p.storm.max_funnel_spacing_m = req.storm_max_funnel_spacing_m
    p.storm.selected_funnel_capacity_lps = (
        req.storm_selected_funnel_capacity_lps
    )
    p.storm.max_funnel_flow_lps = req.storm_max_funnel_flow_lps
    p.storm.risers_count = req.storm_risers_count
    p.storm.selected_riser_dn_mm = req.storm_selected_riser_dn_mm
    p.storm.max_riser_flow_lps = req.storm_max_riser_flow_lps
    p.storm.funnels_on_different_levels = (
        req.storm_funnels_on_different_levels
    )
    p.storm.design_m3_day = req.storm_design_m3_day
    p.storm.annual_m3 = req.storm_annual_m3
    p.storm.melt_m3h = req.storm_melt_m3h
    p.storm.melt_m3_day = req.storm_melt_m3_day
    p.storm.melt_m3_year = req.storm_melt_m3_year
    p.storm.treatment_volume_m3 = req.storm_treatment_volume_m3
    p.storm.storage_volume_m3 = req.storm_storage_volume_m3
    p.grease_trap = decide_grease_trap(
        req.catering_type,
        req.catering_seats,
        req.catering_conditional_dishes,
        req.school_grease_by_assignment,
    )
    p.normative = derive_requirements(
        p.building,
        [code for code, _ in p.consumer_groups],
        req.owner_groups_count,
    )
    p.building.separate_k1 = p.normative.separate_k1_required
    p.meters.owner_groups_count = req.owner_groups_count
    p.meters.has_apartment_meters = (
        p.building.purpose == BuildingPurpose.RESIDENTIAL
        and req.apartments > 0
    )
    p.pumps.frequency_drive_required = p.normative.frequency_drive_required
    p.pumps.dispatch_required = p.normative.pump_dispatch_required

    return p
