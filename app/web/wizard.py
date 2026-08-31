# -*- coding: utf-8 -*-
"""
app/web/wizard.py — Wizard: веб-форма ввода объекта ИОС2 (слой 3 цепочки ввода).

Форма НЕ знает Project: она собирает IOS2Request (намерение) из полей,
отдаёт его в ProjectBuilder и показывает результат design_ios2, включая
самостоятельный комплект К1/К2/К3.

    браузер → GET /wizard           форма (одна страница, секциями)
            → POST /wizard/design   сборка DTO → Builder → design_ios2
            → GET /wizard/result/{run_id}         статус + ссылки на PDF
            → GET /wizard/file/{run_id}/{name}    отдача PDF

MVP-упрощения (осознанные):
  • до 12 групп потребителей, одно характерное помещение, до 6 участков В2,
    12 участков труб К1/К2/К3 и 24 подтверждённых элементов в форме
    (для демо достаточно; полный ввод — следующая итерация);
  • активные результаты кэшируются в памяти, а снимок выпуска сохраняется в
    ReleaseStore и восстанавливается после перезапуска процесса.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.intake.request_dto import (
    IOS2Request, DocumentRequest, RoomRequest, NetworkRequest,
    MainRunRequest, RiserRequest, SourceDataRequest, ConsumerGroupRequest,
    SewageRiserRequest, SewerPipeRequest, SewerElementRequest,
    SewerDischargeEventRequest, SewerFixtureSafetyRequest,
    SewerBoundaryLevelRequest, SewerFirstManholeRequest,
    SewerInternalNodeRequest,
)
from app.intake.project_builder import build_project, RequestValidationError
from app.intake.advisories import review_request
from app.intake.applicability import applicability_rules_for_web
from app.pz.ios2_orchestrator import design_ios2
from app.intake.project_store import ProjectStore
from app.intake.passport_store import PassportStore
from app.intake.release_store import (
    ReleaseIntegrityError,
    ReleaseNotFoundError,
    ReleaseStore,
)
from app.intake.yaml_io import load_request_file
from app.pz.generator import cold_meter_loss
from app.pz.impact import (
    ImpactValidationError,
    calculate_impact_preview,
    impact_form_context,
)
from app.pz.proof import build_proof_graph
from app.pz.wastewater_topology import build_wastewater_topology
from app.pz.defense import (
    build_defense_payload,
    generate_expert_response_pdf,
)
from app.pz.digital_passport import build_passport_info, new_passport_id
from app.schemas.impact import ImpactPreviewInput
from app.data.sp30_tables import list_consumer_norms
from app.data.storm_cities import list_cities

router = APIRouter(prefix="/wizard", tags=["wizard"])
_TPL = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
_TPL.env.filters["ru_num"] = lambda value, precision=1: (
    "—" if value is None else f"{value:.{precision}f}".replace(".", ",")
)

# run_id → {"bundle": IOS2DesignBundle, "outdir": str}
_RUNS: Dict[str, dict] = {}
_OUT_ROOT = "/tmp/zarya_wizard_runs"
_STORE = ProjectStore()
_PASSPORT_STORE = PassportStore()
_RELEASE_STORE = ReleaseStore()
_CONSUMER_NORMS = list_consumer_norms()
_STORM_CITIES = list_cities()
_DEMO_PROJECT = Path(__file__).parents[2] / "demo" / "demo_project.yaml"

_DOCUMENT_GROUPS = (
    ("common", "00", "Основной комплект",
     "Общие документы, баланс и сводные материалы проекта"),
    ("ios2", "ИОС2", "Система водоснабжения",
     "В1, В2, Т3 и Т4: расчёты и обоснования принятых решений"),
    ("ios3", "ИОС3", "Система водоотведения",
     "К1, К2 и К3: отдельная ПЗ, расчёты, схема и спецификация"),
)

_DOCUMENTS = (
    ("common", "Пояснительная записка", "pz_pdf"),
    ("common", "Паспорт проекта и нормативный контроль",
     "commission_control_pdf"),
    ("common", "Баланс водопотребления и водоотведения", "balance_pdf"),
    ("common", "Сводная спецификация", "spec_pdf"),
    ("common", "Сводная принципиальная схема", "scheme_pdf"),
    ("ios2", "Схема вводов и узлов учёта", "metering_scheme_pdf"),
    ("ios2", "Схема насосов, зон и ГВС", "pump_zone_scheme_pdf"),
    ("ios2", "Расчётные обоснования В1 и Т3", "v1_calculation_pdf"),
    ("ios2", "Расчёт и подбор насосов", "pump_selection_pdf"),
    ("ios2", "Гидравлический расчёт В2", "hydraulic_pdf"),
    ("ios2", "Проверка живучести кольца В2", "resilience_pdf"),
    ("ios3", "Комплект ИОС3 К1, К2 и К3",
     "wastewater_package_pdf"),
    ("ios3", "Пояснительная записка ИОС3", "wastewater_pz_pdf"),
    ("ios3", "Баланс ИОС3 по приложению А ГОСТ Р 21.620", "wastewater_balance_pdf"),
    ("ios3", "Расчётные обоснования К1 и К2",
     "wastewater_calculation_pdf"),
    ("ios3", "Принципиальная схема ИОС3", "wastewater_scheme_pdf"),
    ("ios3", "Ведомость УГО К1, К2 и К3", "wastewater_ugo_pdf"),
    ("ios3", "Спецификация К1, К2 и К3", "wastewater_spec_pdf"),
)


def _form_context(**values):
    return {
        "consumer_norms": _CONSUMER_NORMS,
        "storm_cities": _STORM_CITIES,
        "applicability_rules": applicability_rules_for_web(),
        "advisories": [],
        "example_mode": False,
        **values,
    }


def _group_documents(documents: list[dict]) -> tuple[list[dict], list[dict]]:
    groups = {
        key: {
            "key": key,
            "code": code,
            "label": label,
            "description": description,
            "documents": [],
        }
        for key, code, label, description in _DOCUMENT_GROUPS
    }
    for document in documents:
        group = document["group"]
        if group in groups:
            groups[group]["documents"].append(document)
    document_groups = [
        groups[key] for key, *_ in _DOCUMENT_GROUPS
        if groups[key]["documents"]
    ]
    return documents, document_groups


def _bundle_documents(bundle) -> tuple[list[dict], list[dict]]:
    """Единый каталог фактически выпущенных PDF для результата и Defense."""
    wastewater_topology = build_wastewater_topology(bundle.project)
    incomplete_wastewater_documents = {
        "wastewater_package_pdf",
        "wastewater_scheme_pdf",
    }
    documents = []
    for group, label, attribute in _DOCUMENTS:
        path = getattr(bundle, attribute, None)
        if not path:
            continue
        document = {
            "group": group,
            "label": label,
            "name": os.path.basename(path),
            "state": (
                "incomplete"
                if (
                    attribute in incomplete_wastewater_documents
                    and not wastewater_topology.ready
                )
                else "ready"
            ),
            "state_note": (
                "Каркас: нужны стояки, ветви, магистрали и выпуски К1/К2/К3"
                if (
                    attribute in incomplete_wastewater_documents
                    and not wastewater_topology.ready
                )
                else ""
            ),
        }
        documents.append(document)
    return _group_documents(documents)


def _run_documents(run: dict) -> tuple[list[dict], list[dict]]:
    documents = run.get("documents")
    if documents is not None:
        return _group_documents(documents)
    return _bundle_documents(run["bundle"])


def _restore_run(run_id: str) -> dict:
    snapshot = _RELEASE_STORE.load(run_id)
    req = snapshot.request()
    project = build_project(req)
    suffix = f"/p/{snapshot.passport_id}"
    public_base = (
        snapshot.passport_url[:-len(suffix)]
        if snapshot.passport_url.endswith(suffix)
        else snapshot.passport_url.rsplit("/", 1)[0]
    )
    project.digital_passport = build_passport_info(
        snapshot.passport_id,
        public_base,
    )
    outdir = os.path.join(_OUT_ROOT, run_id)
    bundle = design_ios2(
        project,
        output_dir=outdir,
        render_documents=False,
    )
    bundle.commission_report = snapshot.commission_report()
    bundle.status = list(snapshot.status)
    bundle.warnings = list(snapshot.warnings)
    run = {
        "bundle": bundle,
        "outdir": outdir,
        "project_id": snapshot.project_id,
        "advisories": snapshot.advisories(),
        "request": req,
        "proof_graph": snapshot.proof_graph(),
        "defense_payload": snapshot.defense_payload,
        "passport_id": snapshot.passport_id,
        "passport_url": snapshot.passport_url,
        "documents": snapshot.documents,
        "release_id": run_id,
    }
    _RUNS[run_id] = run
    return run


def _get_run(run_id: str) -> dict | None:
    run = _RUNS.get(run_id)
    if run is not None:
        return run
    try:
        return _restore_run(run_id)
    except (
        ReleaseNotFoundError,
        ReleaseIntegrityError,
        RequestValidationError,
        ValueError,
    ):
        return None


def _run_file(run: dict, name: str) -> str | None:
    if not name or os.path.basename(name) != name:
        return None
    path = os.path.join(run["outdir"], name)
    if (
        not os.path.isfile(path)
        or os.path.dirname(os.path.abspath(path))
        != os.path.abspath(run["outdir"])
    ):
        try:
            passport_path, _ = _PASSPORT_STORE.document(
                run.get("passport_id", ""),
                name,
            )
            return str(passport_path)
        except (FileNotFoundError, ValueError):
            try:
                answer_path = _RELEASE_STORE.answer_path(
                    run.get("release_id", ""), name
                )
            except (FileNotFoundError, ValueError):
                return None
            return str(answer_path) if answer_path.is_file() else None
    return path


def _public_base_url(request: Request) -> str:
    configured = os.environ.get("ZARYA_PUBLIC_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    try:
        return str(request.base_url).rstrip("/")
    except Exception:
        return "http://127.0.0.1:8000"


@router.get("", response_class=HTMLResponse)
def wizard_form(request: Request, example: bool = False):
    prefill = load_request_file(str(_DEMO_PROJECT)) if example else None
    return _TPL.TemplateResponse(
        request,
        "wizard_form.html",
        _form_context(
            errors=[],
            prefill=prefill,
            example_mode=example,
            advisories=(review_request(prefill) if prefill else []),
        ),
    )


@router.post("/design")
async def wizard_design(request: Request):
    """Принимает форму, собирает IOS2Request, строит Project, гонит design_ios2."""
    form = await request.form()

    def fv(name, default=""):
        return str(form.get(name, default)).strip()

    def ff(name, default=0.0):
        try:
            return float(str(form.get(name, default)).replace(",", "."))
        except (TypeError, ValueError):
            return default

    def fi(name, default=0):
        try:
            return int(float(str(form.get(name, default))))
        except (TypeError, ValueError):
            return default

    # магистраль В2: до 6 участков (пустые строки пропускаются)
    runs = []
    for i in range(1, 7):
        a, b = fv(f"run{i}_from"), fv(f"run{i}_to")
        if a and b:
            runs.append(MainRunRequest(
                a, b, length_m=ff(f"run{i}_len"), dn=fi(f"run{i}_dn", 100),
                equiv_length_m=ff(f"run{i}_leq"),
                repair_section_id=fv(f"run{i}_repair")))
    # стояки: до 4
    risers = []
    for i in range(1, 5):
        nm = fv(f"riser{i}_name")
        if nm:
            risers.append(RiserRequest(
                nm, at_node=fv(f"riser{i}_node"), height_m=ff(f"riser{i}_h"),
                cabinet_elevation_m=ff(f"riser{i}_elev"), dn=fi(f"riser{i}_dn", 65),
                equiv_length_m=ff(f"riser{i}_leq"),
                repair_section_id=fv(f"riser{i}_repair")))

    network = None
    if runs:
        network = NetworkRequest(
            runs=runs, risers=risers, source_node=fv("source_node"),
            source_kind=fv("source_kind", "city_main"),
            available_head_m=(ff("available_head") if fv("available_head") else None),
            water_level_m=(ff("water_level") if fv("water_level") else None),
            suction_head_loss_m=ff("suction_loss"))

    rooms = []
    if fv("room_name"):
        rooms.append(RoomRequest(
            fv("room_name"), length_m=ff("room_len"), width_m=ff("room_wid"),
            height_m=ff("room_h"), space_kind=fv("room_kind", "corridor"),
            placement=fv("room_place", "two_opposite_sides")))

    consumers = []
    for i in range(1, 13):
        code = fv(f"consumer{i}_code")
        count = fi(f"consumer{i}_count")
        if code and count > 0:
            consumers.append(ConsumerGroupRequest(
                code=code,
                count=count,
                name=fv(f"consumer{i}_name"),
            ))
    # Совместимость со старой формой и внешними клиентами Wizard.
    if not consumers and fi("consumer_count") > 0:
        consumers.append(ConsumerGroupRequest(
            fv("consumer_code", "residential_full_bath"),
            fi("consumer_count"),
        ))

    sewage_risers = []
    for i in range(1, 4):
        riser_id = fv(f"sewage_riser{i}_id")
        if riser_id:
            sewage_risers.append(SewageRiserRequest(
                riser_id=riser_id,
                design_flow_lps=ff(f"sewage_riser{i}_flow"),
                material=fv(f"sewage_riser{i}_material", "pp"),
                ventilation=fv(
                    f"sewage_riser{i}_ventilation", "ventilated"
                ),
                riser_dn_mm=fi(f"sewage_riser{i}_dn", 110),
                branch_dn_mm=fi(f"sewage_riser{i}_branch_dn", 110),
                branch_angle_deg=ff(f"sewage_riser{i}_angle", 87.5),
                has_toilet=bool(form.get(f"sewage_riser{i}_toilet")),
                working_height_m=(
                    ff(f"sewage_riser{i}_height")
                    if fv(f"sewage_riser{i}_height") else None
                ),
                inner_diameter_mm=(
                    ff(f"sewage_riser{i}_inner")
                    if fv(f"sewage_riser{i}_inner") else None
                ),
                branch_inner_diameter_mm=(
                    ff(f"sewage_riser{i}_branch_inner")
                    if fv(f"sewage_riser{i}_branch_inner") else None
                ),
                minimum_trap_seal_mm=(
                    ff(f"sewage_riser{i}_trap_seal")
                    if fv(f"sewage_riser{i}_trap_seal") else None
                ),
                pressure_input_source=fv(
                    f"sewage_riser{i}_pressure_source"
                ),
                air_valve_free_area_mm2=(
                    ff(f"sewage_riser{i}_valve_area")
                    if fv(f"sewage_riser{i}_valve_area") else None
                ),
                air_valve_source=fv(f"sewage_riser{i}_valve_source"),
            ))

    sewer_pipes = []
    for i in range(1, 13):
        section_id = fv(f"sewer_pipe{i}_id")
        if section_id:
            sewer_pipes.append(SewerPipeRequest(
                system=fv(f"sewer_pipe{i}_system", "K1"),
                section_id=section_id,
                purpose=fv(f"sewer_pipe{i}_purpose"),
                material=fv(f"sewer_pipe{i}_material"),
                standard=fv(f"sewer_pipe{i}_standard"),
                outer_diameter_mm=ff(f"sewer_pipe{i}_outer"),
                wall_thickness_mm=ff(f"sewer_pipe{i}_wall"),
                length_m=ff(f"sewer_pipe{i}_length"),
                nominal_diameter_mm=(
                    fi(f"sewer_pipe{i}_nominal")
                    if fv(f"sewer_pipe{i}_nominal") else None
                ),
                slope_per_mille=(
                    ff(f"sewer_pipe{i}_slope")
                    if fv(f"sewer_pipe{i}_slope") else None
                ),
                fill_ratio=(
                    ff(f"sewer_pipe{i}_fill")
                    if fv(f"sewer_pipe{i}_fill") else None
                ),
                from_node=fv(f"sewer_pipe{i}_from"),
                to_node=fv(f"sewer_pipe{i}_to"),
                room=fv(f"sewer_pipe{i}_room"),
                elevation_start_m=(
                    ff(f"sewer_pipe{i}_elev_start")
                    if fv(f"sewer_pipe{i}_elev_start") else None
                ),
                elevation_end_m=(
                    ff(f"sewer_pipe{i}_elev_end")
                    if fv(f"sewer_pipe{i}_elev_end") else None
                ),
                absolute_elevation_start_m=(
                    ff(f"sewer_pipe{i}_abs_elev_start")
                    if fv(f"sewer_pipe{i}_abs_elev_start") else None
                ),
                absolute_elevation_end_m=(
                    ff(f"sewer_pipe{i}_abs_elev_end")
                    if fv(f"sewer_pipe{i}_abs_elev_end") else None
                ),
                insulated=bool(form.get(f"sewer_pipe{i}_insulated")),
                critical_velocity_mps=(
                    ff(f"sewer_pipe{i}_critical_velocity")
                    if fv(f"sewer_pipe{i}_critical_velocity") else None
                ),
                critical_velocity_source=fv(
                    f"sewer_pipe{i}_critical_velocity_source"
                ),
                critical_fill_ratio=(
                    ff(f"sewer_pipe{i}_critical_fill")
                    if fv(f"sewer_pipe{i}_critical_fill") else None
                ),
            ))

    sewer_elements = []
    for i in range(1, 49):
        element_id = fv(f"sewer_element{i}_id")
        if element_id:
            sewer_elements.append(SewerElementRequest(
                element_id=element_id,
                system=fv(f"sewer_element{i}_system", "K1"),
                kind=fv(f"sewer_element{i}_kind", "other"),
                name=fv(f"sewer_element{i}_name"),
                quantity=fi(f"sewer_element{i}_quantity", 1),
                typical_quantity=(
                    fi(f"sewer_element{i}_typical_quantity")
                    if fv(f"sewer_element{i}_typical_quantity") else None
                ),
                floor_from=fi(f"sewer_element{i}_floor_from", 1),
                floor_to=(
                    fi(f"sewer_element{i}_floor_to")
                    if fv(f"sewer_element{i}_floor_to") else None
                ),
                room_number=fv(f"sewer_element{i}_room_number"),
                room_name=fv(f"sewer_element{i}_room"),
                elevation_m=(
                    ff(f"sewer_element{i}_elevation")
                    if fv(f"sewer_element{i}_elevation") else None
                ),
                dn_mm=(
                    fi(f"sewer_element{i}_dn")
                    if fv(f"sewer_element{i}_dn") else None
                ),
                slope_per_mille=(
                    ff(f"sewer_element{i}_slope")
                    if fv(f"sewer_element{i}_slope") else None
                ),
                section_id=fv(f"sewer_element{i}_section"),
                connects_to=fv(f"sewer_element{i}_connects_to"),
                type_mark=fv(f"sewer_element{i}_type_mark"),
                standard=fv(f"sewer_element{i}_standard"),
                include_in_spec=bool(form.get(f"sewer_element{i}_include_spec")),
                layout_column=fi(f"sewer_element{i}_column"),
            ))

    sewer_discharge_events = []
    for i in range(1, 9):
        event_id = fv(f"sewer_event{i}_id")
        if event_id:
            sewer_discharge_events.append(SewerDischargeEventRequest(
                event_id=event_id,
                fixture_id=fv(f"sewer_event{i}_fixture"),
                floor=fi(f"sewer_event{i}_floor", 1),
                instance_no=fi(f"sewer_event{i}_instance", 1),
                start_seconds=ff(f"sewer_event{i}_start"),
                duration_seconds=ff(f"sewer_event{i}_duration"),
                flow_lps=ff(f"sewer_event{i}_flow"),
                source=fv(f"sewer_event{i}_source"),
                suspended_solids_mg_l=(
                    ff(f"sewer_event{i}_solids")
                    if fv(f"sewer_event{i}_solids") else None
                ),
                suspended_solids_source=fv(
                    f"sewer_event{i}_solids_source"
                ),
            ))

    sewer_fixture_safety_inputs = []
    for i in range(1, 9):
        fixture_id = fv(f"sewer_safety{i}_fixture")
        if fixture_id:
            sewer_fixture_safety_inputs.append(SewerFixtureSafetyRequest(
                fixture_id=fixture_id,
                floor=fi(f"sewer_safety{i}_floor", 1),
                instance_no=fi(f"sewer_safety{i}_instance", 1),
                connection_absolute_elevation_m=ff(
                    f"sewer_safety{i}_connection_abs"
                ),
                overflow_absolute_elevation_m=ff(
                    f"sewer_safety{i}_overflow_abs"
                ),
                trap_seal_depth_mm=ff(f"sewer_safety{i}_trap_seal"),
                minimum_residual_seal_mm=ff(
                    f"sewer_safety{i}_minimum_residual"
                ),
                source=fv(f"sewer_safety{i}_source"),
            ))

    sewer_first_manholes = []
    for i in range(1, 4):
        manhole_id = fv(f"sewer_manhole{i}_id")
        if manhole_id:
            levels = []
            for j in range(1, 4):
                level_value = fv(f"sewer_manhole{i}_level{j}")
                if level_value:
                    levels.append(SewerBoundaryLevelRequest(
                        time_seconds=ff(f"sewer_manhole{i}_time{j}"),
                        water_level_absolute_elevation_m=ff(
                            f"sewer_manhole{i}_level{j}"
                        ),
                    ))
            sewer_first_manholes.append(SewerFirstManholeRequest(
                manhole_id=manhole_id,
                outlet_section_id=fv(f"sewer_manhole{i}_outlet"),
                invert_absolute_elevation_m=ff(f"sewer_manhole{i}_invert_abs"),
                levels=levels,
                source=fv(f"sewer_manhole{i}_source"),
            ))

    sewer_internal_nodes = []
    for i in range(1, 5):
        node_id = fv(f"sewer_internal_node{i}_id")
        if node_id:
            upstream_ids = [
                row.strip()
                for row in fv(f"sewer_internal_node{i}_upstream").split(",")
                if row.strip()
            ]
            sewer_internal_nodes.append(SewerInternalNodeRequest(
                node_id=node_id,
                downstream_section_id=fv(
                    f"sewer_internal_node{i}_downstream"
                ),
                upstream_section_ids=upstream_ids,
                invert_absolute_elevation_m=ff(
                    f"sewer_internal_node{i}_invert_abs"
                ),
                overflow_absolute_elevation_m=ff(
                    f"sewer_internal_node{i}_overflow_abs"
                ),
                storage_volume_m3=ff(
                    f"sewer_internal_node{i}_storage"
                ),
                overflow_location=fv(
                    f"sewer_internal_node{i}_location"
                ),
                source=fv(f"sewer_internal_node{i}_source"),
            ))

    req = IOS2Request(
        document=DocumentRequest(
            cipher=fv("cipher"), object_name=fv("object_name"),
            organization=fv("organization"), object_address=fv("address"),
            object_part=fv("object_part"), stage=fv("stage", "П"),
            developer=fv("developer"), inspector=fv("inspector"),
            dept_head=fv("dept_head"), gip=fv("gip"), norm_control=fv("norm_control")),
        building_type=fv("building_type"),
        floors=fi("floors"), building_height_m=ff("height"),
        total_area_m2=ff("total_area"),
        hws_type=fv("hws_type", "central"),
        risers_v1=fi("risers_v1"), risers_t3=fi("risers_t3"),
        risers_t4=fi("risers_t4"),
        insulation_location=fv("insulation_location", "room_hot"),
        insulation_t_room_manual=ff("insulation_t_room", 5.0),
        insulation_humidity=fi("insulation_humidity", 60),
        insulation_hvs_water_temp=ff("insulation_hvs_temp", 10.0),
        insulation_gvs_water_temp=ff("insulation_gvs_temp", 60.0),
        fire_mode=fv("fire_mode", "auto"),
        fire_height_m=(ff("fire_height") if fv("fire_height") else None),
        fire_category=fv("fire_category"),
        fire_hall_seats=(
            fi("fire_hall_seats") if fv("fire_hall_seats") else None
        ),
        fire_area_m2=(
            ff("fire_area_m2") if fv("fire_area_m2") else None
        ),
        fire_geometry_confirmed=bool(form.get("fire_geometry_confirmed")),
        streams=(fi("streams") if fv("streams") else None),
        nozzle_mm=fi("nozzle_mm", 13),
        compact_jet_m=fi("compact_jet_m", 12),
        fire_topology=fv("fire_topology", "auto"),
        fire_topology_basis=fv("fire_topology_basis"),
        fire_branch_electric_valves=bool(form.get("fire_branch_electric_valves")),
        zones=fi("zones", 1), rooms=rooms, network=network,
        apartments=fi("apartments"),
        owner_groups_count=fi("owner_groups_count", 1),
        roof_type=fv("roof_type", "not_set"),
        sewage_max_fixture_lps=ff("sewage_max_fixture_lps", 1.6),
        sewage_risers=sewage_risers,
        sewer_pipes=sewer_pipes,
        sewer_elements=sewer_elements,
        sewer_discharge_events=sewer_discharge_events,
        sewer_fixture_safety_inputs=sewer_fixture_safety_inputs,
        sewer_first_manholes=sewer_first_manholes,
        sewer_internal_nodes=sewer_internal_nodes,
        sewer_transient_step_seconds=(
            ff("sewer_transient_step_seconds")
            if fv("sewer_transient_step_seconds") else None
        ),
        sewer_transient_duration_seconds=(
            ff("sewer_transient_duration_seconds")
            if fv("sewer_transient_duration_seconds") else None
        ),
        sewage_outlets_count=fi("sewage_outlets_count"),
        wastewater_basement_floor_elevation_m=(
            ff("wastewater_basement_floor_elevation_m")
            if fv("wastewater_basement_floor_elevation_m") else None
        ),
        wastewater_design_assignment_ref=fv("wastewater_design_assignment_ref"),
        wastewater_survey_ref=fv("wastewater_survey_ref"),
        wastewater_service_life_years=(
            fi("wastewater_service_life_years")
            if fv("wastewater_service_life_years") else None
        ),
        wastewater_overhaul_period_years=(
            fi("wastewater_overhaul_period_years")
            if fv("wastewater_overhaul_period_years") else None
        ),
        wastewater_disposal_mode=fv("wastewater_disposal_mode", "not_set"),
        wastewater_tu_org=fv("wastewater_tu_org"),
        wastewater_tu_number=fv("wastewater_tu_number"),
        wastewater_tu_date=fv("wastewater_tu_date"),
        wastewater_discharge_standard_ref=fv(
            "wastewater_discharge_standard_ref"
        ),
        wastewater_water_body_characteristics_note=fv(
            "wastewater_water_body_characteristics_note"
        ),
        wastewater_existing_network_type=fv("wastewater_existing_network_type"),
        wastewater_existing_network_material=fv("wastewater_existing_network_material"),
        wastewater_existing_network_standard=fv("wastewater_existing_network_standard"),
        wastewater_existing_network_outer_diameter_mm=(
            ff("wastewater_existing_network_outer")
            if fv("wastewater_existing_network_outer") else None
        ),
        wastewater_existing_network_wall_thickness_mm=(
            ff("wastewater_existing_network_wall")
            if fv("wastewater_existing_network_wall") else None
        ),
        wastewater_discharge_point_k1=fv("wastewater_discharge_point_k1"),
        wastewater_discharge_point_k2=fv("wastewater_discharge_point_k2"),
        wastewater_discharge_point_k3=fv("wastewater_discharge_point_k3"),
        wastewater_k1_min_hourly_m3h=(
            ff("wastewater_k1_min_hourly_m3h")
            if fv("wastewater_k1_min_hourly_m3h") else None
        ),
        wastewater_k3_max_hourly_m3h=(
            ff("wastewater_k3_max_hourly_m3h")
            if fv("wastewater_k3_max_hourly_m3h") else None
        ),
        wastewater_k3_min_hourly_m3h=(
            ff("wastewater_k3_min_hourly_m3h")
            if fv("wastewater_k3_min_hourly_m3h") else None
        ),
        wastewater_quality_indicators_note=fv(
            "wastewater_quality_indicators_note"
        ),
        wastewater_laying_method=fv("wastewater_laying_method"),
        wastewater_fire_barrier_note=fv("wastewater_fire_barrier_note"),
        wastewater_deformation_joint_note=fv("wastewater_deformation_joint_note"),
        wastewater_waste_handling_note=fv("wastewater_waste_handling_note"),
        wastewater_external_network_in_scope=bool(
            form.get("wastewater_external_network_in_scope")
        ),
        wastewater_external_network_design_note=fv(
            "wastewater_external_network_design_note"
        ),
        wastewater_external_scheme_source=fv("wastewater_external_scheme_source"),
        wastewater_site_plan_source=fv("wastewater_site_plan_source"),
        wastewater_pump_required=bool(form.get("wastewater_pump_required")),
        wastewater_pump_location=fv("wastewater_pump_location"),
        wastewater_pump_model=fv("wastewater_pump_model"),
        wastewater_pump_q_m3h=(
            ff("wastewater_pump_q_m3h") if fv("wastewater_pump_q_m3h") else None
        ),
        wastewater_pump_head_m=(
            ff("wastewater_pump_head_m") if fv("wastewater_pump_head_m") else None
        ),
        wastewater_pump_power_kw=(
            ff("wastewater_pump_power_kw") if fv("wastewater_pump_power_kw") else None
        ),
        wastewater_pump_reserve_note=fv("wastewater_pump_reserve_note"),
        wastewater_pump_power_category=fv("wastewater_pump_power_category"),
        wastewater_pump_automation_note=fv("wastewater_pump_automation_note"),
        wastewater_treatment_required=bool(
            form.get("wastewater_treatment_required")
        ),
        wastewater_treatment_location=fv("wastewater_treatment_location"),
        wastewater_treatment_type=fv("wastewater_treatment_type"),
        wastewater_treatment_capacity_lps=(
            ff("wastewater_treatment_capacity_lps")
            if fv("wastewater_treatment_capacity_lps") else None
        ),
        wastewater_treatment_capacity_m3_day=(
            ff("wastewater_treatment_capacity_m3_day")
            if fv("wastewater_treatment_capacity_m3_day") else None
        ),
        wastewater_treatment_technology=fv("wastewater_treatment_technology"),
        storm_city=fv("storm_city"),
        storm_roof_area_m2=ff("storm_roof_area"),
        storm_walls_area_m2=ff("storm_walls_area"),
        storm_period_years=fi("storm_period_years", 1),
        storm_roof_sections=fi("storm_roof_sections"),
        storm_funnels_count=fi("storm_funnels_count"),
        storm_sectional_residential_single_funnel=bool(
            form.get("storm_sectional_residential_single_funnel")
        ),
        storm_max_funnel_spacing_m=(
            ff("storm_max_funnel_spacing_m")
            if fv("storm_max_funnel_spacing_m") else None
        ),
        storm_selected_funnel_capacity_lps=(
            ff("storm_selected_funnel_capacity_lps")
            if fv("storm_selected_funnel_capacity_lps") else None
        ),
        storm_max_funnel_flow_lps=(
            ff("storm_max_funnel_flow_lps")
            if fv("storm_max_funnel_flow_lps") else None
        ),
        storm_risers_count=fi("storm_risers_count"),
        storm_selected_riser_dn_mm=fi("storm_selected_riser_dn_mm"),
        storm_max_riser_flow_lps=(
            ff("storm_max_riser_flow_lps")
            if fv("storm_max_riser_flow_lps") else None
        ),
        storm_funnels_on_different_levels=bool(
            form.get("storm_funnels_on_different_levels")
        ),
        storm_design_m3_day=(
            ff("storm_design_m3_day") if fv("storm_design_m3_day") else None
        ),
        storm_annual_m3=(
            ff("storm_annual_m3") if fv("storm_annual_m3") else None
        ),
        storm_melt_m3h=(
            ff("storm_melt_m3h") if fv("storm_melt_m3h") else None
        ),
        storm_melt_m3_day=(
            ff("storm_melt_m3_day") if fv("storm_melt_m3_day") else None
        ),
        storm_melt_m3_year=(
            ff("storm_melt_m3_year") if fv("storm_melt_m3_year") else None
        ),
        storm_treatment_volume_m3=(
            ff("storm_treatment_volume_m3")
            if fv("storm_treatment_volume_m3") else None
        ),
        storm_storage_volume_m3=(
            ff("storm_storage_volume_m3")
            if fv("storm_storage_volume_m3") else None
        ),
        catering_type=fv("catering_type", "none"),
        catering_seats=fi("catering_seats"),
        catering_conditional_dishes=fi("catering_conditional_dishes"),
        school_grease_by_assignment=bool(form.get("school_grease_by_assignment")),
        group_showers_answer=fv("group_showers_answer", "unknown"),
        group_showers_count=fi("group_showers_count"),
        food_service_answer=fv("food_service_answer", "unknown"),
        grease_wastewater_answer=fv(
            "grease_wastewater_answer", "unknown"
        ),
        grease_trap_location=fv("grease_trap_location", "unknown"),
        source_data=SourceDataRequest(
            source_description=fv("source_description"),
            water_protection_note=fv("water_protection_note"),
            reserve_water_note=fv("reserve_water_note"),
            tu_org=fv("tu_org"), tu_number=fv("tu_number"), tu_date=fv("tu_date"),
            connection_point=fv("connection_point"),
            guaranteed_head_m=(ff("tu_guaranteed_head") if fv("tu_guaranteed_head") else None),
            maximum_head_m=(ff("tu_maximum_head") if fv("tu_maximum_head") else None),
            tu_limit_q_day=(ff("tu_limit_q_day") if fv("tu_limit_q_day") else None),
            water_main_dn=fi("water_main_dn"),
            h_geom_m=(ff("h_geom") if fv("h_geom") else None),
            h_il_m=(ff("h_il") if fv("h_il") else None),
            network_kind=fv("network_kind", "domestic"),
            h_pr_m=ff("h_pr", 20.0),
            h_tepl_m=ff("h_tepl", 0.0),
            h_apartment_c_meter_m=(ff("h_apartment_c_meter") if fv("h_apartment_c_meter") else None),
            h_apartment_h_meter_m=(ff("h_apartment_h_meter") if fv("h_apartment_h_meter") else None),
            hws_heater_in_scope=bool(form.get("hws_heater_in_scope")),
            h_vvod_m=(ff("h_vvod") if fv("h_vvod") else None),
            inputs_count=fi("inputs_count", 1),
            npsh_available_m=(ff("npsh_available") if fv("npsh_available") else None),
        ),
        consumers=consumers,
    )
    advisories = review_request(req)

    pid = fv("project_id") or None
    try:
        project = build_project(req)
    except RequestValidationError as e:
        return _TPL.TemplateResponse(request, "wizard_form.html", _form_context(**{
            "errors": e.problems, "advisories": advisories,
            "prefill": req, "project_id": pid,
        }))

    passport_id = new_passport_id()
    project.digital_passport = build_passport_info(
        passport_id,
        _public_base_url(request),
    )

    # персистентность: намерение сохраняется (source of truth — вход)
    project_id = _STORE.save(req, project_id=(pid if pid and _STORE.exists(pid) else None))

    run_id = uuid.uuid4().hex[:10]
    outdir = os.path.join(_OUT_ROOT, run_id)
    try:
        bundle = design_ios2(project, output_dir=outdir)
    except Exception as exc:
        return _TPL.TemplateResponse(request, "wizard_form.html", _form_context(**{
            "errors": [f"Комплект не собран: {exc}"],
            "advisories": advisories,
            "prefill": req,
            "project_id": project_id,
        }), status_code=422)
    proof_graph = build_proof_graph(
        bundle.project, bundle.commission_report,
    )
    documents, _ = _bundle_documents(bundle)
    defense_payload = build_defense_payload(
        proof_graph,
        documents,
        outdir,
        run_id=run_id,
    )
    try:
        passport_manifest = _PASSPORT_STORE.publish(
            passport_id=passport_id,
            canonical_url=bundle.project.digital_passport.url,
            project_id=project_id,
            project=bundle.project,
            commission=bundle.commission_report,
            defense_payload=defense_payload,
            documents=documents,
            outdir=outdir,
        )
        release_manifest = _RELEASE_STORE.publish(
            release_id=run_id,
            project_id=project_id,
            passport_id=passport_id,
            passport_url=bundle.project.digital_passport.url,
            request=req,
            commission=bundle.commission_report,
            proof_graph=proof_graph,
            defense_payload=defense_payload,
            documents=documents,
            advisories=advisories,
            status=bundle.status,
            warnings=bundle.warnings,
        )
    except Exception as exc:
        return _TPL.TemplateResponse(request, "wizard_form.html", _form_context(**{
            "errors": [f"Постоянный выпуск не сохранён: {exc}"],
            "advisories": advisories,
            "prefill": req,
            "project_id": project_id,
        }), status_code=422)
    _RUNS[run_id] = {
        "bundle": bundle, "outdir": outdir, "project_id": project_id,
        "advisories": advisories,
        "request": req,
        "proof_graph": proof_graph,
        "defense_payload": defense_payload,
        "passport_id": passport_id,
        "passport_url": bundle.project.digital_passport.url,
        "passport_manifest": passport_manifest,
        "release_manifest": release_manifest,
        "release_id": run_id,
        "documents": documents,
    }
    return RedirectResponse(url=f"/wizard/result/{run_id}", status_code=303)


@router.get("/result/{run_id}", response_class=HTMLResponse)
def wizard_result(request: Request, run_id: str):
    run = _get_run(run_id)
    if run is None:
        return HTMLResponse("<h2>Прогон не найден</h2>", status_code=404)
    b = run["bundle"]
    proof_graph = run["proof_graph"]
    pdfs, document_groups = _run_documents(run)
    f = b.project.fire
    p = b.project
    wastewater_topology = build_wastewater_topology(p)
    from app.pz.rules import project_governing_head
    head = project_governing_head(
        p, fallback_h_vod_m=cold_meter_loss(p.meters),
    )
    return _TPL.TemplateResponse(request, "wizard_result.html", {
        "run_id": run_id, "pdfs": pdfs, "document_groups": document_groups,
        "project_id": run.get("project_id"),
        "passport_id": run.get("passport_id"),
        "passport_url": run.get("passport_url"),
        "status": b.status,
        "commission": getattr(b, "commission_report", None),
        "proof": proof_graph,
        "impact": impact_form_context(run["request"]),
        "warnings": b.warnings + [
            f"{item.message} ({item.reference})"
            for item in run.get("advisories", [])
        ],
        "project": {
            "title": p.document.object_name,
            "cipher": p.document.cipher,
            "stage": p.document.stage_label,
        },
        "v1": {
            "q_day": p.flows.q_day_tot,
            "q_sec": p.flows.q_sec_c,
            "required_head": head.h_required_m,
            "guaranteed_head": head.h_guaranteed_m,
            "pump_required": p.pumps.required,
            "pump_model": p.pumps.model,
            "pump_q": p.pumps.wp_q or p.pumps.q_m3h,
            "pump_h": p.pumps.wp_h or p.pumps.head_m,
        },
        "fire": {
            "required": f.required,
            "note": f.normative_note,
            "flow": f.q_total,
            "pk_total": f.pk_total,
            "required_head": f.required_head_m,
            "available_head": f.available_head_m,
            "needs_pump": f.needs_pump,
            "dictating": f.dictating_cabinet_id,
        },
        "fire_pump": {
            "model": p.fire_pumps.model,
            "q": p.fire_pumps.wp_q or p.fire_pumps.q_m3h,
            "h": p.fire_pumps.wp_h or p.fire_pumps.head_m,
        },
        "sewage": {
            "flow": (
                p.sewage.result.total.q_sewage_lps
                if p.sewage.result else None
            ),
            "riser_count": len(p.sewage.risers),
            "checked_count": (
                p.sewage.result.checked_risers if p.sewage.result else 0
            ),
            "outlets_count": p.sewage.outlets_count,
            "scheme_ready": wastewater_topology.ready,
            "scheme_missing": (
                wastewater_topology.errors
                if wastewater_topology.errors
                else (
                    [
                        "Не заполнена направленная топология: стояки, "
                        "этажные ветви с приборами, подвальные магистрали "
                        "и выпуски."
                    ]
                    if not wastewater_topology.ready else []
                )
            ),
        },
        "storm": {
            "required": p.storm.system_kind == "internal",
            "flow": (
                p.storm.result.q_total_l_per_s if p.storm.result else None
            ),
            "funnels_count": p.storm.funnels_count,
            "risers_count": p.storm.risers_count,
            "status": (
                p.storm.network_assessment.status
                if p.storm.network_assessment else "stage_r"
            ),
        },
        "pump_duty": (b.fire_hydraulic_result.pump_duty
                      if b.fire_hydraulic_result else None),
    })


@router.get("/proof/{run_id}")
def wizard_proof(run_id: str):
    """Машиночитаемый доказательный граф того же расчётного прогона."""
    run = _get_run(run_id)
    if run is None:
        return JSONResponse({"detail": "прогон не найден"}, status_code=404)
    graph = run["proof_graph"]
    filename = f"zarya-proof-{graph.project_fingerprint}.json"
    return JSONResponse(
        graph.to_dict(),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/impact/{run_id}")
def wizard_impact(run_id: str, data: ImpactPreviewInput):
    """Предпросмотр «было → станет» без сохранения и выпуска документов."""
    run = _get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="прогон не найден")
    try:
        preview = calculate_impact_preview(
            run["request"],
            run["bundle"].project,
            run["bundle"].commission_report,
            data,
        )
    except ImpactValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(preview.to_dict())


@router.get("/defense/{run_id}", response_class=HTMLResponse)
def wizard_defense(request: Request, run_id: str):
    """Полноэкранный режим живой защиты выпущенного расчётного прогона."""
    run = _get_run(run_id)
    if run is None:
        return HTMLResponse("<h2>Прогон не найден</h2>", status_code=404)
    bundle = run["bundle"]
    documents, _ = _run_documents(run)
    defense = run.get("defense_payload")
    if defense is None:
        defense = build_defense_payload(
            run["proof_graph"],
            documents,
            run["outdir"],
            run_id=run_id,
        )
        run["defense_payload"] = defense
    primary_id = "v1-pump"
    if not any(row["id"] == primary_id for row in defense["decisions"]):
        primary_id = defense["decisions"][0]["id"]
    passport = next(
        (
            document for document in documents
            if document["label"] == "Паспорт проекта и нормативный контроль"
        ),
        None,
    )
    project = bundle.project
    commission = bundle.commission_report
    return _TPL.TemplateResponse(request, "wizard_defense.html", {
        "run_id": run_id,
        "defense": defense,
        "primary_id": primary_id,
        "passport": passport,
        "passport_id": run.get("passport_id"),
        "passport_url": run.get("passport_url"),
        "impact": impact_form_context(run["request"]),
        "commission": commission,
        "project": {
            "title": project.document.object_name or "Комплект без реквизитов",
            "cipher": project.document.cipher,
            "stage": project.document.stage_label,
            "purpose": project.building.purpose.value,
            "floors": project.building.floors_above,
            "height": project.building.height_m,
            "fire_height": project.building.fire_height_m,
        },
    })


@router.post("/defense/{run_id}/answer")
def wizard_defense_answer(
    run_id: str,
    decision_id: str = Form(...),
    question: str = Form(""),
):
    """Сформировать проверяемый PDF-ответ по уже рассчитанному решению."""
    run = _get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="прогон не найден")
    if len(question) > 1000:
        raise HTTPException(status_code=422, detail="вопрос длиннее 1000 знаков")
    decision = next(
        (
            row for row in run["proof_graph"].decisions
            if row.id == decision_id
        ),
        None,
    )
    if decision is None:
        raise HTTPException(status_code=404, detail="решение не найдено")
    documents, _ = _run_documents(run)
    defense = run.get("defense_payload") or build_defense_payload(
        run["proof_graph"],
        documents,
        run["outdir"],
        run_id=run_id,
    )
    run["defense_payload"] = defense
    evidence = next(
        row["documents"] for row in defense["decisions"]
        if row["id"] == decision_id
    )
    output_name = f"Ответ_эксперту_{decision_id}.pdf"
    try:
        output_path = str(_RELEASE_STORE.answer_path(run_id, output_name))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="выпуск не найден") from exc
    generate_expert_response_pdf(
        run["bundle"].project,
        run["proof_graph"],
        decision,
        question,
        evidence,
        output_path,
    )
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=output_name,
    )


@router.get("/view/{run_id}/{name}")
def wizard_view(run_id: str, name: str):
    """Открыть выпущенный PDF внутри Defense без принудительного скачивания."""
    run = _get_run(run_id)
    if run is None:
        return HTMLResponse("нет прогона", status_code=404)
    path = _run_file(run, name)
    if path is None:
        return HTMLResponse("нет файла", status_code=404)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/file/{run_id}/{name}")
def wizard_file(run_id: str, name: str):
    run = _get_run(run_id)
    if run is None:
        return HTMLResponse("нет прогона", status_code=404)
    path = _run_file(run, name)
    if path is None:
        return HTMLResponse("нет файла", status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=name)


# ── МОИ ПРОЕКТЫ (персистентность поверх YAML-стора) ─────────────────────────

@router.get("/projects", response_class=HTMLResponse)
def wizard_projects(request: Request):
    """Список сохранённых проектов."""
    return _TPL.TemplateResponse(request, "wizard_projects.html",
                                 {"projects": _STORE.list()})


@router.get("/open/{project_id}", response_class=HTMLResponse)
def wizard_open(request: Request, project_id: str):
    """Открыть сохранённый проект: форма, предзаполненная из YAML."""
    try:
        req_dto = _STORE.load(project_id)
    except (FileNotFoundError, ValueError):
        return HTMLResponse("<h2>Проект не найден</h2>", status_code=404)
    return _TPL.TemplateResponse(request, "wizard_form.html", {
        **_form_context(errors=[], advisories=review_request(req_dto)),
        "prefill": req_dto, "project_id": project_id})


@router.post("/projects/{project_id}/delete")
def wizard_delete(project_id: str):
    try:
        _STORE.delete(project_id)
    except ValueError:
        pass
    return RedirectResponse(url="/wizard/projects", status_code=303)
