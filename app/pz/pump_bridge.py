# -*- coding: utf-8 -*-
"""
app/pz/pump_bridge.py — мост подбора насоса в модель проекта.

Берёт расчётный расход и параметры системы, гонит штатный calculate_pump
(требуемый напор → кривая системы H=H_ст+k·Q² → рабочая точка → кавитация →
подбор насоса), раскладывает лучший вариант в PumpSystem проекта — откуда
ПЗ берёт модель, рабочую точку, мощность и строит график Q-H.

Мост, не расчётчик: подбор и рабочая точка — в app/calc/pumps.py.
"""
from __future__ import annotations

from app.calc.pumps import PumpInput, calculate_pump, interpolate_pump_head
from app.pz.project import PumpComplianceCheck, PumpSystem
from app.pz.rules import HeadCalc


def compute_pump(
    *,
    q_design_m3h: float,
    floors: int,
    floor_height_m: float = 3.0,
    h_losses_m: float = 8.0,
    h_pr_m: float = 20.0,
    h_gar_m: float | None = None,
    npsh_a_m: float | None = None,
    purpose: str = "хозяйственно-питьевой",
) -> tuple[PumpSystem, float]:
    """Подбор насоса → (PumpSystem, требуемый напор H_тр).

    Возвращает и PumpSystem (для ПЗ), и H_тр отдельно (для раздела напора).
    Если кандидатов нет — PumpSystem.required=True, но без модели (честно:
    подбор не дал результата, проектировщик подбирает вручную).
    """
    if q_design_m3h <= 0:
        return PumpSystem(required=False), 0.0
    if h_gar_m is None:
        raise ValueError("Для подбора насоса требуется Hгар из ТУ")

    res = calculate_pump(PumpInput(
        q_design_m3h=q_design_m3h, pump_type="boost", floors=floors,
        floor_height=floor_height_m, h_losses=h_losses_m,
        h_pr=h_pr_m, h_gar=h_gar_m, npsh_a=npsh_a_m))

    ps = PumpSystem(
        required=True, purpose=purpose,
        h_stat=round(res.h_stat, 2), k_sys=round(res.k_sys, 5))

    if not res.candidates:
        ps.count_note = "подбор не дал результата — подобрать вручную"
        return ps, round(res.h_required, 2)

    best = res.candidates[0]
    pump = best.pump
    wp = best.working_point
    ps.model = f"{pump.brand} {pump.model}"
    ps.q_m3h = round(wp.q, 2)
    ps.head_m = round(wp.h, 2)
    ps.power_kw = pump.p_kw
    ps.wp_q = round(wp.q, 2)
    ps.wp_h = round(wp.h, 2)
    ps.q_opt = pump.q_opt
    ps.curve = [(pt.q, pt.h) for pt in pump.curve]   # формат графика: (q, h)
    ps.count_note = "1 рабочий + 1 резервный"
    ps.top3 = [f"{c.pump.brand} {c.pump.model} "
               f"(Q={c.working_point.q:.1f} м³/ч, H={c.working_point.h:.1f} м)"
               for c in res.candidates[:3]]
    return ps, round(res.h_required, 2)


def compute_pump_from_head(
    *,
    q_design_m3h: float,
    head: HeadCalc,
    npsh_a_m: float | None = None,
    purpose: str = "хозяйственно-питьевой",
) -> PumpSystem:
    """Подобрать повысительную установку по уже рассчитанному Hтр.

    Функция принципиально не восстанавливает геометрию по этажности и не
    подставляет условные потери. При неполном Hтр или отсутствии Hгар подбор
    не выполняется.
    """
    if q_design_m3h <= 0 or head.h_required_m is None or head.h_guaranteed_m is None:
        return PumpSystem(required=False)
    if not head.pump_needed:
        return PumpSystem(required=False)
    if head.h_geom_m is None or head.h_losses_dynamic_m is None:
        return PumpSystem(required=False)

    res = calculate_pump(PumpInput(
        q_design_m3h=q_design_m3h,
        pump_type="boost",
        h_geom_manual=head.h_geom_m,
        h_losses=head.h_losses_dynamic_m,
        h_pr=head.h_pr_m,
        h_gar=head.h_guaranteed_m,
        npsh_a=npsh_a_m,
    ))

    # Единый мост сохраняет подробные характеристики кандидатов для таблицы
    # ГОСТ Р 21.619-2023, п. 5.1.8, и графика Q-H.
    from app.pz.flows_bridge import pump_from_calc
    return pump_from_calc(
        res,
        purpose=purpose,
        type_label="хозяйственно-питьевой",
        scheme_note="1 рабочий + 1 резервный",
    )


