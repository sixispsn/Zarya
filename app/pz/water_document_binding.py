"""Read-only IOS2 text binding to the same inputs as the water drawings.

No new hydraulics, nominal-size inference or pressure-regulator selection.
An empty list of checks is not proof that pressure regulation is unnecessary.
"""
from dataclasses import dataclass

from app.pz.water_pipe_binding import bind_v1_pipes, bind_t3_pipes
from app.pz.water_static_review import WaterStaticReview, review_water_static_pressure
from app.pz.water_control_review import WaterControlReview, review_water_control
from app.pz.water_regulation_plan import BranchRegulationPlan, branch_regulation_plan
from app.pz.water_apartment_assembly import apartment_components


@dataclass(frozen=True)
class WaterMaterialRow:
    key: str
    system: str
    role: str
    material: str
    size: str
    inner_mm: float | None
    source: str


def _material_rows(bindings, system, roles):
    rows = []
    for role, title in roles:
        binding = bindings[role]
        pipe = binding.pipe
        rows.append(WaterMaterialRow(f"{system}-{role}", system, title,
            pipe.material if pipe else "Требует уточнения",
            binding.label, pipe.inner_mm if pipe else None,
            ", ".join(binding.source_ids) if pipe else binding.issue))
    return tuple(rows)


def water_material_context(project):
    cold = bool(project.v1_network or project.v1_sections)
    hot = bool(project.t3_sections) and project.building.hws_type.value == "central"
    return dict(
        apartment_rows=tuple(item for system in ('В1', 'Т3')
                             for item in apartment_components(project, system)),
        cold_bound=cold, hot_bound=hot,
        cold_rows=_material_rows(bind_v1_pipes(project), "В1", (
            ("inlet", "Ввод"), ("main", "Магистраль"),
            ("riser", "Стояк"), ("apartment", "Квартирная подводка"))) if cold else (),
        hot_rows=_material_rows(bind_t3_pipes(project), "Т3", (
            ("main", "Магистраль"), ("riser", "Стояк"),
            ("apartment", "Квартирная подводка"))) if hot else (),
    )


@dataclass(frozen=True)
class WaterPressurePresentation:
    state: str
    text: str
    drawing_lines: tuple[str, ...]
    static_review: WaterStaticReview | None = None
    control_review: WaterControlReview | None = None
    regulation_plan: BranchRegulationPlan | None = None


def water_pressure_presentation(project):
    result = project.v1_hydraulic_result
    checks = list(getattr(result, "pressure_checks", ()) or ())
    if not checks:
        review = review_water_static_pressure(project)
        control = review_water_control(project)
        plan = branch_regulation_plan(project)
        if review.rows:
            value = f"{review.source_head_m:.2f}".replace('.', ',')
            summary = (f"В1: Hмакс + Hнас(Q=0) = {value} м."
                       if review.pump_zero_head_m is not None else f"В1: Hмакс = {value} м, без насоса.")
            conclusion = ("В сценарии без регулирования превышен порог 45 м у заданного прибора. "
                          if review.has_exceedance else "")
            lower = ("Нижний прибор проверен по указанной отметке; основание приведено в расчёте. "
                     if any(row.kind == "lowest_fixture" for row in review.rows) else
                     "Напор на уровне пола не является напором у нижнего прибора: его отметка не подтверждена. ")
            solution = (f"Принципиально предусмотрены РД на квартирных ветвях В1/Т3 этажей {plan.floor_text}. "
                        if plan.floors else "")
            lines = ((f"РД В1/Т3: квартирные ветви, эт. {plan.floor_text}.",
                      "Граница предварительная; расчёт и ПЧ - см. ПЗ.") if plan.floors else
                     (summary, "Без регулирования; РД/автоматика - см. ПЗ."))
            return WaterPressurePresentation("static_only",
                conclusion + "Выполнена только предварительная статическая проверка В1. "
                + lower + solution +
                "Проверка минимальных давлений и окончательные уставки требуют увязки.",
                lines, review, control, plan)
        return WaterPressurePresentation("not_checked",
            "Проверка минимальных и максимальных давлений в узлах В1 не выполнена. "
            "Расчёт напора диктующего направления не подтверждает допустимое давление "
            "у нижних приборов. Границы зон, необходимость регуляторов и их уставки "
            "должны быть подтверждены отдельно; число зон в исходных данных не является проверкой.",
            ("В1: проверка давлений не выполнена.", "Зонирование и РД требуют подтверждения."), review, control, plan)
    if any(c.minimum_ok is False or c.maximum_ok is False for c in checks):
        return WaterPressurePresentation("outside_limits",
            "В рассчитанных узлах В1 выявлены нарушения ограничений давления. "
            "Требуется решение по регулированию или разделению сети; наличие регуляторов "
            "в расчётном предложении не означает, что нарушения устранены.",
            ("В1: есть нарушения по давлению.", "Регулирование требует решения."))
    if any(c.maximum_ok is None or c.minimum_ok is None for c in checks):
        return WaterPressurePresentation("partial",
            "Проверка давлений В1 неполна: для части рассчитанных узлов нет подтверждения "
            "максимального либо минимального давления. Регулирование не считается проверенным.",
            ("В1: проверка давлений неполна.", "Регулирование не подтверждено."))
    return WaterPressurePresentation("checked_nodes",
        "В рассчитанных узлах В1 ограничения минимального и максимального давления соблюдены. "
        "Вывод относится только к узлам и режимам представленного расчёта и не переносится на Т3/Т4.",
        ("В1: давления проверены в расчётных узлах.", "Вывод не распространяется на Т3/Т4."))
