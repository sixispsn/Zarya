"""
Мост между расчётным ядром (app.calc.water_demand) и моделью ПЗ (FlowsData).

Расходы в пояснительной записке должны считаться ядром из состава потребителей,
а не задаваться вручную. Эта функция берёт результат calculate_water_demand()
и раскладывает его в FlowsData, который потребляет генератор ПЗ.
"""
from app.calc.water_demand import WaterDemandResult, calculate_water_demand, ConsumerGroup
from app.pz.project import (FlowsData, PumpSystem, PumpCandidate,
    MetersSystem, MeterRow, BalanceData, ConsumerRow, FireSystem)


def flows_from_demand(
    result: WaterDemandResult,
    *,
    irrigation_m3_day: float = 0.0,
    q_year_m3: float = 0.0,
) -> FlowsData:
    """
    Собрать FlowsData из результата расчёта водопотребления.

    Args:
        result: выход calculate_water_demand()
        irrigation_m3_day: суточный расход на полив (из блока irrigation, если есть)
        q_year_m3: годовой расход (если посчитан отдельно; иначе ПЗ возьмёт q_day*365)
    """
    return FlowsData(
        q_day_tot=result.total.q_day,
        q_day_c=result.cold.q_day,
        q_day_h=result.hot.q_day,
        q_sec_tot=result.total.q_sec,
        q_sec_c=result.cold.q_sec,
        q_sec_h=result.hot.q_sec,
        q_hr_tot=result.total.q_hr,
        q_hr_c=result.cold.q_hr,
        q_hr_h=result.hot.q_hr,
        sewage_l_per_s=result.sewage_flow,
        sewage_q0s_l_per_s=result.sewage_fixture_discharge,
        heat_max_kw=result.heat_max_kw,
        irrigation_m3_day=irrigation_m3_day,
        q_year_m3=q_year_m3,
    )


def flows_from_consumers(
    groups: list[ConsumerGroup],
    *,
    apply_k06: bool = False,
    irrigation_m3_day: float = 0.0,
    q_year_m3: float = 0.0,
) -> FlowsData:
    """
    Удобная обёртка: состав потребителей -> расчёт ядром -> FlowsData.
    """
    result = calculate_water_demand(groups, apply_k06=apply_k06)
    return flows_from_demand(
        result, irrigation_m3_day=irrigation_m3_day, q_year_m3=q_year_m3
    )

# ==== функции моста для ПЗ (насос/счётчик/баланс) ====


# ==== мост для ПЗ: насос / счётчик / баланс ====


# ── утилиты ────────────────────────────────────────────────────────────────

def _g(obj, *names, default=None):
    """Первое существующее (и непустое) из перечисленных полей объекта."""
    for n in names:
        v = getattr(obj, n, None)
        if v not in (None, ""):
            return v
    return default


def _clean_reason(s: str) -> str:
    """Убрать ведущие глифы ✓/⚠/✗/↔/↕ из reasons ядра — для формальной ПЗ."""
    return s.lstrip("✓⚠✗↔↕ ").strip()


def _meter_type_label(meter) -> str:
    t = str(_g(meter, "type", default="w")).lower()
    return "турбинный" if t in ("t", "turbine", "турбинный") else "крыльчатый"


def _pump_power(pump, wp_q: float, wp_h: float) -> tuple[float, float]:
    """(P₂, мин. мощность двигателя). Каталожная, если есть; иначе гидравл. оценка."""
    cat = _g(pump, "p_kw", "power_kw", "p2_kw", "power", "motor_kw")
    if cat:
        return round(float(cat), 2), round(float(cat), 2)
    # P_гидр = ρ·g·Q·H / 3.6e6 (кВт при η=1); η_насос+двиг ≈ 0.6; запас двигателя 15%
    p_hydro = 1000 * 9.81 * (wp_q / 3600.0) * wp_h / 1000.0
    p2 = p_hydro / 0.6
    return round(p2, 2), round(p2 * 1.15, 2)


