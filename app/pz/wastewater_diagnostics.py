"""Диагностика потока, самоочищения и эксплуатационной доступности К1/К2.

Модуль связывает инженерный граф с гидравликой и точками обслуживания. Он не
подменяет стадию Р: участок рассчитывается только при наличии явной длины,
геометрии, расхода и коэффициента шероховатости. Неполные данные получают
статус ``pending``, а не вымышленные результаты.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from app.calc.sewer_hydraulics import (
    SewerHydraulicInput,
    SewerHydraulicResult,
    calculate_sewer_hydraulics,
)
from app.pz.project import Project, SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_topology import SewerBranch, build_wastewater_topology


@dataclass(frozen=True)
class FixtureDiameterCheck:
    element_id: str
    section_id: str
    fixture_kind: str
    fixture_dn_mm: Optional[int]
    generated_segment_dn_mm: Optional[int]
    pipe_nominal_dn_mm: Optional[int]
    minimum_dn_mm: int
    status: str
    note: str


@dataclass(frozen=True)
class NetworkDiameterCheck:
    node_id: str
    incoming_section_id: str
    outgoing_section_id: str
    incoming_dn_mm: Optional[int]
    outgoing_dn_mm: Optional[int]
    transition_element_id: str
    status: str
    note: str


@dataclass(frozen=True)
class VentilationCheck:
    outlet_node: str
    riser_ids: Tuple[str, ...]
    ventilated_riser_ids: Tuple[str, ...]
    status: str
    note: str


@dataclass(frozen=True)
class TurnServiceCheck:
    riser_id: str
    outgoing_section_id: str
    access_element_id: str
    access_kind: str
    access_fitting: str
    status: str
    note: str


@dataclass(frozen=True)
class LinearServiceCheck:
    section_id: str
    calculation_length_m: Optional[float]
    access_chainages_m: Tuple[float, ...]
    maximum_gap_m: Optional[float]
    status: str
    note: str


@dataclass(frozen=True)
class SedimentRiskZone:
    zone_id: str
    section_id: str
    node_id: str
    reason: str
    severity: str
    serviced: Optional[bool]
    location_note: str = ""
    access_element_ids: Tuple[str, ...] = ()
    placement_rule: str = ""


@dataclass
class WastewaterDiagnosticAssessment:
    resolved_flows_lps: Dict[str, float] = field(default_factory=dict)
    hydraulics: List[SewerHydraulicResult] = field(default_factory=list)
    diameter_checks: List[FixtureDiameterCheck] = field(default_factory=list)
    network_diameter_checks: List[NetworkDiameterCheck] = field(default_factory=list)
    ventilation_checks: List[VentilationCheck] = field(default_factory=list)
    turn_checks: List[TurnServiceCheck] = field(default_factory=list)
    linear_service_checks: List[LinearServiceCheck] = field(default_factory=list)
    risk_zones: List[SedimentRiskZone] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.errors


def _is_riser(pipe: SewerPipeSpec) -> bool:
    purpose = (pipe.purpose or "").strip().lower()
    return purpose.startswith((
        "стояк",
        "канализационный стояк",
        "водосточный стояк",
        "вертикаль",
        "вертикальный участок",
    ))


def _is_branch(pipe: SewerPipeSpec) -> bool:
    purpose = (pipe.purpose or "").lower()
    return any(word in purpose for word in ("ответвлен", "ветвь", "подключен"))


def _outgoing_mains(
    pipes: Iterable[SewerPipeSpec],
    riser_id: str,
    system: str,
) -> List[SewerPipeSpec]:
    return [
        pipe for pipe in pipes
        if pipe.system == system
        and not _is_riser(pipe)
        and not _is_branch(pipe)
        and pipe.from_node == riser_id
    ]


def resolve_k1_main_flows(project: Project) -> tuple[Dict[str, float], List[str]]:
    """Суммировать только явно заданные нагрузки стояков по направленному графу."""
    pipes = [
        pipe for pipe in project.sewage.pipes
        if pipe.system == "K1" and not _is_riser(pipe) and not _is_branch(pipe)
    ]
    outgoing: Dict[str, List[SewerPipeSpec]] = {}
    for pipe in pipes:
        outgoing.setdefault(pipe.from_node, []).append(pipe)
    result: Dict[str, float] = {
        pipe.section_id: float(pipe.design_flow_lps)
        for pipe in pipes
        if pipe.design_flow_lps is not None
    }
    derived: Dict[str, float] = {}
    warnings: List[str] = []

    for riser in project.sewage.risers:
        if riser.design_flow_lps <= 0:
            continue
        node = riser.riser_id
        visited_nodes = set()
        while node in outgoing:
            if node in visited_nodes:
                warnings.append(
                    f"{riser.riser_id}: цикл не позволяет суммировать расход К1"
                )
                break
            visited_nodes.add(node)
            choices = outgoing[node]
            if len(choices) != 1:
                warnings.append(
                    f"{node}: расход стояка нельзя распределить между "
                    f"{len(choices)} выходящими участками без явных долей"
                )
                break
            pipe = choices[0]
            derived[pipe.section_id] = (
                derived.get(pipe.section_id, 0.0) + riser.design_flow_lps
            )
            node = pipe.to_node

    for section_id, value in derived.items():
        if section_id in result:
            if abs(result[section_id] - value) > 0.001:
                warnings.append(
                    f"{section_id}: явный расход {result[section_id]:.3f} л/с "
                    f"не совпадает с суммой стояков {value:.3f} л/с"
                )
        else:
            result[section_id] = value
    return {key: round(value, 3) for key, value in result.items()}, warnings


def _fixture_minimum_dn(kind: str) -> int:
    # Зафиксированное пользователем проектное правило генератора: выпуски
    # обычных приборов моделируются DN50, унитаза и проходного участка после
    # него — DN100. Фактический выпуск выбранного изделия всё равно хранится
    # в реестре и не подменяется условным наружным диаметром трубы.
    return 100 if kind == "toilet" else 50


def _fixture_diameter_checks(
    branches: Iterable[SewerBranch],
) -> List[FixtureDiameterCheck]:
    checks: List[FixtureDiameterCheck] = []
    for branch in branches:
        pipe_dn = branch.pipe.nominal_diameter_mm
        generated_segment_dn = 0
        for element in branch.elements:
            minimum = _fixture_minimum_dn(element.kind)
            generated_segment_dn = max(generated_segment_dn, minimum)
            if element.dn_mm is None or pipe_dn is None:
                status = "pending"
                note = "нужны DN выпуска прибора и номинальный DN ветви"
            elif element.dn_mm < minimum:
                status = "fail"
                note = (
                    f"DN выпуска прибора {element.dn_mm} меньше конструктивного "
                    f"минимума {minimum}"
                )
            elif pipe_dn < minimum or pipe_dn < element.dn_mm:
                status = "fail"
                note = (
                    f"DN ветви {pipe_dn} меньше требуемого DN "
                    f"{max(minimum, element.dn_mm)}"
                )
            else:
                status = "verified"
                note = "диаметр выпуска прибора и ветви подтверждён"
            checks.append(FixtureDiameterCheck(
                element_id=element.element_id,
                section_id=branch.pipe.section_id,
                fixture_kind=element.kind,
                fixture_dn_mm=element.dn_mm,
                generated_segment_dn_mm=generated_segment_dn,
                pipe_nominal_dn_mm=pipe_dn,
                minimum_dn_mm=minimum,
                status=status,
                note=note,
            ))
    return checks


def _turn_service_check(
    project: Project,
    riser: SewerPipeSpec,
    outgoing: SewerPipeSpec,
) -> TurnServiceCheck:
    elements = list(project.sewage.elements or [])
    candidates: List[SewerElementSpec] = []
    # Ревизия нижнего этажа может обслуживать нижний поворот только при явно
    # заданном направлении вниз по потоку и доступном люке.
    candidates.extend(
        row for row in elements
        if row.kind == "revision"
        and row.system == riser.system
        and row.section_id == riser.section_id
        and row.floor_from <= 1
        and row.accessible
        and row.service_direction in {"downstream", "both"}
        and row.service_fitting == "revision_opening"
    )
    # Прочистка нижнего поворота должна принадлежать конкретной паре
    # «стояк -> выходящий горизонтальный участок», а не произвольной трубе.
    candidates.extend(
        row for row in elements
        if row.kind == "cleanout"
        and row.system == riser.system
        and row.section_id == outgoing.section_id
        and row.connects_to == riser.section_id
        and row.accessible
        and row.service_direction in {"downstream", "both"}
        and row.service_fitting == "wye_45"
    )
    if candidates:
        preferred = next(
            # Direct access at the turn is the deterministic first choice;
            # a lower-floor revision remains a valid alternative when a
            # project explicitly omits the separate wye cleanout.
            (row for row in candidates if row.kind == "cleanout"),
            candidates[0],
        )
        return TurnServiceCheck(
            riser_id=riser.section_id,
            outgoing_section_id=outgoing.section_id,
            access_element_id=preferred.element_id,
            access_kind=preferred.kind,
            access_fitting=preferred.service_fitting,
            status="verified",
            note=(
                "нижний поворот достижим через ревизию"
                if preferred.kind == "revision"
                else "прочистка встроена косой фасонной частью по направлению потока"
            ),
        )
    return TurnServiceCheck(
        riser_id=riser.section_id,
        outgoing_section_id=outgoing.section_id,
        access_element_id="",
        access_kind="",
        access_fitting="",
        status="fail",
        note=(
            "нет подтверждённого пути обслуживания: тип и положение ревизии "
            "или прочистки определить по п. 18.26, а для К2 также по п. 21.8 "
            "СП 30.13330.2020 с привязкой по плану/аксонометрии"
        ),
    )


def service_limit_m(system: str, nominal_dn: int, kind: str) -> Optional[float]:
    """Предельный шаг по таблице 18.1 СП 30 (редакция с изм. № 1–5)."""
    water_drain = system == "K2"
    if nominal_dn <= 50:
        return (15.0 if kind == "revision" else 10.0) if water_drain else (
            12.0 if kind == "revision" else 8.0
        )
    if nominal_dn <= 150:
        return (20.0 if kind == "revision" else 15.0) if water_drain else (
            15.0 if kind == "revision" else 10.0
        )
    if kind == "cleanout":
        return None
    return 25.0 if water_drain else 20.0


def _access_points(
    project: Project,
    pipe: SewerPipeSpec,
    length: float,
) -> List[tuple[float, str, float, str]]:
    points: List[tuple[float, str, float, str]] = []
    nominal_dn = pipe.nominal_diameter_mm or 0
    for row in project.sewage.elements:
        if not row.accessible:
            continue
        if row.kind == "cleanout" and row.section_id == pipe.section_id:
            chainage = row.service_chainage_m
            if chainage is None and row.connects_to == pipe.from_node:
                chainage = 0.0
            elif chainage is None and row.connects_to == pipe.to_node:
                chainage = length
            if chainage is None or not 0 <= chainage <= length:
                continue
            limit = service_limit_m(pipe.system, nominal_dn, "cleanout")
            if limit is not None:
                points.append((chainage, "cleanout", limit, row.element_id))
        elif row.kind == "revision" and row.floor_from <= 1:
            if row.section_id == pipe.from_node and row.service_direction in {
                "downstream", "both",
            }:
                limit = service_limit_m(pipe.system, nominal_dn, "revision")
                if limit is not None:
                    points.append((0.0, "revision", limit, row.element_id))
            if row.section_id == pipe.to_node and row.service_direction in {
                "upstream", "both",
            }:
                limit = service_limit_m(pipe.system, nominal_dn, "revision")
                if limit is not None:
                    points.append((length, "revision", limit, row.element_id))
        elif (
            row.kind == "outlet"
            and row.section_id == pipe.section_id
            and row.connects_to == pipe.to_node
        ):
            # Доступ из наружного колодца считается только при явно
            # зарегистрированном узле выпуска.
            limit = service_limit_m(pipe.system, nominal_dn, "revision")
            if limit is not None:
                points.append((length, "outlet", limit, row.element_id))
    # В одной точке сохраняем наиболее дальнодействующий доступ.
    by_chainage: Dict[float, tuple[float, str, float, str]] = {}
    for point in points:
        old = by_chainage.get(round(point[0], 6))
        if old is None or point[2] > old[2]:
            by_chainage[round(point[0], 6)] = point
    return sorted(by_chainage.values(), key=lambda item: item[0])


def _linear_service_check(
    project: Project,
    pipe: SewerPipeSpec,
) -> LinearServiceCheck:
    length = pipe.calculation_length_m
    if length is None or pipe.nominal_diameter_mm is None:
        return LinearServiceCheck(
            section_id=pipe.section_id,
            calculation_length_m=length,
            access_chainages_m=(),
            maximum_gap_m=None,
            status="pending",
            note=(
                "для проверки таблицы 18.1 нужны расчётная длина участка и "
                "номинальный DN"
            ),
        )
    points = _access_points(project, pipe, length)
    if not points:
        return LinearServiceCheck(
            section_id=pipe.section_id,
            calculation_length_m=length,
            access_chainages_m=(),
            maximum_gap_m=length,
            status="fail",
            note="на горизонтальном участке нет подтверждённых точек обслуживания",
        )
    uncovered: List[str] = []
    if points[0][0] > points[0][2]:
        uncovered.append(f"начало–{points[0][0]:g} м")
    maximum_gap = points[0][0]
    for left, right in zip(points, points[1:]):
        gap = right[0] - left[0]
        maximum_gap = max(maximum_gap, gap)
        if gap > min(left[2], right[2]) + 1e-9:
            uncovered.append(f"{left[0]:g}–{right[0]:g} м")
    tail_gap = length - points[-1][0]
    maximum_gap = max(maximum_gap, tail_gap)
    if tail_gap > points[-1][2] + 1e-9:
        uncovered.append(f"{points[-1][0]:g}–{length:g} м")
    status = "fail" if uncovered else "verified"
    note = (
        "превышена достижимость прочистки на интервалах " + ", ".join(uncovered)
        if uncovered else
        "вся длина участка покрыта точками обслуживания по таблице 18.1"
    )
    return LinearServiceCheck(
        section_id=pipe.section_id,
        calculation_length_m=length,
        access_chainages_m=tuple(point[0] for point in points),
        maximum_gap_m=round(maximum_gap, 3),
        status=status,
        note=note,
    )


def _service_access_element_ids(
    project: Project,
    pipe: SewerPipeSpec,
) -> Tuple[str, ...]:
    """Вернуть реальные точки, которыми достигается расчётный участок."""
    length = pipe.calculation_length_m
    if length is None or length <= 0:
        return ()
    return tuple(
        dict.fromkeys(
            point[3] for point in _access_points(project, pipe, length)
        )
    )


def _network_diameter_checks(
    project: Project,
    topology,
) -> List[NetworkDiameterCheck]:
    """Проверить неуменьшение DN по потоку и явные переходы на увеличении."""
    checks: List[NetworkDiameterCheck] = []
    mains = list(topology.mains)
    elements = list(project.sewage.elements or [])

    for outgoing in mains:
        incoming = [
            pipe for pipe in mains
            if pipe.system == outgoing.system and pipe.to_node == outgoing.from_node
        ]
        riser = topology.risers.get(outgoing.from_node)
        sources: List[tuple[str, Optional[int]]] = [
            (pipe.section_id, pipe.nominal_diameter_mm) for pipe in incoming
        ]
        if riser is not None and riser.system == outgoing.system:
            sources.append((riser.section_id, riser.nominal_diameter_mm))
        if not sources:
            continue

        known_source_dns = [dn for _, dn in sources if dn is not None]
        source_mark = "+".join(section for section, _ in sources)
        if not known_source_dns or outgoing.nominal_diameter_mm is None:
            checks.append(NetworkDiameterCheck(
                node_id=outgoing.from_node,
                incoming_section_id=source_mark,
                outgoing_section_id=outgoing.section_id,
                incoming_dn_mm=max(known_source_dns) if known_source_dns else None,
                outgoing_dn_mm=outgoing.nominal_diameter_mm,
                transition_element_id="",
                status="pending",
                note="нужны номинальные DN всех сходящихся участков",
            ))
            continue

        required_dn = max(known_source_dns)
        outgoing_dn = outgoing.nominal_diameter_mm
        transition = next((
            row for row in elements
            if row.system == outgoing.system
            and row.kind == "transition"
            and row.section_id == outgoing.section_id
            and row.connects_to == outgoing.from_node
        ), None)
        if outgoing_dn < required_dn:
            status = "fail"
            note = (
                f"DN уменьшается по потоку с {required_dn} до {outgoing_dn}; "
                "самотечная магистраль не должна иметь такое сужение"
            )
        elif outgoing_dn > required_dn and transition is None:
            status = "fail"
            note = (
                f"увеличение DN{required_dn}→DN{outgoing_dn} не подтверждено "
                "переходом в реестре"
            )
        elif outgoing_dn > required_dn:
            status = "verified"
            note = f"увеличение DN{required_dn}→DN{outgoing_dn} выполнено переходом"
        else:
            status = "verified"
            note = f"проходной DN{outgoing_dn} не уменьшается по потоку"
        checks.append(NetworkDiameterCheck(
            node_id=outgoing.from_node,
            incoming_section_id=source_mark,
            outgoing_section_id=outgoing.section_id,
            incoming_dn_mm=required_dn,
            outgoing_dn_mm=outgoing_dn,
            transition_element_id=transition.element_id if transition else "",
            status=status,
            note=note,
        ))
    return checks


def _terminal_for_riser(
    riser_id: str,
    system: str,
    mains: Iterable[SewerPipeSpec],
) -> Optional[str]:
    outgoing: Dict[str, List[SewerPipeSpec]] = {}
    for pipe in mains:
        if pipe.system == system:
            outgoing.setdefault(pipe.from_node, []).append(pipe)
    node = riser_id
    visited = set()
    while node not in visited:
        visited.add(node)
        edges = outgoing.get(node, [])
        if len(edges) != 1:
            return node if not edges else None
        node = edges[0].to_node
    return None


def _ventilation_checks(project: Project, topology) -> List[VentilationCheck]:
    """Проверить наличие вентилируемого стояка в каждой группе выпуска К1."""
    riser_specs = {row.riser_id: row for row in project.sewage.risers}
    groups: Dict[str, List[str]] = {}
    for riser_id, pipe in topology.risers.items():
        if pipe.system != "K1":
            continue
        terminal = _terminal_for_riser(riser_id, "K1", topology.mains)
        groups.setdefault(terminal or "не определён", []).append(riser_id)

    checks: List[VentilationCheck] = []
    purpose = getattr(project.building.purpose, "value", project.building.purpose)
    residential = purpose == "residential"
    for terminal, riser_ids in sorted(groups.items()):
        ventilated = tuple(sorted(
            riser_id for riser_id in riser_ids
            if riser_specs.get(riser_id) is not None
            and riser_specs[riser_id].ventilation == "ventilated"
        ))
        unknown = [riser_id for riser_id in riser_ids if riser_id not in riser_specs]
        valve_only = [
            riser_id for riser_id in riser_ids
            if riser_specs.get(riser_id) is not None
            and riser_specs[riser_id].ventilation == "vacuum_valve"
        ]
        if unknown:
            status = "pending"
            note = "не задан режим вентиляции стояков " + ", ".join(sorted(unknown))
        elif not ventilated:
            status = "fail" if residential else "pending"
            suffix = (
                "; воздушные клапаны не подтверждают сообщение сети с атмосферой"
                if valve_only else ""
            )
            note = (
                "в группе выпуска нет вентилируемого стояка" + suffix
                + (
                    ""
                    if residential
                    else "; для нежилого объекта требуется расчёт вентиляции сети"
                )
            )
        elif valve_only:
            status = "pending"
            note = (
                "атмосферная вентиляция группы обеспечена; применимость и доступ "
                "к воздушным клапанам проверить отдельным расчётом"
            )
        else:
            status = "verified"
            note = "стояки группы выведены на вентиляционную часть выше кровли"
        checks.append(VentilationCheck(
            outlet_node=terminal,
            riser_ids=tuple(sorted(riser_ids)),
            ventilated_riser_ids=ventilated,
            status=status,
            note=note,
        ))
    return checks


def assess_wastewater_diagnostics(project: Project) -> WastewaterDiagnosticAssessment:
    assessment = WastewaterDiagnosticAssessment()
    topology = build_wastewater_topology(project)
    assessment.errors.extend(topology.errors)
    assessment.warnings.extend(topology.warnings)

    flows, flow_warnings = resolve_k1_main_flows(project)
    assessment.resolved_flows_lps = flows
    assessment.warnings.extend(flow_warnings)
    assessment.diameter_checks = _fixture_diameter_checks(topology.branches)
    for check in assessment.diameter_checks:
        if check.status == "fail":
            assessment.errors.append(f"{check.element_id}: {check.note}")
        elif check.status == "pending":
            assessment.warnings.append(f"{check.element_id}: {check.note}")

    assessment.network_diameter_checks = _network_diameter_checks(
        project, topology,
    )
    for check in assessment.network_diameter_checks:
        message = f"{check.outgoing_section_id}: {check.note}"
        if check.status == "fail":
            assessment.errors.append(message)
        elif check.status == "pending":
            assessment.warnings.append(message)

    assessment.ventilation_checks = _ventilation_checks(project, topology)
    for check in assessment.ventilation_checks:
        message = f"К1 → {check.outlet_node}: {check.note}"
        if check.status == "fail":
            assessment.errors.append(message)
        elif check.status == "pending":
            assessment.warnings.append(message)

    pipes = list(project.sewage.pipes or [])
    for riser_id, riser in topology.risers.items():
        outgoing = _outgoing_mains(pipes, riser_id, riser.system)
        if len(outgoing) != 1:
            note = (
                f"ожидался один выходящий участок, найдено {len(outgoing)}; "
                "путь обслуживания не определяется"
            )
            check = TurnServiceCheck(
                riser_id=riser_id,
                outgoing_section_id="",
                access_element_id="",
                access_kind="",
                access_fitting="",
                status="fail",
                note=note,
            )
        else:
            check = _turn_service_check(project, riser, outgoing[0])
        assessment.turn_checks.append(check)
        serviced = check.status == "verified"
        assessment.risk_zones.append(SedimentRiskZone(
            zone_id=f"turn:{riser_id}",
            section_id=check.outgoing_section_id,
            node_id=riser_id,
            reason="нижний поворот стояка в горизонтальную магистраль",
            severity="high" if not serviced else "controlled",
            serviced=serviced,
            location_note=f"узел {riser_id}: нижний поворот стояка",
            access_element_ids=(
                (check.access_element_id,) if check.access_element_id else ()
            ),
            placement_rule=(
                "использовать доступную ревизию перед поворотом"
                if check.access_kind == "revision" else
                "прочистка выполнена заглушённым концом косой фасонной части"
                if check.access_kind == "cleanout" else
                "нужна ревизия перед поворотом либо прочистка на выходящем участке"
            ),
        ))
        if not serviced:
            assessment.errors.append(f"{riser_id}: {check.note}")

    for pipe in pipes:
        if _is_riser(pipe) or _is_branch(pipe):
            continue
        if (
            pipe.calculation_length_m is not None
            and pipe.slope_per_mille is not None
            and pipe.elevation_start_m is not None
            and pipe.elevation_end_m is not None
        ):
            geometric_slope = (
                (pipe.elevation_start_m - pipe.elevation_end_m)
                / pipe.calculation_length_m
                * 1000.0
            )
            if abs(geometric_slope - pipe.slope_per_mille) > 0.5:
                assessment.errors.append(
                    f"{pipe.section_id}: уклон {pipe.slope_per_mille:g}‰ "
                    f"не совпадает с отметками ({geometric_slope:.2f}‰)"
                )
        if pipe.system in {"K1", "K2"}:
            service = _linear_service_check(project, pipe)
            assessment.linear_service_checks.append(service)
            if service.status == "fail":
                assessment.errors.append(f"{pipe.section_id}: {service.note}")
                assessment.risk_zones.append(SedimentRiskZone(
                    zone_id=f"service:{pipe.section_id}",
                    section_id=pipe.section_id,
                    node_id="",
                    reason="участок не покрыт доступом для механической прочистки",
                    severity="high",
                    serviced=False,
                    location_note="непокрытый интервал горизонтального участка",
                    access_element_ids=(),
                    placement_rule=(
                        "тип и место точки обслуживания определяются по "
                        "непокрытому интервалу и подтверждённой трассировке"
                    ),
                ))
            elif service.status == "pending":
                assessment.warnings.append(f"{pipe.section_id}: {service.note}")

        flow = flows.get(pipe.section_id, pipe.design_flow_lps)
        if pipe.system not in {"K1", "K3"} or flow is None:
            continue
        if pipe.slope_per_mille is None or pipe.manning_n is None:
            assessment.warnings.append(
                f"{pipe.section_id}: расчёт Шези требует уклон и явный n"
            )
            continue
        try:
            hydraulic = calculate_sewer_hydraulics(SewerHydraulicInput(
                section_id=pipe.section_id,
                design_flow_lps=flow,
                inner_diameter_mm=pipe.inner_diameter_mm,
                slope_per_mille=pipe.slope_per_mille,
                material=pipe.material,
                manning_n=pipe.manning_n,
                roughness_source=pipe.hydraulic_source,
                declared_fill_ratio=pipe.fill_ratio,
            ))
        except ValueError as exc:
            assessment.errors.append(f"{pipe.section_id}: {exc}")
            continue
        assessment.hydraulics.append(hydraulic)
        if hydraulic.status == "fail":
            assessment.errors.append(f"{pipe.section_id}: {hydraulic.note}")
            assessment.risk_zones.append(SedimentRiskZone(
                zone_id=f"hydraulic:{pipe.section_id}",
                section_id=pipe.section_id,
                node_id="",
                reason=hydraulic.note,
                severity="high",
                serviced=None,
                location_note="расчётный горизонтальный участок",
                access_element_ids=_service_access_element_ids(project, pipe),
                placement_rule=(
                    "сначала устранить гидравлическое несоответствие; "
                    "прочистка не заменяет требуемую пропускную способность"
                ),
            ))

    # Стационарная проверка расчётного расхода и кратковременный сценарий
    # отвечают на разные вопросы. Сценарий может выявить периоды V < Vкр даже
    # у участка, который проходит нормативную проверку на расчётном расходе.
    # Такая строка является зоной возможных отложений, но не доказывает массу
    # осадка без концентрации взвесей и калибровки.
    transient = project.sewage.transient_assessment
    if transient is None and project.sewage.discharge_events:
        from app.pz.wastewater_transients import assess_wastewater_transients
        transient = assess_wastewater_transients(project)
        project.sewage.transient_assessment = transient
    pipe_by_id = {row.section_id: row for row in pipes}
    service_by_section = {
        row.section_id: row for row in assessment.linear_service_checks
    }
    for summary in (
        getattr(transient, "network_summaries", ()) if transient else ()
    ):
        pipe = pipe_by_id.get(summary.section_id)
        minimum_velocity = summary.minimum_wet_velocity_mps
        critical_velocity = pipe.critical_velocity_mps if pipe else None
        if (
            pipe is None
            or minimum_velocity is None
            or critical_velocity is None
            or minimum_velocity + 1e-12 >= critical_velocity
        ):
            continue
        service = service_by_section.get(pipe.section_id)
        serviced = bool(service and service.status == "verified")
        assessment.risk_zones.append(SedimentRiskZone(
            zone_id=f"transient:{pipe.section_id}",
            section_id=pipe.section_id,
            node_id="",
            reason=(
                "в заданном временном сценарии минимальная скорость "
                f"{minimum_velocity:.3f} м/с ниже Vкр={critical_velocity:.3f} м/с"
            ),
            severity="controlled" if serviced else "high",
            serviced=serviced,
            location_note=(
                "по длине участка; одноячейковая модель не локализует "
                "точку осаждения внутри прямой трубы"
            ),
            access_element_ids=_service_access_element_ids(project, pipe),
            placement_rule=(
                "существующие точки обслуживания расставлены по достижимости "
                "троса; дополнительная прочистка не требуется"
                if serviced else
                "выбрать ревизию либо прочистку для непокрытого интервала "
                "после точной привязки по плану/аксонометрии"
            ),
        ))
    assessment.errors = list(dict.fromkeys(assessment.errors))
    assessment.warnings = list(dict.fromkeys(assessment.warnings))
    return assessment
