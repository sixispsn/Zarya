"""Комиссионный паспорт: воспроизводимость, трассировка и контроль выпуска.

Модуль не выполняет новых инженерных расчётов. Он читает уже полученные
результаты Project и объясняет, из каких данных и нормативных решений собран
комплект, а также честно показывает незакрытые вопросы стадии П/Р.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.pz.project import BuildingPurpose, Project
from app.pz.rules import decide_fire_network, project_governing_head
from app.pz.pump_validation import check_project_booster
from app.normative.baseline import get_active_baseline


APP_VERSION = "0.6.1"
@dataclass(frozen=True)
class PassportItem:
    label: str
    value: str


@dataclass(frozen=True)
class TraceRow:
    requirement: str
    reference: str
    source_data: str
    decision: str
    deliverable: str
    status: str = "specified"


@dataclass(frozen=True)
class ControlCheck:
    code: str
    check: str
    status: str
    result: str
    action: str
    reference: str
    blocking: bool = False


@dataclass
class CommissionReport:
    passport: list[PassportItem] = field(default_factory=list)
    trace_rows: list[TraceRow] = field(default_factory=list)
    checks: list[ControlCheck] = field(default_factory=list)
    normative_audits: list[dict] = field(default_factory=list)
    project_fingerprint: str = ""
    legacy_fingerprint: str = ""
    build_commit: str = ""
    generated_at: str = ""

    @property
    def blocking_count(self) -> int:
        return sum(1 for row in self.checks if row.blocking)

    @property
    def pending_r_count(self) -> int:
        return sum(1 for row in self.checks if row.status == "stage_r")

    @property
    def release_status(self) -> str:
        if self.blocking_count:
            return "Есть блокирующие замечания к исходным данным или расчётам"
        return "Комплект пригоден для рассмотрения на стадии П"


def _ru(value: Optional[float], precision: int = 2, suffix: str = "") -> str:
    if value is None:
        return "не задано"
    return f"{value:.{precision}f}".replace(".", ",") + suffix


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "недоступен"
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _git_commit(repo_root: Path) -> str:
    configured = os.environ.get("ZARYA_BUILD_COMMIT", "").strip()
    if configured:
        return configured[:16]
    git_dir = repo_root / ".git"
    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return "не задан в сборке"
    head = head_path.read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head[:16]
    ref = head.removeprefix("ref: ").strip()
    ref_path = git_dir / ref
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8").strip()[:16]
    packed = git_dir / "packed-refs"
    if packed.exists():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith(("#", "^")):
                commit, name = line.split(" ", 1)
                if name == ref:
                    return commit[:16]
    return "не задан в сборке"


def _project_fingerprint(project: Project) -> str:
    """Стабильный отпечаток исходных данных, а не результатов/времени выпуска."""
    source = project.source
    payload = {
        "document": {
            "cipher": project.document.cipher,
            "name": project.document.object_name,
            "stage": project.document.stage_label,
        },
        "building": {
            "purpose": project.building.purpose.value,
            "floors": project.building.floors_above,
            "height_m": project.building.height_m,
            "fire_height_m": project.building.fire_height_m,
            "area_m2": project.building.total_area_m2,
            "apartments": project.building.apartments,
            "zones": project.building.zones,
        },
        "consumers": list(project.consumer_groups),
        "t3_sections": [vars(row) for row in project.t3_sections],
        "source": {
            "guaranteed_head_m": source.guaranteed_head_m,
            "maximum_head_m": source.maximum_head_m,
            "h_geom_m": source.h_geom_m,
            "h_il_m": source.h_il_m,
            "h_il_hot_m": source.h_il_hot_m,
            "internal_losses_scope": source.internal_losses_scope,
            "h_pr_m": source.h_pr_m,
            "h_vod_m": source.h_vod_m,
            "h_tepl_m": source.h_tepl_m,
            "h_vvod_m": source.h_vvod_m,
            "inputs_count": source.inputs_count,
        },
        "fire": {
            "mode": project.fire.determination_mode,
            "required": project.fire.required,
            "streams": project.fire.streams,
            "q_per_stream": project.fire.q_per_stream,
        },
        "storm": {
            "roof_type": project.storm.roof_type,
            "city": project.storm.city_code,
            "roof_area_m2": project.storm.roof_area_m2,
            "walls_area_m2": project.storm.walls_area_m2,
            "period_years": project.storm.period_years,
            "roof_sections": project.storm.roof_sections,
            "funnels_count": project.storm.funnels_count,
            "max_funnel_spacing_m": project.storm.max_funnel_spacing_m,
            "funnel_capacity_lps":
                project.storm.selected_funnel_capacity_lps,
            "max_funnel_flow_lps": project.storm.max_funnel_flow_lps,
            "risers_count": project.storm.risers_count,
            "riser_dn_mm": project.storm.selected_riser_dn_mm,
            "max_riser_flow_lps": project.storm.max_riser_flow_lps,
            "design_m3_day": project.storm.design_m3_day,
            "annual_m3": project.storm.annual_m3,
            "melt_m3h": project.storm.melt_m3h,
            "melt_m3_day": project.storm.melt_m3_day,
            "melt_m3_year": project.storm.melt_m3_year,
            "treatment_volume_m3": project.storm.treatment_volume_m3,
            "storage_volume_m3": project.storm.storage_volume_m3,
        },
        "sewage": {
            "q0s_lps": project.sewage_max_fixture_lps,
            "outlets_count": project.sewage.outlets_count,
            "risers": [vars(row) for row in project.sewage.risers],
            "pipes": [vars(row) for row in project.sewage.pipes],
            "elements": [vars(row) for row in project.sewage.elements],
            "discharge_events": [
                vars(row) for row in project.sewage.discharge_events
            ],
            "fixture_safety_inputs": [
                vars(row) for row in project.sewage.fixture_safety_inputs
            ],
            "first_manholes": [{
                **{
                    key: value for key, value in vars(row).items()
                    if key != "levels"
                },
                "levels": [vars(point) for point in row.levels],
            } for row in project.sewage.first_manholes],
            "internal_nodes": [
                vars(row) for row in project.sewage.internal_nodes
            ],
            "gost_inputs": {
                key: (value.to_mapping() if key in {
                    "presentation", "fan_ventilation", "fan_geometry",
                } and value is not None else value)
                for key, value in vars(project.sewage).items()
                if key not in {
                    "result", "hydraulic_assessment", "transient_assessment",
                    "risers", "pipes", "elements", "discharge_events",
                    "fixture_safety_inputs", "first_manholes",
                    "internal_nodes",
                }
            },
        },
        "catering": {
            "type": project.grease_trap.preparation_type,
            "seats": project.grease_trap.seats,
            "dishes": project.grease_trap.conditional_dishes,
            "school_assignment": project.grease_trap.school_by_assignment,
        },
        "owner_groups": project.meters.owner_groups_count,
        "meter_minimum_checks": project.source.meter_minimum_checks,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _cold_meter_loss(project: Project) -> Optional[float]:
    for row in project.meters.rows or []:
        if "ввод" in row.label.lower():
            return row.h_a
    for row in project.meters.rows or []:
        if "хвс" in row.label.lower() or "холодн" in row.label.lower():
            return row.h_a
    return project.source.h_vod_m


def _consumer_source(project: Project) -> str:
    if not project.consumer_groups:
        return "группы потребителей не заданы"
    details = []
    names = {
        code: name for name, code, _ in (project.consumer_details or [])
    }
    for code, count in project.consumer_groups:
        details.append(f"{names.get(code) or code}: {count}")
    return "; ".join(details)


def _systems(project: Project) -> str:
    systems = ["В1"]
    if project.building.hws_type.value != "none":
        systems.extend(("Т3", "Т4"))
    if project.fire.required:
        systems.append("В2")
    systems.append("К1")
    if project.storm.roof_type != "not_set":
        systems.append("К2")
    return ", ".join(systems)


def _purpose_label(purpose: BuildingPurpose) -> str:
    return {
        BuildingPurpose.RESIDENTIAL: "жилое",
        BuildingPurpose.PUBLIC: "общественное",
        BuildingPurpose.INDUSTRIAL: "производственное",
    }[purpose]


def build_commission_report(
    project: Project,
    artifacts: Optional[dict[str, bool]] = None,
) -> CommissionReport:
    repo_root = Path(__file__).resolve().parents[2]
    legacy_hash = _file_sha256(repo_root / "legacy" / "sp30_calculator.html")
    commit = _git_commit(repo_root)
    project_hash = _project_fingerprint(project)
    normative_baseline = get_active_baseline()
    generated_at = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M %Z")
    head = project_governing_head(
        project, fallback_h_vod_m=_cold_meter_loss(project),
    )
    fire_net = decide_fire_network(
        project.fire, project.materials, project.normative,
    )
    head_paths_complete = (
        project.head_paths is None or project.head_paths.complete
    )
    from app.pz.fire_calculation_evidence import fire_calculation_evidence
    fire_evidence = fire_calculation_evidence(project)
    from app.normative.audit_matrix import build_project_gost_matrices

    gost_matrices = build_project_gost_matrices(
        project,
        artifacts=artifacts,
        baseline=normative_baseline,
    )
    gost_by_discipline = {
        matrix.discipline: matrix for matrix in gost_matrices
    }

    passport = [
        PassportItem("Объект", project.document.object_name or "не задан"),
        PassportItem("Шифр / стадия", f"{project.document.cipher or 'без шифра'} / {project.document.stage_label}"),
        PassportItem(
            "Назначение и геометрия",
            f"{_purpose_label(project.building.purpose)}; "
            f"{project.building.floors_above} эт.; "
            f"{_ru(project.building.height_m, 1, ' м')}",
        ),
        PassportItem("Системы комплекта", _systems(project)),
        PassportItem("Расчётное ядро", f"legacy/sp30_calculator.html, SHA-256 {legacy_hash}"),
        PassportItem("Версия приложения / commit", f"Zarya {APP_VERSION} / {commit}"),
        PassportItem("Fingerprint исходных данных", project_hash),
        PassportItem(
            "Нормативная база",
            normative_baseline.commission_summary(),
        ),
        PassportItem(
            "Граница стадии",
            "Точные расходы и напоры — по введённым данным; количества и настройки, "
            "требующие планов/аксонометрии, маркируются для стадии Р.",
        ),
    ]

    flow_ok = bool(project.consumer_groups) and project.flows.q_day_tot > 0
    transient = project.sewage.transient_assessment
    fixture_checks = list(
        getattr(transient, "fixture_checks", ()) if transient else ()
    )
    fixture_safety_ok = bool(fixture_checks) and all(
        row.status.value == "Норма" for row in fixture_checks
    )
    fixture_safety_critical = any(
        row.status.value in {"Критическое состояние", "Подпор", "Подтопление"}
        for row in fixture_checks
    )
    internal_node_checks = list(
        getattr(transient, "internal_node_summaries", ()) if transient else ()
    )
    internal_node_overflow = any(
        row.status.value == "overflow" for row in internal_node_checks
    )
    internal_nodes_ok = bool(internal_node_checks) and not internal_node_overflow
    trace_rows = [
        TraceRow(
            "Расчётные расходы В1/Т3",
            "СП 30.13330.2020, приложение А",
            _consumer_source(project),
            (
                f"Qсут={_ru(project.flows.q_day_tot, 2, ' м³/сут')}; "
                f"qсек={_ru(project.flows.q_sec_tot, 3, ' л/с')}"
                if flow_ok else "расчёт не подтверждён"
            ),
            "ПЗ, подп. г; Расчёты В1; Баланс ВиВ",
            "verified" if flow_ok else "missing",
        ),
        TraceRow(
            "Расчётный расход К1",
            "СП 30.13330.2020, п. 5.5, формула (5)",
            (
                f"qtot={_ru(project.flows.q_sec_tot, 3, ' л/с')}; "
                f"q0s={_ru(project.sewage_max_fixture_lps, 3, ' л/с')}"
            ),
            (
                f"qs={_ru(project.sewage.result.total.q_sewage_lps, 3, ' л/с')}"
                if project.sewage.result else "расчёт не подтверждён"
            ),
            "ПЗ К1/К2; Расчёты К1/К2; схема К1/К2",
            "verified" if project.sewage.result else "missing",
        ),
        TraceRow(
            "Гидрозатворы и подпор от первого колодца",
            "СП 30.13330.2020, раздел 19",
            (
                f"точных привязок приборов: {len(fixture_checks)}; "
                f"первых колодцев: {len(project.sewage.first_manholes)}"
                if fixture_checks else
                "абсолютные отметки приборов/уровни первых колодцев не заданы"
            ),
            (
                "гидрозатворы сохранены, подпор к приборам отсутствует"
                if fixture_safety_ok else
                "обнаружено критическое состояние/подпор"
                if fixture_safety_critical else
                "требуются точные высотные и граничные данные"
            ),
            "Расчёты К1/К2 — временной сценарий",
            (
                "verified" if fixture_safety_ok else
                "fail" if fixture_safety_critical else "stage_r"
            ),
        ),
        TraceRow(
            "Локализация накопления и аварийного перелива К1",
            "СП 30.13330.2020, раздел 19; профиль и аксонометрия К1",
            (
                f"внутренних узлов с точной геометрией: "
                f"{len(project.sewage.internal_nodes)}"
                if project.sewage.internal_nodes else
                "отметки перелива и объёмы внутренних узлов не заданы"
            ),
            (
                "перелив в расчётном сценарии отсутствует"
                if internal_nodes_ok else
                "обнаружен аварийный перелив в зарегистрированном узле"
                if internal_node_overflow else
                "место выхода воды нельзя подтвердить"
            ),
            "Расчёты К1/К2 — временной сценарий",
            (
                "verified" if internal_nodes_ok else
                "fail" if internal_node_overflow else "stage_r"
            ),
        ),
        TraceRow(
            "Требуемый напор В1",
            "СП 30.13330.2020, п. 8.27, формула (14)",
            (
                f"Hгеом={_ru(head.h_geom_m, 2, ' м')}; "
                f"ΣHпот={_ru(head.h_losses_dynamic_m, 2, ' м')}; "
                f"Hпр={_ru(head.h_pr_m, 2, ' м')}; "
                f"Hгар={_ru(head.h_guaranteed_m, 2, ' м')}"
            ),
            (
                f"Hтр={_ru(head.h_required_m, 2, ' м')}; "
                f"насос {'требуется' if head.pump_needed else 'не требуется'}"
                if head.h_required_m is not None and head.pump_needed is not None
                else "исходные данные недостаточны"
            ),
            "ПЗ, подп. е; Расчёты В1; Подбор насосов",
            "verified" if head.h_required_m is not None and head_paths_complete else "missing",
        ),
        TraceRow(
            "Внутренний противопожарный водопровод",
            "СП 10.13130.2020, таблица 7.1 и разделы 6, 12",
            (
                f"режим={project.fire.determination_mode}; "
                f"hпт={_ru(project.building.fire_height_m, 1, ' м')}; "
                f"струй={project.fire.streams}"
            ),
            fire_evidence["result"],
            "ПЗ; схема; гидравлический расчёт; подбор насосов",
            fire_evidence["status"],
        ),
    ]

    if project.normative.separate_v1_v2_required:
        trace_rows.append(TraceRow(
            "Раздельные системы В1 и В2 высотного здания",
            "СП 253.1325800.2016, п. 10.3",
            f"высота здания {_ru(project.building.height_m, 1, ' м')}",
            fire_net.summary if fire_net else "В2 не определён",
            "ПЗ, подп. в; схема; спецификация",
            "specified" if fire_net and not fire_net.combined else "missing",
        ))
    if project.normative.apartment_hose_tap_required:
        trace_rows.append(TraceRow(
            "Квартирный кран Ду15 со шлангом и распылителем",
            "СП 54.13330.2022, п. 6.2.4.3",
            f"квартир: {project.building.apartments or 'не задано'}",
            (
                f"{project.building.apartments} комплектов"
                if project.building.apartments else "количество не определено"
            ),
            "ПЗ, подп. в; спецификация В1",
            "specified" if project.building.apartments else "missing",
        ))
    if project.normative.sp253_applicable:
        trace_rows.extend((
            TraceRow(
                "Теплоизоляция трубопроводов высотного здания",
                "СП 253.1325800.2016, п. 10.15",
                "расчёт толщины legacy + нормативный минимум",
                "ХВС ≥10 мм; ГВС и циркуляция ≥25 мм",
                "ПЗ, подп. в; спецификация В1/Т3-Т4",
                "specified",
            ),
            TraceRow(
                "Резервирование, привод и управление насосами",
                "СП 253.1325800.2016, пп. 10.23, 10.25, 10.27",
                "рабочие точки В1/В2 по расчёту напора",
                "100% резерв; регулируемый привод; диспетчеризация",
                "ПЗ; подбор насосов; спецификация",
                "specified",
            ),
        ))
    if project.normative.separate_owner_metering_required:
        trace_rows.append(TraceRow(
            "Автономный учёт групп разных собственников",
            "СП 118.13330.2022, п. 8.24",
            f"групп собственников: {project.meters.owner_groups_count}",
            "самостоятельные узлы учёта ХВС и ГВС",
            "ПЗ, подп. л; спецификация В1/Т3-Т4",
            "specified",
        ))
    if project.normative.separate_k1_required:
        trace_rows.append(TraceRow(
            "Раздельные выпуски канализации функциональных частей",
            "СП 253.1325800.2016, п. 11.2",
            "смешанный функциональный состав высотного здания",
            "самостоятельные системы и выпуски К1",
            "ПЗ; графические решения стадии Р",
            "stage_r",
        ))
    if project.storm.roof_type != "not_set":
        storm_result = project.storm.result
        trace_rows.append(TraceRow(
            "Система К2 и расход дождевых вод",
            "СП 30.13330.2020, пп. 21.5–21.12",
            (
                f"кровля={project.storm.roof_type}; город={project.storm.city_code or 'не задан'}; "
                f"Fкр={_ru(project.storm.roof_area_m2, 1, ' м²')}"
            ),
            (
                f"{project.storm.system_note} Q={_ru(storm_result.q_total_l_per_s, 3, ' л/с')}"
                if storm_result else project.storm.system_note
            ),
            "ПЗ К1/К2; Расчёты К1/К2; схема К1/К2; спецификация К1/К2",
            "verified" if storm_result else "missing",
        ))
    if project.grease_trap.preparation_type != "none":
        trace_rows.append(TraceRow(
            "Жироуловители производственных стоков",
            "СП 118.13330.2022, п. 8.7",
            (
                f"тип={project.grease_trap.preparation_type}; "
                f"мест={project.grease_trap.seats}; "
                f"блюд={project.grease_trap.conditional_dishes}"
            ),
            project.grease_trap.decision_note,
            "ПЗ; спецификация К1",
            "stage_r" if project.grease_trap.required else "verified",
        ))

    checks: list[ControlCheck] = []

    def add(
        code: str,
        check: str,
        status: str,
        result: str,
        action: str,
        reference: str,
        blocking: bool = False,
    ) -> None:
        checks.append(ControlCheck(
            code, check, status, result, action, reference, blocking,
        ))

    add(
        "SRC-01", "Группы потребителей заданы",
        "verified" if project.consumer_groups else "missing",
        _consumer_source(project),
        "Нет действий" if project.consumer_groups else "Заполнить блок 02 Wizard",
        "СП 30.13330.2020, приложение А",
        blocking=not bool(project.consumer_groups),
    )
    add(
        "CALC-01", "Расходы В1/Т3/К1 рассчитаны",
        "verified" if flow_ok else "missing",
        (
            f"Qсут={_ru(project.flows.q_day_tot, 2, ' м³/сут')}; "
            f"qсек={_ru(project.flows.q_sec_tot, 3, ' л/с')}"
            if flow_ok else "расчётного результата нет"
        ),
        "Нет действий" if flow_ok else "Проверить группы потребителей",
        "СП 30.13330.2020, приложение А",
        blocking=not flow_ok,
    )
    head_ok = head.h_required_m is not None and head.h_guaranteed_m is not None and head_paths_complete
    add(
        "CALC-02", "Требуемый и гарантированный напоры сопоставлены",
        "verified" if head_ok else "missing",
        (
            f"Hтр={_ru(head.h_required_m, 2, ' м')}; "
            f"Hгар={_ru(head.h_guaranteed_m, 2, ' м')}"
        ),
        "Нет действий" if head_ok else "Получить ТУ и заполнить составляющие Hтр",
        "СП 30.13330.2020, п. 8.27",
        blocking=not head_ok,
    )
    if project.t3_sections:
        t3 = project.t3_hydraulic_result
        t3_ok = bool(t3 and t3.total_loss_m is not None and t3.all_velocities_ok)
        add(
            "CALC-T3", "Заданный путь Т3 и скорости проверены",
            "verified" if t3_ok else "missing",
            (f"ΣHil={_ru(t3.total_loss_m, 3, ' м')}; отдельное расширение ядра"
             if t3_ok else "; ".join(t3.missing) if t3 and t3.missing
             else "Расчёт отсутствует либо превышен заданный предел скорости"),
            "Нет действий" if t3_ok else "Уточнить путь, учёт циркуляции и сечения Т3",
            "СП 30.13330.2020, пп. 10.9, 10.11, 8.26; приложение Г",
            blocking=not t3_ok,
        )
    from app.pz.meter_validation import check_meter_average
    average_checks = [check_meter_average(row, project.flows, project.source)
                      for row in project.meters.rows]
    from app.pz.meter_products import evaluate_meter_product
    product_checks = [evaluate_meter_product(project, row) for row in project.meters.rows]
    product_errors = [e for c in product_checks for e in c.errors]
    meters_ok = (not project.meters.selection_error and bool(project.meters.rows)
                 and not product_errors and all(ok is True for ok, _ in average_checks)) and all(
        row.ok_a and (row.ok_b or row.need_bypass) and
        (check.minimum_ok if (check.product or check.automatic or check.errors) else row.ok_v) is True
        for row, check in zip(project.meters.rows, product_checks)
    )
    add(
        "CALC-03", "Водомерные узлы подобраны по расчётным расходам",
        "verified" if meters_ok else "fail" if project.meters.selection_error
        or product_errors or any(ok is False for ok, _ in average_checks) else "missing",
        (f"расчётных узлов: {len(project.meters.rows or [])}; "
         + (project.meters.selection_error + "; " if project.meters.selection_error else "")
         + "; ".join(note for ok, note in average_checks if ok is not True)
         + "; ".join(
            f"{r.label}: {c.minimum_note if (c.product or c.automatic or c.errors) else r.minimum_flow_note or 'проверка минимального расхода не подтверждена'}"
            for r, c in zip(project.meters.rows, product_checks)
            if c.errors or (c.minimum_ok if (c.product or c.automatic) else r.ok_v) is not True
        )),
        "Нет действий" if meters_ok else "Проверить Qсред ≤ Qэкспл и потери; подтвердить минимальный часовой расход и паспорт выбранного счётчика",
        "СП 30.13330.2020, раздел 12",
        blocking=not meters_ok,
    )
    # Composition is independent of legacy hydraulics. A known incompatible
    # device/location must not become releasable merely because Q and H pass.
    from app.pz.metering_detail import drawing_state as metering_state
    from app.pz.metering_rules import evaluate_metering_rules, special_layout_pending
    ms = metering_state(project)
    vu_rules = evaluate_metering_rules(project, ms.meter,
                                       inputs_count=ms.inputs_count, bypass=ms.bypass)
    vu_errors = [r for r in vu_rules if r.status == "error"]
    vu_special = special_layout_pending(project)
    # Pending passport/installation information remains visible in the rule
    # sheets and bundle warnings; this gate rejects known contradictions and
    # an unimplemented special physical layout, not unspecified mounting mm.
    vu_result = "; ".join(f"{r.code}: {r.message}" for r in vu_errors)
    if vu_special:
        vu_result += "; Специальная компоновка ввода не сформирована"
    add("VU-COMPOSITION", "Водомерный узел: противоречия и особые условия",
        "fail" if vu_errors else "missing" if vu_special else "specified",
        vu_result.lstrip("; ") or "Явных противоречий не обнаружено; незакрытые условия см. на листах компоновки",
        "Исправить решение и подтвердить привязку; расчётные Q/H автоматически не меняются",
        "СП 30.13330.2020, разделы 12, 15.2, 15.4",
        blocking=bool(vu_errors or vu_special))
    from app.pz.metering_hot_node import hot_meter_view
    hot_view = hot_meter_view(project)
    if hot_view is not None:
        from app.pz.metering_detail import drawing_state
        from app.pz.metering_product_selection import resolve_metering_products
        hot_state = drawing_state(hot_view)
        hot_selection = resolve_metering_products(hot_view, hot_state.meter,
                                                  bypass=False, electric_bypass=False)
        hot_errors = list(hot_selection.errors)
        if hot_state.meter is None:
            hot_errors.extend(hot_state.missing)
        add("VU-HOT-COMPOSITION", "Горячий узел учёта: независимость и комплектация",
            "fail" if hot_errors else "specified",
            "; ".join(dict.fromkeys(hot_errors)) or
            "Отдельный узел и спецификация; монтажная привязка и условия применения требуют подтверждения",
            "Проверить исходные горячего узла; обвязка холодного ввода не переносится",
            "СП 30.13330.2020, пп. 12.8–12.13; ГОСТ Р 21.619-2023, п. 5.2.2.6",
            blocking=bool(hot_errors))
    pump_status, pump_result = check_project_booster(project, head)
    pump_blocking = pump_status in {"missing", "fail"}
    add(
        "CALC-04", "Насос В1 обеспечивает полную расчётную пару Q/H",
        pump_status, pump_result,
        "Пересчитать подбор по актуальным исходным и каталожной кривой" if pump_blocking
        else "Подтвердить остальные условия установки" if pump_status == "verified"
        else "Нет действий",
        "СП 30.13330.2020, пп. 13.9, 13.11; без регулирующей ёмкости",
        blocking=pump_blocking,
    )
    add(
        "FIRE-01", "Применимость и расчётные параметры В2",
        fire_evidence["status"], fire_evidence["result"], fire_evidence["action"],
        "СП 10.13130.2020",
        blocking=fire_evidence["status"] in {"missing", "fail"},
    )
    if fire_evidence["preliminary"]:
        add("FIRE-L06", "Проектная применимость предварительного варианта В2",
            "missing", "Расчётная матрица проверена; паспортные ограничения и NPSH, покрытие помещений "
            "и соответствие модели реальным ремонтным секциям не подтверждены.",
            "Подтвердить оборудование и увязку модели с планами; не повторять уже выполненный расчёт",
            "СП 10.13130.2020; ГОСТ Р 21.619-2023, пп. 5.1.8, 5.2.2", blocking=True)
    if project.normative.apartment_hose_tap_required:
        apartment_ok = project.building.apartments > 0
        add(
            "SP54-01", "Количество квартирных кранов Ду15 определено",
            "specified" if apartment_ok else "missing",
            (
                f"{project.building.apartments} комплектов"
                if apartment_ok else "число квартир не задано"
            ),
            "Нет действий" if apartment_ok else "Получить экспликацию квартир АР",
            "СП 54.13330.2022, п. 6.2.4.3",
            blocking=not apartment_ok,
        )
    if project.normative.sp253_applicable:
        add(
            "SP253-01", "Раздельные В1/В2 и требования к оборудованию учтены",
            "specified",
            "В1/В2 раздельные; изоляция 10/25 мм; резерв и регулируемый привод",
            "Подтвердить марки и сигналы диспетчеризации на стадии Р",
            "СП 253.1325800.2016, пп. 10.3, 10.15, 10.23, 10.25, 10.27",
        )
    sewage_ok = project.sewage.result is not None
    add(
        "K1-00", "Расчётный расход К1 подтверждён",
        "verified" if sewage_ok else "missing",
        (
            f"Q={_ru(project.sewage.result.total.q_sewage_lps, 3, ' л/с')}"
            if sewage_ok else "нет групп потребителей"
        ),
        "Нет действий" if sewage_ok else "Заполнить группы потребителей",
        "СП 30.13330.2020, п. 5.5, формула (5)",
        blocking=not sewage_ok,
    )
    if project.sewage.risers:
        failed_risers = [
            row.riser_id for row in project.sewage.result.risers
            if row.status == "fail"
        ] if sewage_ok else []
        pending_risers = [
            row.riser_id for row in project.sewage.result.risers
            if row.status in ("missing", "stage_r")
        ] if sewage_ok else []
        riser_status = (
            "missing" if not sewage_ok or failed_risers
            else "stage_r" if pending_risers
            else "verified"
        )
        add(
            "K1-02", "Характерные стояки К1 проверены по приложению К",
            riser_status,
            (
                "общий расход К1 не рассчитан"
                if not sewage_ok else
                "не соответствуют: " + ", ".join(failed_risers)
                if failed_risers else
                "требуют точной аксонометрии: " + ", ".join(pending_risers)
                if pending_risers else
                f"проверено {len(project.sewage.result.risers)} стояков"
            ),
            (
                "Проверить диаметр и назначенную нагрузку"
                if failed_risers else
                "Завершить по аксонометрии стадии Р"
                if pending_risers else "Нет действий"
            ),
            "СП 30.13330.2020, пп. 19.7–19.8, приложение К",
            blocking=bool(failed_risers),
        )
    add(
        "K1-03", "Конкретные гидрозатворы проверены по давлению стояков и уровню первого колодца",
        (
            "verified" if fixture_safety_ok else
            "missing" if fixture_safety_critical else "stage_r"
        ),
        (
            f"проверено {len(fixture_checks)} приборов; срыв и подпор отсутствуют"
            if fixture_safety_ok else
            "обнаружено критическое состояние, подпор или подтопление"
            if fixture_safety_critical else
            "нет полной абсолютной привязки приборов и первых колодцев"
        ),
        (
            "Нет действий" if fixture_safety_ok else
            "Устранить причину подпора/срыва и пересчитать"
            if fixture_safety_critical else
            "Задать абсолютные отметки, гидрозатворы и уровни первых колодцев"
        ),
        "СП 30.13330.2020, раздел 19; профиль выпуска",
        blocking=fixture_safety_critical,
    )
    add(
        "K1-04", "Накопление и аварийный перелив локализованы внутренними узлами",
        (
            "verified" if internal_nodes_ok else
            "missing" if internal_node_overflow else "stage_r"
        ),
        (
            f"проверено узлов: {len(internal_node_checks)}; перелив отсутствует"
            if internal_nodes_ok else
            "в расчётном сценарии зафиксирован аварийный перелив"
            if internal_node_overflow else
            "нет полного реестра отметок перелива и доступных объёмов"
        ),
        (
            "Нет действий" if internal_nodes_ok else
            "Устранить перегрузку и пересчитать сценарий"
            if internal_node_overflow else
            "Задать внутренние узлы по аксонометрии и планам АР"
        ),
        "СП 30.13330.2020, раздел 19; профиль и аксонометрия К1",
        blocking=internal_node_overflow,
    )
    if project.sewage.pipes:
        diagnostic = project.sewage.hydraulic_assessment
        diagnostic_errors = diagnostic.errors if diagnostic else []
        diagnostic_warnings = diagnostic.warnings if diagnostic else []
        add(
            "K1-05", "Диаметры, вентиляция и доступность обслуживания самотёчной сети",
            "missing" if diagnostic_errors else
            "stage_r" if diagnostic is None or diagnostic_warnings else "verified",
            ("; ".join(diagnostic_errors or diagnostic_warnings)
             or "рассчитанная диагностика сети не содержит ошибок") if diagnostic else
            "диагностика сети не выполнена",
            "Исправить перечисленные участки по подтверждённой трассировке и пересчитать"
            if diagnostic_errors else
            "Дополнить данные для диагностики сети" if diagnostic is None or diagnostic_warnings
            else "Нет действий",
            "СП 30.13330.2020, пп. 18.26–18.27, таблица 18.1; пп. 21.8, 21.15",
            blocking=bool(diagnostic_errors),
        )
    if project.storm.system_kind == "internal":
        storm_ok = project.storm.result is not None
        add(
            "K2-01", "Расход внутреннего водостока рассчитан",
            "verified" if storm_ok else "missing",
            (
                f"Q={_ru(project.storm.result.q_total_l_per_s, 3, ' л/с')}"
                if storm_ok else "нет города и/или площади кровли"
            ),
            "Нет действий" if storm_ok else "Заполнить исходные данные К2",
            "СП 30.13330.2020, раздел 21",
            blocking=not storm_ok,
        )
        assessment = project.storm.network_assessment
        assessment_status = (
            "missing" if assessment and assessment.status == "fail"
            else assessment.status if assessment else "stage_r"
        )
        assessment_detail = "; ".join(assessment.notes) if assessment else ""
        if not assessment_detail:
            missing = []
            for field_name, label in (
                ("funnels_count", "количество воронок по плану кровли"),
                ("selected_funnel_capacity_lps", "паспортная пропускная способность воронки"),
                ("max_funnel_flow_lps", "нагрузка на диктующую воронку"),
                ("risers_count", "количество стояков К2"),
                ("selected_riser_dn_mm", "DN стояка К2"),
                ("max_riser_flow_lps", "нагрузка на диктующий стояк"),
            ):
                if not assessment or not getattr(assessment, field_name):
                    missing.append(label)
            assessment_detail = (
                ("Расход кровли рассчитан. " if storm_ok else "Расход кровли не рассчитан. ")
                + ("Для проверки элементов не заданы: " + "; ".join(missing) + "."
                   if missing else "Подробности проверки элементов К2 не представлены.")
            )
        add(
            "K2-02", "Воронки и стояки К2 проверены по плану кровли",
            assessment_status,
            assessment_detail,
            (
                "Исправить несоответствие исходных данных"
                if assessment and assessment.status == "fail"
                else "Разработать планы и аксонометрию на стадии Р"
                if assessment_status == "stage_r"
                else "Нет действий"
            ),
            "СП 30.13330.2020, пп. 21.5, 21.6, таблица 21.1",
            blocking=bool(assessment and assessment.status == "fail"),
        )
    if project.grease_trap.required:
        add(
            "K1-01", "Жироуловители предусмотрены",
            "stage_r",
            "необходимость подтверждена; число и производительность не назначены",
            "Получить задание ТХ и схему производственных выпусков",
            "СП 118.13330.2022, п. 8.7",
        )
    if project.normative.separate_owner_metering_required:
        add(
            "METER-01", "Раздельный учёт собственников предусмотрен",
            "specified",
            f"групп собственников: {project.meters.owner_groups_count}",
            "Уточнить границы балансовой принадлежности и Ду на стадии Р",
            "СП 118.13330.2022, п. 8.24",
        )
    add(
        "STAGE-01", "Граница стадии П/Р соблюдена",
        "stage_r",
        "циркуляционные расходы ветвей Т4, Kv балансиров и окончательные "
        "рабочие точки без аксонометрии не выдаются",
        "Закрыть после разработки точной аксонометрии стадии Р",
        "Правила расчётного ядра Zarya; СП 30.13330.2020",
    )
    if artifacts is not None:
        from app.pz.artifact_readiness import COMMISSION_DOCUMENT_ARTIFACTS
        core_names = COMMISSION_DOCUMENT_ARTIFACTS["DOC-01"]
        missing_documents = [name for name in core_names if not artifacts.get(name)]
        add(
            "DOC-01", "Основные документы комплекта сформированы",
            "verified" if not missing_documents else "missing",
            (
                "ПЗ, расчёты, баланс, подбор насосов, спецификация и схема сформированы"
                if not missing_documents else
                "не сформированы: " + ", ".join(missing_documents)
            ),
            "Нет действий" if not missing_documents else "Устранить ошибку сборки документа",
            "ПП РФ № 87; ГОСТ Р 21.619-2023",
            blocking=bool(missing_documents),
        )
        wastewater_names = COMMISSION_DOCUMENT_ARTIFACTS["DOC-03"]
        missing_wastewater = [
            name for name in wastewater_names if not artifacts.get(name)
        ]
        add(
            "DOC-03", "Самостоятельный комплект К1/К2 сформирован",
            "verified" if not missing_wastewater else "missing",
            (
                "ПЗ К1/К2 с расчётным приложением и балансом приложения А, "
                "схема, спецификация и единый PDF сформированы"
                if not missing_wastewater else
                "не сформированы: " + ", ".join(missing_wastewater)
            ),
            (
                "Нет действий" if not missing_wastewater
                else "Устранить ошибку сборки комплекта К1/К2"
            ),
            "ПП РФ № 87, пункт 18; ГОСТ Р 21.620-2023; СП 30.13330.2020",
            blocking=bool(missing_wastewater),
        )
        wastewater_audit = gost_by_discipline["ИОС3"]
        add(
            "DOC-04", "Состав ИОС3 проверен по ГОСТ Р 21.620-2023",
            "verified" if wastewater_audit.release_ready else "missing",
            (
                "машинная матрица требований не содержит блокировок выпуска"
                if wastewater_audit.release_ready else
                "не закрыты: " + "; ".join(
                    f"{row.rule_id} {row.title}: {row.evidence}"
                    for row in wastewater_audit.release_blockers
                )
            ),
            (
                "Нет действий" if wastewater_audit.release_ready else
                "Заполнить обязательные исходные данные ИОС3"
            ),
            "ГОСТ Р 21.620-2023, разделы 5-6",
            blocking=not wastewater_audit.release_ready,
        )
        water_audit = gost_by_discipline["ИОС2"]
        add(
            "DOC-05", "Состав ИОС2 проверен по ГОСТ Р 21.619-2023",
            "verified" if water_audit.release_ready else "missing",
            (
                "машинная матрица требований не содержит блокировок выпуска"
                if water_audit.release_ready else
                "не закрыты: " + "; ".join(
                    f"{row.rule_id} {row.title}: {row.evidence}"
                    for row in water_audit.release_blockers
                )
            ),
            (
                "Нет действий" if water_audit.release_ready else
                "Заполнить обязательные сведения и артефакты ИОС2"
            ),
            "ГОСТ Р 21.619-2023, раздел 5",
            blocking=not water_audit.release_ready,
        )
        hydraulic_exists = bool(artifacts.get("Гидравлический расчёт В2"))
        add(
            "DOC-02", "Расчётное обоснование В2 приложено",
            (
                "verified" if hydraulic_exists
                else "missing" if project.fire.required
                else "not_applicable"
            ),
            (
                "гидравлический расчёт В2 сформирован"
                if hydraulic_exists else
                "В2 требуется, расчётный лист отсутствует"
                if project.fire.required else
                "В2 не требуется"
            ),
            (
                "Нет действий" if hydraulic_exists or not project.fire.required
                else "Задать расчётную схему В2 и сформировать гидравлический лист"
            ),
            "СП 10.13130.2020",
            blocking=project.fire.required and not hydraulic_exists,
        )

    if project.rainwater_reuse.enabled:
        from app.calc.rainwater_reuse import assess as assess_rainwater
        from app.calc.rainwater_treatment import project_context
        rain = assess_rainwater(project.rainwater_reuse, **project_context(project))
        add(
            "RAIN-01", "Использование дождевой воды обосновано",
            "verified" if rain["design"]["confirmed"] else "missing",
            ("Решение подтверждено проектировщиком: " + rain["design"]["review"]["reviewer"]
             if rain["design"]["confirmed"] else
             "Паспорт дождевой системы: " + ("; ".join(rain["design"]["missing"])
             or "требуется актуальное подтверждение проектировщика")),
            "Хранить указанные расчёты и листы в комплекте. " + rain["design"]["notice"],
            "СП 30, пп. 4.10, 14.18, 23.5; ГОСТ Р 21.619-2023, п. 5.1.22",
            blocking=not rain["design"]["confirmed"],
        )
    if project.metering_detail.russian_equipment_only:
        from app.pz.equipment_origin import review_equipment_origin
        origin_review = review_equipment_origin(project)
        missing = [r["name"] for r in origin_review["rows"] if not r["ready"]]
        add("EQUIP-RU", "Оборудование российского производства",
            "verified" if origin_review["ready"] else "missing",
            "Происхождение подтверждено" if origin_review["ready"] else
            f"Не подтверждено позиций: {len(missing)}. " + "; ".join(missing[:6]),
            "Назначить изделия с подтверждённой страной производства. " + origin_review["notice"],
            "Требование заказчика к оборудованию", blocking=not origin_review["ready"])
    return CommissionReport(
        passport=passport,
        trace_rows=trace_rows,
        checks=checks,
        normative_audits=[matrix.to_dict() for matrix in gost_matrices],
        project_fingerprint=project_hash,
        legacy_fingerprint=legacy_hash,
        build_commit=commit,
        generated_at=generated_at,
    )
