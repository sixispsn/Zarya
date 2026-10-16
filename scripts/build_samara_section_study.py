"""Reproducible private control run; never deploys or changes production defaults.

PYTHONPATH=. NODE_BINARY=/path/to/node venv/bin/python scripts/build_samara_section_study.py
The basis contains separately identified drawing evidence and authorised study
assumptions. Authorised missing design inputs are assigned for this study only;
manufacturer evidence and release checks are never fabricated.
"""
from dataclasses import asdict, replace
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import subprocess
from xml.sax.saxutils import escape

from app.calc.water_meters import MeterInput, calculate_meters
from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.calc.water_local_losses import local_loss_factor
from app.calc.storm import StormInput, calculate_storm
from app.calc.fire_pump_station import CommonFireStation, StationSupply, calculate_common_fire_station
from app.calc.pump_curve import interpolate_head
from app.calc.fire_hydraulics import PipeSegment
from app.data.sp30_tables import CONSUMER_NORMS
from app.intake.studio_intake import answer_field, calculate_draft, build_handoff_request, accepted_values
from app.intake.project_builder import build_project
from app.intake.request_dto import RoomRequest, NetworkRequest, MainRunRequest, RiserRequest
from app.intake.yaml_io import dump_request_file
from app.intake.studio_project import calculate_project
from app.intake.studio_section import section_model
from app.pz.residential_concept_section import generate_concept_section_pdf
from app.pz.ios2_orchestrator import design_ios2
from app.pz.generator import merge_pdfs
from app.pz.fire_station_study_sheet import generate_fire_station_study_sheet

ROOT = Path(__file__).resolve().parents[1]
BASIS = ROOT / "demo/samara_section_3_2.basis.json"
OUTPUT = ROOT / "output/pdf/samara-section-3-2"


def load_basis():
    return json.loads(BASIS.read_text())


def make_draft(basis):
    a, r, u, derived = (basis[k] for k in (
        "study_assumptions", "read_from_drawings", "user_confirmed", "derived_for_study"))
    assert derived["apartments_total"] == r["apartments_first_floor"] + (a["residential_floors"]-1)*r["apartments_typical_floor"]
    draft = dict(revision=0, documents=[], answers={})
    s = basis["study_design_inputs"]
    values = dict(
        object_name="Жилой дом №2. Секция 3.2", building_purpose="residential",
        residents=a["residents"], apartments=derived["apartments_total"],
        consumer_code="residential_full_bath", floors=a["residential_floors"],
        building_height_m=derived["roof_relative_m"], floor_height_m=a["floor_to_floor_m"],
        basement_kind="basement", basement_floor_m=r["basement_floor_relative_m"],
        attic_kind="technical", roof_type=a["roof_kind"],
        hws_type="central", hws_heater_in_scope="yes", inputs_count=len(r["water_inlets"]),
        fire_topology="separate",
        guaranteed_head_m=u["guaranteed_pressure_head_m"], technology_presence="no",
        pressure_loss_mode="sections", t3_loss_mode="sections", storm_city="samara",
        storm_funnels_count=len(r["roof_funnel_labels"]), section_drainage="internal",
        fire_height_m=s["fire_technical_height_m"], fire_corridor_length_m=s["fire_corridor_length_m"],
        building_area_m2=s["building_area_m2"],
        h_geom_m=s["fixture_outlet_relative_m"]-derived["connection_pipe_axis_relative_m"],
        h_tepl_m=s["heater_design_pressure_loss_m"],
        apartment_design_residents=s["design_apartment_residents"],
        storm_roof_area_m2=s["roof_catchment_area_m2"], storm_walls_area_m2=s["adjacent_walls_area_m2"],
        storm_selected_riser_dn_mm=s["k2_riser_dn_mm"], storm_risers_count=s["k2_actual_risers"],
        section_funnel_heated="yes", storm_funnels_on_different_levels="no",
        section_fan_mode="common", section_fan_space="technical_storey",
        section_fan_member_ids=", ".join(s["representative_fan_members"]),
        section_fan_working_diameter_mm=100,
        section_fan_opening_distance_m=s["fan_opening_distance_m"],
        section_fan_plastic_exposed="yes", section_fan_uv_protected="yes",
        section_fan_collector_low_m=s["fan_collector_low_relative_m"],
        section_fan_collector_high_m=s["fan_collector_high_relative_m"],
        section_fan_space_floor_m=derived["technical_floor_relative_m"],
        section_fan_roof_level_m=derived["roof_relative_m"],
        section_fan_source_ref="3.2.pdf, лист 5: техэтаж. Характерная группа из 4 стояков; отметки, состав и отступы условно заданы для учебного прогона.",
    )
    for system in ("k1", "k2"):
        values.update({f"section_{system}_{key}": value for key, value in dict(
            dn_mm=s[f"{system}_main_dn_mm"], slope=s[f"{system}_main_slope"],
            outlet_invert_m=s[f"sewer_{system}_outlet_invert_relative_m"],
            discharge_point=s[f"{system}_receiver"], source_ref="Учебные проектные решения, 04.10.2026; подтвердить по АР/ТУ перед реальным выпуском.",
        ).items()})
    storm = calculate_storm(StormInput("samara", s["roof_catchment_area_m2"], s["adjacent_walls_area_m2"]))
    # All roof flow is explicitly routed to ONE declared riser, not split by
    # the number of schematic symbols or unverified catchments.
    values["storm_max_riser_flow_lps"] = storm.q_total_l_per_s
    for key, value in values.items():
        answer_field(draft, key, value)
    # Preserve the actual source and pressure datum outside fields unsupported
    # by Studio. No claim that the UI already carries this datum to its pump.
    draft["control_basis"] = basis
    demand = calculate_draft(draft)
    code = values["consumer_code"]
    riser = calculate_water_demand([ConsumerGroup(code, s["design_riser_residents"])])
    apartment = calculate_water_demand([ConsumerGroup(code, s["design_apartment_residents"])])
    v1, t3 = [], []
    for idx, row in enumerate(s["water_path"]):
        geometry = dict(length_m=row["length_m"], inner_diameter_mm=row["outer_mm"]-2*row["wall_mm"],
                        roughness_mm=row["roughness_mm"], material=row["material"])
        cold = (None, demand["cold"]["q_sec"], riser.cold.q_sec, apartment.cold.q_sec)[idx]
        v1.append(dict(section_id="В1-"+row["id"], role="input" if idx == 0 else "internal",
                       flow_lps=cold, **geometry))
        if idx:
            hot = (None, demand["hot"]["q_sec"], riser.hot.q_sec, apartment.hot.q_sec)[idx]
            circulation = {1:s["t3_main_circulation_input_lps"], 2:s["t3_riser_circulation_input_lps"]}.get(idx)
            t3.append(dict(section_id="Т3-"+row["id"], flow_lps=hot, **geometry,
                flow_mode="main" if circulation else "terminal", circulation_flow_lps=circulation,
                velocity_limit_mps=s["t3_velocity_limit_mps"], basis=s["circulation_note"]))
    # Feed from common inlet/meter to the building heater is part of the HOT
    # path. Common inlet loss is subsequently added once by head_paths.
    t3.insert(0, dict(t3[0], section_id="В1-к-водонагревателю", length_m=s["hot_feed_to_heater_length_m"],
        flow_mode="terminal", circulation_flow_lps=None, basis="Условный подвод В1 к ИТП; циркуляция ГВС через холодный подвод не проходит."))
    answer_field(draft, "v1_sections", v1)
    answer_field(draft, "t3_sections", t3)
    draft["calculation"] = calculate_draft(draft)
    return draft


