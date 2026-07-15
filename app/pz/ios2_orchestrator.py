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
    resilience_report: Optional[object] = None
    resilience_pdf: Optional[str] = None
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

    # ── Автопостроение геометрии из спецификаций проекта (truly one-click) ──
    # Явно переданные аргументы имеют приоритет; спеки используются, только
    # если аргумента нет. Построение — чистая развёртка, без расчётов.
    from app.pz import geometry_builder as _gb
    if layout_inputs is None and _gb.project_has_layout_geometry(project):
        try:
            layout_inputs = _gb.build_layout_inputs(project)
            bundle.status.append(
                f"geometry: layout_inputs построены из project.fire_rooms "
                f"({len(layout_inputs)} помещений)")
        except ValueError as e:
            bundle.warnings.append(f"geometry: fire_rooms не развёрнуты: {e}")
    if network is None and _gb.project_has_network_geometry(project):
        try:
            network = _gb.build_network(project)
            bundle.status.append("geometry: network построена из project.fire_network")
        except ValueError as e:
            bundle.warnings.append(f"geometry: fire_network не развёрнута: {e}")

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

    # ── Живучесть кольца: только если сеть кольцевая и гидравлика решена ──
    if network is not None and hydraulic_result is not None \
            and hydraulic_result.dictating_scenario is not None:
        from app.calc.ring_hydraulics import analyze_ring_resilience
        try:
            resilience = analyze_ring_resilience(network, required_jets,
                                                 mode=network_mode,
                                                 scenario_filter=scenario_filter)
        except Exception as e:
            resilience = None
            bundle.warnings.append(f"resilience: анализ не выполнен ({e})")
        if resilience is not None:
            bundle.resilience_report = resilience
            bundle.status.append(
                "ring_resilience: проверены одиночные отказы участков кольца")

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

    # ── Расходы В1/Т3 из групп потребителей (СП 30, метод α) ──
    if getattr(project, "consumer_groups", None):
        from app.pz.demand_bridge import compute_flows
        try:
            project.flows = compute_flows(
                project.consumer_groups,
                sewage_max_fixture_lps=project.sewage_max_fixture_lps,
            )
            bundle.status.append(
                f"water_demand: расходы В1/Т3 рассчитаны "
                f"(q_сут={project.flows.q_day_tot:.1f} м³/сут, "
                f"q_сек={project.flows.q_sec_tot:.2f} л/с)")
        except Exception as e:
            bundle.warnings.append(f"water_demand: расчёт расходов не выполнен ({e})")

        # ── Водомер → Hтр → насос В1. Порядок важен: потери в водомере
        # входят в формулу (14) п. 8.27 СП 30.13330.2020. ──
        try:
            from app.calc.water_meters import MeterInput, calculate_meters
            from app.pz.flows_bridge import meters_from_calc
            from app.pz.rules import calc_required_head
            from app.pz.pump_bridge import compute_pump_from_head

            hws = getattr(project.building.hws_type, "value", project.building.hws_type)
            hws_type = "local" if hws == "local" else "central"
            meter_res = calculate_meters(MeterInput(
                hws_type=hws_type,
                period_hours=project.source.water_use_period_h,
                q_fire_l_per_s=project.fire.q_total if project.fire.required else 0.0,
                inputs_count=project.source.inputs_count,
                q_sec_tot=project.flows.q_sec_tot,
                q_sec_c=project.flows.q_sec_c,
                q_sec_h=project.flows.q_sec_h,
                q_day_tot=project.flows.q_day_tot,
                q_day_c=project.flows.q_day_c,
                q_day_h=project.flows.q_day_h,
                q_hr_c=project.flows.q_hr_c,
                q_hr_h=project.flows.q_hr_h,
            ))
            project.meters = meters_from_calc(meter_res)
            # Для local это общий ввод, для central — узел ХВС.
            head_meter = next((m for m in meter_res.meters
                               if ("ввод" in m.label.lower() if hws_type == "local"
                                   else "хвс" in m.label.lower())), None)
            h_vod = head_meter.h_normal if head_meter is not None else None
            project.source.h_vod_m = h_vod
            bundle.status.append(
                f"meters: подобрано узлов {len(project.meters.rows)}; "
                f"потери диктующего узла {h_vod:.3f} м" if h_vod is not None
                else f"meters: подобрано узлов {len(project.meters.rows)}")

            head = calc_required_head(project.source, h_vod_m=h_vod)
            if head.h_required_m is None:
                bundle.warnings.append(
                    "head: H_тр не рассчитан — задайте Hgeom (отметки), потери "
                    "внутренней сети и потери на вводе; условные значения не подставляются")
                project.pumps = replace(project.pumps, required=False)
            elif head.h_guaranteed_m is None:
                bundle.warnings.append(
                    f"head: H_тр={head.h_required_m:.2f} м, но H_гар по ТУ не задан — "
                    "необходимость и рабочая точка насоса не определены")
                project.pumps = replace(project.pumps, required=False)
            else:
                bundle.status.append(
                    f"head: H_тр={head.h_required_m:.2f} м; "
                    f"H_гар={head.h_guaranteed_m:.2f} м")
                q_sec = (project.flows.q_sec_tot if hws_type == "local"
                         else project.flows.q_sec_c)
                ps = compute_pump_from_head(
                    q_design_m3h=q_sec * 3.6,
                    head=head,
                    npsh_a_m=project.source.npsh_available_m,
                )
                project.pumps = ps
                if ps.required and ps.model:
                    bundle.status.append(
                        f"pump: подобран {ps.model} "
                        f"(рабочая точка Q={ps.wp_q:.1f} м³/ч, H={ps.wp_h:.1f} м)")
                elif head.pump_needed:
                    bundle.warnings.append(
                        "pump: повысительная установка требуется, но каталог не дал кандидата")
                else:
                    bundle.status.append("pump: H_гар достаточен, повысительная установка не требуется")
        except Exception as e:
            bundle.warnings.append(f"meters/head/pump: расчётная цепочка не выполнена ({e})")
    else:
        bundle.warnings.append(
            "water_demand: группы потребителей не заданы — расходы В1 нулевые, "
            "ПЗ покажет прочерки (задайте consumers в запросе)")

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

    if bundle.resilience_report is not None:
        from app.pz.generator import generate_resilience_pdf
        bundle.resilience_pdf = generate_resilience_pdf(
            project, bundle.resilience_report,
            os.path.join(output_dir, "Проверка_живучести.pdf"))
        bundle.status.append("Проверка_живучести.pdf собрана")

    return bundle
