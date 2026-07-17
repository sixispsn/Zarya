# -*- coding: utf-8 -*-
"""
app/calc/fire_hydraulic_report.py — отчёт гидравлического расчёта В2 (уровень A).

СБОРЩИК, не расчётчик: собирается из уже готовых результатов и форматирует их
как гидравлический расчёт для ПЗ / отдельного листа. Сам ничего не считает.

    build_hydraulic_report(scenario_result, diameter_audit_result, *, ...)
        -> FireHydraulicReport
        -> .render_text()  # текст для пояснительной записки

Пять блоков (по постановке Антона):
  1. Шапка расчёта (сценарий, расход, диктующий, напор, насос).
  2. Таблица участков (Q, Ду, внутр.Ø, скорость, пределы, потери, shared, ПК).
  3. Вердикт по диаметрам (норматив/target/рекомендуемый Ду/причина).
  4. Диктующий путь (последовательность, где набирается потеря, итог).
  5. Текстовое заключение для ПЗ в проектном стиле.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.calc.fire_hydraulics import (
    ScenarioResult, HydraulicScenario, SectionFlow, PumpDutyPoint,
    ScenarioCabinet, NetworkMode, SourceKind,
)
from app.calc.diameter_audit import (
    DiameterAuditResult, SegmentDiameterAudit, AuditVerdict,
)


# ============================================================
# БЛОК 1 — ШАПКА
# ============================================================

@dataclass
class ReportHeader:
    mode: NetworkMode
    active_cabinet_ids: List[str]
    n_simultaneous: int
    total_flow_lps: float
    dictating_label: str                  # диктующий ПК или пара
    required_head_at_source_m: float
    available_head_m: Optional[float]
    needs_pump: Optional[bool]
    pump_duty: Optional[PumpDutyPoint]


# ============================================================
# БЛОК 2/3 — СТРОКА УЧАСТКА (гидравлика + аудит вместе)
# ============================================================

@dataclass
class ReportSegmentRow:
    segment_id: str
    from_node: str
    to_node: str
    effective_length_m: float
    flow_lps: float
    current_dn: Optional[int]
    inner_diameter_mm: Optional[float]
    velocity_mps: Optional[float]
    normative_limit_mps: float
    design_limit_mps: float
    head_loss_m: float
    is_shared: bool
    serving_cabinets: List[str]
    # из diameter audit:
    normative_ok: Optional[bool]
    design_ok: Optional[bool]
    recommended_dn: Optional[int]
    verdict: AuditVerdict


# ============================================================
# БЛОК 4 — ДИКТУЮЩИЙ ПУТЬ
# ============================================================

@dataclass
class DictatingPath:
    cabinet_id: str
    segments: List[str]                   # последовательность участков
    total_loss_m: float
    max_loss_segment: Optional[str]       # где основная потеря
    max_loss_m: float
    required_head_at_source_m: float


# ============================================================
# ОТЧЁТ ЦЕЛИКОМ
# ============================================================

@dataclass
class FireHydraulicReport:
    header: ReportHeader
    segments: List[ReportSegmentRow] = field(default_factory=list)
    dictating_paths: List[DictatingPath] = field(default_factory=list)
    audit_notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def render_text(self) -> str:
        """Собирает все блоки в текст для ПЗ / листа расчёта."""
        parts = [self._render_header(), self._render_segments_table(),
                 self._render_diameter_verdicts(), self._render_dictating_path(),
                 self._render_conclusion()]
        return "\n\n".join(p for p in parts if p)

    # ── блок 1 ──
    def _render_header(self) -> str:
        h = self.header
        L = ["РАСЧЁТ ВНУТРЕННЕГО ПРОТИВОПОЖАРНОГО ВОДОПРОВОДА (В2)",
             f"Расчётный сценарий: {h.n_simultaneous} одновременно действующих ПК "
             f"({', '.join(h.active_cabinet_ids)}).",
             f"Расчётный расход: {h.total_flow_lps:.1f} л/с.",
             f"Диктующий: {h.dictating_label}.",
             f"Требуемый напор на вводе: {h.required_head_at_source_m:.1f} м."]
        if h.available_head_m is not None:
            L.append(f"Доступный напор источника: {h.available_head_m:.1f} м.")
        if h.needs_pump is True and h.pump_duty:
            L.append(f"Требуется повысительная насосная установка: "
                     f"Q = {h.pump_duty.flow_lps:.1f} л/с, H = {h.pump_duty.required_head_m:.1f} м.")
        elif h.needs_pump is False:
            L.append("Повысительная насосная установка не требуется.")
        return "\n".join(L)

    # ── блок 2 ──
    def _render_segments_table(self) -> str:
        if not self.segments:
            return ""
        L = ["ТАБЛИЦА УЧАСТКОВ",
             f"{'участок':10}{'откуда→куда':16}{'L_eff':>7}{'Q':>7}{'Ду':>5}"
             f"{'Øвн':>7}{'v':>7}{'потери':>8}{'общий':>7}"]
        for s in self.segments:
            arrow = f"{s.from_node}→{s.to_node}"
            v = f"{s.velocity_mps:.2f}" if s.velocity_mps is not None else "—"
            dn = str(s.current_dn) if s.current_dn else "—"
            din = f"{s.inner_diameter_mm:.0f}" if s.inner_diameter_mm else "—"
            L.append(f"{s.segment_id:10}{arrow:16}{s.effective_length_m:7.1f}"
                     f"{s.flow_lps:7.1f}{dn:>5}{din:>7}{v:>7}{s.head_loss_m:8.2f}"
                     f"{'да' if s.is_shared else 'нет':>7}")
        return "\n".join(L)

    # ── блок 3 ──
    def _render_diameter_verdicts(self) -> str:
        rows = [s for s in self.segments if s.current_dn is not None]
        if not rows:
            return ""
        L = ["ВЕРДИКТ ПО ДИАМЕТРАМ"]
        for s in rows:
            if s.verdict == AuditVerdict.OK:
                L.append(f"  {s.segment_id}: Ду{s.current_dn} — норматив и проектный "
                         f"предел соблюдены.")
            elif s.verdict == AuditVerdict.OVERSIZED_TARGET:
                L.append(f"  {s.segment_id}: Ду{s.current_dn} — норматив соблюдён "
                         f"(v≤{s.normative_limit_mps:.0f}), но выше проектного предела "
                         f"{s.design_limit_mps:.0f} м/с. Рекомендуется Ду{s.recommended_dn}.")
            else:  # NORMATIVE_FAIL
                L.append(f"  {s.segment_id}: Ду{s.current_dn} — ПРЕВЫШЕНИЕ норматива "
                         f"скорости ({s.velocity_mps:.2f}>{s.normative_limit_mps:.0f} м/с). "
                         f"Требуется увеличение до Ду{s.recommended_dn}.")
        return "\n".join(L)

    # ── блок 4 ──
    def _render_dictating_path(self) -> str:
        if not self.dictating_paths:
            return ""
        L = ["ДИКТУЮЩИЙ ПУТЬ"]
        for p in self.dictating_paths:
            L.append(f"  ПК {p.cabinet_id}: {' → '.join(p.segments)}")
            L.append(f"    суммарные потери по пути: {p.total_loss_m:.2f} м")
            if p.max_loss_segment:
                L.append(f"    наибольшая потеря — участок {p.max_loss_segment} "
                         f"({p.max_loss_m:.2f} м)")
            L.append(f"    требуемый напор на вводе: {p.required_head_at_source_m:.1f} м")
        return "\n".join(L)

    # ── блок 5 ──
    def _render_conclusion(self) -> str:
        h = self.header
        L = ["ЗАКЛЮЧЕНИЕ",
             f"Расчёт В2 выполнен для диктующего сценария из {h.n_simultaneous} "
             f"одновременно действующих ПК при расчётном расходе {h.total_flow_lps:.1f} л/с. "
             f"Требуемый напор на вводе составляет {h.required_head_at_source_m:.1f} м."]
        if h.needs_pump is True and h.pump_duty:
            avail = (f"при доступном напоре {h.available_head_m:.1f} м "
                     if h.available_head_m is not None else "")
            L.append(f"{avail.capitalize()}предусматривается повысительная насосная "
                     f"установка с рабочей точкой Q = {h.pump_duty.flow_lps:.1f} л/с, "
                     f"H = {h.pump_duty.required_head_m:.1f} м.")
        elif h.needs_pump is True:
            deficit = h.required_head_at_source_m - (h.available_head_m or 0.0)
            L.append(f"Доступного напора недостаточно (дефицит {deficit:.1f} м) — "
                     "предусматривается повысительная насосная установка В2; "
                     "рабочую точку основного расчётного режима требуется определить "
                     "с учётом совместной работы источников по п. 12.1 СП 10.13130.2020.")
        elif h.needs_pump is False:
            L.append(f"Доступного напора источника ({h.available_head_m:.1f} м) достаточно; "
                     "повысительная насосная установка не требуется.")

        fails = [s for s in self.segments if s.verdict == AuditVerdict.NORMATIVE_FAIL]
        warns = [s for s in self.segments if s.verdict == AuditVerdict.OVERSIZED_TARGET]
        if fails:
            ids = ", ".join(f"{s.segment_id} (до Ду{s.recommended_dn})" for s in fails)
            L.append(f"На участках {ids} скорость превышает нормативный предел — "
                     "требуется увеличение диаметра.")
        if warns:
            ids = ", ".join(f"{s.segment_id} (до Ду{s.recommended_dn})" for s in warns)
            L.append(f"На участках {ids} скорость превышает проектный целевой предел; "
                     "для запаса гидравлики рекомендуется увеличение диаметра.")
        if not fails and not warns:
            L.append("Скорости на всех участках в пределах нормативных и проектных "
                     "ограничений.")
        return "\n".join(L)


# ============================================================
# СБОРКА (не расчёт — только достаёт из результатов)
# ============================================================

def build_hydraulic_report(
    scenario_result: ScenarioResult,
    diameter_audit_result: Optional[DiameterAuditResult] = None,
    *,
    dn_by_segment: Optional[Dict[str, int]] = None,
) -> Optional[FireHydraulicReport]:
    """Собирает отчёт из результата гидравлики + аудита диаметров.

    Ничего не считает: берёт диктующий сценарий, его секции, рабочую точку насоса
    и вердикты аудита, раскладывает по пяти блокам. Если сценарий не рассчитан
    (нет диктующего) — возвращает None (расчёт не состоялся).
    """
    scen = scenario_result.dictating_scenario
    if scen is None:
        return None
    dn_by_segment = dn_by_segment or {}

    dictating_label = "+".join(scen.active_cabinet_ids)
    header = ReportHeader(
        mode=NORMATIVE_MODE(diameter_audit_result),
        active_cabinet_ids=scen.active_cabinet_ids,
        n_simultaneous=len(scen.active_cabinet_ids),
        total_flow_lps=scen.total_flow_lps,
        dictating_label=dictating_label,
        required_head_at_source_m=scenario_result.required_head_at_source_m,
        available_head_m=scenario_result.available_head_m,
        needs_pump=scenario_result.needs_pump,
        pump_duty=scenario_result.pump_duty,
    )

    # индекс аудита по segment_id
    audit_by_id: Dict[str, SegmentDiameterAudit] = {}
    if diameter_audit_result:
        audit_by_id = {a.segment_id: a for a in diameter_audit_result.segments}

    rows: List[ReportSegmentRow] = []
    for s in scen.sections:
        a = audit_by_id.get(s.segment_id)
        rows.append(ReportSegmentRow(
            segment_id=s.segment_id, from_node=s.from_node, to_node=s.to_node,
            effective_length_m=s.effective_length_m, flow_lps=s.flow_lps,
            current_dn=(a.current_dn if a else dn_by_segment.get(s.segment_id)),
            inner_diameter_mm=s.inner_diameter_mm, velocity_mps=s.velocity_mps,
            normative_limit_mps=s.velocity_normative_limit_mps,
            design_limit_mps=s.velocity_design_limit_mps,
            head_loss_m=s.head_loss_m, is_shared=s.is_shared,
            serving_cabinets=s.serving_cabinets,
            normative_ok=(a.normative_ok if a else s.velocity_normative_ok),
            design_ok=(a.design_ok if a else s.velocity_design_ok),
            recommended_dn=(a.recommended_dn if a else None),
            verdict=(a.verdict if a else AuditVerdict.OK),
        ))

    # диктующие пути из ScenarioCabinet.path
    paths: List[DictatingPath] = []
    for cab in scen.cabinets:
        if not cab.path:
            continue
        max_row = max(cab.path, key=lambda r: r.head_loss_m)
        paths.append(DictatingPath(
            cabinet_id=cab.cabinet_id,
            segments=[r.segment_id for r in cab.path],
            total_loss_m=cab.path_head_loss_m,
            max_loss_segment=max_row.segment_id, max_loss_m=max_row.head_loss_m,
            required_head_at_source_m=cab.required_head_at_source_m,
        ))
    # оставляем путь диктующего (с максимальным требуемым напором)
    if paths:
        paths.sort(key=lambda p: -p.required_head_at_source_m)
        paths = paths[:1]

    return FireHydraulicReport(
        header=header, segments=rows, dictating_paths=paths,
        audit_notes=(diameter_audit_result.notes if diameter_audit_result else []),
        warnings=scenario_result.warnings,
    )


def NORMATIVE_MODE(audit: Optional[DiameterAuditResult]) -> NetworkMode:
    """Режим сети из аудита (если есть), иначе чистый ВПВ по умолчанию."""
    return audit.mode if audit else NetworkMode.PURE_FIRE


def _example() -> None:
    from app.calc.fire_hydraulics import (
        FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode, HydraulicSource,
        solve_fire_hydraulics_scenario,
    )
    from app.calc.diameter_audit import audit_sections

    net = FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "fork": HydraulicNode("fork", 0.0),
               "a": HydraulicNode("a", 27.5), "b": HydraulicNode("b", 27.5)},
        segments=[
            PipeSegment("mag", "src", "fork", length_m=30, A=0.00246, equiv_length_m=8, diameter_mm=65),
            PipeSegment("rA", "fork", "a", length_m=27.5, A=0.011, equiv_length_m=4, diameter_mm=50),
            PipeSegment("rB", "fork", "b", length_m=27.5, A=0.011, equiv_length_m=4, diameter_mm=50)],
        cabinets=[FireCabinetNode("PK-A", "a", riser_id="R1"),
                  FireCabinetNode("PK-B", "b", riser_id="R2")],
        source=HydraulicSource("src", available_head_m=30.0))
    r = solve_fire_hydraulics_scenario(net, 2, mode=NetworkMode.PURE_FIRE)
    audit = audit_sections(r.dictating_scenario.sections, NetworkMode.PURE_FIRE,
                           dn_by_segment={"mag": 65, "rA": 50, "rB": 50})
    report = build_hydraulic_report(r, audit)
    print(report.render_text())


if __name__ == "__main__":
    _example()