def make_request(draft):
    """Same Studio handoff, enriched with the explicitly saved test basis."""
    req = build_handoff_request(draft)
    b = draft["control_basis"]
    s, a, d = (b[k] for k in ("study_design_inputs", "study_assumptions", "derived_for_study"))
    req.document.cipher = "ЗАРЯ-3.2"
    req.document.object_address = "г. Самара (учебные исходные)"
    req.document.object_part = "Секция 3.2"
    req.source_data.basis = "Контрольный прогон по 3.2.pdf и разрешённым учебным исходным от 04.10.2026; перечень допущений приложен."
    req.source_data.source_description = "Наружный водопровод; Hгар=30 м в точке подключения. Входные отметки и трасса условные, потери рассчитаны."
    req.source_data.connection_point = f"Условная точка подключения на оси {d['connection_pipe_axis_relative_m']:+.3f} м; не напор непосредственно перед насосом"
    req.source_data.maximum_head_m = s["maximum_external_head_m"]
    req.source_data.elev_header_m = d["connection_pipe_axis_relative_m"]
    req.source_data.elev_fixture_m = s["fixture_outlet_relative_m"]
    req.floor_elevations_m = {-1:b["read_from_drawings"]["basement_floor_relative_m"],
        **{floor:(floor-1)*a["floor_to_floor_m"] for floor in range(1, req.floors+1)}}
    req.apartments_by_floor = {floor:b["read_from_drawings"]["apartments_first_floor" if floor==1 else "apartments_typical_floor"]
                              for floor in range(1, req.floors+1)}
    req.wastewater_roof_relative_elevation_m = d["roof_relative_m"]
    req.wastewater_ground_relative_elevation_m = a["ground_at_connection_relative_m"]
    req.wastewater_first_manhole_cover_relative_elevation_m = s["sewer_receiver_cover_relative_m"]
    req.wastewater_frost_depth_m = b["user_confirmed"]["frost_depth_below_ground_m"]
    req.fire_topology = "separate"
    req.fire_topology_basis = "Учебное решение: самостоятельный В2, без совмещения с В1."
    req.fire_category = "residential_f13"
    req.rooms = [RoomRequest(f"Учебный коридор {floor} этажа", s["fire_corridor_length_m"], 2.5, 2.7)
                 for floor in range(1, req.floors+1)]
    z_source, z_ring, z_pk = s["fire_station"]["pump_axis_m"], -0.65, 46.35
    # Для этого учебного задания выбран согласованный процентный режим В2.
    # L_eq=k_l*L даёт ровно A*L*Q²*(1+k_l) в существующем решателе;
    # дополнительных местных сопротивлений поверх этого здесь не добавляем.
    fire_kl = local_loss_factor("fire")
    req.network = NetworkRequest(
        source_node="В2-НУ-Выход1", second_source_node="В2-НУ-Выход2",
        # Hydraulic header boundaries, not external city connections. The
        # explicit fire_station argument supplies their calculated common head.
        available_head_m=0.0, second_available_head_m=0.0,
        node_elevations={"В2-НУ-Выход1":z_source, "В2-НУ-Выход2":z_source, **{f"В2-У{i}":z_ring for i in range(1,5)}},
        runs=[MainRunRequest(src,dst,length,dn=100,A=0.0023,
                            equiv_length_m=fire_kl*length,repair_section_id=f"РС-{idx}")
              for idx,(src,dst,length) in enumerate([
                  ("В2-НУ-Выход1","В2-У1",20), ("В2-НУ-Выход2","В2-У3",20),
                  ("В2-У1","В2-У2",34), ("В2-У2","В2-У3",12),
                  ("В2-У3","В2-У4",34), ("В2-У4","В2-У1",12)],1)],
        risers=[RiserRequest(f"СТ-В2-{idx}",node,z_pk-z_ring,z_pk,dn=65,A=0.011,
                            equiv_length_m=fire_kl*(z_pk-z_ring),repair_section_id=f"РС-{2*idx+1}")
                for idx,node in enumerate(("В2-У1","В2-У3"),1)])
    req.metering_detail.room_number = "У-01"
    req.metering_detail.room_name = "Водомерная (учебное размещение)"
    req.metering_detail.room_location = "basement"
    req.metering_detail.room_min_temperature_c = 5.0
    req.metering_detail.service_access_confirmed = True
    req.metering_detail.inlet_dn = 100
    req.metering_detail.inlet_elevation_m = s["water_entry_axis_at_building_relative_m"]
    req.metering_detail.design_pressure_bar = 10.0
    req.metering_detail.water_temperature_c = 10.0
    req.wastewater_design_assignment_ref = "Учебное задание 04.10.2026: секция 3.2, допущения в приложении."
    req.wastewater_disposal_mode = "centralized"
    req.wastewater_discharge_point_k1 = s["k1_receiver"]
    req.wastewater_discharge_point_k2 = s["k2_receiver"]
    req.wastewater_laying_method = "Учебное решение: стояки в шахтах; магистрали подвешены под перекрытием подвала с уклоном 0,010, опуски к раздельным выпускам К1/К2."
    req.wastewater_external_network_design_note = "Наружные сети не проектируются; КК-1 и ДК-1 - условные граничные приёмники для теста."
    return req


