"""Stage-P document references, not engineering approval or calculation defaults.

Shared building references are entered once; water/sewer TU remain independent.
Only accepted Studio values reach the existing request model.
"""
from datetime import datetime


COMMON = {
    "project_assignment_ref": "wastewater_design_assignment_ref",
    "project_survey_ref": "wastewater_survey_ref",
    "project_service_life_years": "wastewater_service_life_years",
    "project_overhaul_period_years": "wastewater_overhaul_period_years",
}
WATER = {"water_" + name: name for name in
         ("tu_org", "tu_number", "tu_date", "connection_point", "source_description")}
SEWER = ("wastewater_disposal_mode", "wastewater_tu_org", "wastewater_tu_number", "wastewater_tu_date")
DATES = {"water_tu_date", "wastewater_tu_date"}
YEARS = {"project_service_life_years", "project_overhaul_period_years"}
NOTICE = ("Реквизиты указываются по документам или ссылке на раздел проекта. "
          "Их заполнение не подтверждает содержание документов, согласование решений "
          "или готовность комплекта к экспертизе. Копии ТУ прикладываются отдельно.")


def document_date(value):
    if not isinstance(value, str):
        raise ValueError("Дата ТУ: ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.")
    value = value.strip()
    import re
    for pattern, fmt in ((r"\d{2}\.\d{2}\.\d{4}", "%d.%m.%Y"), (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d")):
        if re.fullmatch(pattern, value):
            try:
                result = datetime.strptime(value, fmt).date()
                return f"{result.day:02d}.{result.month:02d}.{result.year:04d}"
            except ValueError:
                break
    raise ValueError("Укажите существующую дату ТУ в формате ДД.ММ.ГГГГ.")


def request_fields(values):
    return {**{target: values[key] for key, target in COMMON.items() if key in values},
            **{key: values[key] for key in SEWER if key in values and
               (key == "wastewater_disposal_mode" or values.get("wastewater_disposal_mode") == "centralized")}}


def source_fields(values):
    return {target: values[key] for key, target in WATER.items() if key in values}


def assess(values):
    """Report presence only. No ready/can_release flag and no hidden defaults."""
    rows = []
    def add(code, title, fields, group, applicable=True):
        missing = [key for key in fields if values.get(key) in (None, "", "not_set")]
        rows.append(dict(code=code, title=title, fields=list(fields), group=group,
                         filled=bool(applicable and not missing), missing=missing,
                         applicable=applicable))
    add("assignment", "Задание на проектирование", ("project_assignment_ref",), "building")
    add("survey", "Инженерные изыскания", ("project_survey_ref",), "building")
    add("life", "Срок службы и капитальный ремонт", tuple(sorted(YEARS)), "building")
    add("water_tu", "ТУ на водоснабжение", ("water_tu_org", "water_tu_number", "water_tu_date"), "connection")
    add("water_point", "Точка подключения водопровода", ("water_connection_point",), "connection")
    mode = values.get("wastewater_disposal_mode", "not_set")
    add("sewer_mode", "Способ водоотведения", ("wastewater_disposal_mode",), "connection")
    add("sewer_tu", "ТУ на водоотведение", SEWER[1:], "connection", mode == "centralized")
    active = [row for row in rows if row["applicable"]]
    return dict(rows=rows, filled=sum(row["filled"] for row in active), total=len(active), notice=NOTICE)