# ── НАСОС ───────────────────────────────────────────────────────────────────

def pump_from_calc(res, *, purpose: str = "", type_label: str = "хозяйственно-питьевой",
                   scheme_note: str = "1 раб. + 1 рез.", mode: str = "1") -> PumpSystem:
    """PumpResult -> PumpSystem (с top3, кривой и данными графика Q-H)."""
    if not getattr(res, "candidates", None):
        return PumpSystem(
            required=True, purpose=purpose, count_note="подбор не дал кандидатов",
            q_design_m3h=float(getattr(res, "q_design", 0.0) or 0.0),
            h_design_m=float(getattr(res, "h_required", 0.0) or 0.0),
        )

    top3: list[PumpCandidate] = []
    for c in res.candidates:
        wp = c.working_point
        p2, motor_min = _pump_power(c.pump, wp.q, wp.h)
        top3.append(PumpCandidate(
            model=str(_g(c.pump, "model", "name", default="")),
            brand=str(_g(c.pump, "brand", "manufacturer", default="")),
            type_label=type_label,
            note=scheme_note,
            wp_q=wp.q, wp_h=wp.h,
            p2_kw=p2, motor_min_kw=motor_min,
            p_max_bar=float(_g(c.pump, "p_max_bar", "pmax_bar", default=0) or 0),
            npshr=float(_g(c.pump, "npshr", default=0) or 0),
            score=c.score,
            reasons=[_clean_reason(r) for r in (c.reasons or [])],
            archived=bool(_g(c.pump, "archived", default=False)),
            source_url=str(_g(c.pump, "source_url", default="") or ""),
            source_note=str(_g(c.pump, "source_note", default="") or ""),
        ))

    acc = res.candidates[0]
    mode_factor = 2 if mode == "2p" else 1
    return PumpSystem(
        required=True, purpose=purpose,
        # итоговые
        model=f"{top3[0].brand} {top3[0].model}".strip(),
        q_m3h=acc.working_point.q, head_m=acc.working_point.h,
        power_kw=top3[0].p2_kw, count_note=scheme_note,
        q_design_m3h=float(getattr(res, "q_design", 0.0) or 0.0),
        h_design_m=float(getattr(res, "h_required", 0.0) or 0.0),
        # детальный подбор + график
        top3=top3,
        curve=[(p.q, p.h) for p in acc.eff_curve],
        h_stat=res.h_stat, k_sys=res.k_sys,
        wp_q=acc.working_point.q, wp_h=acc.working_point.h,
        q_opt=float(_g(acc.pump, "q_opt", default=0) or 0) * mode_factor,
        selection_note=(
            "Предварительный подбор по архивной каталожной кривой; "
            "актуальную характеристику и исполнение подтвердить у изготовителя."
            if bool(_g(acc.pump, "archived", default=False)) else ""
        ),
    )


# ── СЧЁТЧИКИ ──────────────────────────────────────────────────────────────────

def meters_from_calc(res) -> MetersSystem:
    """MeterResult -> MetersSystem (со строками проверок а/б/в)."""
    rows: list[MeterRow] = []
    for ch in res.meters:
        m = ch.meter
        rows.append(MeterRow(
            label=ch.label,
            dn=int(_g(m, "d_mm", "dn", "d", default=0) or 0),
            type_label=_meter_type_label(m),
            s_resist=float(_g(m, "s", "s_resist", default=0) or 0),
            qexpl=float(_g(m, "q_expl", "qexpl", "q_nom", default=0) or 0),
            q_meter_min=float(_g(m, "q_min", default=0) or 0),
            qmax=float(_g(m, "q_max", default=0) or 0),
            qmin=float(_g(m, "q_threshold", "qthr", "qmin", default=0) or 0),
            h_a=ch.h_normal, lim_a=ch.h_limit_normal, ok_a=ch.pass_normal,
            h_b=ch.h_fire,
            lim_b=(ch.h_limit_fire or 0),
            ok_b=(ch.pass_fire if ch.pass_fire is not None else True),
            need_bypass=ch.need_bypass,
            q_hr=float(getattr(ch, "q_hr_m3_per_h", 0) or 0),
            ok_v=ch.pass_sensitivity, need_combo=ch.need_combo,
        ))
    # примечание про обводную при 1 вводе — если ядро его выдало
    note_bypass = any("обводн" in str(n).lower() for n in getattr(res, "notes", []))
    cold = next((r for r in rows if "хвс" in r.label.lower() or "ввод" in r.label.lower()), None)
    hot = next((r for r in rows if "гвс" in r.label.lower()), None)
    return MetersSystem(
        hws_type_meters=str(getattr(res, "hws_type", "")),
        cold_meter_dn=cold.dn if cold else None,
        hot_meter_dn=hot.dn if hot else None,
        has_bypass=any(r.need_bypass for r in rows) or note_bypass,
        rows=rows,
        single_input_bypass_note=note_bypass,
    )