def make_fire_station(basis):
    s = basis["study_design_inputs"]["fire_station"]
    kl = local_loss_factor("fire")
    return CommonFireStation(s["pump_axis_m"], tuple(
        StationSupply(f"Наружный ввод {i}",
            basis["derived_for_study"]["connection_pipe_axis_relative_m"],
            basis["user_confirmed"]["guaranteed_pressure_head_m"],
            basis["study_design_inputs"]["maximum_external_head_m"],
            (PipeSegment(f"В2-П{i}", f"Город-{i}", "Всасывающий коллектор",
                s["supply_length_m"], s["supply_A"],
                equiv_length_m=kl*s["supply_length_m"], diameter_mm=s["supply_dn"]),))
        for i in range(1, s["supply_count"]+1)), s["basis"])


def check_fire_pressure_scenarios(basis, bundle):
    """Diagnostic pairs on two representative risers at the legacy FIXED flow.

    Mixed-floor pairs are a sensitivity audit, not proof of plan coverage or
    predicted free discharge. The full-flow single external feed is conservative
    for MINIMUM pressure only. For maximum pressure we also show a no-feed-loss
    upper bound; we do not invent a split between the two external supplies.
    """
    station = make_fire_station(basis)
    ps = bundle.project.fire_pumps
    pump_head = interpolate_head(ps.curve, ps.q_design_m3h)
    if pump_head is None:
        raise ValueError("Pressure review needs a verified published pump curve")
    if any(s.maximum_head_m is None for s in station.supplies):
        raise ValueError("Pressure review needs the maximum head of every supply")
    maximum = replace(station, supplies=tuple(replace(s, guaranteed_head_m=s.maximum_head_m)
        for s in station.supplies))
    base = bundle.fire_station_result.network
    if len(base.cabinets) != 2 or len({c.riser_id for c in base.cabinets}) != 2:
        raise ValueError("Study pressure review requires two distinct representative risers")
    floors = range(1, basis["study_assumptions"]["residential_floors"]+1)
    height = basis["study_assumptions"]["floor_to_floor_m"]
    scenarios, rows = [], {}
    for floor1 in floors:
        for floor2 in floors:
            net = deepcopy(base)
            levels = dict(zip((c.cabinet_id for c in net.cabinets), (floor1,floor2)))
            for cab in net.cabinets:
                z = (levels[cab.cabinet_id]-1)*height+1.35
                net.nodes[cab.node_id].elevation_m = z
                terminal = [s for s in net.segments if s.to_node == cab.node_id]
                if len(terminal) != 1:
                    raise ValueError("Expected one explicit terminal riser segment")
                terminal[0].length_m = z-net.nodes[terminal[0].from_node].elevation_m
                terminal[0].equiv_length_m = local_loss_factor("fire")*terminal[0].length_m
            result = calculate_common_fire_station(net, maximum, 2)
            cabinets = []
            for c in result.hydraulic.dictating_scenario.cabinets:
                floor = levels[c.cabinet_id]
                z = (floor-1)*height+1.35
                losses = c.geodesic_lift_m+c.path_head_loss_m
                p_case = (result.minimum_suction_head_m+pump_head-losses)*.00980665
                p_bound = (result.maximum_static_suction_head_m+pump_head-losses)*.00980665
                p_static = (result.maximum_static_suction_head_m+max(h for _,h in ps.curve)
                            +station.pump_axis_m-z)*.00980665
                cabinets.append(dict(cabinet_id=c.cabinet_id, floor=floor,
                    pressure_case_mpa=p_case, pressure_upper_bound_mpa=p_bound))
                row = rows.setdefault(floor, dict(floor=floor, cabinet_elevation_m=z,
                    dynamic_pressure_mpa=p_case, dynamic_upper_bound_mpa=p_bound,
                    static_envelope_mpa=p_static))
                row["dynamic_pressure_mpa"] = max(row["dynamic_pressure_mpa"],p_case)
                row["dynamic_upper_bound_mpa"] = max(row["dynamic_upper_bound_mpa"],p_bound)
            scenarios.append(dict(floors=[floor1,floor2],
                fixed_total_flow_lps=result.hydraulic.dictating_scenario.total_flow_lps,
                required_header_head_m=result.hydraulic.required_head_at_source_m,
                cabinets=cabinets))
    for row in rows.values():
        row.update(pressure_control_required=row["dynamic_pressure_mpa"] > .45,
                   pressure_control_review_required=row["dynamic_upper_bound_mpa"] > .45,
                   independent_fire_static_ok=row["static_envelope_mpa"] <= .9)
    return dict(mode="fixed_flow_diagnostic_only", free_discharge_verified=False,
        regulatory_coverage_verified=False, scenario_count=len(scenarios),
        floors=[rows[f] for f in sorted(rows)], scenarios=scenarios)


