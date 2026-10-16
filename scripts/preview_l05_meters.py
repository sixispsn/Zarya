"""Control-only PDF using the real meter-table template, no user project changed."""
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from weasyprint import CSS, HTML  # noqa: E402
from app.calc.water_meters import MeterInput, MeterSelectionUnavailable, calculate_meters  # noqa: E402
from app.pz.flows_bridge import meters_from_calc  # noqa: E402
from app.pz.generator import _build_env, TEMPLATES_DIR  # noqa: E402
from app.pz.project import Project, MetersSystem  # noqa: E402


def main():
    inputs = MeterInput(q_sec_c=120, q_day_c=9120, q_hr_c=432, minimum_flow_checks={
        "cold":dict(dn_mm=250, q_min_hourly_m3h=20, q_min_passport_m3h=15,
                    passport_reference="Условные данные только для проверки L05",
                    flow_reference="Контрольное значение минимума 20 м³/ч"),
    })
    boundary = Project()
    boundary.flows.q_day_c = inputs.q_day_c
    boundary.source.water_use_period_h = 24
    boundary.meters = meters_from_calc(calculate_meters(inputs))
    boundary.meters.rows = boundary.meters.rows[:1]
    stale = deepcopy(boundary)
    stale.flows.q_day_c = 9600
    unavailable = deepcopy(stale)
    inputs.q_day_c = 9600
    try:
        calculate_meters(inputs)
    except MeterSelectionUnavailable as exc:
        unavailable.meters = MetersSystem(selection_error=str(exc))
    else:
        raise AssertionError("L05 regression: 400 m³/h was admitted")
    cases = [
        (boundary, "1. Граница каталога: Qсред = 380 м³/ч", "Qсут=9120 м³/сут, T=24 ч. DN250 допустим по среднему расходу. Остальные данные ниже заданы только для контроля алгоритма."),
        (unavailable, "2. Новый расчёт: Qсред = 400 м³/ч", "Qсут=9600 м³/сут, T=24 ч. Подбор остановлен. DN250, потери в нём и зависимый подбор насоса не подставляются."),
        (stale, "3. Старый сохранённый DN250", "Сохранён результат для 380 м³/ч, но текущий расход уже 400 м³/ч. Даже при малых потерях и положительной проверке минимума узел не принимается."),
    ]
    env = _build_env()
    bodies = []
    for i, (project, title, intro) in enumerate(cases):
        table = env.get_template("meter_table.html").render(
            meters=project.meters, flows=project.flows, source=project.source,
        )
        bodies.append(f'<section style="break-before:{"page" if i else "auto"}">'
                      f'<h2>{title}</h2><p>{intro}</p>{table}</section>')
    boundary.document.sheet_title = "Контроль подбора водомеров"
    boundary.document.sheet_total = "3"
    html = env.get_template("document.html").render(
        doc=boundary.document, document_title="L05. Проверка границ каталога водомеров",
        body_html="".join(bodies),
    )
    path = ROOT / "output/pdf/l05_meter_catalog_bounds.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(str(path), stylesheets=[
        CSS(filename=str(TEMPLATES_DIR / name)) for name in ("frame.css", "equipment.css")
    ])
    print(path)


if __name__ == "__main__":
    main()
