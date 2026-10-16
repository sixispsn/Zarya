"""Sourced accessory catalogue, deliberately separate from hydraulic tables.

Product/solution IDs are immutable. Never reinterpret an old saved wish as a
hardware purchase. A new hardware revision needs a new ID and source review.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _catalogue():
    data = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    sources = data["sources"]
    products = {row["id"]: row for row in data["products"]}
    if len(products) != len(data["products"]):
        raise ValueError("Повтор ID дополнительного оборудования ВУ")
    # The modern card reuses the dimensional catalogue, not a second copy of
    # passport numbers. The old model-1 choice is intentionally not migrated.
    from app.data.metering_products import get_metering_catalogue
    geometry = get_metering_catalogue()
    modern = geometry.products["pulsar-m2-e1-t105-rs485-dn32"]
    sources.update({s: dict(geometry.sources[s]) for s in modern.source_ids})
    products[modern.id] = dict(id=modern.id,manufacturer=modern.manufacturer,
        checked_on="2026-10-12",
        model=modern.model,article=modern.article,kind="meter",dn=modern.dn,
        supply="listed",source_ids=list(modern.source_ids),
        facts=[f"DN{modern.dn}; L ≤ {modern.body_length_mm:g} мм, H ≤ {modern.dimensions_mm['H']:g} мм.",
               f"Qmin={modern.flows_m3h['qmin_C']:g}, Qn={modern.flows_m3h['qn']:g}, Qmax={modern.flows_m3h['qmax']:g} м³/ч; класс C.",
               "Россия по паспорту изготовителя. RS-485 Modbus RTU, внешнее питание 9–30 В."],
        requirements=[*modern.notes,"Это кандидат, не автоматическая замена механического счётчика. Требуется характеристика потерь выбранного исполнения."],
        interfaces=["rs485"],power_modes=["mains","backed_up"])
    # Full published size rows, not DN32 reused for every project. The saved
    # legacy model-1 / fixed-DN choices keep their original meaning.
    for part in geometry.products.values():
        if part.technology == "ultrasonic":
            sources.update({s: dict(geometry.sources[s]) for s in part.source_ids})
            products[part.id] = dict(products[modern.id], id=part.id, dn=part.dn,
                article=part.article, model=f"{part.model}, DN{part.dn}", source_ids=list(part.source_ids),
                facts=[f"DN{part.dn}; L ≤ {part.body_length_mm:g} мм; H ≤ {part.dimensions_mm['H']:g} мм.",
                    f"Qmin={part.flows_m3h['qmin_C']:g}, Qn={part.flows_m3h['qn']:g}, Qmax={part.flows_m3h['qmax']:g} м³/ч; класс C.",
                    "RS-485 Modbus RTU, внешнее питание 9–30 В; не импульсный выход."],
                requirements=[*part.notes,"Характеристика потерь конкретной модели не подтверждена текущим механическим расчётом."])
        if part.kind == "strainer" and part.filter_type == "magnetic_mesh":
            sources.update({s: dict(geometry.sources[s]) for s in part.source_ids})
            products[part.id] = dict(id=part.id, manufacturer=part.manufacturer,
                model=f"ФМФ DN{part.dn}", article=part.article, kind="filter", dn=part.dn,
                checked_on="2026-10-12", supply="listed", source_ids=list(part.source_ids),
                facts=[f"L={part.body_length_mm:g} мм; PN{part.pn_bar:g}; +5…+110 °C.",
                    f"Для обслуживания: L*={part.dimensions_mm['L_service']:g}, H*={part.dimensions_mm['H_service']:g} мм."],
                requirements=list(part.notes), interfaces=[], power_modes=[])
    # The historical family choice stays a candidate. Enrich its card from
    # the reviewed catalogue without turning the saved wish into a replacement.
    fmf_sizes = sorted(p.dn for p in geometry.products.values() if p.filter_type == "magnetic_mesh")
    products["vodopribor-fmf"].update(dn_range=fmf_sizes,
        source_ids=[*products["vodopribor-fmf"]["source_ids"], "vodopribor-catalogue-20261012"],
        facts=["Размерные исполнения ФМФ: DN"+", ".join(map(str,fmf_sizes))+". DN125 в таблице отсутствует."],
        checked_on="2026-10-12")
    for source in sources.values():
        if not source["url"].startswith("https://") or not source["title"]:
            raise ValueError("У изделия ВУ отсутствует источник")
    for row in products.values():
        if (not row["source_ids"] or not set(row["source_ids"]) <= sources.keys()
                or not row["requirements"] or row["supply"] not in {"listed", "made_to_order"}):
            raise ValueError(f"Некорректная карточка ВУ: {row['id']}")
    for row in data["solutions"].values():
        if (not set(row["products"]) <= products.keys()
                or row["controller"] not in row["products"]
                or products[row["controller"]]["kind"] != "controller"
                or not set(row["source_ids"]) <= sources.keys()):
            raise ValueError("Неподтверждённая комплектация ВУ")
    data["products"] = products
    return data


def get_metering_extras_catalogue():
    # Consumers cannot mutate the cached reference used in other projects.
    return deepcopy(_catalogue())


# Explicit choices, never defaults. Hydraulic candidates are not approved
# replacements; the existing meter/filter and their calculation remain intact.
PRODUCT_CHOICES = {
    "technology": {"pulsar_us32": "pulsar-us-dn32", "pulsar_em50": "pulsar-em-dn50",
                   "pulsar_m2_us32": "pulsar-m2-e1-t105-rs485-dn32"},
    "telemetry": {"saures_r4": "saures-r4-din", "saures_r7": "saures-r7-din", "vega_si11": "vega-si11"},
    "tamper_monitoring": {"vodopribor_ipk": "vodopribor-ipk"},
    "valve_feedback": {"bolid_sp4_24": "bolid-sp4-24"},
    "assembly": {"vodopribor_module": "vodopribor-module"},
    "magnetic_filter": {"vodopribor_fmf": "vodopribor-fmf"},
}

SUGGESTIONS = {
    ("technology", "ultrasonic"): ["pulsar-m2-e1-t105-rs485-dn32"],
    ("technology", "electromagnetic"): ["pulsar-em-dn50"],
    ("telemetry", "pulse"): ["saures-r4-din", "vega-si11"],
    ("telemetry", "rs485"): ["saures-r4-din", "saures-r7-din"],
    ("telemetry", "nb_iot"): ["saures-r7-din"],
    ("telemetry", "lorawan"): ["vega-si11"],
    ("leak_monitoring", "requested"): ["gidrolock-wsp-plus", "vega-dp2"],
    ("tamper_monitoring", "requested"): ["vodopribor-ipk"],
    ("valve_feedback", "requested"): ["bolid-sp4-24"],
    ("assembly", "factory_module"): ["vodopribor-module"],
    ("magnetic_filter", "requested"): ["vodopribor-fmf"],
}


def extra_choices():
    data = get_metering_extras_catalogue()
    result = {key: {value: data["products"][ident]["model"]
                   for value, ident in values.items()} for key, values in PRODUCT_CHOICES.items()}
    result["leak_monitoring"] = {key: row["label"] for key, row in data["solutions"].items()}
    result["technology"].update(pulsar_us32="Пульсар УЗ · DN32 · кандидат", pulsar_em50="Пульсар ЭМ · DN50 · кандидат")
    result["technology"]["pulsar_m2_us32"] = "Пульсар модель 2 · DN32 · RS-485 · кандидат"
    result["telemetry"].update(saures_r4="SAURES R4 · Wi-Fi", saures_r7="SAURES R7 · NB-IoT (без SIM)", vega_si11="Вега СИ-11 · LoRaWAN")
    result["technology"]["pulsar_m2_us_family"] = "Пульсар модель 2 · по расчётному DN15–40"
    result["magnetic_filter"]["vodopribor_fmf"] = "Водоприбор ФМФ · DN50–250 (кроме DN125)"
    result["magnetic_filter"]["vodopribor_fmf_replace"] = "ФМФ вместо сетчатого фильтра · по DN"
    result["assembly"]["vodopribor_module"] = "Водоприбор · узел по проекту"
    return result


def catalogue_option_details():
    """Small read-only cards for the collapsed Studio controls, before calc."""
    data = get_metering_extras_catalogue()
    result = {}
    pairs = dict(SUGGESTIONS)
    for key, choices in PRODUCT_CHOICES.items():
        pairs.update({(key, value): [ident] for value, ident in choices.items()})
    for value, solution in data["solutions"].items():
        pairs[(solution["option"], value)] = solution["products"]
    pairs[("technology", "pulsar_m2_us_family")] = [k for k in data["products"] if k.startswith("pulsar-m2-e1-t105-rs485-dn")]
    pairs[("magnetic_filter", "vodopribor_fmf_replace")] = [k for k in data["products"] if k.startswith("vodopribor-fmf-dn")]
    for (key, value), ids in pairs.items():
        result.setdefault("vu_" + key, {})[value] = [
            dict(data["products"][ident], checked_on=data["products"][ident].get("checked_on",data["checked_on"]), sources=[data["sources"][source]
                 for source in data["products"][ident]["source_ids"]]) for ident in ids]
    return {"revision": data["revision"], "checked_on": data["checked_on"], "choices": result}