def check_fire_floor_pressures(basis, bundle):
    return check_fire_pressure_scenarios(basis,bundle)["floors"]


def oracle(script, cases, node):
    result = subprocess.run([node, str(ROOT / "scripts" / script)], cwd=ROOT,
        input=json.dumps(dict(working_copy=True, cases=cases)), text=True,
        capture_output=True, check=True)
    return json.loads(result.stdout)


def run_checks(draft, node):
    demand = draft["calculation"]
    code = draft["answers"]["consumer_code"]["value"]
    ref = oracle("legacy_demand_reference.mjs", [[dict(label=CONSUMER_NORMS[code].label,
        count=draft["answers"]["residents"]["value"])]], node)
    for key in ("total", "cold", "hot"):
        for field in ("q_sec", "q_hr"):
            assert demand[key][field] == round(ref["cases"][0][key][field], 3), (key, field)
    # Reuse the established working-HTML oracle for the K1 calculation too.
    values = accepted_values(draft)
    rain_ref = json.loads(subprocess.run([node, str(ROOT / "scripts/legacy_rainwater_reference.mjs")],
        input=json.dumps(dict(cases=[dict(city="Самара", roof=values["storm_roof_area_m2"], walls=values["storm_walls_area_m2"])],
                             residents=[values["residents"]])), text=True, capture_output=True, check=True).stdout)
    assert demand["sewage_flow"] == rain_ref["residents"][0]["sewage_lps"]
    storm = section_model(values).storm.result
    assert storm.q_total_l_per_s == rain_ref["cases"][0]["flow_lps"]
    assert demand["total"]["q_day"] == draft["answers"]["residents"]["value"]*CONSUMER_NORMS[code].qu_tot/1000
    s = draft["control_basis"]["study_design_inputs"]
    counts = [s["design_riser_residents"], s["design_apartment_residents"]]
    branch_ref = oracle("legacy_demand_reference.mjs", [[dict(label=CONSUMER_NORMS[code].label, count=count)] for count in counts], node)
    for count, expected_branch in zip(counts, branch_ref["cases"], strict=True):
        result = calculate_water_demand([ConsumerGroup(code, count)])
        for key in ("cold", "hot"):
            assert getattr(result,key).q_sec == round(expected_branch[key]["q_sec"], 3)
    meter_input = MeterInput(hws_type="central", inputs_count=2,
        q_sec_tot=demand["total"]["q_sec"], q_sec_c=demand["cold"]["q_sec"], q_sec_h=demand["hot"]["q_sec"],
        q_day_tot=demand["total"]["q_day"], q_day_c=demand["cold"]["q_day"], q_day_h=demand["hot"]["q_day"],
        q_hr_c=demand["cold"]["q_hr"], q_hr_h=demand["hot"]["q_hr"])
    meters = calculate_meters(meter_input)
    meter_ref = oracle("legacy_meters_reference.mjs", [asdict(meter_input)], node)
    expected = meter_ref["cases"][0]["meters"]
    assert len(meters.meters) == len(expected)
    for actual, want in zip(meters.meters, expected, strict=True):
        assert actual.meter.d_mm == want["dn"]
        assert actual.h_normal == want["h_normal"]
        assert actual.pass_sensitivity is None  # Unknown passport minimum stays unknown.
    return dict(working_legacy_sha256=ref["source_sha256"], demand_parity=True, k1_parity=True,
        meter_parity=True, rain_parity=True, branch_parity=True, rain=asdict(storm), meters=asdict(meters),
        studio_preview_available=calculate_project(draft).get("can_preview",False))


