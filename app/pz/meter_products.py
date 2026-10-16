"""Bind legacy-sized meters to products without substituting hydraulic data.

Pure evaluation is repeated by output consumers. Studio opts into a catalogue
proposal, not an approved purchase. Missing design minimum is never inferred
from average/peak flow. A conflicting explicit assignment is never replaced.
"""
from dataclasses import dataclass
from math import isfinite

from app.calc.meter_verification import (
    MeterMinimumEvidence, check_minimum_flow, validate_meter_minimum_checks,
)
from app.data.metering_products import MeteringProduct, get_metering_catalogue
from app.pz.meter_validation import meter_node_key


METER_HEAD_BASIS = "h = S·q²; S по таблице 12.1 СП 30.13330.2020, п. 12.15, формула (18)"


def product_hydraulic_evidence(product):
    """Report source limits only; never fit S, interpolate a bound or alter head."""
    limit = product.pressure_loss_limit if product else None
    if limit is None:
        return None
    value = f"{limit.max_mpa:g}".replace(".", ",")
    flow = f"{limit.at_flow_m3h:g}".replace(".", ",")
    return dict(
        status="upper_bound_only", max_pressure_loss_mpa=limit.max_mpa,
        at_flow_m3h=limit.at_flow_m3h, source_id=limit.source_id,
        reference=limit.reference, checked_on=limit.checked_on,
        revision=limit.review_revision,
        # Explicit unknowns prevent a client from presenting a bound as h(Q).
        exact_loss_m=None, resistance_s=None,
        note=f"Паспорт: Δp ≤ {value} МПа при Qmax = {flow} м³/ч. "
             "Это верхняя граница, не характеристика h(Q); паспортный S не определён.",
    )


def primary_meter(project):
    if getattr(project, "metering_node", "") == "hot":
        return project.node_meter
    rows = project.meters.rows
    candidates = [r for r in rows if meter_node_key(r) == "total"]
    if not candidates:
        candidates = [r for r in rows if meter_node_key(r) == "cold" and "кварт" not in r.label.lower()]
    return candidates[0] if len(candidates) == 1 else None


@dataclass(frozen=True)
class MeterProductCheck:
    product: MeteringProduct | None
    node: str | None
    automatic: bool
    evidence: MeterMinimumEvidence
    minimum_ok: bool | None
    minimum_note: str
    errors: tuple[str, ...]
    pending: tuple[str, ...]

    def summary(self):
        p = self.product
        catalog = get_metering_catalogue()
        return dict(
            id=p.id if p else "", name=p.name if p else "",
            model=p.model if p else "", manufacturer=p.manufacturer if p else "",
            node=self.node, automatic=self.automatic, revision=catalog.revision,
            body_length_mm=p.body_length_mm if p else None,
            qmin_m3h=self.evidence.q_min_passport_m3h,
            qmax_m3h=p.flows_m3h.get("qmax") if p else None,
            pn_bar=p.pn_bar if p else None,
            temperature_c=list(p.temperature_c) if p else [],
            interface=p.remote_interface if p else "",
            sources=[dict(catalog.sources[s]) for s in p.source_ids] if p else [],
            minimum_ok=self.minimum_ok, minimum_note=self.minimum_note,
            errors=list(self.errors), pending=list(self.pending),
            hydraulic_basis=METER_HEAD_BASIS,
            hydraulic_evidence=product_hydraulic_evidence(p),
        )


