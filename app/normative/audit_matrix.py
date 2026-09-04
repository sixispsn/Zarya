"""Машиночитаемые матрицы ГОСТ-аудита выпусков ИОС2 и ИОС3.

Матрица не выполняет инженерных расчётов и не подменяет отсутствующие данные.
Она связывает уже полученные факты/артефакты со стабильным ID требования,
пунктом конкретного документа из NormativeBaseline и итогом проверки.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Iterable

from app.normative.baseline import NormativeBaseline, get_active_baseline
from app.pz.project import BuildingPurpose, HwsType, Project


OPEN_STATUSES = frozenset({"missing", "fail"})


@dataclass(frozen=True)
class NormativeAuditRow:
    rule_id: str
    document_id: str
    baseline_id: str
    designation: str
    edition: str
    clauses: tuple[str, ...]
    part: str
    title: str
    systems: tuple[str, ...]
    fact_ids: tuple[str, ...]
    status: str
    evidence: str
    deliverables: tuple[str, ...]
    release_blocking: bool = True

    @property
    def reference(self) -> str:
        clauses = ", ".join(self.clauses)
        return f"{self.designation} ({self.edition}), {clauses}"

    @property
    def blocks_release(self) -> bool:
        return self.release_blocking and self.status in OPEN_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "document_id": self.document_id,
            "baseline_id": self.baseline_id,
            "designation": self.designation,
            "edition": self.edition,
            "clauses": list(self.clauses),
            "reference": self.reference,
            "part": self.part,
            "title": self.title,
            "systems": list(self.systems),
            "fact_ids": list(self.fact_ids),
            "status": self.status,
            "evidence": self.evidence,
            "deliverables": list(self.deliverables),
            "release_blocking": self.release_blocking,
            "blocks_release": self.blocks_release,
        }


@dataclass(frozen=True)
class NormativeAuditMatrix:
    discipline: str
    document_id: str
    baseline_id: str
    baseline_fingerprint: str
    rows: tuple[NormativeAuditRow, ...]
    schema_version: str = "1.0"

    @property
    def missing(self) -> tuple[NormativeAuditRow, ...]:
        return tuple(row for row in self.rows if row.status in OPEN_STATUSES)

    @property
    def release_blockers(self) -> tuple[NormativeAuditRow, ...]:
        return tuple(row for row in self.rows if row.blocks_release)

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def release_ready(self) -> bool:
        return not self.release_blockers

    @property
    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in self.rows:
            result[row.status] = result.get(row.status, 0) + 1
        return result

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self._unsigned_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "discipline": self.discipline,
            "document_id": self.document_id,
            "baseline_id": self.baseline_id,
            "baseline_fingerprint": self.baseline_fingerprint,
            "rows": [row.to_dict() for row in self.rows],
            "summary": {
                "total": len(self.rows),
                "counts": self.counts,
                "missing": len(self.missing),
                "release_blockers": len(self.release_blockers),
                "complete": self.complete,
                "release_ready": self.release_ready,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["fingerprint_sha256"] = self.fingerprint
        return payload


def _artifact_status(
    artifacts: dict[str, bool] | None,
    required: Iterable[str],
) -> tuple[str, str]:
    names = tuple(required)
    if artifacts is None:
        return "pending_build", "проверка артефакта выполняется после сборки"
    missing = [name for name in names if not artifacts.get(name)]
    if missing:
        return "missing", "не сформированы: " + ", ".join(missing)
    return "verified", "сформированы: " + ", ".join(names)


def _row_factory(
    baseline: NormativeBaseline,
    document_id: str,
):
    document = baseline.document(document_id)

    def make(
        rule_id: str,
        clauses: tuple[str, ...],
        part: str,
        title: str,
        systems: tuple[str, ...],
        fact_ids: tuple[str, ...],
        status: str,
        evidence: str,
        deliverables: tuple[str, ...],
        *,
        release_blocking: bool = True,
    ) -> NormativeAuditRow:
        return NormativeAuditRow(
            rule_id=rule_id,
            document_id=document.document_id,
            baseline_id=baseline.baseline_id,
            designation=document.designation,
            edition=document.edition,
            clauses=clauses,
            part=part,
            title=title,
            systems=systems,
            fact_ids=fact_ids,
            status=status,
            evidence=evidence,
            deliverables=deliverables,
            release_blocking=release_blocking,
        )

    return make


_IOS3_META: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "K-GOST-01": ("text", ("project.assignment", "survey.engineering"), ("Пояснительная записка К1/К2",)),
    "K-GOST-02": ("text", ("project.service_life", "project.overhaul_period"), ("Пояснительная записка К1/К2",)),
    "K-GOST-03": ("text", ("sewage.disposal_mode", "sewage.connection_tu"), ("Пояснительная записка К1/К2",)),
    "K-GOST-04": ("text", ("sewage.existing_network" ,), ("Пояснительная записка К1/К2",)),
    "K-GOST-04A": ("text", ("sewage.discharge_standard", "sewage.water_body"), ("Пояснительная записка К1/К2",)),
    "K-GOST-05": ("text", ("sewage.systems", "sewage.discharge_points"), ("Пояснительная записка К1/К2",)),
    "K-GOST-06": ("text", ("balance.rows",), ("Баланс ИОС3 по ГОСТ Р 21.620",)),
    "K-GOST-06A": ("text", ("sewage.flows", "sewage.quality"), ("Пояснительная записка К1/К2", "Расчёты К1/К2")),
    "K-GOST-07": ("text", ("sewage.pipes.geometry",), ("Пояснительная записка К1/К2", "Спецификация ИОС3")),
    "K-GOST-08": ("text", ("sewage.pipes.slope", "sewage.pipes.fill"), ("Расчёты К1/К2", "Принципиальная схема К1/К2")),
    "K-GOST-09": ("text", ("sewage.laying", "building.penetrations"), ("Пояснительная записка К1/К2",)),
    "K-GOST-10": ("text", ("sewage.pump" ,), ("Напорная канализация и рабочая точка",)),
    "K-GOST-11": ("text", ("sewage.treatment" ,), ("Пояснительная записка К1/К2",)),
    "K-GOST-12": ("text", ("sewage.waste_handling" ,), ("Пояснительная записка К1/К2",)),
    "K-GOST-13": ("graphic", ("sewage.topology", "sewage.elements"), ("Принципиальная схема К1/К2",)),
    "K-GOST-13A": ("text", ("sewage.external_scope",), ("Пояснительная записка К1/К2",)),
    "K-GOST-14": ("graphic", ("sewage.external_scheme",), ("Принципиальная схема наружных сетей",)),
    "K-GOST-15": ("graphic", ("sewage.site_plan",), ("План наружных сетей",)),
    "K-GOST-16": ("text", ("storm.flows",), ("Пояснительная записка К1/К2", "Расчёты К1/К2")),
}


def build_ios3_gost_matrix(
    project: Project,
    artifacts: dict[str, bool] | None = None,
    baseline: NormativeBaseline | None = None,
) -> NormativeAuditMatrix:
    """Адаптировать действующий ИОС3-аудит к единому контракту."""
    from app.pz.wastewater_gost import audit_wastewater_gost

    baseline = baseline or get_active_baseline()
    make = _row_factory(baseline, "gost_r_21_620_2023")
    rows: list[NormativeAuditRow] = []
    for check in audit_wastewater_gost(project).checks:
        part, fact_ids, deliverables = _IOS3_META[check.code]
        clause_text = check.reference.partition(",")[2].strip()
        clause_text = clause_text.removeprefix("пп. ").removeprefix("п. ")
        rows.append(make(
            check.code,
            (clause_text,),
            part,
            check.requirement,
            ("К1", "К2", "К3"),
            fact_ids,
            check.status,
            check.evidence,
            deliverables,
        ))

    for rule_id, clauses, title, required in (
        ("K-GOST-A01", ("5.1.1–5.1.6",), "Текстовая часть ИОС3 сформирована", ("Пояснительная записка К1/К2",)),
        ("K-GOST-A02", ("5.1.3.3", "приложение А"), "Баланс ИОС3 оформлен отдельным листом", ("Баланс ИОС3 по ГОСТ Р 21.620",)),
        ("K-GOST-A03", ("5.2.1.5", "5.2.2.1–5.2.2.4"), "Принципиальная схема внутренних систем сформирована", ("Принципиальная схема К1/К2",)),
    ):
        status, evidence = _artifact_status(artifacts, required)
        rows.append(make(
            rule_id, clauses, "artifact", title, ("К1", "К2", "К3"),
            tuple(f"artifact.{name}" for name in required), status, evidence,
            required,
        ))

    return NormativeAuditMatrix(
        discipline="ИОС3",
        document_id="gost_r_21_620_2023",
        baseline_id=baseline.baseline_id,
        baseline_fingerprint=baseline.fingerprint,
        rows=tuple(rows),
    )


def build_ios2_gost_matrix(
    project: Project,
    artifacts: dict[str, bool] | None = None,
    baseline: NormativeBaseline | None = None,
) -> NormativeAuditMatrix:
    """Сформировать профильную матрицу ГОСТ Р 21.619-2023 для ИОС2."""
    from app.pz.rules import project_governing_head

    baseline = baseline or get_active_baseline()
    make = _row_factory(baseline, "gost_r_21_619_2023")
    rows: list[NormativeAuditRow] = []
    source = project.source
    sewage = project.sewage
    meter_loss = source.h_vod_m
    for meter in project.meters.rows or []:
        if "ввод" in meter.label.lower():
            meter_loss = meter.h_a
            break
    else:
        for meter in project.meters.rows or []:
            if "хвс" in meter.label.lower() or "холодн" in meter.label.lower():
                meter_loss = meter.h_a
                break
    head = project_governing_head(project, fallback_h_vod_m=meter_loss)

    def add(
        rule_id: str,
        clauses: tuple[str, ...],
        title: str,
        systems: tuple[str, ...],
        fact_ids: tuple[str, ...],
        ok: bool,
        evidence: str,
        deliverables: tuple[str, ...],
        *,
        applicable: bool = True,
        part: str = "text",
        release_blocking: bool = True,
        open_status: str = "missing",
    ) -> None:
        status = "not_applicable" if not applicable else "verified" if ok else open_status
        rows.append(make(
            rule_id, clauses, part, title, systems, fact_ids, status, evidence,
            deliverables, release_blocking=release_blocking,
        ))

    assignment_ok = bool(sewage.design_assignment_ref and sewage.survey_ref)
    life_ok = sewage.service_life_years is not None and sewage.overhaul_period_years is not None
    add(
        "V-GOST-01", ("5.1.2",), "Основания проектирования, срок службы и капитальный ремонт",
        ("В1", "В2", "Т3", "Т4"),
        ("project.assignment", "survey.engineering", "project.service_life", "project.overhaul_period"),
        assignment_ok and life_ok,
        "; ".join(filter(None, (
            sewage.design_assignment_ref,
            sewage.survey_ref,
            f"срок службы {sewage.service_life_years} лет" if sewage.service_life_years is not None else "",
            f"до капремонта {sewage.overhaul_period_years} лет" if sewage.overhaul_period_years is not None else "",
        ))) or "реквизиты и сроки не заданы",
        ("Пояснительная записка",),
    )
    source_ok = bool(
        source.connection_point and source.tu_number and source.tu_date
        and source.guaranteed_head_m is not None
    )
    add(
        "V-GOST-02", ("5.1.3",), "Источник водоснабжения и условия подключения",
        ("В1", "В2"),
        ("water.source", "water.connection_tu", "water.guaranteed_head"),
        source_ok,
        (
            f"{source.connection_point or 'точка не задана'}; ТУ {source.tu_number or '—'} "
            f"от {source.tu_date or '—'}; Hгар={source.guaranteed_head_m if source.guaranteed_head_m is not None else '—'} м"
        ),
        ("Пояснительная записка", "Схема вводов и узлов учёта"),
    )
    systems_ok = source.inputs_count > 0 and all((
        project.materials.cold_mains,
        project.materials.cold_distribution,
        project.materials.fire_pipes,
    ))
    add(
        "V-GOST-03", ("5.1.5",), "Состав систем, вводы, материалы и зонирование",
        ("В1", "В2", "Т3", "Т4"),
        ("water.systems", "water.inputs_count", "water.materials", "building.zones"),
        systems_ok,
        f"вводов {source.inputs_count}; зон {project.building.zones}; материалы назначены: {'да' if systems_ok else 'нет'}",
        ("Пояснительная записка", "Принципиальная схема", "Спецификация"),
    )
    flow_ok = bool(project.consumer_groups and project.flows.q_day_tot > 0 and project.flows.q_sec_tot > 0)
    add(
        "V-GOST-04", ("5.1.6.1",), "Потребители, нормы и расчётные расходы В1",
        ("В1",),
        ("consumers.groups", "water.norm_basis", "water.q_day", "water.q_second"),
        flow_ok,
        f"групп {len(project.consumer_groups)}; Qсут={project.flows.q_day_tot:.3f} м³/сут; q={project.flows.q_sec_tot:.3f} л/с",
        ("Пояснительная записка", "Расчёты В1", "Баланс ВиВ"),
    )
    fire_ok = bool(project.fire.q_total > 0 and project.fire.required_head_m is not None)
    add(
        "V-GOST-05", ("5.1.6.3",), "Расход и напор внутреннего противопожарного водопровода",
        ("В2",),
        ("fire.applicability", "fire.q_total", "fire.required_head"),
        fire_ok,
        (
            f"q={project.fire.q_total:.3f} л/с; Hтр={project.fire.required_head_m} м"
            if project.fire.required else "В2 не требуется по нормативному решению"
        ),
        ("Пояснительная записка", "Гидравлический расчёт В2"),
        applicable=project.fire.required,
    )
    pump_ok = bool(
        head.h_required_m is not None and head.h_guaranteed_m is not None
        and (not head.pump_needed or (project.pumps.model and project.pumps.wp_q > 0 and project.pumps.wp_h > 0))
    )
    add(
        "V-GOST-06", ("5.1.8",), "Фактический и требуемый напор, насосное решение",
        ("В1",),
        ("water.head.components", "water.guaranteed_head", "water.pump.working_point"),
        pump_ok,
        (
            f"Hтр={head.h_required_m if head.h_required_m is not None else '—'} м; "
            f"Hгар={head.h_guaranteed_m if head.h_guaranteed_m is not None else '—'} м; "
            f"насос={project.pumps.model or ('не требуется' if head.pump_needed is False else 'не подобран')}"
        ),
        ("Пояснительная записка", "Расчёты В1", "Подбор насосов"),
    )
    materials_ok = all((
        project.materials.cold_mains,
        project.materials.cold_distribution,
        project.materials.hot_mains,
        project.materials.hot_distribution,
        project.materials.fire_pipes,
    ))
    add(
        "V-GOST-07", ("5.1.5",), "Материалы труб внутренних систем",
        ("В1", "В2", "Т3", "Т4"),
        ("water.materials", "building.environment"),
        materials_ok,
        "материалы основных и распределительных трубопроводов назначены" if materials_ok else "материалы заданы не для всех систем",
        ("Пояснительная записка", "Спецификация"),
    )
    quality_ok = bool(source.description and source.water_protection_note and source.reserve_water_note)
    add(
        "V-GOST-08", ("5.1.10–5.1.12",), "Качество, подготовка и резервирование воды",
        ("В1", "Т3"),
        ("water.source", "water.quality", "water.treatment", "water.reserve"),
        quality_ok,
        "; ".join(filter(None, (source.description, source.water_protection_note, source.reserve_water_note))) or "сведения не заданы",
        ("Пояснительная записка",),
    )
    meters_ok = bool(project.meters.rows)
    add(
        "V-GOST-09", ("5.1.13", "5.1.23", "5.1.27"), "Узлы учёта и сбор данных",
        ("В1", "Т3"),
        ("water.meters", "water.metering_locations", "water.askue"),
        meters_ok,
        f"расчётных узлов {len(project.meters.rows)}; АСКУЭ: {'да' if project.meters.has_askue else 'не задана'}",
        ("Пояснительная записка", "Схема вводов и узлов учёта"),
    )
    automation_applicable = bool(project.pumps.required or project.fire_pumps.required)
    automation_ok = bool(
        (not project.pumps.required or (project.pumps.frequency_drive_required and project.pumps.dispatch_required))
        and (not project.fire_pumps.required or project.fire_pumps.dispatch_required)
    )
    add(
        "V-GOST-10", ("5.1.14–5.1.16", "5.1.25–5.1.27"), "Автоматизация и энергетическая эффективность",
        ("В1", "В2", "Т3", "Т4"),
        ("water.pump.automation", "water.energy_efficiency"),
        automation_ok,
        "частотное регулирование и диспетчеризация отражены" if automation_ok else "сигналы, алгоритмы или показатели требуют задания",
        ("Пояснительная записка", "Схема насосов, зон и ГВС"),
        applicable=automation_applicable,
        release_blocking=False,
        open_status="manual_review",
    )
    hws_applicable = project.building.hws_type != HwsType.NONE
    hws_ok = bool(project.flows.q_day_h > 0 and project.flows.q_hr_h > 0 and project.materials.hot_mains)
    add(
        "V-GOST-11", ("5.1.17", "5.1.18"), "Система и расчётные расходы горячего водоснабжения",
        ("Т3", "Т4"),
        ("hws.type", "hws.q_day", "hws.q_hour", "hws.materials", "hws.insulation"),
        hws_ok,
        f"тип {project.building.hws_type.value}; Qсут.гор={project.flows.q_day_h:.3f} м³/сут; Qч.гор={project.flows.q_hr_h:.3f} м³/ч",
        ("Пояснительная записка", "Расчёты В1", "Принципиальная схема"),
        applicable=hws_applicable,
    )
    balance_ok = bool(project.balance.rows) and project.building.purpose != BuildingPurpose.INDUSTRIAL
    add(
        "V-GOST-12", ("5.1.20", "5.1.21", "приложение А"), "Баланс водопотребления и водоотведения",
        ("В1", "Т3", "К1"),
        ("balance.rows", "building.purpose"),
        balance_ok,
        (
            f"форма 2; строк {len(project.balance.rows)}"
            if project.building.purpose != BuildingPurpose.INDUSTRIAL else
            "для производственного объекта требуется форма 1; модель не реализована"
        ),
        ("Баланс ВиВ",),
    )

    for rule_id, clauses, title, systems, required in (
        ("V-GOST-A01", ("5.1.1–5.1.28",), "Текстовая часть ИОС2 сформирована", ("В1", "В2", "Т3", "Т4"), ("Пояснительная записка",)),
        ("V-GOST-A02", ("5.1.21", "приложение А, форма 2"), "Баланс непроизводственного объекта оформлен отдельным листом", ("В1", "Т3", "К1"), ("Баланс ВиВ",)),
        ("V-GOST-A03", ("5.1.28",), "Спецификация оборудования и материалов сформирована", ("В1", "В2", "Т3", "Т4"), ("Спецификация",)),
        ("V-GOST-A04", ("5.2.1.5", "5.2.2.1–5.2.2.4"), "Принципиальная схема систем здания сформирована", ("В1", "В2", "Т3", "Т4"), ("Принципиальная схема",)),
        ("V-GOST-A05", ("5.2.2.5",), "Схема насосных станций сформирована", ("В1", "В2"), ("Схема насосов, зон и ГВС",)),
        ("V-GOST-A06", ("5.2.2.6",), "Схема узлов учёта сформирована", ("В1", "Т3"), ("Схема вводов и узлов учёта",)),
        ("V-GOST-A07", ("5.2.1.5",), "План сетей водоснабжения сформирован", ("В1", "В2", "Т3", "Т4"), ("План сетей водоснабжения",)),
    ):
        applicable = not (
            rule_id == "V-GOST-A02" and project.building.purpose == BuildingPurpose.INDUSTRIAL
        ) and not (
            rule_id == "V-GOST-A05" and not (project.pumps.required or project.fire_pumps.required)
        )
        if not applicable:
            status, evidence = "not_applicable", "требование неприменимо к принятому составу систем"
        else:
            status, evidence = _artifact_status(artifacts, required)
        rows.append(make(
            rule_id, clauses, "artifact", title, systems,
            tuple(f"artifact.{name}" for name in required), status, evidence,
            required,
        ))

    rows.append(make(
        "V-GOST-A08", ("5.1.9", "5.2.3"), "graphic",
        "Границы, материалы и план наружной сети водоснабжения подтверждены",
        ("В1",), ("water.external_scope",), "manual_review",
        "Границы наружных сетей не представлены отдельным фактом проекта",
        ("План наружной сети водоснабжения",),
        release_blocking=False,
    ))

    return NormativeAuditMatrix(
        discipline="ИОС2",
        document_id="gost_r_21_619_2023",
        baseline_id=baseline.baseline_id,
        baseline_fingerprint=baseline.fingerprint,
        rows=tuple(rows),
    )


def build_project_gost_matrices(
    project: Project,
    artifacts: dict[str, bool] | None = None,
    baseline: NormativeBaseline | None = None,
) -> tuple[NormativeAuditMatrix, NormativeAuditMatrix]:
    baseline = baseline or get_active_baseline()
    return (
        build_ios2_gost_matrix(project, artifacts, baseline),
        build_ios3_gost_matrix(project, artifacts, baseline),
    )
