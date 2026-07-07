# -*- coding: utf-8 -*-
"""
app/calc/diameter_audit.py — аудит диаметров участков В2 по скорости.

Потребитель section-данных (fire_hydraulics, этап 2.2). По каждому участку даёт
ДВА независимых вердикта (правило зафиксировано Антоном):

  1) Нормативный (hard check) — предел скорости по режиму сети:
     чистый ВПВ 10 м/с, объединённый 3 м/с, хоз 1,5 м/с.
     Нарушение = ошибка (mandatory fail).
  2) Проектный (recommendation) — подбор рекомендуемого Ду по design target
     (чистый ВПВ 4 м/с). Нарушение target = рекомендация увеличить Ду, не ошибка.

Рекомендуемый Ду ВСЕГДА ищется по design target (перебор 50→65→80→100…),
даже при нарушении норматива — чтобы рекомендация была инженерно нормальной,
а не «лишь бы вписаться в 10 м/с».

Три типовых кейса:
  A — проходит и норматив, и target → recommended_dn = current_dn;
  B — норматив OK, target нарушен → рекомендация увеличить Ду (не ошибка);
  C — норматив нарушен → ошибка + рекомендуемый Ду по target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from app.calc.fire_hydraulics import (
    NetworkMode, SectionFlow, velocity_mps, STEEL_INNER_DIAMETER_MM,
    NORMATIVE_VELOCITY_LIMIT_MPS, DESIGN_VELOCITY_TARGET_MPS,
)

# ряд Ду для подбора (стальные трубы В2), по возрастанию
DN_SERIES = [50, 65, 80, 100, 125, 150]


class AuditVerdict(str, Enum):
    """Итоговый вердикт по участку (три кейса из постановки)."""
    OK = "ok"                    # кейс A: норматив и target пройдены
    OVERSIZED_TARGET = "target"  # кейс B: норматив OK, target нарушен (рекомендация)
    NORMATIVE_FAIL = "fail"      # кейс C: нарушение норматива (ошибка)


@dataclass
class SegmentDiameterAudit:
    """Результат аудита диаметра одного участка."""
    segment_id: str
    flow_lps: float
    current_dn: Optional[int]
    current_inner_mm: Optional[float]
    velocity_mps: Optional[float]
    normative_limit_mps: float
    normative_ok: Optional[bool]        # проходит ли жёсткий предел
    design_limit_mps: float
    design_ok: Optional[bool]           # проходит ли проектный target
    recommended_dn: Optional[int]       # подобран по design target
    verdict: AuditVerdict
    message: str


@dataclass
class DiameterAuditResult:
    """Аудит по всем участкам сценария."""
    mode: NetworkMode
    segments: List[SegmentDiameterAudit] = field(default_factory=list)
    has_normative_fail: bool = False    # есть ли хоть одна ошибка (кейс C)
    has_target_warning: bool = False    # есть ли хоть одна рекомендация (кейс B)
    notes: List[str] = field(default_factory=list)


def _inner_for_dn(dn: int) -> float:
    """Внутренний диаметр по Ду (табличный, иначе Ду как приближение)."""
    return STEEL_INNER_DIAMETER_MM.get(int(dn), float(dn))


def recommend_dn_by_target(flow_lps: float, design_target_mps: float,
                           dn_series: Optional[List[int]] = None) -> Optional[int]:
    """Шаг 4: подбор минимального Ду, при котором скорость ≤ design target.
    Перебор 50→65→80→100… Возвращает None, если даже наибольший Ду не проходит."""
    series = dn_series or DN_SERIES
    for dn in series:
        v = velocity_mps(flow_lps, _inner_for_dn(dn))
        if v is not None and v <= design_target_mps + 1e-9:
            return dn
    return None


def audit_segment(
    segment_id: str,
    flow_lps: float,
    current_dn: Optional[int],
    mode: NetworkMode,
    *,
    current_inner_mm: Optional[float] = None,
    design_target_mps: Optional[float] = None,
    dn_series: Optional[List[int]] = None,
) -> SegmentDiameterAudit:
    """Аудит одного участка по шести шагам постановки."""
    norm_limit = NORMATIVE_VELOCITY_LIMIT_MPS[mode]
    design_limit = design_target_mps if design_target_mps is not None \
        else DESIGN_VELOCITY_TARGET_MPS[mode]

    # шаг 1: скорость на текущем диаметре
    inner = current_inner_mm if current_inner_mm is not None else (
        _inner_for_dn(current_dn) if current_dn is not None else None)
    v = velocity_mps(flow_lps, inner)

    # шаги 2-3: статусы
    normative_ok = None if v is None else v <= norm_limit + 1e-9
    design_ok = None if v is None else v <= design_limit + 1e-9

    # шаг 4: рекомендуемый Ду всегда по design target
    recommended = recommend_dn_by_target(flow_lps, design_limit, dn_series)

    # шаги 5-6: вердикт и сообщение
    if v is None:
        verdict = AuditVerdict.OK
        msg = f"участок {segment_id}: диаметр не задан, скорость не определена"
    elif normative_ok is False:
        verdict = AuditVerdict.NORMATIVE_FAIL
        msg = (f"участок {segment_id}: v={v:.2f} м/с превышает норматив "
               f"{norm_limit:.1f} м/с (режим {mode.value}) — ОШИБКА. "
               f"Рекомендуемый Ду по target {design_limit:.1f} м/с: "
               f"{('Ду' + str(recommended)) if recommended else 'нет в ряду — проверить сеть'}")
    elif design_ok is False:
        verdict = AuditVerdict.OVERSIZED_TARGET
        msg = (f"участок {segment_id}: v={v:.2f} м/с в пределах норматива "
               f"{norm_limit:.1f}, но выше проектного target {design_limit:.1f} м/с. "
               f"Рекомендуется увеличить до Ду{recommended}" if recommended
               else f"участок {segment_id}: v={v:.2f} м/с выше target {design_limit:.1f}")
    else:
        verdict = AuditVerdict.OK
        msg = f"участок {segment_id}: v={v:.2f} м/с — в норме (Ду{current_dn} достаточно)"

    return SegmentDiameterAudit(
        segment_id=segment_id, flow_lps=flow_lps, current_dn=current_dn,
        current_inner_mm=inner, velocity_mps=v,
        normative_limit_mps=norm_limit, normative_ok=normative_ok,
        design_limit_mps=design_limit, design_ok=design_ok,
        recommended_dn=recommended, verdict=verdict, message=msg)


def audit_sections(
    sections: List[SectionFlow],
    mode: NetworkMode,
    *,
    dn_by_segment: Optional[dict] = None,
    design_target_mps: Optional[float] = None,
    dn_series: Optional[List[int]] = None,
) -> DiameterAuditResult:
    """Аудит всех участков сценария по section-данным из fire_hydraulics.

    sections: SectionFlow из HydraulicScenario.sections.
    dn_by_segment: {segment_id: Ду} — текущие Ду участков (если section не несёт
        Ду явно; SectionFlow хранит внутренний диаметр, а не Ду).
    """
    dn_by_segment = dn_by_segment or {}
    result = DiameterAuditResult(mode=mode)

    for sec in sections:
        # текущий Ду: из карты, иначе обратный поиск по внутреннему диаметру
        dn = dn_by_segment.get(sec.segment_id)
        if dn is None and sec.inner_diameter_mm is not None:
            dn = _dn_from_inner(sec.inner_diameter_mm)
        seg_audit = audit_segment(
            segment_id=sec.segment_id, flow_lps=sec.flow_lps, current_dn=dn, mode=mode,
            current_inner_mm=sec.inner_diameter_mm,
            design_target_mps=design_target_mps, dn_series=dn_series)
        result.segments.append(seg_audit)
        if seg_audit.verdict == AuditVerdict.NORMATIVE_FAIL:
            result.has_normative_fail = True
        elif seg_audit.verdict == AuditVerdict.OVERSIZED_TARGET:
            result.has_target_warning = True

    if result.has_normative_fail:
        result.notes.append("Есть участки с превышением норматива скорости — "
                            "обязательно увеличить диаметр.")
    if result.has_target_warning:
        result.notes.append("Есть участки выше проектного target скорости — "
                            "рекомендуется увеличить диаметр для запаса гидравлики.")
    return result


def _dn_from_inner(inner_mm: float) -> Optional[int]:
    """Обратный поиск Ду по внутреннему диаметру (для section без явного Ду)."""
    for dn, inner in STEEL_INNER_DIAMETER_MM.items():
        if abs(inner - inner_mm) < 0.5:
            return dn
    return None


def _example() -> None:
    from app.calc.fire_hydraulics import (
        FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode, HydraulicSource,
        SourceKind, solve_fire_hydraulics_scenario,
    )
    # узкая магистраль Ду50 при большом расходе → target/норматив
    net = FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "n": HydraulicNode("n", 20)},
        segments=[PipeSegment("mag", "src", "n", length_m=20, A=0.01, diameter_mm=50)],
        cabinets=[FireCabinetNode("PK-A", "n", riser_id="R1"),
                  FireCabinetNode("PK-B", "n", riser_id="R2")],
        source=HydraulicSource("src", kind=SourceKind.CITY_MAIN, available_head_m=60))
    r = solve_fire_hydraulics_scenario(net, 2, mode=NetworkMode.PURE_FIRE)
    audit = audit_sections(r.dictating_scenario.sections, NetworkMode.PURE_FIRE,
                           dn_by_segment={"mag": 50})
    for s in audit.segments:
        print(f"{s.segment_id}: Ду{s.current_dn} v={s.velocity_mps:.2f} "
              f"[{s.verdict.value}] → рек. Ду{s.recommended_dn}")
        print("   ", s.message)


if __name__ == "__main__":
    _example()
