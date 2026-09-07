"""Controlled handoff from a building programme to system adapters.

The handoff exposes confirmed fixture sources only.  It deliberately does not
create pipe routes, diameters, flows or drawing geometry.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.architecture.residential_program import BuildingProgramTopology


SYSTEMS = ("V1", "T3", "K1", "K2", "K3")

_QUESTION_SYSTEMS: dict[str, tuple[str, ...]] = {
    "apartment_has_washing_machine": ("V1", "K1"),
    "apartment_has_dishwasher": ("V1", "K1"),
    "refuse_chamber_has_drain": ("V1", "K1"),
    "technical_basement_special_drainage": ("V1", "T3", "K1", "K3"),
    "parking_special_drainage": ("V1", "K1", "K2", "K3"),
    "roof_k2_inputs": ("K2",),
    "has_refuse_chamber": ("V1", "K1"),
    "has_underground_parking": ("V1", "K1", "K2", "K3"),
}


@dataclass(frozen=True)
class HandoffBlocker:
    code: str
    message: str


@dataclass(frozen=True)
class SystemHandoffStatus:
    system: str
    fixture_source_count: int
    quantities_ready: bool
    scheme_ready: bool
    quantity_blockers: tuple[HandoffBlocker, ...]
    scheme_blockers: tuple[HandoffBlocker, ...]


@dataclass(frozen=True)
class EngineeringFixtureSource:
    fixture_id: str
    archetype_id: str
    room_id: str
    level_id: str
    section_id: str | None
    sanitary_shaft_id: str | None
    service_ports: tuple[str, ...]


@dataclass(frozen=True)
class BuildingProgramHandoff:
    basis_confirmed: bool
    systems: tuple[SystemHandoffStatus, ...]
    sources: tuple[EngineeringFixtureSource, ...]

    def status(self, system: str) -> SystemHandoffStatus:
        for row in self.systems:
            if row.system == system:
                return row
        raise ValueError(f"Неизвестная система: {system}")

    def sources_for_system(
        self,
        system: str,
    ) -> tuple[EngineeringFixtureSource, ...]:
        status = self.status(system)
        if not status.quantities_ready:
            messages = "; ".join(row.message for row in status.quantity_blockers)
            raise ValueError(
                f"Источники {system} нельзя передать в расчёт: {messages}"
            )
        return tuple(row for row in self.sources if system in row.service_ports)


def _question_applies(question_id: str, system: str) -> bool:
    systems = _QUESTION_SYSTEMS.get(question_id)
    return system in systems if systems is not None else True


def build_engineering_handoff(
    topology: BuildingProgramTopology,
    *,
    basis_confirmed: bool,
) -> BuildingProgramHandoff:
    room_map = {row.room_id: row for row in topology.rooms}
    sources = tuple(
        EngineeringFixtureSource(
            fixture_id=fixture.fixture_id,
            archetype_id=fixture.archetype_id,
            room_id=fixture.room_id,
            level_id=room_map[fixture.room_id].level_id,
            section_id=room_map[fixture.room_id].section_id,
            sanitary_shaft_id=room_map[fixture.room_id].sanitary_shaft_id,
            service_ports=fixture.service_ports,
        )
        for fixture in topology.fixtures
    )
    statuses: list[SystemHandoffStatus] = []
    for system in SYSTEMS:
        system_sources = tuple(row for row in sources if system in row.service_ports)
        quantity_blockers: list[HandoffBlocker] = []
        if not basis_confirmed:
            quantity_blockers.append(HandoffBlocker(
                "basis.unconfirmed",
                "Типологическая основа не подтверждена проектировщиком.",
            ))
        if not system_sources:
            quantity_blockers.append(HandoffBlocker(
                "sources.empty",
                f"Модель не содержит подтверждённых источников {system}.",
            ))
        for question in topology.questions:
            if _question_applies(question.question_id, system):
                quantity_blockers.append(HandoffBlocker(
                    f"question.{question.question_id}",
                    question.prompt,
                ))
        scheme_blockers = list(quantity_blockers)
        scheme_blockers.append(HandoffBlocker(
            "architecture.geometry",
            "Нет подтверждённой геометрии и координат из планов АР.",
        ))
        statuses.append(SystemHandoffStatus(
            system=system,
            fixture_source_count=len(system_sources),
            quantities_ready=not quantity_blockers,
            scheme_ready=False,
            quantity_blockers=tuple(quantity_blockers),
            scheme_blockers=tuple(scheme_blockers),
        ))
    return BuildingProgramHandoff(
        basis_confirmed=basis_confirmed,
        systems=tuple(statuses),
        sources=sources,
    )


__all__ = [
    "BuildingProgramHandoff",
    "EngineeringFixtureSource",
    "HandoffBlocker",
    "SYSTEMS",
    "SystemHandoffStatus",
    "build_engineering_handoff",
]
