"""Inspectable size coverage. Empty cells remain gaps, never nearest-DN parts."""
from app.data.metering_products import get_metering_catalogue

SUPPORTED_DNS = (15,20,25,32,40,50,65,80,100,125,150,200,250)


def metering_coverage(dn, *, russian_only=False, orientation='unknown'):
    c = get_metering_catalogue()
    from app.pz.metering_orientation import check_product_orientation
    from app.data.metering_installation import ORIENTATIONS
    if orientation not in ('unknown', *ORIENTATIONS):
        raise ValueError('Неизвестная ориентация')
    equipment = c.coverage(dn, russian_only=russian_only)
    for technology in ("ultrasonic", "electromagnetic"):
        equipment[technology] = tuple(p.id for p in c.candidates("meter", dn,
            russian_only=russian_only, technology=technology))
    equipment["magnetic_filter"] = tuple(p.id for p in c.candidates("strainer", dn,
        russian_only=russian_only) if p.filter_type == "magnetic_mesh")
    rejected, unconfirmed = {}, {}
    if orientation != 'unknown':
        for role, ids in equipment.items():
            checks = {ident: check_product_orientation(c.products[ident],orientation) for ident in ids}
            rejected[role] = {ident:list(check.errors) for ident, check in checks.items() if check.errors}
            unconfirmed[role] = tuple(ident for ident, check in checks.items() if check.allowed is None)
            equipment[role] = tuple(ident for ident, check in checks.items() if not check.errors)
    fittings = {kind: tuple(p.id for p in c.fitting_candidates(kind, dn, russian_only=russian_only))
                for kind in ("tee", "cross", "elbow90", "coupling", "reducer")}
    from app.pz.equipment_origin import origin
    fittings["thread_reducer"] = tuple(p.id for p in c.reducers.values()
        if p.large_dn == dn and p.dimension_status == "verified"
        and (not russian_only or origin(p.id)["country"] == "RU"))
    # Gauge/cock ports are independent of main DN; do not fabricate DN250 instruments.
    instruments = tuple(p.id for p in c.service_products.values()
        if p.dimension_status == "verified" and (not russian_only or origin(p.id)["country"] == "RU"))
    return {"dn":dn, "equipment":equipment, "fittings":fittings, "service_instruments":instruments,
        "orientation":orientation, "orientation_rejected":rejected, "orientation_unconfirmed":unconfirmed,
        "geometry_complete": bool(all(equipment[k] for k in ("meter","manual_valve","filter","check_valve"))
                                   and fittings["tee"] and fittings["elbow90"]),
        "installation_ready":False,
        "notice":"Покрытие размерной базы, не разрешение монтажа. Ответвления, материал, P/T, "
                 "стыки, потери и обслуживание проверяются по конкретному проекту. "
                 "Приборы подбираются по присоединению и диапазону давления, не по DN магистрали."}


def fitting_card(part):
    c = get_metering_catalogue()
    return {"id":part.id, "name":part.name, "kind":part.kind, "material":part.material,
        "article":part.article, "manufacturer":part.manufacturer, "dimensions_mm":dict(part.dimensions_mm),
        "pn_bar":part.pn_bar, "temperature_c":part.temperature_c, "pressure_temperature":part.pressure_temperature,
        "ports":[{"dn":p.dn,"connection":p.connection,"thread":p.thread,"sex":p.sex,
                  "drilling":p.drilling} for p in part.ports],
        "sources":[dict(c.sources[s], page=part.source_page) for s in part.source_ids],
        "notes":part.notes, "country_of_manufacture":part.country_of_manufacture}