def evaluate_meter_product(project, row) -> MeterProductCheck:
    from app.pz.metering_rules import remote_readout_required
    d, catalog = project.metering_detail, get_metering_catalogue()
    node = meter_node_key(row)
    from app.pz.metering_orientation import meter_orientation
    mounting = meter_orientation(d, node)
    errors, pending = [], []
    explicit = d.meter_products.get(node)
    main_id = d.catalogue_items.get("meter") if row is primary_meter(project) else None
    if explicit and main_id and explicit != main_id:
        errors.append("Модель расчётного узла расходится с моделью деталировки ВУ")
    ident = explicit or main_id
    automatic = not ident and d.meter_selection_mode == "catalogue_proposal"
    enabled = bool(ident or automatic)
    raw = validate_meter_minimum_checks(project.source.meter_minimum_checks).get(node)
    # For old/manual projects keep explicit evidence; never read derived row
    # fields as a new source after the model, mounting or DN has changed.
    evidence = raw or MeterMinimumEvidence()
    if not enabled:
        if row.product.get("id"):
            note = "Привязка модели удалена: сохранённое паспортное подтверждение больше не применяется"
            return MeterProductCheck(None, node, False, evidence, None, note, (note,), ())
        ok, note = check_minimum_flow(row.dn, evidence)
        return MeterProductCheck(None, node, False, evidence, ok, note, (), ())
    if d.catalogue_revision != catalog.revision:
        errors.append("Редакция каталога изменилась: требуется повторный подбор модели")
    if node is None:
        errors.append("Назначение узла учёта не определено")
    technology = d.enhancements.get("technology", "mechanical")
    if technology != "mechanical":
        errors.append("Для выбранной технологии нет проверенной привязки к расчётному типоразмеру; механический прибор не подставлен")
    product = catalog.products.get(ident) if ident else None
    if ident and product is None:
        errors.append("Неизвестная модель водомера")
    if automatic and not errors:
        candidates = [p for p in catalog.candidates("meter", row.dn,
                      technology="mechanical", russian_only=d.russian_equipment_only)
                      if p.remote_readout is True]  # common Studio profile: impulse output
        if len(candidates) == 1:
            product = candidates[0]
        else:
            errors.append("Нет однозначного проверенного изделия нужного DN и исполнения")
    if product:
        from app.pz.metering_orientation import check_product_orientation
        orientation = check_product_orientation(product, mounting)
        errors.extend(orientation.errors)
        pending.extend(orientation.pending)
        if d.russian_equipment_only and not (product.country_of_manufacture == "RU" and product.origin_source_ids):
            errors.append("Российское производство модели не подтверждено")
        if product.kind != "meter" or product.dn != row.dn or product.dimension_status != "verified":
            errors.append("Тип/DN или габариты изделия не соответствуют расчётному узлу")
        if remote_readout_required(project) and product.remote_readout is not True:
            errors.append("Исполнение не подтверждает требуемую дистанционную передачу данных / АСКУЭ")
        if row is primary_meter(project) and d.meter_model and d.meter_model != product.name:
            errors.append("Ручное наименование счётчика расходится с выбранной моделью")
        flow_key = {"total":"tot", "cold":"c", "hot":"h"}.get(node)
        q = getattr(project.flows, f"q_sec_{flow_key}", None)
        qmax = product.flows_m3h.get("qmax")
        if q is None or not isfinite(q) or q < 0 or qmax is None:
            errors.append("Нет текущего расхода или паспортного Qmax для проверки модели")
        elif q * 3.6 > qmax:
            errors.append("Расход проекта выше паспортного Qmax модели")
        elif q * 3.6 > product.flows_m3h.get("qn", 0):
            pending.append("Режим выше Qn допускается паспортом не более 1 ч/сут: подтвердить продолжительность")
        # The common assembly temperature is not a temperature for a DHW node.
        t = d.water_temperature_c if row is primary_meter(project) else None
        if t is not None and not product.temperature_c[0] <= t <= product.temperature_c[1]:
            errors.append("Температура проекта вне паспортного диапазона")
        if d.design_pressure_bar is not None and d.design_pressure_bar > product.pn_bar:
            errors.append("Давление проекта выше PN изделия")
        pending.append("Проверить рабочие P/T, прямые участки и комплект присоединения")
        pending.append("Гидравлическое сопротивление модели по техдокументации не подтверждено; расчёт по СП сохранён")
    if errors:
        product = None
    # Passport evidence is valid only for the current product AND orientation.
    qmin, reference = None, ""
    if product:
        qmin = orientation.qmin_m3h
        if qmin is not None:
            reference = (f"{product.name}; класс {orientation.metrological_class}; "
                         f"{mounting}; {orientation.reference}")
    if raw and raw.dn_mm not in (None, row.dn):
        errors.append("Исходные проверки минимума относятся к другому DN; подтвердить заново")
    if raw and raw.q_min_passport_m3h is not None and qmin is not None and raw.q_min_passport_m3h != qmin:
        errors.append("Ручной паспортный минимум расходится с выбранной моделью/классом")
    evidence = MeterMinimumEvidence(row.dn, raw.q_min_hourly_m3h if raw else None,
                                    qmin, reference, raw.flow_reference if raw else "")
    ok, note = check_minimum_flow(row.dn, evidence)
    if errors:
        ok, note = None, "; ".join(errors)
        product = None
    if automatic:
        pending.insert(0, "Предложение каталога; горизонтальное размещение шкалой вверх, класс B"
                       if mounting == "horizontal_dial_up" else
                       "Предложение каталога; ориентация проверяется по паспорту выбранного исполнения")
    return MeterProductCheck(product, node, automatic, evidence, ok, note, tuple(errors), tuple(pending))


def bind_meter_products(project):
    """Attach derived output; never change DN, S, Qexpl, losses, bypass or head."""
    for row in project.meters.rows:
        check = evaluate_meter_product(project, row)
        row.product = check.summary()
        if check.automatic or check.product or check.errors:
            evidence = check.evidence
            row.ok_v, row.minimum_flow_note = check.minimum_ok, check.minimum_note
            # Same recommendation as calculate_meters, after supplying the
            # model's passport evidence; no new sizing or loss formula.
            row.need_combo = row.ok_a and row.ok_v is False and row.dn > 15
            row.q_min_hourly_m3h = evidence.q_min_hourly_m3h
            row.q_min_passport_m3h = evidence.q_min_passport_m3h
            row.passport_reference, row.flow_reference = evidence.passport_reference, evidence.flow_reference
