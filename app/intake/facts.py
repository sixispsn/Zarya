# -*- coding: utf-8 -*-
"""Реестр исходных фактов проекта и их происхождения.

Реестр ничего не рассчитывает. Он делает видимым, что сообщил пользователь,
что пришло из ТУ/ТЗ, чего нет и что допустимо уточнить только на стадии Р.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from app.intake.project_intent import IntentLike, as_project_intent


class FactStatus(str, Enum):
    CONFIRMED = "confirmed"
    USER_DECLARED = "user_declared"
    DERIVED = "derived"
    NOT_PROVIDED = "not_provided"
    STAGE_R = "stage_r"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ProjectFact:
    fact_id: str
    section: str
    label: str
    value: Any = None
    unit: str = ""
    status: FactStatus = FactStatus.NOT_PROVIDED
    source_kind: str = ""
    source_ref: str = ""
    systems: tuple[str, ...] = ()
    normative_refs: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    required_for: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.fact_id,
            "section": self.section,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "status": self.status.value,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "systems": list(self.systems),
            "normative_refs": list(self.normative_refs),
            "dependencies": list(self.dependencies),
            "required_for": list(self.required_for),
        }


@dataclass
class FactRegistry:
    facts: list[ProjectFact] = field(default_factory=list)

    def add(self, fact: ProjectFact) -> None:
        if any(row.fact_id == fact.fact_id for row in self.facts):
            raise ValueError(f"факт '{fact.fact_id}' уже зарегистрирован")
        self.facts.append(fact)

    def get(self, fact_id: str) -> ProjectFact | None:
        return next((row for row in self.facts if row.fact_id == fact_id), None)

    def require(self, fact_id: str) -> ProjectFact:
        fact = self.get(fact_id)
        if fact is None:
            raise KeyError(f"факт '{fact_id}' не зарегистрирован")
        return fact

    def select(
        self,
        *,
        statuses: Iterable[FactStatus] | None = None,
        system: str | None = None,
    ) -> list[ProjectFact]:
        allowed = set(statuses) if statuses is not None else None
        return [
            row for row in self.facts
            if (allowed is None or row.status in allowed)
            and (system is None or system in row.systems)
        ]

    def to_dict(self) -> dict[str, Any]:
        counts = {
            status.value: len(self.select(statuses=[status]))
            for status in FactStatus
        }
        return {
            "counts": counts,
            "facts": [row.to_dict() for row in self.facts],
        }


def _status(value: Any) -> FactStatus:
    if (
        value is None
        or value == ""
        or value == []
        or value == 0
        or value in ("unknown", "not_set")
    ):
        return FactStatus.NOT_PROVIDED
    return FactStatus.USER_DECLARED


def build_fact_registry(value: IntentLike) -> FactRegistry:
    intent = as_project_intent(value)
    req = intent.request
    registry = FactRegistry()

    def add(
        fact_id: str,
        section: str,
        label: str,
        fact_value: Any,
        *,
        unit: str = "",
        status: FactStatus | None = None,
        source_kind: str | None = None,
        source_ref: str = "",
        systems: tuple[str, ...] = (),
        normative_refs: tuple[str, ...] = (),
        dependencies: tuple[str, ...] = (),
        required_for: tuple[str, ...] = (),
    ) -> None:
        registry.add(ProjectFact(
            fact_id=fact_id,
            section=section,
            label=label,
            value=fact_value,
            unit=unit,
            status=status or _status(fact_value),
            source_kind=source_kind or intent.source_kind,
            source_ref=source_ref or intent.source_ref,
            systems=systems,
            normative_refs=normative_refs,
            dependencies=dependencies,
            required_for=required_for,
        ))

    add("document.cipher", "document", "Шифр проекта", req.document.cipher)
    add("document.object_name", "document", "Наименование объекта", req.document.object_name)
    add("document.organization", "document", "Проектная организация", req.document.organization)
    add("document.stage", "document", "Стадия проектирования", req.document.stage)
    add("document.address", "document", "Адрес объекта", req.document.object_address)
    add("building.type", "building", "Назначение здания", req.building_type,
        systems=("V1", "V2", "T3", "T4", "K1", "K2", "K3"))
    add("building.floors", "building", "Этажность", req.floors, unit="эт.",
        systems=("V1", "V2", "K1", "K2"), required_for=("design",))
    add("building.height", "building", "Высота здания", req.building_height_m,
        unit="м", systems=("V1", "V2", "K1"), required_for=("design",))
    add("building.area", "building", "Общая площадь", req.total_area_m2,
        unit="м²", systems=("V2",), required_for=("fire_applicability",))
    add("building.hws_type", "building", "Тип приготовления ГВС", req.hws_type,
        systems=("T3", "T4"), required_for=("hws_decisions",))
    add("building.apartments", "building", "Количество квартир", req.apartments,
        unit="шт.", systems=("V1",), required_for=("apartment_hose_taps",))
    add("consumers.groups", "loads", "Группы потребителей", [
        {"code": row.code, "name": row.name, "count": row.count}
        for row in req.consumers
    ], systems=("V1", "T3", "K1"), required_for=("water_demand",))
    add("consumers.total", "loads", "Суммарное число потребителей",
        sum(row.count for row in req.consumers), unit="ед.",
        status=(FactStatus.DERIVED if req.consumers else FactStatus.NOT_PROVIDED),
        source_kind="derived_from_consumers", systems=("V1", "T3", "K1"),
        dependencies=("consumers.groups",), required_for=("water_demand",))

    source = req.source_data
    tu_ref = ""
    if source is not None:
        tu_ref = " ".join(part for part in (
            source.tu_org, source.tu_number, source.tu_date,
        ) if part).strip()
    for fact_id, label, fact_value, unit in (
        ("source.guaranteed_head", "Гарантированный напор", source.guaranteed_head_m if source else None, "м"),
        ("source.maximum_head", "Максимальный напор", source.maximum_head_m if source else None, "м"),
        ("source.connection_point", "Точка подключения", source.connection_point if source else "", ""),
        ("head.h_geom", "Геометрическая составляющая напора", source.h_geom_m if source else None, "м"),
        ("head.h_internal", "Потери во внутренней сети", source.h_il_m if source else None, "м"),
        ("head.h_inlet", "Потери на вводе", source.h_vvod_m if source else None, "м"),
        ("head.h_heater", "Потери в водонагревателе/теплообменнике", source.h_tepl_m if source else None, "м"),
        ("head.h_apartment_c", "Потери в квартирном узле учёта ХВС", source.h_apartment_c_meter_m if source else None, "м"),
        ("head.h_apartment_h", "Потери в квартирном узле учёта ГВС", source.h_apartment_h_meter_m if source else None, "м"),
        ("source.inputs_count", "Количество вводов водопровода", source.inputs_count if source else None, "шт."),
        ("source.npsh_available", "Располагаемый кавитационный запас", source.npsh_available_m if source else None, "м"),
    ):
        add(fact_id, "source_data", label, fact_value, unit=unit,
            source_kind="tu_or_design_assignment", source_ref=tu_ref,
            systems=("V1", "V2", "T3"), required_for=("head",))
    add("head.free_fixture", "source_data", "Свободный напор у диктующего прибора",
        source.h_pr_m if source else None, unit="м",
        source_kind="legacy_compatible_input",
        source_ref="legacy/sp30_calculator.html",
        systems=("V1", "T3"), required_for=("head",))
    add("source.network_kind", "source_data", "Расчётный вид сети", source.network_kind if source else "",
        source_kind="design_assignment", systems=("V1", "V2", "T3"),
        required_for=("head", "metering"))
    add("source.hws_heater_scope", "source_data", "Водонагреватель входит в расчётную ветвь",
        source.hws_heater_in_scope if source else None,
        source_kind="design_assignment", systems=("V1", "T3"), required_for=("head",))

    add("v1.sections", "water_network", "Расчётные участки В1", len(req.v1_sections),
        unit="уч.", status=(FactStatus.USER_DECLARED if req.v1_sections else FactStatus.STAGE_R),
        source_kind="design_input", systems=("V1",), required_for=("v1_hydraulics",))
    add("v1.network", "water_network", "Расчётная топология В1",
        {
            "nodes": len(req.v1_network.nodes) if req.v1_network else 0,
            "sections": len(req.v1_network.sections) if req.v1_network else 0,
            "inlets": len(req.v1_network.inlets) if req.v1_network else 0,
        },
        status=(FactStatus.USER_DECLARED if req.v1_network else FactStatus.STAGE_R),
        source_kind="design_input", systems=("V1",),
        required_for=("v1_hydraulics", "head", "diameter"))

    add("fire.mode", "fire", "Режим определения В2", req.fire_mode,
        systems=("V2",), normative_refs=("СП 10.13130.2020",))
    add("fire.height", "fire", "Пожарно-техническая высота", req.fire_height_m,
        unit="м", systems=("V2",), normative_refs=("СП 10.13130.2020",),
        required_for=("fire_applicability",))
    add("fire.category", "fire", "Функциональная категория В2", req.fire_category,
        systems=("V2",), normative_refs=("СП 10.13130.2020, таблица 7.1",))
    add("fire.hall_seats", "fire", "Вместимость зала Ф2.1", req.fire_hall_seats,
        unit="мест", systems=("V2",), normative_refs=("СП 10.13130.2020, таблица 7.1",))
    add("fire.area", "fire", "Площадь расчётной части В2", req.fire_area_m2,
        unit="м²", systems=("V2",), normative_refs=("СП 10.13130.2020, таблица 7.1",))
    add("fire.geometry", "fire", "Плановая геометрия В2",
        {"confirmed": req.fire_geometry_confirmed, "rooms": len(req.rooms)},
        status=(FactStatus.USER_DECLARED if req.fire_geometry_confirmed and req.rooms else FactStatus.STAGE_R),
        source_kind="architecture_input", systems=("V2",), required_for=("fire_hydraulics",))
    add("fire.network", "fire", "Расчётная топология В2",
        {
            "runs": len(req.network.runs) if req.network else 0,
            "risers": len(req.network.risers) if req.network else 0,
            "source": req.network.source_node if req.network else "",
        },
        status=(FactStatus.USER_DECLARED if req.network else FactStatus.STAGE_R),
        source_kind="design_input", systems=("V2",), required_for=("fire_hydraulics",))
    add("fire.topology", "fire", "Разделение В1/В2", req.fire_topology,
        source_kind="design_decision", systems=("V1", "V2"),
        normative_refs=("СП 10.13130.2020",))

    add("storm.roof_type", "storm", "Тип кровли", req.roof_type, systems=("K2",))
    storm_status = (
        FactStatus.NOT_APPLICABLE
        if req.roof_type == "not_set" else _status(req.storm_city)
    )
    add("storm.city", "storm", "Город расчёта дождевого стока", req.storm_city,
        status=storm_status, systems=("K2",), required_for=("storm_flow",))
    add("storm.roof_area", "storm", "Площадь кровли", req.storm_roof_area_m2,
        unit="м²", status=(FactStatus.NOT_APPLICABLE if req.roof_type == "not_set" else None),
        systems=("K2",), required_for=("storm_flow",))
    add("storm.walls_area", "storm", "Площадь примыкающих стен", req.storm_walls_area_m2,
        unit="м²", status=(FactStatus.NOT_APPLICABLE if req.roof_type == "not_set" else None),
        systems=("K2",), required_for=("storm_flow",))
    add("storm.period", "storm", "Период однократного превышения", req.storm_period_years,
        unit="лет", status=(FactStatus.NOT_APPLICABLE if req.roof_type == "not_set" else None),
        systems=("K2",), required_for=("storm_flow",))
    add("storm.network", "storm", "Явные параметры воронок и стояков К2",
        {
            "sections": req.storm_roof_sections,
            "funnels": req.storm_funnels_count,
            "risers": req.storm_risers_count,
            "riser_dn": req.storm_selected_riser_dn_mm,
        },
        status=(
            FactStatus.NOT_APPLICABLE if req.roof_type == "not_set"
            else FactStatus.USER_DECLARED
            if req.storm_funnels_count and req.storm_risers_count
            else FactStatus.STAGE_R
        ),
        source_kind="roof_plan_input", systems=("K2",), required_for=("storm_network",))

    add("technology.group_showers", "technology", "Наличие групповых душевых",
        req.group_showers_answer, systems=("V1", "T3", "K1"))
    add("technology.group_showers_count", "technology", "Количество душевых сеток",
        req.group_showers_count, unit="шт.", systems=("V1", "T3", "K1"))
    add("technology.food_service", "technology", "Наличие предприятия питания",
        req.food_service_answer, systems=("V1", "T3", "K1"))
    add("technology.catering_type", "technology", "Тип приготовления пищи",
        req.catering_type, systems=("V1", "T3", "K1", "K3"))
    add("technology.catering_loads", "technology", "Производственная программа общепита",
        {"seats": req.catering_seats, "conditional_dishes": req.catering_conditional_dishes},
        status=(FactStatus.USER_DECLARED if req.catering_seats or req.catering_conditional_dishes else FactStatus.NOT_PROVIDED),
        systems=("V1", "T3", "K1", "K3"))
    add("technology.grease_wastewater", "technology", "Жиросодержащие стоки",
        req.grease_wastewater_answer, systems=("K1",))
    add("technology.grease_trap_location", "technology", "Место жироуловителя",
        req.grease_trap_location, systems=("K1",))

    add("sewage.max_fixture", "sewage", "Максимальный секундный расход прибора",
        req.sewage_max_fixture_lps, unit="л/с", systems=("K1",),
        normative_refs=("СП 30.13330.2020, п. 5.5",), required_for=("wastewater_flow",))
    add("sewage.risers", "sewage", "Расчётные стояки К1/К3", len(req.sewage_risers),
        unit="шт.", status=(FactStatus.USER_DECLARED if req.sewage_risers else FactStatus.STAGE_R),
        source_kind="design_input", systems=("K1", "K3"), required_for=("riser_capacity",))

    topology_status = FactStatus.USER_DECLARED
    if not req.sewer_pipes:
        topology_status = FactStatus.STAGE_R
    add("sewage.topology", "sewage", "Топология внутренних сетей К1/К2/К3",
        {
            "pipes": len(req.sewer_pipes),
            "elements": len(req.sewer_elements),
            "risers": len(req.sewage_risers),
        }, status=topology_status, source_kind="design_input",
        systems=("K1", "K2", "K3"),
        normative_refs=("ГОСТ Р 21.620-2023, пп. 5.2.2–5.2.4",),
        required_for=("wastewater_scheme", "wastewater_specification"))
    scheme_geometry_status = (
        FactStatus.USER_DECLARED
        if req.wastewater_floor_height_m is not None
        and req.wastewater_roof_kind != "unknown"
        else FactStatus.STAGE_R
    )
    add(
        "sewage.scheme_geometry",
        "sewage",
        "Высота типового этажа и вид кровли для принципиальной схемы",
        {
            "floor_height_m": req.wastewater_floor_height_m,
            "roof_kind": req.wastewater_roof_kind,
        },
        status=scheme_geometry_status,
        source_kind="architecture_input",
        systems=("K1", "K2"),
        normative_refs=("ГОСТ Р 21.620-2023, пп. 5.2.2–5.2.4",),
        required_for=("wastewater_scheme",),
    )
    return registry