def render_report(path, basis, draft, checks):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak
    pdfmetrics.registerFont(TTFont("ZaryaStudy", str(ROOT/"app/assets/fonts/OpenGOSTtypeB-Regular.ttf")))
    body = ParagraphStyle("body", fontName="ZaryaStudy", fontSize=11, leading=14, spaceAfter=7)
    title = ParagraphStyle("title", parent=body, fontSize=20, leading=24, spaceAfter=14)
    def p(text, style=body):
        return Paragraph(escape(text), style)
    def table(rows, widths):
        t = Table([[p(str(c)) for c in row] for row in rows], colWidths=[x*mm for x in widths], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#edf1f5")),
            ("GRID", (0,0), (-1,-1), .3, colors.HexColor("#b4bcc7")),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 7),
            ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 3)]))
        return t
    d = draft["calculation"]
    def n(value, places=3):
        return f"{value:.{places}f}".replace(".", ",")
    calculated = checks["project_calculation"]
    pressure_rows = calculated["fire_floor_pressures"]
    def floor_list(key):
        return ", ".join(str(r["floor"]) for r in pressure_rows if r[key]) or "нет"
    pressure_floors = floor_list("pressure_control_required")
    static_floors = ", ".join(str(r["floor"]) for r in pressure_rows if not r["independent_fire_static_ok"]) or "нет"
    s = basis["study_design_inputs"]
    story = [p("ЗАРЯ / исходные и допущения", title), p("Самара. Жилой дом №2, секция 3.2"),
        p("04.10.2026. Рабочий отчёт проверки генератора, не комплект для экспертизы. "
          "Исходные: 3.2.pdf, планы подвала, первого, типового и технического этажей."),
        table([("Исходное", "Значение / основание"),
            ("Этажность и жители", "16 жилых этажей по 3 м; 350 жителей - разрешённое учебное допущение"),
            ("Квартиры", "143 = 8 + 15 × 9; количество на этажах - по планам"),
            ("Отметки", "Подвал −3,250 - по чертежу. Первый этаж 0,000; последний +45,000; техэтаж +48,000; кровля +51,000 - условно"),
            ("Водоснабжение", "Два ввода по плану. ГВС от водонагревателя; приборная группа с ваннами - предварительно"),
            ("Гарантированный напор", "30 м в наружной точке подключения. Условная ось −2,195. Это не напор непосредственно перед насосом"),
        ], [46, 124]), Spacer(1, 10),
        table([("Поток", "л/с", "м³/ч", "м³/сут"),
            *[(label, n(d[key]["q_sec"]), n(d[key]["q_hr"]), n(d[key]["q_day"],1))
              for key, label in (("total","Общий"),("cold","ХВС"),("hot","ГВС"))]], [65,35,35,35]),
        Spacer(1, 8), p(f"К1: {n(d['sewage_flow'])} л/с. q₀s = 1,6 л/с. "
            f"Тепловая нагрузка ГВС: максимум {n(d['heat_max_kw'],1)} кВт; средняя {n(d['heat_avg_kw'],1)} кВт."),
        p("Расходы воды, К1 и предварительный подбор водомеров сверены с исполняемым рабочим legacy HTML. Расхождений в проверенных значениях нет. "
          "Секундные максимумы ХВС и ГВС не складываются для получения общего: он рассчитан отдельным блоком legacy."),
        p(f"К2: {n(checks['rain']['q_total_l_per_s'])} л/с; Самара, кровля 650 м², примыкающие стены 0 м², P=1 год. "
          "Площадь условная. Расход дождя также совпал с рабочим HTML."),
        PageBreak(), p("Принятые проектные исходные", title),
        table([("Параметр", "Принято для этого учебного прогона"),
            ("Пожарная высота", "46,350 м = 45,000 + 1,200 - (-0,150). Коридор 34 м; В2 раздельный от В1."),
            ("Диктующий прибор", "+46,000 м; Hгеом=48,195 м от наружной точки подключения; Hсвоб=20 м."),
            ("Теплообменник", "Допустимые потери 3 м - заданное требование для последующего подбора, не паспорт готового аппарата."),
            ("Циркуляция для Т3", "Условные входные 0,5 л/с для магистрали и 0,06 л/с для стояка; не рассчитанные кольца Т4."),
            ("Расходы ветвей", "Стояк на 48 жителей; расчётная квартира на 3 жителей. Их расходы рассчитаны отдельно рабочим алгоритмом, а не делением общего расхода."),
            ("К1 / К2 в подвале", "DN150, i=0,010 - назначенные параметры характерных магистралей, не автоматический гидравлический подбор."),
            ("Выпуски и приёмники", "К1: лоток -2,400, КК-1. К2: лоток -2,300, ДК-1. Крышки условных колодцев -0,150. Системы не соединяются."),
            ("Фановая вытяжка", "Типовая группа из 4 стояков DN100. Коллектор +49,500…+49,700 на техэтаже; открытый вывод над кровлей, без колпака. До окон условно 5 м; пластик защищён от УФ."),
            ("Воронки К2", "2 шт. по плану; один стояк DN100 получает весь сток. Достаточность воронок по паспорту остаётся отдельной проверкой."),
        ], [46,124]),
        PageBreak(), p("Расчётные пути и контроль", title),
        table([("Участок", "L, м", "Труба, мм", "Dвн, мм", "ε, мм"),
            *[(r["id"], n(r["length_m"],1), f"{r['outer_mm']:g} × {r['wall_mm']:g}",
               n(r["outer_mm"]-2*r["wall_mm"],1), n(r["roughness_mm"],2)) for r in s["water_path"]]], [50,23,37,32,28]),
        Spacer(1,8), p("Подвод - ПЭ; магистраль и стояк - сталь; квартирная ветвь - PE-X. "
            "В горячем пути дополнительно 5 м холодного подвода к ИТП. Местные потери В1/Т3: 30% линейных, без повторного умножения готовых сумм."),
        table([("Напор", "В1", "Т3"),
            ("Требуемый от точки подключения, м", n(calculated["heads"][0]["required_m"],2), n(calculated["heads"][1]["required_m"],2)),
            ("Добавка к Hгар=30 м, м", n(calculated["heads"][0]["pump_m"],2), n(calculated["heads"][1]["pump_m"],2))], [98,36,36]),
        Spacer(1,8), p(f"Предварительный кандидат В1/Т3: {calculated['pump']['model']}. "
            f"Расчётная пара: {n(calculated['pump']['q_design_m3h'],3)} м³/ч; {n(calculated['pump']['h_design_m'],2)} м. "
            "Каталожная кривая приведена в приложении. Пересечение с оценочной кривой сети не подменяет расчётную пару и регулирование."),
        p("Что этот комплект не подтверждает", title),
        p("Реальные АР/ТУ, паспортные минимумы водомеров, пропускную способность конкретной воронки, "
          "окончательный подбор теплообменника, NPSH, циркуляцию Т4 и балансировку. Объёмы труб нельзя получать из длины линий условного разреза; спецификация не является полной ведомостью объёмов."),
        p("В2: задана общая насосная с двумя наружными вводами и двумя выходами к кольцу. "
          "Hгар=30 м остаётся на отметке наружного подключения. Местные потери приняты 10% линейных "
          "(k_l из общего справочника); Lэфф=L×1,1. Рабочий и резервный агрегаты не суммируются."),
        p("Проверка состава выполнена встроенными аудитами: ИОС2 - ГОСТ Р 21.619-2023; баланс - п. 5.1.21, форма 2. "
          "ИОС3 - ГОСТ Р 21.620-2023, п. 5.1.3.3 и п. 5.2.2.4. Планы выполняются отдельно. "
          "Это полный прогон доступной PDF-выдачи на учебных исходных, не разрешение выпуска в экспертизу."),
    ]
    hyd = calculated["fire_hydraulics"]
    resilience = calculated["fire_resilience"]
    station, fp = calculated["fire_station"], calculated["fire_pump"]
    suction = station["minimum_suction_head_m"]
    catalog_head = interpolate_head(fp["curve"], fp["q_design_m3h"])
    story += [PageBreak(), p("В2 / общая пожарная насосная", title),
        p("Учебная компоновка: два наружных ввода по 20 м DN100 к общей насосной, ось -2,450. "
          "От напорного коллектора два плеча по 20 м к противоположным точкам кольца 34×12 м на отметке -0,650. "
          "Стояки DN65 до ПК +46,350. A=0,0023 / 0,011 - учебные входные сопротивления, не паспорт сортамента."),
        table([("Подвод к насосной", "Q, л/с", "Потери, м", "До насоса, м"),
            *[(row["name"], n(row["flow_lps"],1),n(row["loss_m"],3),n(row["suction_head_m"],3))
              for row in station["supplies"]]], [77,27,33,33]), Spacer(1,8),
        p(f"Каждый ввод проверен на полный расход 5,2 л/с (СП 10, п. 12.27 с изм. 1). "
          f"Hвсас=30+(-2,195)-(-2,450)-1,368={n(suction,3)} м. "
          "Разделение расхода между одновременно открытыми наружными вводами не моделируется."),
        table([("Режим", "Q, л/с", "Hтреб, м", "Дефицит, м"),
            ("Два выхода НУ к кольцу", n(hyd["dictating_scenario"]["total_flow_lps"],1),
             n(hyd["required_head_at_source_m"],2), n(hyd["required_head_at_source_m"]-suction,2)),
            *[("Закрыт выход НУ №"+str(i), n(hyd["dictating_scenario"]["total_flow_lps"],1),
               n(c["required_head_at_source_m"],2), n(c["required_head_at_source_m"]-c["available_head_m"],2))
              for i,c in enumerate(resilience["source_failure_cases"],1)]], [77,27,33,33]),
        Spacer(1,8), p("Hтреб в этой таблице относится к напорному коллектору на отметке оси насосов, "
          "не к городской сети. Дефицит - добавка насосом. Два выхода коллектора не означают два работающих насоса."),
        p(f"Кандидат: {fp['model']}. Qрасч={n(fp['q_design_m3h'],2)} м³/ч; "
          f"Hнас={n(fp['h_design_m'],2)} м; каталог при Qрасч: {n(catalog_head,2)} м. "
          "Состав: 1 рабочий + 1 резервный. Каталожная кривая и характеристики - в насосном приложении."),
        p(f"Худшее отключение ремонтной секции: после НУ требуется "
          f"{n(resilience['worst_case']['required_head_at_source_m'],2)} м, насосная добавка "
          f"{n(resilience['worst_case']['required_head_at_source_m']-suction,2)} м. "
          f"Запас каталога по напору: {n(suction+catalog_head-resilience['worst_case']['required_head_at_source_m'],2)} м. "
          "Подбор сделан по основному режиму; отказ проверен после подбора, без изменения потребности под каталог."),
        p("Каталожный кандидат перекрывает Q/H при заданном расходе, но не принят как готовое решение: "
          "проверка статического давления выявила превышение (следующий лист). NPSH, помещение, "
          "электроснабжение и автоматика также не подтверждены."),
        PageBreak(), p("В2 / давление по этажам", title),
        p(f"{calculated['fire_pressure_review']['scenario_count']} сочетаний этажей двух представительных стояков, "
          "строго по 2,6 л/с на ПК; Hmax=35 м. Это диагностика при заданном расходе, не свободный расход "
          "и не подтверждение покрытия помещений разновысотными ПК."),
        table([("Этаж", "ПК, м", "Один ввод, МПа", "Верх. граница, МПа", "Статика, МПа"),
            *[(r["floor"],n(r["cabinet_elevation_m"],2),n(r["dynamic_pressure_mpa"],3),
               n(r["dynamic_upper_bound_mpa"],3),n(r["static_envelope_mpa"],3))
              for r in pressure_rows]], [17,28,42,45,38]),
        p("«Один ввод»: наружный подвод несёт полный расход; при двух открытых вводах потери ниже. "
          "Верхняя граница: без вычитания потерь наружного подвода, при том же Q. Это огибающая, не точный режим двух вводов."),
        p(f"Давление более 0,45 МПа в проверенном режиме: этажи {pressure_floors}. "
          "П. 7.5: диафрагма/регулятор между пожарным клапаном и соединительной головкой. Настройки пока не рассчитаны."),
        p(f"Статическая огибающая выше 0,9 МПа: этажи {static_floors}. "
          "Без ограничения давления/зонирования решение не проходит п. 6.2.20 с изм. 1. "
          "Диафрагма при отсутствии расхода давление не снижает."),
        PageBreak(), p("В2 / сверка исходных и ограничения", title),
        p("Исправлен перенос данных, а не таблица или формулы legacy: диаметр отверстия ствола "
          "и высота компактной струи терялись при построении графа. Проверки только общего расхода этого не выявляли."),
        table([("Параметр ПК", "Прежний граф", "Анкета и новый граф"),
            ("DN клапана / ствол / рукав / струя", "50 / 16 мм / 20 м / 6 м", "50 / 13 мм / 20 м / 12 м"),
            ("Расход одного ПК", "2,6 л/с", "2,6 л/с"),
            ("Давление по таблице 7.3", "0,100 МПа", "0,210 МПа"),
            ("Требуемая добавка насосом", "34,293 м", n(fp['h_design_m'],3)+" м")], [63,49,58]), Spacer(1,10),
        p("Во всех 108 строках таблицы проверяется сохранение четырёх параметров от анкеты до ПК графа. "
          "Таблица дополнительно исполняется из рабочего HTML без поправок; архивный legacy не изменён."),
        p("Отдельный незакрытый вопрос: legacy принимает Q=n×q диктующего ПК, а текущий решатель задаёт "
          "расход каждому ПК независимо от его доступного давления. Пункт 7.6 СП 10 (с изм. 1) требует "
          "учитывать потери между одновременно работающими ПК. Перебор 256 сочетаний сам по себе "
          "не заменяет проверку неравных расходов или подтверждённых регулирующих устройств."),
        p("Отдельная методика L06 согласована 04.10.2026; её результаты вынесены в самостоятельное "
          "приложение «В2 - совместная работа ПК». Этот лист сохраняет фиксированные расходы для сравнения. "
          "Диаметры диафрагм, уставки регуляторов и окончательный насос в этом прогоне не утверждены. "
          "Прежний вывод о достаточности В2 при Hнас=34,29 м использовать нельзя."),
    ]
    def page(canvas, doc):
        canvas.setFont("ZaryaStudy", 9)
        canvas.drawString(20*mm, 12*mm, "Секция 3.2 / частный контрольный пример")
        canvas.drawRightString(190*mm, 12*mm, str(doc.page))
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
        topMargin=18*mm, bottomMargin=22*mm, title="ЗАРЯ - контроль секции 3.2").build(story, onFirstPage=page, onLaterPages=page)


