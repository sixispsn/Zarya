"""Compose explicit VU accessory selections without changing accepted hydraulics.

One room/one controller/one leak point is an explicit named solution, not an
estimate of an entire building. Candidates never acquire procurement quantity.
"""
from app.data.metering_extras import get_metering_extras_catalogue, PRODUCT_CHOICES, SUGGESTIONS
from app.pz.metering_options import option_requests


def resolve_metering_extras(project):
    catalog = get_metering_extras_catalogue()
    detail = project.metering_detail
    values = detail.enhancements
    requests = option_requests(detail)  # Validate saved values before lookup.
    plan = {"revision": catalog["revision"], "checked_on": catalog["checked_on"],
            "notice": catalog["scope"], "selections": [], "items": [], "issues": []}
    items = {}
    selected_controller = PRODUCT_CHOICES["telemetry"].get(values.get("telemetry"))
    leak = catalog["solutions"].get(values.get("leak_monitoring"))
    controllers = {x for x in (selected_controller, leak["controller"] if leak else None) if x}
    conflict = len(controllers) > 1
    network_conflict = bool(leak and values.get("telemetry") in {"nb_iot", "lorawan"}
                            and values["telemetry"] != leak["network"])
    interface_conflict = bool(leak and values.get("telemetry") in {"rs485", "mbus"}
        and values["telemetry"] not in catalog["products"][leak["controller"]]["interfaces"])
    if conflict or network_conflict or interface_conflict:
        plan["issues"].append("Выбраны разные сети/контроллеры для одной водомерной. "
                              "Согласуйте единый вариант; лишние регистраторы не добавлены в количество.")

    def card(ident):
        product = catalog["products"][ident]
        return dict(product, sources=[dict(catalog["sources"][key], checked_on=catalog["sources"][key].get("checked_on",catalog["checked_on"]))
                                      for key in product["source_ids"]])

    for request in requests:
        key, value = request["key"], request["value"]
        solution = catalog["solutions"].get(value) if key == "leak_monitoring" else None
        ident = PRODUCT_CHOICES.get(key, {}).get(value)
        ids = solution["products"] if solution else [ident] if ident else SUGGESTIONS.get((key, value), [])
        family = ((key == "technology" and value in ("ultrasonic", "pulsar_m2_us_family"))
                  or (key == "magnetic_filter" and value in ("vodopribor_fmf", "vodopribor_fmf_replace")))
        if family:
            from app.pz.metering_detail import drawing_state
            meter = drawing_state(project).meter
            dn = meter.dn if meter else None
            prefix = "pulsar-m2-e1-t105-rs485" if key == "technology" else "vodopribor-fmf"
            exact = f"{prefix}-dn{dn}"
            ids = [exact] if exact in catalog["products"] else []
        chosen = bool(solution or ident)
        # Only an explicitly selected single controller or complete one-point
        # monitoring solution has a known quantity. Never quantify candidates.
        countable = bool(solution or (ident and catalog["products"][ident]["kind"] == "controller"))
        row = dict(request, status="selected" if countable else "candidate" if chosen else "request",
                   products=[card(i) for i in ids], notes=[], quantity_scope="")
        if family:
            countable = False
            chosen = value != "ultrasonic"
            row["status"] = ("candidate" if chosen else "request") if ids else "unavailable"
            row["notes"].append("Размерный кандидат по текущему DN, не подтверждение гидравлики и не дополнительная закупочная позиция.")
            if not ids:
                row["notes"].append(f"Для DN{dn if dn else ' не задан'} нет проверенной модели семейства. Соседний DN не подставлен.")
                plan["issues"].append(request["title"] + ": " + row["notes"][-1])
            if value == "vodopribor_fmf_replace":
                row["notes"].append("Замена учитывается в основной позиции фильтра ВУ, без второго фильтра; потери проверить отдельно.")
            if value == "pulsar_m2_us_family" and ids and values.get("power") == "battery":
                row["status"] = "conflict"
                row["notes"].append("Это исполнение требует внешнего питания 9–30 В; автономность не подтверждена.")
        if solution:
            row["notes"].append(solution["note"])
        if countable:
            row["quantity_scope"] = "Одна водомерная: один контроллер; датчик — только при выборе комплекта на одну точку."
            row["notes"].append(row["quantity_scope"] + " Число вводов не умножает эту комплектацию. Кабели и шкаф по месту не посчитаны.")
        if not chosen and ids:
            row["notes"].append("Примеры из базы, не назначенное оборудование. Выберите конкретное решение в настройках.")
        if chosen:
            for product in row["products"]:
                from app.pz.equipment_origin import origin_error
                if error := origin_error(detail, product["id"]):
                    row["notes"].append(error)
                    row["status"] = "conflict"
                row["notes"].extend(product["requirements"])
                minimum = product.get("ambient_min_c")
                if (minimum is not None and detail.room_min_temperature_c is not None
                        and detail.room_min_temperature_c < minimum):
                    row["notes"].append(f"{product['model']}: температура помещения ниже паспортных +{minimum} °C.")
                    row["status"] = "conflict"
                if (countable and product["kind"] == "controller" and values.get("power")
                        and values["power"] not in product["power_modes"]):
                    row["notes"].append(f"{product['model']}: выбранный способ питания не подтверждён.")
                    row["status"] = "conflict"
            if countable and (conflict or network_conflict or interface_conflict):
                row["status"] = "conflict"
            if ident and catalog["products"][ident]["kind"] == "meter":
                from app.pz.metering_detail import drawing_state
                meter = drawing_state(project).meter
                dn = catalog["products"][ident]["dn"]
                if meter and meter.dn != dn:
                    row["notes"].append(f"Расчётный DN{meter.dn} не совпадает с DN{dn} кандидата. Автозамена запрещена.")
                    row["status"] = "conflict"
                if values.get("power") == "battery":
                    row["notes"].append("Выбранный расходомер требует внешнего питания; автономность не подтверждена.")
                    row["status"] = "conflict"
        if row["status"] == "conflict":
            plan["issues"].append(request["title"] + ": " + " ".join(row["notes"]))
        if countable and row["status"] == "selected":
            for product in row["products"]:
                item = items.setdefault(product["id"], dict(product, qty=1, unit="шт.", roles=[],
                    note="Одна водомерная. Предварительная комплектация по явному выбору; подключение и монтаж уточнить."))
                item["roles"].append(key)
        plan["selections"].append(row)

    # Any incompatible assignment of a shared device withdraws it everywhere.
    invalid = {p["id"] for row in plan["selections"] if row["status"] == "conflict" for p in row["products"]}
    plan["items"] = [item for ident, item in items.items() if ident not in invalid]
    return plan


def metering_option_rows(project):
    """Common wording in UI, PZ, drawing conditions and specification."""
    rows = []
    for selection in resolve_metering_extras(project)["selections"]:
        row = {key: selection[key] for key in ("key", "title", "value", "label", "requirement")}
        if row["key"] == "leak_monitoring" and selection["status"] in {"selected", "conflict"}:
            row["requirement"] = ("Контроль появления воды у датчика на полу, без автоматического перекрытия воды. "
                "Не является обнаружением скрытой утечки по расходу; пожарное водоснабжение не отключается.")
        if selection["products"]:
            names = "; ".join(p["manufacturer"] + " " + p["model"]
                              + (f", арт. {p['article']}" if p["article"] else "") for p in selection["products"])
            status = {"selected": "Предварительная комплектация", "candidate": "Кандидат из базы",
                      "request": "Примеры из базы", "conflict": "Есть несовместимость",
                      "unavailable": "Нет проверенной модели"}[selection["status"]]
            row["requirement"] += f" {status}: {names}. " + " ".join(selection["notes"])
        elif selection["notes"]:
            row["requirement"] += " " + " ".join(selection["notes"])
        rows.append(row)
    return rows
