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
from app.pz.flows_bridge import (
    balance_from_calc,
    enrich_fire_from_layout_and_hydraulics,
)
from app.pz.generator import (
    generate_pz_pdf, generate_spec_pdf, generate_scheme_pdf,
    generate_hydraulic_report_pdf, generate_pump_selection_pdf,
    generate_balance_pdf, generate_v1_calculation_pdf, append_pdf,
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
    pump_selection_pdf: Optional[str] = None
    v1_calculation_pdf: Optional[str] = None
    balance_pdf: Optional[str] = None
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
    required_jets: Optional[int] = None,
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
    purpose = getattr(project.building.purpose, "value", project.building.purpose)
    if purpose in ("residential", "public"):
        bundle.status.append(
            "gost_r_21_619: состав ПЗ проверяется по ГОСТ Р 21.619-2023; "
            "баланс непроизводственного объекта — п. 5.1.21, форма 2 приложения А"
        )
    else:
        bundle.status.append(
            "gost_r_21_619: для производственного объекта требуется баланс "
            "по п. 5.1.20, форма 1 приложения А"
        )
    fire = project.fire
    if fire.required:
        required_jets = required_jets or fire.streams
    else:
        layout_inputs = None
        network = None
        required_jets = 0
        bundle.status.append(
            "fire: ВПВ не требуется; геометрия, гидравлика, насосы "
            "и спецификация В2 исключены"
        )

    # ── Автопостроение геометрии из спецификаций проекта (truly one-click) ──
    # Явно переданные аргументы имеют приоритет; спеки используются, только
    # если аргумента нет. Построение — чистая развёртка, без расчётов.
    from app.pz import geometry_builder as _gb
    if fire.required and layout_inputs is None and _gb.project_has_layout_geometry(project):
        try:
            layout_inputs = _gb.build_layout_inputs(project)
            bundle.status.append(
                f"geometry: layout_inputs построены из project.fire_rooms "
                f"({len(layout_inputs)} помещений)")
        except ValueError as e:
            bundle.warnings.append(f"geometry: fire_rooms не развёрнуты: {e}")
    if fire.required and network is None and _gb.project_has_network_geometry(project):
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
    elif fire.required:
        bundle.warnings.append("fire_layout skipped: layout_inputs not provided")

    # ── Режим 1б: гидравлика + аудит (если есть network) ──
    hydraulic_result = None
    audit = None
    report = hydraulic_report   # может прийти готовым (режим 2)
    if fire.required and network is not None:
        if required_jets not in (1, 2):
            raise ValueError(
                "Для гидравлического расчёта В2 требуется 1 или 2 "
                f"одновременные струи; получено {required_jets!r}"
            )
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
    elif fire.required:
        bundle.warnings.append("fire_hydraulics skipped: network not provided")

    bundle.hydraulic_report = report

    # ── Живучесть кольца: только если сеть кольцевая и гидравлика решена ──
    if fire.required and network is not None and hydraulic_result is not None \
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
            if resilience.explicit_repair_sections and not resilience.normative_warnings:
                bundle.status.append(
                    "ring_resilience: проверены ремонтные секции и отказы вводов")
            else:
                bundle.status.append(
                    "ring_resilience: предварительно, требуется секционирование СП 10")

    # ── Мост: обогащаем FireSystem результатами (только если что-то посчитано) ──
    if fire.required and (layout_results or hydraulic_result):
        enriched = enrich_fire_from_layout_and_hydraulics(
            fire, layout_results=layout_results, hydraulic_result=hydraulic_result)
        project = replace(project, fire=enriched)
        bundle.project = project
        bundle.status.append("enrich_fire: FireSystem обогащён расчётными данными")
    elif fire.required:
        bundle.warnings.append("documents built from pre-filled project.fire "
                               "(расчётные слои пропущены)")

    # Пожарная насосная В2 — отдельный подбор по рабочей точке основного
    # расчётного сценария. Ремонтный/аварийный режим кольца сюда не подмешивается.
    if (fire.required and hydraulic_result is not None
            and hydraulic_result.pump_duty is not None):
        from app.pz.pump_bridge import compute_fire_pump_from_duty
        project.fire_pumps = compute_fire_pump_from_duty(
            hydraulic_result.pump_duty,
            npsh_a_m=project.source.npsh_available_m,
            maximum_source_head_m=project.source.maximum_head_m,
        )
        if project.fire_pumps.model:
            bundle.status.append(
                f"fire_pump: подобран {project.fire_pumps.model} "
                f"(Q={project.fire_pumps.wp_q:.1f} м³/ч, "
                f"H={project.fire_pumps.wp_h:.1f} м; 1 раб. + 1 рез.)")
        else:
            bundle.warnings.append(
                "fire_pump: насос В2 требуется, но архивный каталог не дал "
                "кандидата; в ПЗ сохранена расчётная точка")
        bundle.project = project

    # ── Документы: всегда собираются из текущего project ──
    doc_cipher = (project.document.cipher or "ИОС2")

    # ── Расходы В1/Т3 из групп потребителей (СП 30, метод α) ──
    if (getattr(project, "consumer_groups", None)
            or getattr(project, "v1_network", None)):
        from app.pz.demand_bridge import compute_flows
        try:
            project.flows = compute_flows(
                project.consumer_groups,
                sewage_max_fixture_lps=project.sewage_max_fixture_lps,
            )
            balance_groups = (
                project.consumer_details
                if getattr(project, "consumer_details", None)
                else project.consumer_groups
            )
            project.balance = balance_from_calc(balance_groups, project.flows)
            bundle.status.append(
                f"water_demand: расходы В1/Т3 рассчитаны "
                f"(q_сут={project.flows.q_day_tot:.1f} м³/сут, "
                f"q_сек={project.flows.q_sec_tot:.2f} л/с)")
            bundle.status.append(
                f"balance: форма 2 собрана, строк {len(project.balance.rows)}")
        except Exception as e:
            bundle.warnings.append(f"water_demand: расчёт расходов не выполнен ({e})")

        # ── Стадия П: точные сечения и проверка скорости на вводе В1 ──
        # Без аксонометрии расход по отдельному стояку/ветви не назначается.
        if not getattr(project, "v1_network", None) and not getattr(project, "v1_sections", None):
            from app.calc.v1_stage_p import calculate_v1_stage_p
            try:
                hws = getattr(project.building.hws_type, "value", project.building.hws_type)
                v1_flow = project.flows.q_sec_tot if hws == "local" else project.flows.q_sec_c
                project.v1_stage_p_result = calculate_v1_stage_p(
                    v1_flow, project.source.inputs_count)
                inlet = project.v1_stage_p_result.rows[0]
                bundle.status.append(
                    f"v1_stage_p: ввод DN{inlet.dn} {inlet.outer_mm:g}×{inlet.wall_mm:g}; "
                    f"dвн={inlet.inner_mm:g} мм; Q={inlet.flow_lps:.3f} л/с; "
                    f"v={inlet.velocity_mps:.3f} м/с; "
                    f"скорость {'соответствует' if inlet.velocity_ok else 'не соответствует'}")
            except Exception as e:
                bundle.warnings.append(f"v1_stage_p: проверка сечений не выполнена ({e})")

        # ── Гидравлика В1: топология приоритетна, ручной путь — резерв ──
        if getattr(project, "v1_network", None):
            from app.calc.v1_hydraulics import (
                V1InletInput, V1NetworkSectionInput, V1NodeInput,
                apply_v1_inlets, calculate_v1_network,
            )
            try:
                network = project.v1_network
                hws = getattr(project.building.hws_type, "value", project.building.hws_type)
                v1_result = calculate_v1_network(
                    [V1NodeInput(**vars(node)) for node in network.nodes],
                    [V1NetworkSectionInput(**vars(section)) for section in network.sections],
                    network.source_node,
                    flow_kind="total" if hws == "local" else "cold",
                )
                if network.inlets:
                    v1_result = apply_v1_inlets(
                        v1_result,
                        [V1InletInput(**vars(inlet)) for inlet in network.inlets],
                    )
                    dictating_inlet = next(
                        x for x in v1_result.inlet_checks
                        if x.inlet_id == v1_result.dictating_inlet_id
                    )
                    project.source.inputs_count = len(v1_result.inlet_checks)
                    project.source.guaranteed_head_m = dictating_inlet.guaranteed_head_m
                    project.source.maximum_head_m = max(
                        x.maximum_head_m for x in v1_result.inlet_checks
                    )
                project.v1_hydraulic_result = v1_result
                direct_q = sum(node.direct_demand_lps for node in network.nodes)
                if direct_q:
                    # Прямой технологический/приборный расход входит и в расход
                    # корневого участка, и в расчётный секундный расход водомера.
                    if hws == "local":
                        project.flows = replace(
                            project.flows, q_sec_tot=v1_result.source_flow_lps)
                    else:
                        project.flows = replace(
                            project.flows,
                            q_sec_c=v1_result.source_flow_lps,
                            q_sec_tot=round(project.flows.q_sec_tot + direct_q, 3),
                        )
                dictating = next(x for x in v1_result.node_checks
                                 if x.node_id == v1_result.dictating_node_id)
                source_node = next(x for x in network.nodes if x.node_id == network.source_node)
                project.source.elev_header_m = source_node.elevation_m
                project.source.elev_fixture_m = dictating.elevation_m
                project.source.h_geom_m = None
                project.source.h_pr_m = dictating.h_pr_m
                project.source.il_dict_m = None
                project.source.h_il_m = v1_result.internal_loss_m
                project.source.il_vvod_m = None
                project.source.h_vvod_m = v1_result.input_loss_m
                inlet_status = (
                    f"; проверено вводов {len(v1_result.inlet_checks)} при 100% расходе; "
                    f"диктующий ввод {v1_result.dictating_inlet_id}"
                    if v1_result.inlet_checks else ""
                )
                ring_status = (
                    f"; кольцо увязано за {v1_result.ring_iterations} ит.; "
                    f"проверено отказов {len(v1_result.ring_scenarios)}; "
                    f"диктующий отказ {v1_result.dictating_outage_section_id}"
                    if v1_result.topology_kind == "single_ring" else ""
                )
                bundle.status.append(
                    f"v1_hydraulics: топология {len(v1_result.sections)} участков; "
                    f"диктующий узел {v1_result.dictating_node_id}; "
                    f"автоподбор dвн на "
                    f"{sum(s.diameter_selection == 'auto' for s in v1_result.sections)} участках; "
                    f"ΣHil={v1_result.internal_loss_m:.3f} м; "
                    f"Hlввод={v1_result.input_loss_m:.3f} м; "
                    f"vmax={v1_result.max_velocity_mps:.2f} м/с"
                    f"{inlet_status}{ring_status}")
                if not v1_result.all_velocities_ok:
                    bad = ", ".join(s.section_id for s in v1_result.sections if not s.velocity_ok)
                    bundle.warnings.append(
                        f"v1_hydraulics: превышена допустимая скорость на участках {bad}")
            except Exception as e:
                bundle.warnings.append(f"v1_hydraulics: расчёт не выполнен ({e})")
        elif getattr(project, "v1_sections", None):
            from app.calc.v1_hydraulics import V1SectionInput, calculate_v1_hydraulics
            try:
                v1_result = calculate_v1_hydraulics([
                    V1SectionInput(**vars(section)) for section in project.v1_sections
                ])
                project.v1_hydraulic_result = v1_result
                # Готовые суммы уже содержат местные сопротивления по формуле (15),
                # поэтому кладём их в ready-поля, не применяя k_l второй раз.
                project.source.il_dict_m = None
                project.source.h_il_m = v1_result.internal_loss_m
                project.source.il_vvod_m = None
                project.source.h_vvod_m = v1_result.input_loss_m
                bundle.status.append(
                    f"v1_hydraulics: ручной путь, {len(v1_result.sections)} участков; "
                    f"ΣHil={v1_result.internal_loss_m:.3f} м; "
                    f"Hlввод={v1_result.input_loss_m:.3f} м; "
                    f"vmax={v1_result.max_velocity_mps:.2f} м/с")
                if not v1_result.all_velocities_ok:
                    bad = ", ".join(s.section_id for s in v1_result.sections if not s.velocity_ok)
                    bundle.warnings.append(
                        f"v1_hydraulics: превышена допустимая скорость на участках {bad}")
            except Exception as e:
                bundle.warnings.append(f"v1_hydraulics: расчёт не выполнен ({e})")
        else:
            bundle.warnings.append(
                "v1_hydraulics: участки диктующего направления не заданы; "
                "потери В1 принимаются только из явных исходных данных")

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

            v1_pressure_result = project.v1_hydraulic_result
            if (getattr(v1_pressure_result, "node_checks", None)
                    and head.h_required_m is not None):
                from app.calc.v1_hydraulics import audit_v1_pressures
                static_source_head = None
                if project.source.maximum_head_m is not None:
                    if project.pumps.required:
                        if project.pumps.curve:
                            static_source_head = (
                                project.source.maximum_head_m
                                + max(point[1] for point in project.pumps.curve))
                    else:
                        static_source_head = project.source.maximum_head_m
                common_dynamic_loss = (h_vod or 0.0) + project.source.h_tepl_m
                pressure_result = audit_v1_pressures(
                    v1_pressure_result,
                    required_source_head_m=head.h_required_m,
                    common_dynamic_loss_m=common_dynamic_loss,
                    static_source_head_m=static_source_head,
                )
                project.v1_hydraulic_result = pressure_result
                project.building = replace(
                    project.building,
                    zones=max(project.building.zones,
                              len(pressure_result.pressure_zones)),
                )
                bundle.status.append(
                    f"v1_pressure_zones: проверено {len(pressure_result.pressure_checks)} "
                    f"узлов; рекомендовано зон {len(pressure_result.pressure_zones)}; "
                    f"привязано ветвей {sum(x.topology_feasible for x in pressure_result.zone_regulators)}")
                infeasible = [x.zone_id for x in pressure_result.zone_regulators
                              if x.required and not x.topology_feasible]
                if infeasible:
                    bundle.warnings.append(
                        "v1_pressure_zones: для зон " + ", ".join(infeasible)
                        + " нет отдельной питающей ветви; требуется разделить трассы")
                if not pressure_result.all_minimum_pressures_ok:
                    bad = ", ".join(x.node_id for x in pressure_result.pressure_checks
                                    if not x.minimum_ok)
                    bundle.warnings.append(
                        f"v1_pressure_zones: недостаточный динамический напор в узлах {bad}")
                if pressure_result.all_maximum_pressures_ok is None:
                    bundle.warnings.append(
                        "v1_pressure_zones: максимальный статический напор не проверен — "
                        "задайте source_data.maximum_head_m по ТУ")
                elif not pressure_result.all_maximum_pressures_ok:
                    bad = ", ".join(x.node_id for x in pressure_result.pressure_checks
                                    if x.maximum_ok is False)
                    bundle.warnings.append(
                        f"v1_pressure_zones: превышен максимальный статический напор "
                        f"в узлах {bad}; требуется зонирование/регулирование давления")
        except Exception as e:
            bundle.warnings.append(f"meters/head/pump: расчётная цепочка не выполнена ({e})")
    else:
        bundle.warnings.append(
            "water_demand: группы потребителей не заданы — расходы В1 нулевые, "
            "ПЗ покажет прочерки (задайте consumers в запросе)")

    bundle.pz_pdf = generate_pz_pdf(project, os.path.join(output_dir, "ПЗ.pdf"))
    bundle.status.append("ПЗ.pdf собран")

    bundle.v1_calculation_pdf = generate_v1_calculation_pdf(
        project, os.path.join(output_dir, "Расчеты_В1.pdf"))
    append_pdf(bundle.pz_pdf, bundle.v1_calculation_pdf)
    bundle.status.append(
        "Расчеты_В1.pdf собран отдельным расчётным приложением "
        "и добавлен в конец ПЗ.pdf")

    bundle.balance_pdf = generate_balance_pdf(
        project, os.path.join(output_dir, "Баланс_ВиВ.pdf"))
    append_pdf(bundle.pz_pdf, bundle.balance_pdf)
    bundle.status.append(
        "Баланс_ВиВ.pdf собран по форме 2 ГОСТ Р 21.619-2023 "
        "и добавлен в конец ПЗ.pdf")

    bundle.pump_selection_pdf = generate_pump_selection_pdf(
        project, os.path.join(output_dir, "Подбор_насосов.pdf"))
    append_pdf(bundle.pz_pdf, bundle.pump_selection_pdf)
    bundle.status.append(
        "Подбор_насосов.pdf собран отдельным приложением и добавлен в конец ПЗ.pdf")

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
