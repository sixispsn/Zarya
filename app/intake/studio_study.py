"""Explicit, private educational cases. Never a fallback for missing project AR.

The stored template snapshot plus accepted answers are the sole input to the
screen, schematic and IOS3 text. Fixed layout strategies remain bounded to the
two reviewed houses; this is not automatic plan recognition.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from app.calc.storm import StormInput
from app.intake.request_dto import ConsumerGroupRequest, DocumentRequest, IOS2Request
from app.intake.studio_intake import IntakeError, accepted_values, answer_field, calculate_draft
from app.intake.yaml_io import load_request

ROOT = Path(__file__).resolve().parents[2]
EDITABLE = frozenset({"residents", "storm_city", "storm_roof_area_m2", "roof_type"})
TITLES = {"two": "2 этажа · 8 квартир", "three": "3 этажа · 12 квартир",
          "samara": "Самара · секция 3.2 · 16 этажей"}


def initialize_study(draft: dict, kind: str, return_id: str | None) -> None:
    if kind == "samara":
        from app.intake.samara_study import initialize
        initialize(draft, return_id)
        return
    if kind not in TITLES:
        raise IntakeError("Выберите двух- или трёхэтажный учебный пример.")
    if kind == "two":
        snapshot = (ROOT / "demo/residential_2floors_8apartments.yaml").read_text()
        count, area, floors = 20, 252, 2
        description = "Подвал −3,100 м; кровля +6,600 м, неэксплуатируемая; 4 воронки."
    else:
        snapshot = json.loads((ROOT / "demo/residential_3floors_accessible_roof.json").read_text())
        count, area, floors = snapshot["residents"], snapshot["roof_area_m2"], 3
        description = "Техподполье 1,5 м, неотапливаемое; кровля +10,500 м, эксплуатируемая; 2 водосбора."
    for key, value in dict(residents=count, floors=floors, apartments=floors*4,
                           consumer_code="residential_full_bath", hws_type="central",
                           roof_type="flat_non_accessible" if kind == "two" else "flat_accessible",
                           storm_city="moscow", storm_roof_area_m2=area,
                           storm_walls_area_m2=0, object_name="Учебный пример — "+TITLES[kind]).items():
        answer_field(draft, key, value)
        draft["answers"][key]["source"]["kind"] = "educational_template"
    draft["study"] = {"kind": kind, "title": TITLES[kind], "description": description,
                      "version": 1, "snapshot": snapshot, "return_id": return_id}
    draft["calculation"] = calculate_draft(draft)
    draft["project_calculation"] = calculate_study(draft)


def public_study(draft: dict) -> dict | None:
    study = draft.get("study")
    if not study:
        return None
    return {key: study[key] for key in ("kind", "title", "description", "version")}


def build_study(draft: dict):
    from app.architecture.residential_section_case import residential_section_case_from_mapping
    from app.pz.small_residential_calculation import calculate_residential_study
    from app.pz.small_residential_preview import build_small_residential_preview
    from app.pz.wastewater_basement_profile import basement_profile_from_request

    study, values = draft["study"], accepted_values(draft)
    if any(key not in values for key in EDITABLE):
        raise IntakeError("Для учебного примера нужны жители, город, площадь и вид кровли.")
    expected_floors = 2 if study["kind"] == "two" else 3
    for key, value in {"floors": expected_floors, "apartments": expected_floors*4,
                       "consumer_code": "residential_full_bath", "hws_type": "central",
                       "storm_walls_area_m2": 0,
                       "sewage_max_fixture_lps": 1.6}.items():
        if values.get(key) != value:
            raise IntakeError("Исходные не соответствуют выбранной учебной компоновке. Выберите другой пример.")
    expected_roof = "flat_non_accessible" if study["kind"] == "two" else "flat_accessible"
    if values["roof_type"] == "flat":
        raise IntakeError("Уточните эксплуатацию плоской кровли в списке, чтобы обновить учебные документы.")
    if values["roof_type"] != expected_roof:
        raise IntakeError("Выбор кровли сохранён. Для этого вида нужна новая геометрия кровли и фановых выводов: выбранная учебная схема её пока не поддерживает. Верните исходный вид кровли или выберите другой пример; прежний PDF отозван.")
    storm_input = StormInput(values["storm_city"], values["storm_roof_area_m2"])
    if study["kind"] == "two":
        req = load_request(study["snapshot"])
        model = build_small_residential_preview(
            req, basement=basement_profile_from_request(
                req, proposed_invert_m=-2.2, preview_dn_mm=100,
                proposed_invert_basis="Учебное предложение по исходному примеру, не отметка ТУ."),
            source_ref="Учебная компоновка по ранее согласованным планам; не распознавание загруженного PDF.",
            proposed_shafts=4, branch_outer_mm=50, stack_outer_mm=110, include_roof=True)
        calculation = calculate_residential_study(model, residents=values["residents"], storm_input=storm_input)
        water, storm = calculation.water, calculation.storm
        funnels = 4
    else:
        data = deepcopy(study["snapshot"])
        data.update(residents=values["residents"], city=values["storm_city"], roof_area_m2=values["storm_roof_area_m2"])
        data["roof_catchments_m2"] = [data["roof_area_m2"]/len(data["roof_catchments_m2"])]*len(data["roof_catchments_m2"])
        model = residential_section_case_from_mapping(data)
        calculation = None
        water, storm = model.calculate()
        funnels = len(model.catchments)
        req = IOS2Request(
            document=DocumentRequest("", "", ""), building_height_m=0,
            floors=3, apartments=12, floors_below=1, building_type="residential",
            basement_clear_height_m=model.subfloor_clear_m,
            floor_elevations_m={-1: model.subfloor_m, **model.floor_levels},
            apartments_by_floor={floor: 4 for floor in model.floor_levels},
            wastewater_basement_floor_elevation_m=model.subfloor_m,
            wastewater_roof_kind="flat_accessible", wastewater_roof_relative_elevation_m=model.roof_m,
            wastewater_design_assignment_ref="Учебная компоновка по ранее согласованному плану. " + " ".join(model.assumptions),
        )
    req.document = DocumentRequest("", "Учебный пример — "+study["title"], "")
    req.residents = values["residents"]
    req.hws_type = "central"
    req.consumers = [ConsumerGroupRequest(code="residential_full_bath", count=req.residents)]
    req.roof_type = "flat"
    req.storm_city, req.storm_roof_area_m2 = values["storm_city"], values["storm_roof_area_m2"]
    req.storm_walls_area_m2, req.storm_period_years = 0, 1
    req.storm_funnels_count = req.storm_risers_count = funnels
    req.fire_geometry_confirmed = False
    req.wastewater_design_assignment_ref = (
        "УЧЕБНЫЙ ПРИМЕР. Не проект для выпуска. " + study["description"]
        + " Число жителей, город и площадь кровли берутся из текущей версии Studio. "
        + "Ванна ≥1500 мм, централизованное ГВС. К1 — PP HT, К2 — SML. "
        + "Уклоны, длины коллекторов, водосборы и трассы — учебные предложения. "
        + "Подключение к наружным сетям, абсолютные отметки, ТУ и доступ для обслуживания не подтверждены."
    )
    if calculation is not None:
        profiles = (calculation.basement.k1, calculation.rain_profile)
        fan_note = "4 отдельных фановых вывода К1, открытые устья на 0,200 м выше кровли."
    else:
        profiles = (model.k1.profile, model.k2.profile)
        fan_note = "4 стояка К1 объединены над кровлей в ограждённой технической зоне; открытое устье на 3,000 м выше кровли. Трасса по квартирам не проходит."
    req.wastewater_laying_method = (
        "УЧЕБНОЕ ПРЕДЛОЖЕНИЕ. По 4 квартиры на этаже: кухня, санузел; мойка, ванна, умывальник и унитаз. "
        "К1 и К2 раздельно, коллекторы под перекрытием; опуски перед выпусками. "
        + " ".join(f"{p.system}: L={p.length_m:g} м, i={p.slope:g}; лоток {p.start_invert_m:.3f} → {p.end_invert_m:.3f} м." for p in profiles)
        + " " + fan_note + " Реальные трассы, окна, УФ-защита и доступ уточняются по АР."
    )
    takeoff_hash = None
    if calculation is not None:
        from app.pz.small_residential_takeoff import educational_residential_takeoff
        takeoff_hash = educational_residential_takeoff(model, calculation).fingerprint
    fingerprint = hashlib.sha256(json.dumps({"version": study["version"], "kind": study["kind"],
        "snapshot": study["snapshot"], "answers": values, "takeoff_hash": takeoff_hash},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if asdict(water) != calculate_draft(draft):
        raise IntakeError("Расходы схемы и Studio разошлись. Экспорт остановлен.")
    return req, model, calculation, water, storm, fingerprint


def calculate_study(draft: dict) -> dict:
    if draft.get('study', {}).get('kind') == 'samara':
        from app.intake.samara_study import calculate
        return calculate(draft)
    try:
        _, _, _, water, storm, fingerprint = build_study(draft)
    except (ValueError, IntakeError) as exc:
        return {"state": "blocked", "can_preview": False, "can_release": False,
                "issues": [{"message": str(exc)}]}
    return {"state": "study", "can_preview": True, "can_release": False,
            "model_hash": fingerprint, "storm": asdict(storm),
            "sewer_scheme": {"ready": True, "reasons": []}, "sewage_lps": water.sewage_flow}


def verify_legacy(water, storm, residents: int) -> tuple[str, str]:
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        raise IntakeError("Для проверки legacy перед экспортом нужен Node.js на сервере.")
    result = subprocess.run([node, str(ROOT / "scripts/legacy_rainwater_reference.mjs")],
        input=json.dumps({"residents": [residents], "cases": [{"city": storm.city.name,
            "roof": storm.f_calculated_m2, "walls": 0, "period": 1}]}),
        text=True, capture_output=True, check=True, timeout=30)
    ref = json.loads(result.stdout)
    r, w = ref["cases"][0], ref["residents"][0]
    if ((storm.q_total_l_per_s, storm.q5, storm.f_calculated_m2) != (r["flow_lps"], r["q5"], r["area"])
        or (water.total.q_sec, water.total.q_hr, water.sewage_flow) != (w["total_lps"], w["hourly_m3"], w["sewage_lps"])):
        raise IntakeError("Расчёт расходится с legacy. Экспорт остановлен; эталон не изменён.")
    return node, ref["rain_sha256"]


def render_study(draft: dict, folder: Path) -> tuple[list[dict], str]:
    if draft.get('study', {}).get('kind') == 'samara':
        from app.intake.samara_study import render
        return render(draft, folder)
    from app.pz.generator import (generate_wastewater_pz_pdf, generate_wastewater_balance_pdf,
                                  generate_wastewater_calculation_pdf, append_pdf)
    from app.pz.residential_case_section import generate_residential_case_pdf
    from app.pz.small_residential_section import generate_small_residential_section_pdf
    from app.pz.small_residential_calculation_pdf import generate_residential_calculation_pdf

    req, model, calculation, water, storm, fingerprint = build_study(draft)
    node, source_hash = verify_legacy(water, storm, req.residents)
    project = study_ios3_project(req, water, storm)
    if (project.flows.sewage_l_per_s != water.sewage_flow or project.flows.q_day_tot != water.total.q_day
            or project.storm.result != storm):
        raise IntakeError("Расчёт ПЗ и схемы разошёлся; экспорт остановлен.")
    folder.mkdir(parents=True, exist_ok=True)
    scheme = folder / "Схема_К1_К2.pdf"
    if calculation is not None:
        generate_small_residential_section_pdf(str(scheme), model, calculation=calculation, compact_demo=True)
        generate_residential_calculation_pdf(str(folder / "Расчёт_учебной_модели.pdf"), model, calculation,
                                             rain_source_sha256=source_hash)
        from app.pz.network_takeoff_pdf import generate_network_takeoff_pdf
        from app.pz.small_residential_takeoff import educational_residential_takeoff
        takeoff = educational_residential_takeoff(model, calculation)
        generate_network_takeoff_pdf(str(folder / "Объёмы_сети_К1_К2.pdf"), takeoff)
        (folder / "Объёмы_сети_К1_К2.json").write_text(json.dumps({
            "network": asdict(takeoff), "rows": [asdict(r) for r in takeoff.rows()],
            "network_hash": takeoff.fingerprint, "model_hash": fingerprint, "purchase_ready": False,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        generate_residential_case_pdf(scheme, model, node=node, root=ROOT)
    pz = generate_wastewater_pz_pdf(project, str(folder / "ПЗ_ИОС3.pdf"))
    report = generate_wastewater_calculation_pdf(project, str(folder / "Расчёты_К1_К2.pdf"))
    balance = generate_wastewater_balance_pdf(project, str(folder / "Баланс_ИОС3.pdf"))
    append_pdf(pz, report)
    append_pdf(pz, balance)
    if calculation is not None:
        append_pdf(pz, str(folder / "Расчёт_учебной_модели.pdf"))
    labels = {"Схема_К1_К2.pdf": ("wastewater_scheme_pdf", "Схема К1 и К2 · учебный разрез"),
              "ПЗ_ИОС3.pdf": ("wastewater_pz_pdf", "Пояснительная записка ИОС3 · учебная"),
              "Расчёты_К1_К2.pdf": ("wastewater_calculation_pdf", "Расчёты К1 и К2"),
              "Баланс_ИОС3.pdf": ("wastewater_balance_pdf", "Баланс ИОС3"),
              "Расчёт_учебной_модели.pdf": ("study_calculation_pdf", "Расчёт к учебной схеме"),
              "Объёмы_сети_К1_К2.pdf": ("study_takeoff_pdf", "Объёмы полной сети К1/К2 · предварительные")}
    return [{"name": p.name, "kind": labels[p.name][0], "label": labels[p.name][1],
             "state": "incomplete", "state_note": "Учебные исходные. Не для выпуска.",
             "model_hash": fingerprint} for p in sorted(folder.glob("*.pdf"))], fingerprint


def study_ios3_project(req, water, storm):
    """IOS3-only presentation adapter: do not fabricate fire/head inputs merely
    to satisfy the all-systems IOS2 builder. Existing flow/balance bridges only.
    Detailed study routing remains proposed, not confirmed production inventory.
    """
    from app.calc.sewage import DomesticSewageResult, check_sewage_system
    from app.pz.flows_bridge import flows_from_demand, balance_from_calc
    from app.pz.project import (Project, DocumentInfo, BuildingFlags, BuildingPurpose,
                                HwsType, SewageDesign, StormDesign)
    p = Project()
    p.document = DocumentInfo(object_name=req.document.object_name)
    p.building = BuildingFlags(purpose=BuildingPurpose.RESIDENTIAL, floors_above=req.floors,
        floors_below=req.floors_below, apartments=req.apartments, residents=req.residents,
        basement_clear_height_m=req.basement_clear_height_m, floor_elevations_m=req.floor_elevations_m,
        apartments_by_floor=req.apartments_by_floor, hws_type=HwsType.CENTRAL,
        height_m=req.wastewater_roof_relative_elevation_m - req.floor_elevations_m[1],
        unheated_zones=req.floors == 3)
    p.consumer_groups = [(row.code, row.count) for row in req.consumers]
    p.consumer_details = [("Квартиры · учебный пример", row.code, row.count) for row in req.consumers]
    p.flows = flows_from_demand(water)
    p.balance = balance_from_calc(p.consumer_details, p.flows)
    p.sewage = SewageDesign(
        basement_floor_elevation_m=req.wastewater_basement_floor_elevation_m,
        roof_kind=req.wastewater_roof_kind, roof_relative_elevation_m=req.wastewater_roof_relative_elevation_m,
        design_assignment_ref=req.wastewater_design_assignment_ref,
        laying_method=req.wastewater_laying_method,
        result=check_sewage_system(DomesticSewageResult(water.total.q_sec, water.sewage_fixture_discharge, water.sewage_flow), []))
    p.storm = StormDesign(roof_type="flat", system_kind="internal",
        system_note="Внутренний водосток К2 — учебное предложение, подключение к наружным сетям не определено.",
        city_code=req.storm_city, roof_area_m2=req.storm_roof_area_m2, walls_area_m2=0,
        period_years=1, funnels_count=req.storm_funnels_count, risers_count=req.storm_risers_count,
        result=storm)
    p.storm_city = req.storm_city
    return p
