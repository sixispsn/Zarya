# -*- coding: utf-8 -*-
"""
app/pz/ios2_orchestrator.py — pipeline coordinator комплекта ИОС2 (не solver).

design_ios2() координирует уже готовые слои, НЕ содержит расчётной логики и НЕ
придумывает данные. Два прозрачных режима:

  Режим 1 (расчёт + документы): переданы layout_inputs и network →
    нормативы → fire_layout → fire_hydraulics → diameter_audit →
    enrich_fire → ПЗ / спека / схема / гидролист.

  Режим 2 (только документы): геометрии нет → ничего не досчитываем «из воздуха»,
    собираем комплект из уже заполненного project.fire; гидролист рендерим только
    если передан готовый hydraulic_report.

Правило: есть входы → считаем; нет → не считаем, только собираем. Каждый
пропущенный шаг явно отмечается в warnings, чтобы не было иллюзии «всё посчитано».
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple

from app.pz.project import Project
from app.pz.flows_bridge import enrich_fire_from_layout_and_hydraulics
from app.pz.generator import (
    generate_pz_pdf, generate_spec_pdf, generate_scheme_pdf,
    generate_hydraulic_report_pdf,
)

# расчётные слои (импортируются лениво внутри режима 1, чтобы режим 2 не тянул их)


@dataclass
class IOS2DesignBundle:
    """Структурированный результат: обновлённый проект, промежуточные результаты
    расчёта (для инспекции швов) и пути к сгенерированным PDF."""
    project: Project
    fire_layout_results: Optional[list] = None
    fire_hydraulic_result: Optional[object] = None
    diameter_audit: Optional[object] = None
    hydraulic_report: Optional[object] = None
    pz_pdf: Optional[str] = None
    spec_pdf: Optional[str] = None
    scheme_pdf: Optional[str] = None
    hydraulic_pdf: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    status: List[str] = field(default_factory=list)


def design_ios2(
    project: Project,
    *,
    output_dir: str = "output",
    layout_inputs: Optional[List[Tuple[object, object]]] = None,
    network: Optional[object] = None,
    required_jets: int = 2,
    network_mode: Optional[object] = None,
    dn_by_segment: Optional[dict] = None,
    hydraulic_report: Optional[object] = None,
    scenario_filter: Optional[object] = None,
) -> IOS2DesignBundle:
    """Координатор комплекта ИОС2.

    project: модель проекта (документ, здание, системы).
    layout_inputs: список пар (FireNormativeContext, RectangularRoom) — по помещению.
        Если задан → режим 1 для геометрии ПК.
    network: FireNetwork сети В2. Если задан → режим 1 для гидравлики.
    required_jets: число одновременных ПК для гидравлического сценария.
    network_mode: NetworkMode (по умолчанию PURE_FIRE).
    dn_by_segment: карта {segment_id: Ду} для аудита диаметров.
    hydraulic_report: готовый FireHydraulicReport (для режима 2, если сеть не дана).
    scenario_filter: предикат допустимости сценария (напр. разные стояки).

    Возвращает IOS2DesignBundle с путями к PDF и промежуточными результатами.
    Пропущенные шаги отражены в warnings/status.
    """
    os.makedirs(output_dir, exist_ok=True)
    bundle = IOS2DesignBundle(project=project)
    fire = project.fire

    # ── Режим 1а: расчёт геометрии ПК (если есть layout_inputs) ──
    layout_results = None
    if layout_inputs:
        from app.calc.fire_design import design_fire_cabinets_from_context
        layout_results = []
        for ctx, room in layout_inputs:
            res = design_fire_cabinets_from_context(ctx, room)
            layout_results.append(res)
            if res.layout is None:
                bundle.warnings.append(
                    f"fire_layout: помещение {getattr(room, 'room_id', '?')} — "
                    f"расстановка невозможна (см. результат).")
        bundle.fire_layout_results = layout_results
        bundle.status.append(f"fire_layout: рассчитано помещений {len(layout_results)}")
    else:
        bundle.warnings.append("fire_layout skipped: layout_inputs not provided")

    # ── Режим 1б: гидравлика + аудит (если есть network) ──
    hydraulic_result = None
    audit = None
    report = hydraulic_report   # может прийти готовым (режим 2)
    if network is not None:
        from app.calc.fire_hydraulics import (
            solve_fire_hydraulics_scenario, NetworkMode,
        )
        from app.calc.diameter_audit import audit_sections
        from app.calc.fire_hydraulic_report import build_hydraulic_report
        mode = network_mode or NetworkMode.PURE_FIRE

        hydraulic_result = solve_fire_hydraulics_scenario(
            network, required_jets, mode=mode, scenario_filter=scenario_filter)
        bundle.fire_hydraulic_result = hydraulic_result
        if hydraulic_result.dictating_scenario is None:
            bundle.warnings.append(
                "fire_hydraulics: сценарий не рассчитан "
                f"({'; '.join(hydraulic_result.warnings) or 'нет диктующего'})")
            bundle.status.append("fire_hydraulics: без диктующего сценария")
        else:
            audit = audit_sections(
                hydraulic_result.dictating_scenario.sections, mode,
                dn_by_segment=dn_by_segment)
            bundle.diameter_audit = audit
            report = build_hydraulic_report(hydraulic_result, audit)
            bundle.status.append("fire_hydraulics + diameter_audit: рассчитаны")
    else:
        bundle.warnings.append("fire_hydraulics skipped: network not provided")

    bundle.hydraulic_report = report

    # ── Мост: обогащаем FireSystem результатами (только если что-то посчитано) ──
    if layout_results or hydraulic_result:
        enriched = enrich_fire_from_layout_and_hydraulics(
            fire, layout_results=layout_results, hydraulic_result=hydraulic_result)
        project = replace(project, fire=enriched)
        bundle.project = project
        bundle.status.append("enrich_fire: FireSystem обогащён расчётными данными")
    else:
        bundle.warnings.append("documents built from pre-filled project.fire "
                               "(расчётные слои пропущены)")

    # ── Документы: всегда собираются из текущего project ──
    doc_cipher = (project.document.cipher or "ИОС2")

    bundle.pz_pdf = generate_pz_pdf(project, os.path.join(output_dir, "ПЗ.pdf"))
    bundle.status.append("ПЗ.pdf собран")

    bundle.spec_pdf = generate_spec_pdf(project, os.path.join(output_dir, "Спецификация.pdf"))
    bundle.status.append("Спецификация.pdf собрана")

    try:
        bundle.scheme_pdf = generate_scheme_pdf(project, os.path.join(output_dir, "Схема.pdf"))
        bundle.status.append("Схема.pdf собрана")
    except Exception as e:
        bundle.warnings.append(f"scheme skipped: {e}")

    # гидролист — только если есть отчёт (расчётный или переданный)
    if report is not None:
        bundle.hydraulic_pdf = generate_hydraulic_report_pdf(
            project, report, os.path.join(output_dir, "Гидравлический_расчет.pdf"))
        bundle.status.append("Гидравлический_расчет.pdf собран")
    else:
        bundle.warnings.append("hydraulic report PDF skipped: no hydraulic report available")

    return bundle
