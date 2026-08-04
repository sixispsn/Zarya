"""Нормативный контроль подраздела ИОС3 по ГОСТ Р 21.620-2023.

Модуль не выполняет гидравлических расчётов и не заполняет отсутствующие
исходные данные. Он только проверяет, достаточно ли данных для обязательного
состава текстовой и графической частей, и формирует прозрачную трассировку.
"""
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class WastewaterGostCheck:
    code: str
    requirement: str
    reference: str
    status: str  # verified / missing / not_applicable
    evidence: str


@dataclass(frozen=True)
class WastewaterGostAudit:
    checks: List[WastewaterGostCheck]

    @property
    def missing(self) -> List[WastewaterGostCheck]:
        return [row for row in self.checks if row.status == "missing"]

    @property
    def complete(self) -> bool:
        return not self.missing


def audit_wastewater_gost(project) -> WastewaterGostAudit:
    """Проверить обязательные сведения в границах фактического проекта."""
    s = project.sewage
    storm_required = project.storm.system_kind == "internal"
    production_required = project.grease_trap.preparation_type != "none"
    checks: List[WastewaterGostCheck] = []

    def add(code, requirement, reference, ok, evidence, *, applicable=True):
        checks.append(WastewaterGostCheck(
            code=code,
            requirement=requirement,
            reference=reference,
            status=("verified" if ok else "missing") if applicable else "not_applicable",
            evidence=evidence,
        ))

    add(
        "K-GOST-01", "Задание на проектирование и инженерные изыскания",
        "ГОСТ Р 21.620-2023, п. 5.1.2",
        bool(s.design_assignment_ref and s.survey_ref),
        "; ".join(filter(None, [s.design_assignment_ref, s.survey_ref]))
        or "реквизиты не заданы",
    )
    add(
        "K-GOST-02", "Срок службы и период до капитального ремонта",
        "ГОСТ Р 21.620-2023, п. 5.1.2",
        s.service_life_years is not None and s.overhaul_period_years is not None,
        (
            f"срок службы {s.service_life_years} лет; до капремонта "
            f"{s.overhaul_period_years} лет"
            if s.service_life_years is not None and s.overhaul_period_years is not None
            else "значения не заданы"
        ),
    )
    centralized = s.disposal_mode == "centralized"
    local = s.disposal_mode == "local"
    water_body = s.disposal_mode == "water_body"
    add(
        "K-GOST-03", "Способ водоотведения и реквизиты условий подключения",
        "ГОСТ Р 21.620-2023, пп. 5.1.2, 5.1.3.1",
        s.disposal_mode != "not_set" and (
            not centralized
            or bool(s.connection_tu_org and s.connection_tu_number and s.connection_tu_date)
        ),
        (
            f"режим {s.disposal_mode}; ТУ {s.connection_tu_number} от "
            f"{s.connection_tu_date}, {s.connection_tu_org}"
            if centralized else f"режим {s.disposal_mode}"
        ),
    )
    add(
        "K-GOST-04", "Характеристика существующей централизованной сети",
        "ГОСТ Р 21.620-2023, п. 5.1.3.1",
        bool(
            s.existing_network_type
            and s.existing_network_material
            and s.existing_network_standard
            and s.existing_network_outer_diameter_mm
            and s.existing_network_wall_thickness_mm
        ),
        (
            f"{s.existing_network_type}; {s.existing_network_material}; "
            f"{s.existing_network_outer_diameter_mm}×"
            f"{s.existing_network_wall_thickness_mm} мм; "
            f"{s.existing_network_standard}"
        ),
        applicable=centralized,
    )
    add(
        "K-GOST-04A", "Норматив допустимого сброса и характеристика водного объекта",
        "ГОСТ Р 21.620-2023, пп. 5.1.2, 5.1.3.1",
        bool(s.discharge_standard_ref and s.water_body_characteristics_note),
        (
            "; ".join(filter(None, [
                s.discharge_standard_ref,
                s.water_body_characteristics_note,
            ])) or "реквизиты НДС и данные водного объекта не заданы"
        ) if water_body else "сброс в водный объект не предусмотрен",
        applicable=water_body,
    )
    points_ok = bool(s.discharge_point_k1)
    if storm_required:
        points_ok = points_ok and bool(s.discharge_point_k2)
    if production_required:
        points_ok = points_ok and bool(s.discharge_point_k3)
    add(
        "K-GOST-05", "Источники стоков, марки систем и точки сброса",
        "ГОСТ Р 21.620-2023, п. 5.1.3.2",
        points_ok,
        "; ".join(filter(None, [
            f"К1 → {s.discharge_point_k1}" if s.discharge_point_k1 else "",
            f"К2 → {s.discharge_point_k2}" if storm_required and s.discharge_point_k2 else "",
            f"К3 → {s.discharge_point_k3}" if production_required and s.discharge_point_k3 else "",
        ])) or "точки сброса не заданы",
    )
    add(
        "K-GOST-06", "Баланс водопотребления и водоотведения по приложению А",
        "ГОСТ Р 21.620-2023, п. 5.1.3.3, приложение А",
        bool(project.balance.rows),
        f"строк баланса: {len(project.balance.rows)}",
    )
    flow_quality_ok = bool(s.quality_indicators_note) and (
        s.k1_min_hourly_m3h is not None
    )
    if production_required:
        flow_quality_ok = flow_quality_ok and (
            s.k3_max_hourly_m3h is not None
            and s.k3_min_hourly_m3h is not None
        )
    add(
        "K-GOST-06A", "Максимальные/минимальные расходы и показатели состава стоков",
        "ГОСТ Р 21.620-2023, п. 5.1.4.1",
        flow_quality_ok,
        s.quality_indicators_note or "показатели состава и минимальные расходы не заданы",
    )

    pipe_geometry_ok = bool(s.pipes) and all(
        p.material and p.standard and p.outer_diameter_mm > 0
        and p.wall_thickness_mm > 0 and p.length_m > 0
        for p in s.pipes
    )
    add(
        "K-GOST-07", "Материал, наружный диаметр и толщина стенки труб",
        "ГОСТ Р 21.620-2023, пп. 5.1.4.1, 5.1.6.1",
        pipe_geometry_ok,
        f"подтверждено участков: {len(s.pipes)}" if s.pipes else "участки не заданы",
    )
    gravity = [
        p for p in s.pipes
        if "стояк" not in p.purpose.lower() and "вертик" not in p.purpose.lower()
    ]
    hydraulic_ok = bool(gravity) and all(
        p.slope_per_mille is not None and p.fill_ratio is not None
        for p in gravity
    )
    add(
        "K-GOST-08", "Уклоны в промилле и коэффициенты наполнения",
        "ГОСТ Р 21.620-2023, пп. 5.1.4.1, 5.1.6.1",
        hydraulic_ok,
        (
            f"самотечных горизонтальных участков: {len(gravity)}"
            if gravity else "горизонтальные участки не заданы"
        ),
    )
    add(
        "K-GOST-09", "Способ прокладки и пересечения конструкций",
        "ГОСТ Р 21.620-2023, пп. 5.1.4.1, 5.1.6.1",
        bool(s.laying_method and s.fire_barrier_note and s.deformation_joint_note),
        "; ".join(filter(None, [
            s.laying_method, s.fire_barrier_note, s.deformation_joint_note,
        ])) or "решения не заданы",
    )
    pump_ok = bool(
        s.pump_location and s.pump_model and s.pump_q_m3h is not None
        and s.pump_head_m is not None and s.pump_power_kw is not None
        and s.pump_reserve_note and s.pump_power_category
        and s.pump_automation_note
    )
    add(
        "K-GOST-10", "Канализационная насосная установка",
        "ГОСТ Р 21.620-2023, п. 5.1.4.2",
        pump_ok,
        (
            f"{s.pump_model}; Q={s.pump_q_m3h} м³/ч; H={s.pump_head_m} м; "
            f"P={s.pump_power_kw} кВт"
        ) if s.pump_required else "насосное оборудование не предусмотрено",
        applicable=s.pump_required,
    )
    treatment_ok = bool(
        s.treatment_location and s.treatment_type
        and s.treatment_capacity_lps is not None
        and s.treatment_capacity_m3_day is not None
        and s.treatment_technology
    )
    add(
        "K-GOST-11", "Локальные очистные сооружения",
        "ГОСТ Р 21.620-2023, п. 5.1.4.3",
        treatment_ok,
        (
            f"{s.treatment_type}; {s.treatment_location}; "
            f"{s.treatment_capacity_lps} л/с; "
            f"{s.treatment_capacity_m3_day} м³/сут"
            if treatment_ok else "характеристики локальной очистки не заданы"
        ) if s.treatment_required or local
        else "локальные очистные сооружения не предусмотрены",
        applicable=s.treatment_required or local,
    )
    add(
        "K-GOST-12", "Порядок обращения с отходами очистки",
        "ГОСТ Р 21.620-2023, п. 5.1.5",
        bool(s.waste_handling_note),
        (
            s.waste_handling_note or "порядок не задан"
            if s.treatment_required or production_required
            else "отходы очистки в границах проекта не образуются"
        ),
        applicable=s.treatment_required or local or production_required,
    )

    from app.pz.wastewater_registry import audit_wastewater_registry

    registry = audit_wastewater_registry(project)
    required_systems = {"K1"}
    if storm_required:
        required_systems.add("K2")
    if production_required:
        required_systems.add("K3")
    registered_systems = {row.system for row in s.elements}
    outlets_registered = sum(
        row.quantity for row in s.elements
        if row.system == "K1" and row.kind == "outlet"
    )
    topology_ok = bool(s.risers and s.outlets_count and s.pipes) and all(
        p.from_node and p.to_node and p.room
        and p.elevation_start_m is not None and p.elevation_end_m is not None
        for p in s.pipes
    ) and registry.ready and required_systems <= registered_systems and (
        outlets_registered >= s.outlets_count
    )
    add(
        "K-GOST-13", "Принципиальная схема внутренних систем",
        "ГОСТ Р 21.620-2023, пп. 5.2.2.1-5.2.2.4",
        topology_ok,
        (
            f"стояков {len(s.risers)}; выпусков {s.outlets_count}; "
            f"топологических участков {len(s.pipes)}; "
            f"элементов реестра {len(s.elements)}"
        ),
    )
    add(
        "K-GOST-13A", "Текстовые решения по наружным сетям водоотведения",
        "ГОСТ Р 21.620-2023, п. 5.1.6.1",
        bool(s.external_network_design_note),
        (
            s.external_network_design_note
            if s.external_network_in_scope
            else "наружные сети не входят в заданные границы"
        ),
        applicable=s.external_network_in_scope,
    )
    add(
        "K-GOST-14", "Принципиальная схема наружных сетей",
        "ГОСТ Р 21.620-2023, п. 5.2.3",
        bool(s.external_scheme_source),
        (
            s.external_scheme_source or "графический источник не задан"
            if s.external_network_in_scope
            else "наружные сети не входят в заданные границы"
        ),
        applicable=s.external_network_in_scope,
    )
    add(
        "K-GOST-15", "План наружных сетей на опорном плане",
        "ГОСТ Р 21.620-2023, п. 5.2.4",
        bool(s.site_plan_source),
        (
            s.site_plan_source or "опорный план не задан"
            if s.external_network_in_scope
            else "наружные сети не входят в заданные границы"
        ),
        applicable=s.external_network_in_scope,
    )
    add(
        "K-GOST-16", "Объёмы дождевых и талых вод",
        "ГОСТ Р 21.620-2023, п. 5.1.6.2",
        bool(
            project.storm.design_m3_day is not None
            and project.storm.annual_m3 is not None
            and project.storm.melt_m3h is not None
            and project.storm.melt_m3_day is not None
            and project.storm.melt_m3_year is not None
        ),
        (
            f"дождевые {project.storm.design_m3_day} м³/сут, "
            f"{project.storm.annual_m3} м³/год; талые "
            f"{project.storm.melt_m3h} м³/ч, "
            f"{project.storm.melt_m3_day} м³/сут, "
            f"{project.storm.melt_m3_year} м³/год"
        ) if storm_required else "внутренний водосток К2 не предусмотрен",
        applicable=storm_required,
    )
    return WastewaterGostAudit(checks)
