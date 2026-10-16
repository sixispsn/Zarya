"""Country of manufacture is evidence for a product, never inferred from a brand.

Project-wide procurement guard. No hydraulic method, duty or DN is modified to
fit the origin filter. A preliminary PDF remains available, release does not.
"""
from app.data.metering_products import get_metering_catalogue


def origin(ident):
    from app.data.metering_supports import PRODUCTS, SOURCES
    support = PRODUCTS.get(ident)
    if support and support.country == 'RU':
        return {'country':'RU', 'sources':[dict(SOURCES[s]) for s in support.sources],
                'evidence':'manufacturer_statement'}
    catalog = get_metering_catalogue()
    product = catalog.products.get(ident)
    if product and product.country_of_manufacture == "RU" and product.origin_source_ids:
        return {"country": "RU", "sources": [dict(catalog.sources[s]) for s in product.origin_source_ids],
                "evidence": "manufacturer_statement"}
    # Exact article / passport, not a rule for all brass or all LD products.
    if ident == "ld-67-501-50":
        return {"country": "RU", "sources": [dict(catalog.sources["ld-nipple-passport"])],
                "evidence": "manufacturer_statement"}
    return {"country": "unknown", "sources": [], "evidence": "missing"}


def origin_error(detail, ident):
    return ("Российское производство изделия не подтверждено"
            if detail.russian_equipment_only and origin(ident)["country"] != "RU" else "")


def review_equipment_origin(project):
    enabled = project.metering_detail.russian_equipment_only
    report = {"enabled": enabled, "ready": not enabled, "rows": [],
        "notice": "Страна изготовления проверяется по конкретному изделию, не по бренду. "
        "Подтверждение изготовителя не заменяет запись реестра Минпромторга, если её требует заказчик. "
        "Фильтр не меняет расчётные расходы, DN и напоры. Автозамена насоса без проверенной характеристики запрещена."}
    if not enabled:
        return report
    from app.pz.spec import build_specification
    for section in build_specification(project).sections:
        for row in section.rows:
            if row.pos is None or row.unit.strip().lower() not in {"шт.", "шт", "компл.", "компл", "комплект"}:
                continue
            if row.qty == 0:
                continue
            evidence = origin(row.catalogue_id)
            report["rows"].append({"section": section.title, "name": row.name,
                "model": row.type_mark, "catalogue_id": row.catalogue_id,
                "ready": evidence["country"] == "RU", **evidence})
    report["ready"] = bool(report["rows"]) and all(row["ready"] for row in report["rows"])
    return report
