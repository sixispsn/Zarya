"""Stage-P evidence checklist, not a treatment or tank-sizing algorithm.

Document references describe engineer decisions. The application checks their
presence/consistency; it does NOT certify water quality or approve the project.
"""
from dataclasses import asdict
import hashlib
import json
import math

VERSION = "rain-design-1"
SECTIONS = {
    "design_basis": ("Задание и ТЭО", "Реквизиты ТЗ/ТЭО, способ полива, потребность и действия при нехватке дождевой воды."),
    "design_storage": ("Бак и срок хранения", "Модель/чертёж бака, полезный и полный объём, отстойная зона, удаление осадка, слив при застое и санитарная обработка; лист и ревизия."),
    "design_diversion": ("Первый сток, перелив и зимний режим", "Узел отвода первого стока (обоснование режима), пропуск пикового К2, отметки, DN, защита от подпора и маршрут слива/перелива; зимнее отключение либо защита от замерзания; лист и ревизия."),
    "design_quality": ("Очистка и защитная автоматика", "Исходное/требуемое качество, подтверждение поставщиком насоса/фильтра/УФ, отстаивание, контроль расхода и дозы, запрет подачи при отказе и обслуживание; документы и ревизии."),
    "design_network": ("Сеть, схема и спецификация", "Отдельная маркированная сеть без связи с В1, планы/схема с DN и отметками, размещение бака, нагрузки/доступ, питание, автоматика и ведомость оборудования; шифры листов и ревизии."),
    "design_annual": ("Годовая экономия", "Расчёт годовой экономии с периодом полива, климатическими данными, потерями первого стока/слива и границами обеспеченности; шифр расчёта и ревизия. Короткий ряд не экстраполировать на год."),
}
WINTER = {"seasonal": "Сезонная работа · отключение и слив на зиму",
          "protected": "Работа зимой · подтверждённая защита от замерзания"}
DISCHARGE = {"storm": "Отдельная дождевая сеть · согласованный приёмник",
             "other": "Другое решение · вне типового сценария"}
NOTICE = ("Реквизиты не заменяют приложенные расчёты, планы и паспорта. "
          "Подтверждение проектировщика не является электронной подписью, "
          "санитарным заключением или положительным заключением экспертизы.")


def validate(d):
    errors = []
    for key in SECTIONS:
        value = getattr(d, key)
        if not isinstance(value, str) or len(value) > 1200:
            errors.append(f"Паспорт дождевой системы: {key} — текст до 1200 символов.")
    for key, options in (("design_winter", WINTER), ("design_discharge", DISCHARGE)):
        if not isinstance(getattr(d, key), str) or getattr(d, key) not in {"", *options}:
            errors.append(f"Паспорт дождевой системы: неизвестное {key}.")
    for key in ("design_storage_days", "design_annual_saving_m3"):
        v = getattr(d, key)
        if v is not None and (type(v) not in (int, float) or not math.isfinite(v) or v < 0
                              or (key == "design_storage_days" and v == 0)):
            errors.append(f"Паспорт дождевой системы: некорректное {key}.")
    review = d.design_review
    if not isinstance(review, dict) or (review and (
        set(review) != {"fingerprint", "reviewer", "reviewed_at"}
        or any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in review.values())
    )):
        errors.append("Паспорт дождевой системы: некорректная запись проверки.")
    return errors


def fingerprint(d, *, building_kind=None, roof_kind=None):
    from app.data.rainwater_pumps import CATALOG as pumps
    from app.data.rainwater_treatment import CATALOG as treatment
    data = asdict(d)
    data.pop("design_review")
    raw = json.dumps([VERSION, building_kind, roof_kind, data, pumps, treatment], ensure_ascii=False,
                     sort_keys=True, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def assess_design(d, calculation, *, building_kind=None, roof_kind=None):
    rows = []
    def add(code, title, ok, note, kind="calculation"):
        rows.append(dict(code=code, title=title, ready=bool(ok), note=note, kind=kind))
    r = dict(status="disabled", ready_for_review=False, confirmed=False,
             rows=rows, missing=[], notice=NOTICE, review={})
    if not d.enabled:
        return r
    errors = validate(d)
    if errors:
        r.update(status="invalid", missing=errors)
        return r
    treatment, pump = calculation["treatment"], calculation["pump"]
    add("scope", "Жилая терраса → декоративный полив",
        building_kind == "residential" and roof_kind == "flat_accessible"
        and d.purpose == "irrigation" and d.treatment_surface == "hard_terrace"
        and bool(d.treatment_setup), "Другие водосборы и потребители требуют отдельной проработки.")
    add("balance", "Проверка полезного объёма", bool(calculation["totals"])
        and not calculation["errors"], "Суточный баланс не определяет срок хранения и пиковый пропуск К2.")
    add("equipment", "Расчётная точка и ограничения оборудования",
        treatment["ready_for_pump"] and bool(pump.get("selected")),
        "; ".join(treatment["missing"] + treatment["errors"] + pump["missing"] + pump["errors"])
        or "Каталожный кандидат проверен; окончательный выбор подтверждается листами подбора.")
    add("storage", "Допустимый срок хранения",
        d.design_storage_days is not None and 0 < d.design_storage_days <= 7,
        "Для полива — обоснованный срок не более 3–7 суток (СП 30, п. 14.18); более короткий срок допустим. Режим слива обязателен в решении по баку.")
    add("winter", "Режим зимой", bool(d.design_winter), WINTER.get(d.design_winter, "Выберите сезонное отключение или защищённую работу."))
    add("discharge", "Отвод вне К1", d.design_discharge == "storm",
        "Нужен согласованный дождевой приёмник; связь с К1 не добавляется. Иное решение требует отдельной проверки.")
    add("annual", "Годовая экономия задана по расчёту", d.design_annual_saving_m3 is not None,
        "Величина из отдельного обоснования; автоматического вычитания из В1 нет.")
    for key, (title, help_text) in SECTIONS.items():
        add(key, title, bool(getattr(d, key).strip()), getattr(d, key).strip() or help_text, "document")
    r["missing"] = [row["title"] for row in rows if not row["ready"]]
    r["ready_for_review"] = not r["missing"]
    r["review"] = dict(d.design_review)
    current = (bool(d.design_review) and not calculation["errors"]
               and d.design_review["fingerprint"] == fingerprint(d, building_kind=building_kind, roof_kind=roof_kind))
    r["confirmed"] = bool(r["ready_for_review"] and current)
    r["status"] = ("confirmed" if r["confirmed"] else "stale" if d.design_review
                   else "awaiting_review" if r["ready_for_review"] else "needs_data")
    return r