def main():
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise RuntimeError("Set NODE_BINARY: working HTML parity is mandatory")
    basis = load_basis()
    draft = make_draft(basis)
    checks = run_checks(draft, node)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = Path(basis["source_pdf"])
    checks["source_pdf_sha256"] = sha256(source.read_bytes()).hexdigest()
    request = make_request(draft)
    dump_request_file(request, str(OUTPUT/"project-inputs.yaml"))
    project = build_project(request)
    project.document.review_notes = (
        "Учебные исходные заданы с разрешения пользователя. Перечень допущений приложен; перед реальным выпуском заменить данными АР/ТУ.",
        "Расчёт Т3 использует условные входные расходы циркуляции. Паспортные проверки оборудования не подменены допущениями.",
    )
    station = make_fire_station(basis)
    preflight = design_ios2(deepcopy(project), output_dir=str(OUTPUT/"documents"),
                           fire_station=station, render_documents=False)
    pressure_review = check_fire_pressure_scenarios(basis, preflight)
    floor_pressures = pressure_review["floors"]
    project.fire.pressure_at_lowest_pk_mpa = max(r["static_envelope_mpa"] for r in floor_pressures)
    station = replace(station, review_notes=(
        "В2: только предварительный каталожный кандидат при заданных расходах. "
        "Статическое давление превышает предел 0,9 МПа: требуются снижение давления/зонирование. "
        "Настройки, свободные расходы ПК, NPSH и строительные решения насосной не подтверждены; "
        "см. таблицу диагностики давления в контрольном приложении.",
    ))
    (OUTPUT/"fire-station-inputs.json").write_text(json.dumps(asdict(station), ensure_ascii=False, indent=2))
    bundle = design_ios2(project, output_dir=str(OUTPUT/"documents"), fire_station=station)
    project = bundle.project
    assert project.head_paths.complete
    assert all(p.head.km == .3 for p in project.head_paths.paths)
    checks["project_calculation"] = dict(
        heads=[dict(code=p.code, required_m=p.head.h_required_m, pump_m=p.head.h_pump_m,
                    components=p.head.components) for p in project.head_paths.paths],
        pump=asdict(project.pumps), fire=asdict(project.fire),
        fire_hydraulics=asdict(bundle.fire_hydraulic_result),
        fire_resilience=asdict(bundle.resilience_report),
        fire_pump=asdict(project.fire_pumps),
        fire_station=dict(pump_axis_m=bundle.fire_station_result.pump_axis_m,
            supplies=[asdict(x) for x in bundle.fire_station_result.supplies],
            minimum_suction_head_m=bundle.fire_station_result.minimum_suction_head_m,
            maximum_static_suction_head_m=bundle.fire_station_result.maximum_static_suction_head_m,
            basis=bundle.fire_station_result.basis),
        fire_floor_pressures=floor_pressures,
        fire_pressure_review=pressure_review,
        warnings=bundle.warnings, status=bundle.status,
        normative_audits=bundle.commission_report.normative_audits,
    )
    for name, obj in (("studio-draft.json", draft), ("check-results.json", checks)):
        (OUTPUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False))
    generate_concept_section_pdf(OUTPUT/"scheme-k1-k2.pdf", section_model({k:r["value"] for k,r in draft["answers"].items()}))
    render_report(OUTPUT/"control-report.pdf", basis, draft, checks)
    station_pdf = generate_fire_station_study_sheet(OUTPUT/"fire-station.pdf",project,bundle.fire_station_result)
    water = merge_pdfs([str(OUTPUT/"control-report.pdf"), *[x for x in (
        bundle.pz_pdf, bundle.scheme_pdf, bundle.metering_scheme_pdf,
        bundle.pump_zone_scheme_pdf, station_pdf, bundle.spec_pdf, bundle.hydraulic_pdf,
        bundle.resilience_pdf) if x]], str(OUTPUT/"ИОС2-секция-3.2.pdf"))
    sewer = merge_pdfs([str(OUTPUT/"control-report.pdf"), bundle.wastewater_package_pdf], str(OUTPUT/"ИОС3-секция-3.2.pdf"))
    print(json.dumps(dict(output=str(OUTPUT), parity=True, packages=[water,sewer],
        head_required=project.head_paths.governing.head.h_required_m,
        pump_head=project.head_paths.governing.head.h_pump_m), ensure_ascii=False))


if __name__ == "__main__":
    main()