# ── БАЛАНС ────────────────────────────────────────────────────────────────────
# ВНИМАНИЕ: расчёт водопотребления возвращает группы потребителей в своей
# структуре (app/calc/water_demand.py). Поля g.* ниже — предположительные,
# подгони под фактический результат, когда дойдём до подключения баланса.

def balance_from_calc(groups, flows, *, irrigation_days: int = 50) -> BalanceData:
    """Группы потребителей + полив -> BalanceData (форма 2)."""
    rows: list[ConsumerRow] = []
    for g in groups:
        days = int(_g(g, "days_year", "days", default=0) or 0)
        qc = float(_g(g, "q_day_c", "q_cold_day", default=0) or 0)
        qh = float(_g(g, "q_day_h", "q_hot_day", default=0) or 0)
        rows.append(ConsumerRow(
            name=str(_g(g, "label", "name", default="")),
            count=float(_g(g, "U", "count", "n", default=0) or 0),
            count_unit=str(_g(g, "unit", "count_unit", default="")),
            norm_display=str(_g(g, "norm_str", "norm_display", default="")),
            nd_ref=str(_g(g, "nd", "nd_ref", default="")),
            regime_h=float(_g(g, "hours", "regime_h", default=0) or 0),
            days_year=days,
            q_cold_day=qc, q_cold_year=round(qc * days, 1),
            q_hot_day=qh,  q_hot_year=round(qh * days, 1),
            q_sew_day=round(qc + qh, 2), q_sew_year=round((qc + qh) * days, 1),
        ))
    if getattr(flows, "irrigation_m3_day", 0):
        q = flows.irrigation_m3_day
        rows.append(ConsumerRow(
            name="Полив территории", count=0, count_unit="",
            norm_display="—", nd_ref="СП 30.13330.2020, п. 5.3",
            regime_h=0, days_year=irrigation_days,
            q_cold_day=q, q_cold_year=round(q * irrigation_days, 1),
            q_hot_day=0, q_hot_year=0, q_sew_day=0, q_sew_year=0,
        ))
    return BalanceData(rows=rows)


