"""Evidence-based fan ventilation checks. No hydraulic sizing or auto valves.

SP 30.13330.2020, amendments 1-5: 18.18-18.25, 19.8-19.9.
The foreign-system separation rule is a Zarya design invariant, not an
invented paragraph of the current SP. Roof heights are shared with drafting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from math import isfinite
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from app.pz.project import Project

ROOF_VENT_HEIGHT_M = {
    "flat_non_accessible": .2, "pitched": .2, "single_slope": .2, "gable": .2,
    "collecting_vent_shaft": .1, "flat_accessible": 3.,
}
Status = Literal["verified", "pending", "fail"]


class FanInputError(ValueError):
    """Optional source address, independent of Studio and unchanged error text."""
    def __init__(self, detail, code, field, *, row_index=None, scope="terminal"):
        super().__init__(detail)
        self.code, self.field = code, field
        self.row_index, self.scope = row_index, scope


@dataclass(frozen=True)
class FanTerminal:
    terminal_id: str
    riser_ids: tuple[str, ...]
    kind: str = "unknown"  # roof / valve / unventilated / unknown
    source_ref: str = ""
    height_m: float | None = None
    diameter_mm: float | None = None
    collector_diameter_mm: float | None = None
    opening_distance_m: float | None = None
    no_openings_confirmed: bool | None = None
    open_end_confirmed: bool | None = None
    separate_from_other_systems: bool | None = None
    condensate_drains_to_risers: bool | None = None
    cold_attic: bool | None = None
    attic_insulated: bool | None = None
    plastic_exposed: bool | None = None
    uv_protected: bool | None = None
    valve_above_highest_fixture: bool | None = None
    valve_on_top_floor: bool | None = None
    valve_sizing_verified: bool | None = None
    valve_sizing_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.terminal_id, str) or not self.terminal_id.strip():
            raise FanInputError("fan terminal needs an ID", "fan_model_id", "terminal_id")
        if (not isinstance(self.riser_ids, tuple) or not self.riser_ids
                or any(not isinstance(x, str) or not x.strip() for x in self.riser_ids)
                or len(set(self.riser_ids)) != len(self.riser_ids)):
            raise FanInputError("fan terminal needs unique explicit riser IDs", "fan_model_riser_ids", "riser_ids")
        if self.kind not in {"roof", "valve", "unventilated", "unknown"}:
            raise FanInputError("unsupported fan termination kind", "fan_model_kind", "kind")
        for name in ("height_m", "diameter_mm", "collector_diameter_mm", "opening_distance_m"):
            value = getattr(self, name)
            if value is not None and (type(value) not in (int, float) or not isfinite(value) or value < 0):
                raise FanInputError(f"{name} must be a finite non-negative number", "fan_model_number", name)
        for f in fields(self):
            if f.type == "bool | None" and getattr(self, f.name) is not None and type(getattr(self, f.name)) is not bool:
                raise FanInputError(f"{f.name} must be boolean or null", "fan_model_boolean", f.name)
        if not isinstance(self.source_ref, str) or not isinstance(self.valve_sizing_ref, str):
            raise FanInputError("evidence references must be strings", "fan_model_reference",
                                "source_ref" if not isinstance(self.source_ref, str) else "valve_sizing_ref")


@dataclass(frozen=True)
class FanVentilationInput:
    terminals: tuple[FanTerminal, ...] = ()
    external_ventilation_verified: bool | None = None
    external_ventilation_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.terminals, tuple) or any(not isinstance(t, FanTerminal) for t in self.terminals):
            raise ValueError("terminals must be FanTerminal records")
        if len({t.terminal_id for t in self.terminals}) != len(self.terminals):
            seen = set()
            for index, terminal in enumerate(self.terminals):
                if terminal.terminal_id in seen:
                    raise FanInputError("duplicate fan terminal ID", "fan_model_duplicate_id", "terminal_id", row_index=index)
                seen.add(terminal.terminal_id)
        if self.external_ventilation_verified is not None and type(self.external_ventilation_verified) is not bool:
            raise FanInputError("external ventilation verification must be boolean or null",
                                "fan_global_boolean", "external_ventilation_verified", scope="global")
        if not isinstance(self.external_ventilation_ref, str):
            raise FanInputError("external ventilation reference must be a string",
                                "fan_global_text", "external_ventilation_ref", scope="global")

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> FanVentilationInput:
        if not isinstance(value, dict):
            raise ValueError("fan_ventilation must be an object")
        data = dict(value)
        raw = data.pop("terminals", [])
        if not isinstance(raw, (list, tuple)):
            raise ValueError("fan terminals must be an array")
        terminals = []
        for index, row in enumerate(raw):
            if not isinstance(row, dict) or not isinstance(row.get("riser_ids"), (list, tuple)):
                raise ValueError("each fan terminal needs an array of riser_ids")
            try:
                terminals.append(FanTerminal(**(row | {"riser_ids": tuple(row["riser_ids"])})))
            except FanInputError as exc:
                raise FanInputError(str(exc), exc.code, exc.field, row_index=index) from exc
        return cls(terminals=tuple(terminals), **data)

    def to_mapping(self) -> dict[str, Any]:
        result = asdict(self)
        result["terminals"] = [dict(asdict(t), riser_ids=list(t.riser_ids)) for t in self.terminals]
        return result


@dataclass(frozen=True)
class FanRiser:
    riser_id: str
    diameter_mm: float | None
    mode: str = "unknown"
    outlet_id: str | None = None


@dataclass(frozen=True)
class FanCheck:
    code: str
    target: str
    status: Status
    message: str
    reference: str


@dataclass(frozen=True)
class FanVentilationAudit:
    checks: tuple[FanCheck, ...]

    @property
    def status(self) -> Status:
        return "fail" if any(c.status == "fail" for c in self.checks) else (
            "pending" if any(c.status == "pending" for c in self.checks) else "verified")

    @property
    def ready(self) -> bool:
        return self.status == "verified"

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(f"{c.target}: {c.message} ({c.reference})" for c in self.checks if c.status != "verified")


def audit_fan_ventilation(*, roof_kind: str, risers: tuple[FanRiser, ...],
                          evidence: FanVentilationInput | None,
                          residential: bool) -> FanVentilationAudit:
    checks: list[FanCheck] = []

    def add(code: str, target: str, ok: bool | None, message: str, ref: str) -> None:
        checks.append(FanCheck(code, target, "pending" if ok is None else "verified" if ok else "fail", message, ref))

    if not risers and not (evidence and evidence.terminals):
        return FanVentilationAudit(())  # K2-only projects do not need K1 fan checks.
    lookup = {r.riser_id: r for r in risers}
    if len(lookup) != len(risers):
        add("FAN-IDS", "К1", False, "Повторные марки стояков", "Топология К1")
    if evidence is None:
        add("FAN-DATA", "К1", None, "Не заданы подтверждённые окончания фановой вентиляции", "СП 30, 18.18-18.25")
        return FanVentilationAudit(tuple(checks))
    assigned: dict[str, FanTerminal] = {}
    for t in evidence.terminals:
        target = t.terminal_id
        add("FAN-SOURCE", target, True if t.source_ref.strip() else None,
            "Нужен источник подтверждения схемы фановой вентиляции", "Исходные данные АР/ВК")
        for rid in t.riser_ids:
            add("FAN-MEMBER", target, rid in lookup, f"Проверить принадлежность стояка {rid} системе К1", "Топология К1")
            if rid in assigned:
                add("FAN-DUPLICATE", target, False, f"Стояк {rid} включён в несколько окончаний", "Топология К1")
            assigned[rid] = t
        members = [lookup[rid] for rid in t.riser_ids if rid in lookup]
        expected_mode = {"roof": "ventilated", "valve": "vacuum_valve", "unventilated": "unventilated"}.get(t.kind)
        for r in members:
            add("FAN-MODE", target, None if r.mode == "unknown" or expected_mode is None else r.mode == expected_mode,
                f"Режим стояка {r.riser_id} должен соответствовать окончанию {t.kind}", "СП 30, 18.18, 18.23")
        add("FAN-SEPARATE", target, t.separate_from_other_systems,
            "Подтвердить отдельность от ОВ и дымоходов", "Проектное правило Zarya: раздельность систем")
        if t.kind == "unknown":
            add("FAN-KIND", target, None, "Не выбран тип окончания", "СП 30, 18.18-18.25")
        elif t.kind == "roof":
            minimum = ROOF_VENT_HEIGHT_M.get(roof_kind)
            height_base = "обрезом сборной вентиляционной шахты" if roof_kind == "collecting_vent_shaft" else "кровлей"
            add("FAN-HEIGHT", target, None if minimum is None or t.height_m is None else t.height_m >= minimum,
                f"Высота над {height_base}: требуется минимум {minimum:g} м" if minimum is not None else "Не задан вид кровли",
                "СП 30, 18.18")
            if roof_kind == "flat_accessible":
                add("FAN-FOUR", target, len(members) >= 4,
                    "Общая вытяжная часть над эксплуатируемой кровлей должна объединять минимум 4 стояка",
                    "СП 30, 18.22")
            add("FAN-OPEN", target, t.open_end_confirmed, "Устье без колпака, флюгарки и дефлектора", "СП 30, 18.21")
            distance_ok = (t.opening_distance_m >= 4 if t.opening_distance_m is not None
                           else True if t.no_openings_confirmed is True else None)
            if t.no_openings_confirmed is True and t.opening_distance_m is not None:
                distance_ok = False  # contradictory evidence must not bypass a short distance
            add("FAN-OPENINGS", target, distance_ok,
                "Подтвердить не менее 4 м по горизонтали до открываемых окон/балконов либо их отсутствие",
                "СП 30, 18.18")
            dns = [r.diameter_mm for r in members
                   if r.diameter_mm is not None and isfinite(r.diameter_mm) and r.diameter_mm > 0]
            required_dn = max(dns) if dns and len(dns) == len(members) else None
            add("FAN-DN", target, None if required_dn is None or t.diameter_mm is None else t.diameter_mm == required_dn,
                "DN вытяжки должен соответствовать наибольшему DN подключённых стояков", "СП 30, 18.19-18.20")
            if len(members) > 1:
                add("FAN-COLLECTOR-DN", target, None if required_dn is None or t.collector_diameter_mm is None
                    else t.collector_diameter_mm == required_dn,
                    "Подтвердить DN сборного вентиляционного трубопровода", "СП 30, 18.20")
                add("FAN-CONDENSATE", target, t.condensate_drains_to_risers,
                    "Нужен уклон сборного вентиляционного трубопровода к стоякам для стока конденсата", "СП 30, 18.20")
                add("FAN-INSULATION", target, None if t.cold_attic is None else
                    (t.attic_insulated if t.cold_attic else True),
                    "На холодном чердаке требуется теплоизоляция сборного трубопровода", "СП 30, 18.20")
            add("FAN-UV", target, None if t.plastic_exposed is None else (t.uv_protected if t.plastic_exposed else True),
                "Подтвердить защиту пластиковых частей на кровле от УФ", "СП 30, 18.19")
        elif t.kind == "valve":
            add("FAN-VALVE-SINGLE", target, len(t.riser_ids) == 1,
                "В этой модели клапан назначается отдельно каждому стояку", "СП 30, 18.22; граница модели")
            add("FAN-VALVE-LEVEL", target, t.valve_above_highest_fixture,
                "Клапан должен быть выше борта наиболее высокого прибора", "СП 30, 18.22")
            add("FAN-VALVE-FLOOR", target, t.valve_on_top_floor,
                "Подтвердить установку клапана над полом верхнего этажа", "СП 30, 18.22")
            sizing = t.valve_sizing_verified if t.valve_sizing_verified is False or t.valve_sizing_ref.strip() else None
            add("FAN-VALVE-SIZING", target, sizing,
                "Нужен проверенный подбор воздушного клапана с источником расчёта", "СП 30, 19.8-19.9")
        else:
            add("FAN-UNVENTILATED", target, None, "Невентилируемое окончание требует отдельного обоснования",
                "СП 30, 18.23-18.25")
    for r in risers:
        if r.riser_id not in assigned:
            add("FAN-COVERAGE", r.riser_id, None, "Не задано окончание стояка", "СП 30, 18.18-18.25")
    outlets = {r.outlet_id for r in risers if r.outlet_id}
    if any(r.outlet_id is None for r in risers):
        add("FAN-OUTLETS", "К1", None, "Не определена принадлежность всех стояков выпускам", "СП 30, 18.25")
    if residential:
        for outlet in sorted(outlets):
            members = [r for r in risers if r.outlet_id == outlet]
            complete = all(r.riser_id in assigned and assigned[r.riser_id].kind != "unknown" for r in members)
            atmospheric = any(r.mode == "ventilated" and r.riser_id in assigned
                              and assigned[r.riser_id].kind == "roof" for r in members)
            add("FAN-ATMOSPHERE", outlet, True if atmospheric else False if complete else None,
                "Для жилья нужен минимум один вентилируемый стояк на выпуск; клапан не является вытяжкой",
                "СП 30, 18.25, примечание 4")
    if not residential or any(t.kind != "roof" for t in evidence.terminals):
        proof = evidence.external_ventilation_verified
        if proof is True and not evidence.external_ventilation_ref.strip():
            proof = None
        add("FAN-EXTERNAL", "К1", proof, "Подтвердить сохранение вентиляции наружной сети",
            "СП 30, 18.23-18.25")
    return FanVentilationAudit(tuple(checks))


def project_fan_risers(project: Project) -> tuple[FanRiser, ...]:
    """Adapt actual K1 risers/outlets; never count four K2 funnels as four K1 vents."""
    from app.pz.wastewater_diagnostics import _terminal_for_riser
    from app.pz.wastewater_topology import build_wastewater_topology

    topology = build_wastewater_topology(project)
    specs = {r.riser_id: r for r in project.sewage.risers}
    ids = {rid for rid, pipe in topology.risers.items() if pipe.system == "K1"}
    ids |= set(specs) - set(topology.risers)
    outlet_sections = {e.section_id for e in project.sewage.elements if e.system == "K1" and e.kind == "outlet"}
    outlets = {p.to_node for p in topology.mains if p.system == "K1" and p.section_id in outlet_sections}

    def outlet_for(rid: str) -> str | None:
        node = _terminal_for_riser(rid, "K1", topology.mains)
        return node if node in outlets else None

    return tuple(FanRiser(
        # The drawing uses nominal DN from the pipe record; hydraulic input
        # riser_dn_mm may contain an OD (e.g. 110). Never mix these conventions.
        rid, topology.risers[rid].nominal_diameter_mm if rid in topology.risers else None,
        specs[rid].ventilation if rid in specs else "unknown",
        outlet_for(rid) if rid in topology.risers else None,
    ) for rid in sorted(ids))


def audit_project_fan_ventilation(project: Project) -> FanVentilationAudit:
    return audit_fan_ventilation(roof_kind=project.sewage.roof_kind, risers=project_fan_risers(project),
                                evidence=project.sewage.fan_ventilation,
                                residential=getattr(project.building.purpose, "value", project.building.purpose) == "residential")


def fan_drafting_limitations(project: Project) -> tuple[str, ...]:
    """Do not draw independent open stacks for an accepted collector or valve.

    Geometry can be saved through the Wizard, but the opt-in bound preview
    does not establish a production release adapter. Keep that boundary explicit.
    This is a product limitation, not a prohibition in SP 30.
    """
    evidence = project.sewage.fan_ventilation
    if evidence is None:
        return ()
    reasons = []
    for t in evidence.terminals:
        if t.kind != "roof" or len(t.riser_ids) != 1:
            reasons.append(
                f"{t.terminal_id}: графический модуль общей вытяжки/клапана доступен в контрольной сборке, "
                "но подтверждённая геометрия ещё не передаётся штатным выпуском; "
                "подмена отдельными открытыми стояками запрещена."
            )
        elif t.height_m != ROOF_VENT_HEIGHT_M.get(project.sewage.roof_kind):
            reasons.append(
                f"{t.terminal_id}: заданная высота вытяжки не поддержана текущим графическим шаблоном; "
                "нельзя заменить её минимальной высотой по СП."
            )
    return tuple(reasons)