def compute_fire_pump_from_duty(
    pump_duty,
    *,
    npsh_a_m: float | None = None,
    maximum_source_head_m: float | None = None,
) -> PumpSystem:
    """Подобрать пожарную установку по рабочей точке основного режима В2.

    ``pump_duty`` формирует гидравлика В2: расход всего расчётного сценария и
    напор, который должен создать насос. Характеристика системы строится тем же
    legacy-алгоритмом ``H=kQ²`` при Hст=0. Резервный агрегат не складывается с
    рабочим: подбор выполняется по кривой одного рабочего насоса.
    """
    if pump_duty is None:
        return PumpSystem(required=False)
    q_lps = float(getattr(pump_duty, "flow_lps", 0.0) or 0.0)
    head_m = float(getattr(pump_duty, "required_head_m", 0.0) or 0.0)
    if q_lps <= 0 or head_m <= 0:
        return PumpSystem(required=False)

    res = calculate_pump(PumpInput(
        q_design_m3h=q_lps * 3.6,
        pump_type="fire",
        mode="1",
        h_geom_manual=head_m,
        h_losses=0.0,
        h_pr=0.0,
        h_gar=0.0,
        npsh_a=npsh_a_m,
    ))

    # СП 10, п. 12.1 требует обеспечить именно максимальные расчётные Q/H.
    # Legacy-скоринг допускает отклонение рабочей точки до 15%; для В2 это
    # недостаточно, поэтому нормативный слой оставляет только кривые, которые
    # фактически дают Hрасч при полном Qрасч.
    res.candidates = [
        candidate for candidate in res.candidates
        if interpolate_pump_head(candidate.eff_curve, res.q_design)
        >= res.h_required - 1e-9
    ]
    from app.pz.flows_bridge import pump_from_calc
    ps = pump_from_calc(
        res,
        purpose="внутреннее пожаротушение В2",
        type_label="пожарный",
        scheme_note="1 рабочий + 1 резервный (СП 10.13130.2020, п. 12.3)",
    )
    ps.working_units = 1
    ps.reserve_units = 1

    curve_check = None
    if res.candidates:
        curve_check = interpolate_pump_head(
            res.candidates[0].eff_curve, res.q_design)
        ps.pump_head_at_design_m = round(curve_check, 1)

        shutoff_head_m = max(point.h for point in res.candidates[0].eff_curve)
        if maximum_source_head_m is not None:
            ps.maximum_system_pressure_bar = round(
                (maximum_source_head_m + shutoff_head_m) / 10.1972, 2)

    ps.sp10_checks = [
        PumpComplianceCheck(
            clause="12.1",
            requirement="Обеспечение максимальных расчётных расхода и давления",
            decision=(
                f"Один рабочий агрегат: при Q={res.q_design:.2f} м³/ч "
                f"каталожный напор {curve_check:.1f} м >= Hрасч={res.h_required:.1f} м"
                if curve_check is not None else
                "Подходящая Q-H характеристика в подключённом каталоге не найдена"
            ),
            status="verified" if curve_check is not None else "fail",
        ),
        PumpComplianceCheck(
            clause="12.3",
            requirement="Резерв наиболее производительного рабочего агрегата",
            decision="Предусмотрен 1 рабочий и 1 однотипный резервный агрегат; автоматический ввод резерва",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.5",
            requirement="Категории надежности",
            decision="Подача воды - II категория; электроснабжение - I категория",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.9-12.11",
            requirement="Размещение и противопожарное отделение насосной станции",
            decision="Помещение и строительные конструкции подтвердить решениями АР",
            status="pending",
        ),
        PumpComplianceCheck(
            clause="12.12-12.15",
            requirement="Условия помещения, освещение, связь и световое табло",
            decision="Предусмотреть 5-35 °C, рабочее/аварийное освещение, связь с пожарным постом и табло у входа",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.17",
            requirement="Подключение мобильной пожарной техники",
            decision="Предусмотреть не менее двух выведенных наружу патрубков DN 80; количество проверить по расчётному расходу",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.20-12.21",
            requirement="Условия всасывания и установка насоса",
            decision="NPSHa и отметку оси насоса проверить по схеме и документации изготовителя",
            status="pending",
        ),
        PumpComplianceCheck(
            clause="12.26",
            requirement="Фундамент насосных агрегатов",
            decision="Массу фундамента принять по документации изготовителя; при отсутствии данных - не менее четырёх масс агрегатов",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.27",
            requirement="Не менее двух всасывающих трубопроводов",
            decision="Предусмотреть 2 линии, каждая на полный расчётный расход",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.28",
            requirement="Не менее двух напорных трубопроводов",
            decision="Предусмотреть 2 линии, каждая на полный расчётный расход",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.30",
            requirement="Арматура и контроль у каждого насоса",
            decision="На напоре: манометр, обратный клапан и запорное устройство; на всасе: манометр и запорное устройство",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.33-12.34",
            requirement="Пуск после проверки давления и контроль агрегатов",
            decision="Автоматический/дистанционный пуск после контроля давления; контроль давления у каждого агрегата",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="12.36",
            requirement="Проверка проектного расхода",
            decision="Предусмотреть устройство проверки проектного расхода В2",
            status="specified",
        ),
        PumpComplianceCheck(
            clause="13.8",
            requirement="Контроль положения запорных устройств",
            decision="Предусмотреть сигнализацию положений «Закрыто»/«Открыто» входной и выходной напорной арматуры",
            status="specified",
        ),
    ]

    suction_check = next(c for c in ps.sp10_checks if c.clause == "12.20-12.21")
    if npsh_a_m is not None and res.candidates:
        npshr = res.candidates[0].pump.npshr
        ok = npsh_a_m >= npshr + 0.5
        suction_check.decision = f"NPSHa={npsh_a_m:.1f} м; NPSHr+0,5={npshr + 0.5:.1f} м"
        suction_check.status = "verified" if ok else "fail"

    if maximum_source_head_m is None:
        ps.sp10_checks.append(PumpComplianceCheck(
            clause="13.12",
            requirement="Проверка максимального давления после насосов",
            decision="Требуется максимальный напор наружной сети по ТУ",
            status="pending",
        ))
    elif ps.maximum_system_pressure_bar is not None and res.candidates:
        pmax = res.candidates[0].pump.p_max_bar
        ok = ps.maximum_system_pressure_bar <= pmax
        ps.sp10_checks.append(PumpComplianceCheck(
            clause="13.12",
            requirement="Проверка максимального давления после насосов",
            decision=(f"Расчётное максимальное давление {ps.maximum_system_pressure_bar:.2f} бар; "
                      f"допустимое для установки {pmax:.1f} бар"),
            status="verified" if ok else "fail",
        ))

    if any(check.status == "fail" for check in ps.sp10_checks):
        ps.sp10_compliant = False
    elif any(check.status == "pending" for check in ps.sp10_checks):
        ps.sp10_compliant = None
    else:
        ps.sp10_compliant = True
    if not res.candidates:
        ps.selection_note = (
            f"Каталог не содержит установки, перекрывающей расчётную точку "
            f"Q={q_lps * 3.6:.2f} м³/ч, H={head_m:.1f} м; марку уточнить "
            "по актуальным кривым изготовителя."
        )
    return ps


def head_components(
    *,
    q_design_m3h: float,
    floors: int,
    floor_height_m: float = 3.0,
    h_losses_m: float = 8.0,
    h_pr_m: float = 20.0,
    h_gar_m: float | None = None,
) -> dict:
    """Разложение требуемого напора для таблицы ПЗ (формула 14 п.8.27).
    H_тр = H_геом + ∑потери + H_пр (− H_гар даёт напор насоса)."""
    if h_gar_m is None:
        raise ValueError("Для расчёта напора требуется Hгар из ТУ")
    res = calculate_pump(PumpInput(
        q_design_m3h=q_design_m3h, pump_type="boost", floors=floors,
        floor_height=floor_height_m, h_losses=h_losses_m,
        h_pr=h_pr_m, h_gar=h_gar_m))
    return {
        "h_required_m": round(res.h_required, 2),
        "h_geom_m": round(res.h_geom, 2),
        "h_losses_m": round(h_losses_m, 2),
        "h_pr_m": round(h_pr_m, 2),
        "h_gar_m": round(h_gar_m, 2),
    }