def fire_from_calc(res, *, pk_total: int = 0, nozzle_dn: int = 50,
                   hose_length_m: int = 20, fire_duration_min: int = 60,
                   has_aupt: bool = False) -> FireSystem:
    """FireResult (расчёт ВПВ) -> FireSystem для модели ПЗ.

    Переносит из расчётного ядра блоки 1–2 по СП 10.13130.2020:
      • applicability — требуется ли ВПВ (res.required);
      • demand — число одновременных струй и расходы (табл. 7.1/7.2).

    ВНИМАНИЕ по pk_total (блок 3, layout). Фактическое число пожарных кранов
    и шкафов НЕ вычисляется по таблицам СП — это результат ГРАФИЧЕСКОЙ
    расстановки ПК на планах из условия орошения каждой точки защищаемого
    помещения расчётным числом струй (радиус действия = длина рукава + вылет
    компактной части струи). Такой геометрии в модели пока нет, поэтому
    pk_total передаётся ЯВНО проектировщиком (результат его расстановки);
    по умолчанию 0 — «определяется по планам». Автоприкидка сознательно НЕ
    делается: правдоподобное число из воздуха для экспертизы хуже честного 0.
    Будущий геометрический определитель — отдельный модуль (calc/fire_layout.py).

    Args:
        res: FireResult из calculate_fire() (или None -> ВПВ не требуется).
        pk_total: фактическое число ПК из графической расстановки (0 = н/д).
        nozzle_dn: Ду пожарного крана (клапана), из FireInput.dn.
        hose_length_m: длина рукава, м (из FireInput.hose_m).
        fire_duration_min: расчётная продолжительность тушения, мин.
        has_aupt: наличие АУПТ (влияет на схему В2).
    """
    if res is None or not getattr(res, "required", False):
        return FireSystem(required=False)
    return FireSystem(
        required=True,
        streams=int(getattr(res, "streams", 0) or 0),
        q_per_stream=float(getattr(res, "q_per_stream", 0.0) or 0.0),
        q_total=float(getattr(res, "q_total", 0.0) or 0.0),
        pressure_mpa=getattr(res, "pressure_mpa", None),
        pk_total=int(pk_total or 0),
        nozzle_dn=int(nozzle_dn),
        hose_length_m=int(hose_length_m),
        fire_duration_min=int(fire_duration_min),
        has_aupt=bool(has_aupt),
    )


def enrich_fire_from_layout_and_hydraulics(
    fire: FireSystem,
    *,
    layout_results=None,
    hydraulic_result=None,
) -> FireSystem:
    """Дополняет FireSystem результатами геометрии (fire_layout) и гидравлики
    (fire_hydraulics) — мост из расчётного ядра ВПВ в модель документа (ИОС2).

    layout_results: список результатов расстановки ПК по помещениям здания
        (каждый — FireCabinetLayoutSummary или FireDesignResult, у которого есть
        число расставленных ПК). pk_total = СУММА по всем помещениям здания.
    hydraulic_result: результат гидравлики В2 по сети — ScenarioResult или
        HydraulicResult (диктующий напор, needs_pump). Берётся напор на источнике
        и вердикт о насосной.

    Мост НЕ считает сам — принимает уже посчитанные результаты солверов и
    переносит их в FireSystem, откуда их подхватывают спека/схема/ПЗ.
    Возвращает НОВЫЙ FireSystem (dataclasses.replace), исходный не мутируется.
    """
    import dataclasses

    updates = {}

    # pk_total — сумма расставленных ПК по всем помещениям здания
    if layout_results:
        total = 0
        for lr in layout_results:
            # поддерживаем и FireDesignResult (.pk_total), и layout summary
            if hasattr(lr, "pk_total"):
                total += int(lr.pk_total or 0)
            elif hasattr(lr, "placement_result"):
                total += len(lr.placement_result.placements)
        updates["pk_total"] = total

    # напор и вердикт о насосе — из гидравлики В2
    if hydraulic_result is not None:
        req = getattr(hydraulic_result, "required_head_at_source_m", None)
        if req is not None:
            updates["required_head_m"] = float(req)
        avail = getattr(hydraulic_result, "available_head_m", None)
        if avail is not None:
            updates["available_head_m"] = float(avail)
        needs = getattr(hydraulic_result, "needs_pump", None)
        if needs is not None:
            updates["needs_pump"] = bool(needs)
        # диктующий ПК (одиночный) или диктующая пара (сценарий)
        dic = getattr(hydraulic_result, "dictating_cabinet_id", None)
        if dic is None:
            scen = getattr(hydraulic_result, "dictating_scenario", None)
            if scen is not None:
                dic = "+".join(scen.active_cabinet_ids)
        if dic is not None:
            updates["dictating_cabinet_id"] = str(dic)

    return dataclasses.replace(fire, **updates)
