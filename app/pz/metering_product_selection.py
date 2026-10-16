"""Bind catalogue geometry to current project DNs without changing its calculation.

Candidates are suggestions. Explicit IDs are revalidated on every generation.
An exact assembly length is intentionally unavailable until joining parts,
straight sections, dismantling/service space and installed lengths are defined.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.data.metering_products import MeteringProduct, get_metering_catalogue
from app.pz.metering_rules import remote_readout_required, seismic_metering_rules
from app.pz.metering_accessories import AccessoryCheck, check_accessories
from app.pz.metering_pipes import pipe_checks, support_pipe
from app.pz.metering_connections import ConnectionCheck, check_connections
from app.pz.metering_reducers import ReducerCheck, check_reducers
from app.pz.metering_joint_audit import InlineJointCheck, check_inline_joints
from app.pz.metering_service import ServiceCheck, check_service_components
from app.pz.rules import decide_fire_network


CATALOGUE_ROLES = {
    "meter": ("Счётчик", "meter"),
    "inlet_valve": ("Кран на вводе", "shutoff"),
    "meter_valves": ("Краны до и после счётчика", "shutoff"),
    "filter": ("Фильтр", "strainer"),
    "check_valve": ("Обратный клапан", "check"),
    "bypass_valve": ("Арматура обводной линии", "shutoff"),
    "outlet_valve": ("Отсечка со стороны здания", "shutoff"),
}


@dataclass(frozen=True)
class ProductPosition:
    role: str
    title: str
    dn: int | None
    quantity_per_inlet: int
    product: MeteringProduct | None
    candidates: tuple[MeteringProduct, ...]
    errors: tuple[str, ...]
    pending: tuple[str, ...]


@dataclass(frozen=True)
class MeteringProductSelection:
    revision: str
    positions: tuple[ProductPosition, ...]
    errors: tuple[str, ...]
    pending: tuple[str, ...]
    accessories: tuple[AccessoryCheck, ...] = ()
    connections: tuple[ConnectionCheck, ...] = ()
    reducers: tuple[ReducerCheck, ...] = ()
    inline_joints: tuple[InlineJointCheck, ...] = ()
    services: tuple[ServiceCheck, ...] = ()
    fittings: tuple = ()
    flexible_connections: tuple = ()

    @property
    def assembly_length_mm(self) -> None:
        # Adding body lengths would double-count engaged threads and omit
        # tails, reducers, straight pipe, gauge tees and dismantling lengths.
        return None

    def selected(self, role: str) -> MeteringProduct | None:
        return next((p.product for p in self.positions if p.role == role), None)


def resolve_metering_products(project, meter, *, bypass: bool,
                              electric_bypass: bool) -> MeteringProductSelection:
    detail = project.metering_detail
    catalog = get_metering_catalogue()
    errors = list(detail.validate())
    if errors:
        return MeteringProductSelection(catalog.revision, (), tuple(errors), ())
    from app.pz.metering_orientation import filter_offset_choices, meter_orientation
    from app.pz.meter_validation import meter_node_key
    detail, offset_errors = filter_offset_choices(detail, meter.dn if meter else None)
    errors.extend(offset_errors)
    if meter and meter_orientation(detail, meter_node_key(meter)) != detail.meter_mounting:
        errors.append("Ориентация счётчика основного узла расходится с ориентацией деталировки")
    fire = decide_fire_network(project.fire, project.materials, project.normative)
    pipe_errors, _ = pipe_checks(detail, bypass=bypass,
        fire_branch=bool(project.fire.required and fire and fire.topology == "pre_meter_branch"),
        meter_dn=meter.dn if meter else None)
    errors.extend(pipe_errors)
    if "pipe_clamp" not in detail.catalogue_items:
        errors.extend(support_pipe(detail)[2])
    choices = detail.catalogue_items if isinstance(detail.catalogue_items, dict) else {}
    revision_ok = detail.catalogue_revision == catalog.revision
    if (choices or detail.connection_items or detail.connection_thread_items or detail.reducer_items or detail.fitting_items or detail.inline_joint_items or detail.service_items) and not revision_ok:
        errors.append("Редакция каталога не подтверждена: требуется повторный выбор изделий")
    expected = {
        "meter": (meter.dn if meter else None, 1, None),
        "inlet_valve": (detail.inlet_dn, 1, "manual"),
        "meter_valves": (meter.dn if meter else None, 2, "manual"),
        "filter": (meter.dn if meter else None, 1, None),
        # The existing drawing returns to inlet DN before the check valve.
        "check_valve": (detail.inlet_dn, 1, None),
    }
    branch = getattr(project, "metering_node", "") == "hot"
    switching = (not branch and detail.inlet_metering_mode == 'common' and detail.common_topology == 'gost_g1'
        and (len(getattr(project.v1_network, 'inlets', ()) or ()) or project.source.inputs_count) == 2)
    if switching:
        expected['inlet_valve'] = (detail.inlet_dn, 2, 'manual')
    if branch:
        # No third inlet valve on a branch; only the two meter isolators.
        expected.pop("inlet_valve")
    if detail.maintenance_layout == "serviceable":
        expected["outlet_valve"] = (detail.inlet_dn, 1, "manual")
    elif "outlet_valve" in choices:
        errors.append("Выходная ремонтная отсечка выбрана, но компоновка обслуживания не включена")
    if bypass:
        expected["bypass_valve"] = (detail.bypass_dn, 2 if switching else 1, "electric" if electric_bypass else "manual")
    elif "bypass_valve" in choices:
        errors.append("Арматура обводной выбрана, но обводной линии в проекте нет")
    positions = []
    for role, (dn, quantity, drive) in expected.items():
        title, kind = CATALOGUE_ROLES[role]
        magnetic_replacement = role == "filter" and detail.enhancements.get("magnetic_filter") == "vodopribor_fmf_replace"
        candidates = catalog.candidates(kind, dn, drive=drive,
                                        russian_only=detail.russian_equipment_only,
                                        technology=detail.enhancements.get("technology", "mechanical") if kind == "meter" else None)
        if role == "meter" and remote_readout_required(project):
            candidates = tuple(p for p in candidates if p.remote_readout is True)
        from app.pz.metering_orientation import check_product_orientation, component_orientation
        orientation = component_orientation(detail, role)
        candidates = tuple(p for p in candidates if not check_product_orientation(p, orientation).errors)
        position_errors, pending = [], []
        ident = choices.get(role)
        # Reuse an explicitly selected compatible valve family, not an
        # arbitrary catalogue default. All ordinary checks below still apply.
        if (not ident and role == "outlet_valve"
                and detail.service_selection_mode == "catalogue_proposal"):
            for other in ("inlet_valve", "meter_valves"):
                candidate = catalog.products.get(choices.get(other))
                if candidate and candidate.dn == dn:
                    ident = candidate.id
                    pending.append("Предварительно предложена выбранная серия арматуры; новая выходная отсечка")
                    break
        if magnetic_replacement:
            candidates = tuple(p for p in candidates if p.filter_type == "magnetic_mesh")
            if not ident:
                ident = f"vodopribor-fmf-dn{dn}" if dn is not None else None
        product = catalog.products.get(ident) if isinstance(ident, str) else None
        # Same node/model as the calculation and specification. The old manual
        # assembly-only workflow remains explicit; Studio opts into proposals.
        binding = None
        if role == "meter" and meter is not None and (
            detail.meter_selection_mode == "catalogue_proposal" or detail.meter_products or ident
        ):
            from app.pz.meter_products import evaluate_meter_product
            binding = evaluate_meter_product(project, meter)
            product = binding.product
            position_errors.extend(binding.errors)
            pending.extend(binding.pending)
        if ident and product is None:
            position_errors.append("Неизвестный идентификатор изделия")
        if product:
            orientation_check = check_product_orientation(product, orientation)
            position_errors.extend(orientation_check.errors)
            pending.extend(orientation_check.pending)
            if magnetic_replacement and product.filter_type != "magnetic_mesh":
                position_errors.append("Выбрана замена на ФМФ, но сохранён другой фильтр; конфликт выбора")
            if product.filter_type == "magnetic_mesh":
                pending.append("Размерная модель ФМФ не подтверждает потери фильтра в балансе напора; проверить отдельно")
            if detail.russian_equipment_only and not (product.country_of_manufacture == "RU" and product.origin_source_ids):
                position_errors.append("Российское производство не подтверждено; изделие исключено")
            if product.kind != kind or product.dn != dn:
                position_errors.append("Тип/DN изделия не соответствует текущему проекту")
            if product.dimension_status != "verified":
                position_errors.append("Конфликт габаритов в источниках производителя")
            if drive and product.drive != drive:
                position_errors.append("Исполнение привода не соответствует решению проекта")
            if role == "meter" and remote_readout_required(project) and product.remote_readout is not True:
                position_errors.append("Исполнение счётчика не подтверждает дистанционную передачу данных "
                                       "(СП 30, п. 12.13 / заданная АСКУЭ)")
            pressure, temperature = detail.design_pressure_bar, detail.water_temperature_c
            if pressure is not None and pressure > product.pn_bar:
                position_errors.append("Давление проекта выше PN изделия")
            if temperature is not None and not product.temperature_c[0] <= temperature <= product.temperature_c[1]:
                position_errors.append("Температура проекта вне подтверждённой области применения каталога")
            if pressure is None or temperature is None:
                pending.append("Нужны расчётное максимальное давление и температура, не только Hгар")
            elif product.pressure_temperature:
                table = dict(product.pressure_temperature)
                if temperature not in table:
                    pending.append("P/T: нет точной табличной точки; интерполяция не выполнялась")
                elif pressure > table[temperature]:
                    position_errors.append("Превышено допустимое давление при заданной температуре")
            else:
                pending.append("Подтвердить допустимость рабочего P/T по паспорту исполнения")
            if role == "meter" and meter is not None and product.kind == "meter":
                # Only test the published maximum; do not derive a new S or
                # replace legacy qmax/qexpl/qmin with manufacturer values.
                key = {"total": "tot", "cold": "c", "hot": "h"}.get(meter_node_key(meter))
                q = getattr(project.flows, f"q_sec_{key}", None)
                if q is None or not isfinite(q) or q < 0:
                    pending.append("Нет текущего расчётного расхода для проверки модели")
                elif q * 3.6 > product.flows_m3h["qmax"]:
                    position_errors.append("Расход проекта выше паспортного Qmax модели")
                if binding is None:
                    pending += ["Проверить минимальный расход и потери именно выбранной модели",
                                "Подтвердить паспортный класс для текущей ориентации и комплект прямых участков"]
                elif binding.minimum_ok is not True:
                    pending.append(binding.minimum_note)
                if product.remote_readout:
                    pending.append("Согласовать цену импульса, вход регистратора и линию связи; "
                                   "наличие выхода не подтверждает готовность АСКУЭ")
                if detail.meter_model and detail.meter_model != product.name:
                    position_errors.append("Ручное наименование счётчика расходится с выбранной моделью")
            if not revision_ok or position_errors:
                product = None
        if product is None and not position_errors:
            pending.append("Изделие не выбрано" if candidates else "Нет проверенного изделия нужного исполнения")
        errors.extend(f"{title}: {e}" for e in position_errors)
        positions.append(ProductPosition(role, title, dn, quantity, product, candidates,
                                         tuple(position_errors), tuple(pending)))
    accessories = check_accessories(detail, catalog,
        next((p.product for p in positions if p.role == "meter"), None), revision_ok=revision_ok)
    if detail.russian_equipment_only:
        from dataclasses import replace
        from app.pz.equipment_origin import origin_error
        accessories = tuple(replace(a, errors=(*a.errors, error)) if
            (error := origin_error(detail, a.catalogue_id)) else a for a in accessories)
    errors.extend(f"{a.title}: {e}" for a in accessories for e in a.errors)
    connections = check_connections(detail, catalog, {p.role:p.product for p in positions},
                                    bypass=bypass, revision_ok=revision_ok)
    errors.extend(f"{c.title}: {e}" for c in connections for e in c.errors)
    reducers = check_reducers(detail, catalog, {p.role:p.product for p in positions},
                              meter_dn=meter.dn if meter else None, bypass=bypass, revision_ok=revision_ok)
    errors.extend(f"{r.title}: {e}" for r in reducers for e in r.errors)
    services = check_service_components(detail, meter, catalog, revision_ok=revision_ok)
    errors.extend(f"{s.role}: {e}" for s in services for e in s.errors)
    from app.pz.metering_fitting_selection import check_fittings
    fittings = check_fittings(detail, catalog, meter, bypass=bypass,
        fire_branch=bool(project.fire.required and fire and fire.topology == "pre_meter_branch"),
        revision_ok=revision_ok)
    errors.extend(f"{c.role}: {e}" for c in fittings for e in c.errors)
    pending = (
        "Полная цепочка соединителей, переходов и прямых участков с глубинами свинчивания не подтверждена",
        "Отборы к основной трубе, опоры и пространство обслуживания требуют монтажной привязки",
        "Размер корпуса не равен монтажной длине узла; общий размер не определён",
    )
    pending += tuple(f"{rule.code}; {rule.clause}: {rule.message}"
                     for rule in seismic_metering_rules(project))
    from app.pz.metering_flexible import check_flexible_choices
    flexible = check_flexible_choices(detail, meter.dn if meter else None)
    errors.extend(f"Гибкое соединение {c['role']}: {e}" for c in flexible for e in c['errors'])
    pending += tuple(f"Гибкое соединение {c['role']}: {e}" for c in flexible for e in c['pending'])
    selection = MeteringProductSelection(catalog.revision, tuple(positions), tuple(errors), pending,
                                        accessories, connections, reducers, services=services, fittings=fittings,
                                        flexible_connections=flexible)
    # Construct once with no inline assignments to find the actual F/F joints;
    # the public chain then consumes checked assignments. No resolver recursion.
    from dataclasses import replace
    from types import SimpleNamespace
    from app.pz.metering_chain import build_metering_chain
    state = SimpleNamespace(meter=meter, bypass=bypass, inputs_count=1,
        switching_bridge=(not branch and detail.inlet_metering_mode == "common"
            and detail.common_topology == "gost_g1"
            and (len(getattr(project.v1_network, "inlets", ()) or ()) or project.source.inputs_count) == 2),
        common_inlets=(not branch and detail.inlet_metering_mode == "common"
                       and (len(getattr(project.v1_network, "inlets", ()) or ()) or project.source.inputs_count) > 1),
        fire_branch=bool(project.fire.required and fire and fire.topology == "pre_meter_branch"),
        node_key="hot" if branch else "")
    raw_chain = build_metering_chain(detail, state, selection)
    joints = check_inline_joints(raw_chain, detail, catalog, revision_ok=revision_ok)
    return replace(selection, inline_joints=joints,
        errors=(*selection.errors, *(f"{c.id}: {e}" for c in joints for e in c.errors)))
