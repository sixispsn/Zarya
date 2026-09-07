"""Draft functional topology for a multi-apartment residential building.

This module expands confirmed counts into a deterministic *typological*
programme.  It never claims to be a measured architectural plan.  Every
template-derived room, fixture and shaft assignment remains explicitly marked
for confirmation until it is replaced by imported/confirmed AR data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from typing import Any, Iterable, cast

from app.architecture.catalog import (
    BuildingTypologyCatalog,
    RoomArchetype,
    load_building_typology_catalog,
)


class ProgramEvidence(str, Enum):
    USER_INPUT = "user_input"
    TYPOLOGY_TEMPLATE = "typology_template"


@dataclass(frozen=True)
class ResidentialProgramInput:
    floors_above: int
    apartments_total: int
    source_ref: str
    floors_below: int = 0
    sections_count: int = 1
    sanitary_shafts_per_section: int = 1
    lift_shafts_per_section: int = 1
    apartments_by_floor: tuple[tuple[int, int], ...] = ()
    floor_elevations_m: tuple[tuple[int, float], ...] = ()
    apartment_sanitary_room_id: str = "apartment_sanitary_unit_shower"
    fixture_condition_answers: tuple[tuple[str, bool], ...] = ()
    has_refuse_chamber: bool | None = None
    has_underground_parking: bool | None = None


@dataclass(frozen=True)
class ProgramDecision:
    code: str
    message: str
    requires_confirmation: bool = True


@dataclass(frozen=True)
class ProgramIssue:
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class ProgramQuestion:
    question_id: str
    prompt: str
    related_archetype_id: str


@dataclass(frozen=True)
class BuildingLevel:
    level_id: str
    floor_number: int | None
    role: str
    elevation_m: float | None
    evidence: ProgramEvidence


@dataclass(frozen=True)
class BuildingSection:
    section_id: str
    label: str
    evidence: ProgramEvidence


@dataclass(frozen=True)
class SanitaryShaft:
    shaft_id: str
    section_id: str
    served_floors: tuple[int, ...]
    evidence: ProgramEvidence


@dataclass(frozen=True)
class ApartmentUnit:
    apartment_id: str
    floor_number: int
    section_id: str
    room_ids: tuple[str, ...]
    evidence: ProgramEvidence


@dataclass(frozen=True)
class ProgramRoom:
    room_id: str
    archetype_id: str
    label: str
    role: str
    level_id: str
    section_id: str | None
    apartment_id: str | None
    sanitary_shaft_id: str | None
    requires_sanitary_shaft: bool
    evidence: ProgramEvidence


@dataclass(frozen=True)
class ProgramFixture:
    fixture_id: str
    archetype_id: str
    label: str
    room_id: str
    service_ports: tuple[str, ...]
    evidence: ProgramEvidence


@dataclass(frozen=True)
class BuildingProgramTopology:
    schema_version: str
    catalogue_id: str
    typology_id: str
    source_ref: str
    requested_apartments_total: int
    levels: tuple[BuildingLevel, ...]
    sections: tuple[BuildingSection, ...]
    sanitary_shafts: tuple[SanitaryShaft, ...]
    apartments: tuple[ApartmentUnit, ...]
    rooms: tuple[ProgramRoom, ...]
    fixtures: tuple[ProgramFixture, ...]
    decisions: tuple[ProgramDecision, ...]
    questions: tuple[ProgramQuestion, ...]

    @property
    def requires_confirmation(self) -> bool:
        return any(row.requires_confirmation for row in self.decisions)

    def fixtures_for_system(self, system: str) -> tuple[ProgramFixture, ...]:
        return tuple(row for row in self.fixtures if system in row.service_ports)

    def rooms_for_floor(self, floor_number: int) -> tuple[ProgramRoom, ...]:
        level_ids = {
            row.level_id
            for row in self.levels
            if row.floor_number == floor_number
        }
        return tuple(row for row in self.rooms if row.level_id in level_ids)

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _json_value(asdict(self)))


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(row) for key, row in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(row) for row in value]
    return value


def _floor_id(floor_number: int) -> str:
    return f"F{floor_number:02d}" if floor_number >= 0 else f"B{abs(floor_number):02d}"


def _balanced_counts(total: int, buckets: int) -> tuple[int, ...]:
    base, remainder = divmod(total, buckets)
    return tuple(base + (1 if index < remainder else 0) for index in range(buckets))


def _apartment_counts(
    value: ResidentialProgramInput,
) -> tuple[tuple[int, int], ...]:
    if value.apartments_by_floor:
        rows = tuple((int(floor), int(count)) for floor, count in value.apartments_by_floor)
        floors = [floor for floor, _ in rows]
        if len(set(floors)) != len(floors):
            raise ValueError("apartments_by_floor contains duplicate floors")
        if any(floor < 1 or floor > value.floors_above for floor in floors):
            raise ValueError("apartments_by_floor contains an unknown floor")
        if any(count < 0 for _, count in rows):
            raise ValueError("apartments_by_floor contains a negative count")
        if sum(count for _, count in rows) != value.apartments_total:
            raise ValueError("apartments_by_floor does not match apartments_total")
        by_floor = dict(rows)
        return tuple(
            (floor, by_floor.get(floor, 0))
            for floor in range(1, value.floors_above + 1)
        )
    counts = _balanced_counts(value.apartments_total, value.floors_above)
    return tuple(enumerate(counts, start=1))


def _validate_input(
    value: ResidentialProgramInput,
    catalog: BuildingTypologyCatalog,
) -> None:
    if value.floors_above < 1:
        raise ValueError("floors_above must be positive")
    if value.floors_below < 0:
        raise ValueError("floors_below cannot be negative")
    if value.apartments_total < 1:
        raise ValueError("apartments_total must be positive")
    if value.sections_count < 1:
        raise ValueError("sections_count must be positive")
    if value.sanitary_shafts_per_section < 1:
        raise ValueError("sanitary_shafts_per_section must be positive")
    if value.lift_shafts_per_section < 0:
        raise ValueError("lift_shafts_per_section cannot be negative")
    if not value.source_ref.strip():
        raise ValueError("source_ref is required")
    if value.has_underground_parking is True and value.floors_below < 1:
        raise ValueError("underground parking requires at least one floor below")
    catalog.room(value.apartment_sanitary_room_id)
    known_conditions = {
        slot.condition_key
        for room in catalog.rooms
        for slot in room.fixture_slots
        if slot.condition_key
    }
    unknown_conditions = sorted(
        {key for key, _ in value.fixture_condition_answers} - known_conditions
    )
    if unknown_conditions:
        raise ValueError(
            "unknown fixture conditions: " + ", ".join(unknown_conditions)
        )
    answer_keys = [key for key, _ in value.fixture_condition_answers]
    if len(answer_keys) != len(set(answer_keys)):
        raise ValueError("fixture_condition_answers contains duplicate keys")
    elevations = dict(value.floor_elevations_m)
    if len(elevations) != len(value.floor_elevations_m):
        raise ValueError("floor_elevations_m contains duplicate floors")
    known_floors = set(range(-value.floors_below, value.floors_above + 1))
    known_floors.discard(0)
    if set(elevations) - known_floors:
        raise ValueError("floor_elevations_m contains an unknown floor")
    if not all(isfinite(float(row)) for row in elevations.values()):
        raise ValueError("floor_elevations_m must contain finite values")
    _apartment_counts(value)


def _required_fixtures(
    room: RoomArchetype,
    enabled_conditions: set[str],
) -> Iterable[tuple[str, int]]:
    for slot in room.fixture_slots:
        if slot.required or slot.condition_key in enabled_conditions:
            yield slot.fixture_id, slot.count


def build_residential_program(
    value: ResidentialProgramInput,
    *,
    catalog: BuildingTypologyCatalog | None = None,
) -> BuildingProgramTopology:
    """Expand a residential typology without pretending it is confirmed AR."""
    catalog = catalog or load_building_typology_catalog()
    _validate_input(value, catalog)
    typology = catalog.typology("residential_multi_apartment")
    apartment_room_ids = (
        "apartment_kitchen",
        value.apartment_sanitary_room_id,
    )
    if not set(apartment_room_ids).issubset(set(typology.apartment_rooms) | {
        "apartment_sanitary_unit_bath",
    }):
        raise ValueError("selected apartment rooms are outside residential typology")

    elevations = dict(value.floor_elevations_m)
    levels = [
        BuildingLevel(
            level_id=_floor_id(floor),
            floor_number=floor,
            role="underground" if floor < 0 else "residential",
            elevation_m=elevations.get(floor),
            evidence=ProgramEvidence.USER_INPUT,
        )
        for floor in range(-value.floors_below, value.floors_above + 1)
        if floor != 0
    ]
    levels.append(BuildingLevel(
        level_id="ROOF",
        floor_number=None,
        role="roof",
        elevation_m=None,
        evidence=ProgramEvidence.TYPOLOGY_TEMPLATE,
    ))
    sections = tuple(
        BuildingSection(
            section_id=f"S{number:02d}",
            label=f"Секция {number}",
            evidence=ProgramEvidence.USER_INPUT,
        )
        for number in range(1, value.sections_count + 1)
    )
    served_floors = tuple(range(1, value.floors_above + 1))
    shafts = tuple(
        SanitaryShaft(
            shaft_id=f"{section.section_id}-VK{number:02d}",
            section_id=section.section_id,
            served_floors=served_floors,
            evidence=ProgramEvidence.TYPOLOGY_TEMPLATE,
        )
        for section in sections
        for number in range(1, value.sanitary_shafts_per_section + 1)
    )
    shafts_by_section = {
        section.section_id: tuple(
            row for row in shafts if row.section_id == section.section_id
        )
        for section in sections
    }

    apartments: list[ApartmentUnit] = []
    rooms: list[ProgramRoom] = []
    fixtures: list[ProgramFixture] = []
    condition_answers = dict(value.fixture_condition_answers)
    enabled_conditions = {
        key for key, answer in condition_answers.items() if answer
    }
    apartment_counter = 0

    def add_room(
        *,
        room_id: str,
        archetype_id: str,
        level_id: str,
        section_id: str | None = None,
        apartment_id: str | None = None,
        sanitary_shaft_id: str | None = None,
    ) -> None:
        archetype = catalog.room(archetype_id)
        rooms.append(ProgramRoom(
            room_id=room_id,
            archetype_id=archetype.room_id,
            label=archetype.label,
            role=archetype.role,
            level_id=level_id,
            section_id=section_id,
            apartment_id=apartment_id,
            sanitary_shaft_id=sanitary_shaft_id,
            requires_sanitary_shaft=archetype.requires_sanitary_shaft,
            evidence=ProgramEvidence.TYPOLOGY_TEMPLATE,
        ))
        for fixture_archetype_id, count in _required_fixtures(
            archetype, enabled_conditions,
        ):
            fixture_archetype = catalog.fixture(fixture_archetype_id)
            for fixture_no in range(1, count + 1):
                fixtures.append(ProgramFixture(
                    fixture_id=f"{room_id}-{fixture_archetype_id}-{fixture_no:02d}",
                    archetype_id=fixture_archetype.fixture_id,
                    label=fixture_archetype.label,
                    room_id=room_id,
                    service_ports=fixture_archetype.service_ports,
                    evidence=ProgramEvidence.TYPOLOGY_TEMPLATE,
                ))

    for floor, apartment_count in _apartment_counts(value):
        level_id = _floor_id(floor)
        per_section = _balanced_counts(apartment_count, value.sections_count)
        for section, count in zip(sections, per_section):
            section_prefix = f"{level_id}-{section.section_id}"
            for archetype_id in typology.common_rooms_per_section:
                add_room(
                    room_id=f"{section_prefix}-{archetype_id}",
                    archetype_id=archetype_id,
                    level_id=level_id,
                    section_id=section.section_id,
                )
            for lift_no in range(1, value.lift_shafts_per_section + 1):
                add_room(
                    room_id=f"{section_prefix}-lift-{lift_no:02d}",
                    archetype_id="lift_shaft",
                    level_id=level_id,
                    section_id=section.section_id,
                )
            for local_index in range(count):
                apartment_counter += 1
                apartment_id = f"A{apartment_counter:04d}"
                section_shafts = shafts_by_section[section.section_id]
                shaft = section_shafts[local_index % len(section_shafts)]
                apartment_room_instance_ids: list[str] = []
                for archetype_id in apartment_room_ids:
                    room_id = f"{level_id}-{section.section_id}-{apartment_id}-{archetype_id}"
                    apartment_room_instance_ids.append(room_id)
                    add_room(
                        room_id=room_id,
                        archetype_id=archetype_id,
                        level_id=level_id,
                        section_id=section.section_id,
                        apartment_id=apartment_id,
                        sanitary_shaft_id=shaft.shaft_id,
                    )
                apartments.append(ApartmentUnit(
                    apartment_id=apartment_id,
                    floor_number=floor,
                    section_id=section.section_id,
                    room_ids=tuple(apartment_room_instance_ids),
                    evidence=ProgramEvidence.TYPOLOGY_TEMPLATE,
                ))

    if value.has_refuse_chamber is True:
        add_room(
            room_id="F01-refuse-chamber",
            archetype_id="refuse_chamber",
            level_id="F01",
            section_id=sections[0].section_id,
        )
    for floor in range(-value.floors_below, 0):
        level_id = _floor_id(floor)
        add_room(
            room_id=f"{level_id}-technical-basement",
            archetype_id="technical_basement",
            level_id=level_id,
        )
        if value.has_underground_parking is True:
            add_room(
                room_id=f"{level_id}-underground-parking",
                archetype_id="underground_parking",
                level_id=level_id,
            )
    add_room(room_id="ROOF-roof", archetype_id="roof", level_id="ROOF")

    decisions = [
        ProgramDecision(
            "typology.rooms",
            "Состав помещений создан по типологии и требует подтверждения по АР.",
        ),
        ProgramDecision(
            "typology.fixtures",
            "Состав приборов квартиры создан по профилю и требует подтверждения.",
        ),
        ProgramDecision(
            "typology.shaft_assignment",
            "Привязка квартир к сантехническим шахтам условная до получения планов.",
        ),
        ProgramDecision(
            "architecture.geometry",
            "Геометрия помещений отсутствует; разрешена только принципиальная топология.",
        ),
    ]
    if not value.apartments_by_floor:
        decisions.append(ProgramDecision(
            "typology.apartment_distribution",
            "Квартиры распределены по этажам равномерно и требуют подтверждения.",
        ))
    if value.has_refuse_chamber is None:
        decisions.append(ProgramDecision(
            "question.refuse_chamber",
            "Наличие мусорокамеры не подтверждено.",
        ))
    if value.has_underground_parking is None:
        decisions.append(ProgramDecision(
            "question.underground_parking",
            "Наличие подземного паркинга не подтверждено.",
        ))

    included_archetypes = {row.archetype_id for row in rooms}
    question_rows = [
        ProgramQuestion(
            question_id=question.question_id,
            prompt=question.prompt,
            related_archetype_id=archetype_id,
        )
        for archetype_id in sorted(included_archetypes)
        for question in catalog.room(archetype_id).questions
    ]
    for archetype_id in sorted(included_archetypes):
        for slot in catalog.room(archetype_id).fixture_slots:
            if (
                not slot.required
                and slot.condition_key not in condition_answers
            ):
                question_rows.append(ProgramQuestion(
                    question_id=slot.condition_key,
                    prompt=slot.question,
                    related_archetype_id=archetype_id,
                ))
    if value.has_refuse_chamber is None:
        question_rows.append(ProgramQuestion(
            question_id="has_refuse_chamber",
            prompt="Есть ли мусорокамера?",
            related_archetype_id="refuse_chamber",
        ))
    if value.has_underground_parking is None:
        question_rows.append(ProgramQuestion(
            question_id="has_underground_parking",
            prompt="Есть ли подземный паркинг?",
            related_archetype_id="underground_parking",
        ))
    questions = tuple({row.question_id: row for row in question_rows}.values())
    topology = BuildingProgramTopology(
        schema_version="1.0",
        catalogue_id=catalog.catalog_id,
        typology_id=typology.typology_id,
        source_ref=value.source_ref,
        requested_apartments_total=value.apartments_total,
        levels=tuple(levels),
        sections=sections,
        sanitary_shafts=shafts,
        apartments=tuple(apartments),
        rooms=tuple(rooms),
        fixtures=tuple(fixtures),
        decisions=tuple(decisions),
        questions=questions,
    )
    issues = audit_building_program(topology, catalog=catalog)
    if issues:
        raise RuntimeError(
            "generated building programme is invalid: "
            + "; ".join(row.message for row in issues)
        )
    return topology


def audit_building_program(
    topology: BuildingProgramTopology,
    *,
    catalog: BuildingTypologyCatalog | None = None,
) -> tuple[ProgramIssue, ...]:
    """Check structural integrity before a system engine consumes the model."""
    catalog = catalog or load_building_typology_catalog()
    issues: list[ProgramIssue] = []

    def add(code: str, message: str) -> None:
        issues.append(ProgramIssue(code, message))

    def duplicates(values: Iterable[str], owner: str) -> None:
        rows = list(values)
        for value in sorted({row for row in rows if rows.count(row) > 1}):
            add(f"{owner}.duplicate", f"Повторяется идентификатор {value}.")

    duplicates((row.level_id for row in topology.levels), "level")
    duplicates((row.section_id for row in topology.sections), "section")
    duplicates((row.shaft_id for row in topology.sanitary_shafts), "shaft")
    duplicates((row.apartment_id for row in topology.apartments), "apartment")
    duplicates((row.room_id for row in topology.rooms), "room")
    duplicates((row.fixture_id for row in topology.fixtures), "fixture")

    level_ids = {row.level_id for row in topology.levels}
    floor_rows = [
        row.floor_number
        for row in topology.levels
        if row.floor_number is not None
    ]
    if len(floor_rows) != len(set(floor_rows)):
        add("level.floor_duplicate", "Номера этажей повторяются.")
    floor_numbers = {
        row for row in floor_rows
    }
    section_ids = {row.section_id for row in topology.sections}
    shaft_map = {row.shaft_id: row for row in topology.sanitary_shafts}
    apartment_map = {row.apartment_id: row for row in topology.apartments}
    room_map = {row.room_id: row for row in topology.rooms}
    known_ports = set(catalog.service_ports)
    known_room_archetypes = {row.room_id for row in catalog.rooms}
    known_fixture_archetypes = {row.fixture_id for row in catalog.fixtures}

    if len(topology.apartments) != topology.requested_apartments_total:
        add("apartment.count", "Число квартир не совпадает с исходным заданием.")
    for shaft in topology.sanitary_shafts:
        if shaft.section_id not in section_ids:
            add("shaft.section", f"{shaft.shaft_id}: неизвестная секция.")
        if not set(shaft.served_floors).issubset(floor_numbers):
            add("shaft.floor", f"{shaft.shaft_id}: неизвестный обслуживаемый этаж.")
    for apartment in topology.apartments:
        if apartment.floor_number not in floor_numbers:
            add("apartment.floor", f"{apartment.apartment_id}: неизвестный этаж.")
        if apartment.section_id not in section_ids:
            add("apartment.section", f"{apartment.apartment_id}: неизвестная секция.")
        if not apartment.room_ids:
            add("apartment.rooms", f"{apartment.apartment_id}: нет помещений.")
        for room_id in apartment.room_ids:
            room = room_map.get(room_id)
            if room is None or room.apartment_id != apartment.apartment_id:
                add(
                    "apartment.room_link",
                    f"{apartment.apartment_id}: нарушена связь с {room_id}.",
                )
        apartment_fixtures = tuple(
            fixture
            for fixture in topology.fixtures
            if fixture.room_id in apartment.room_ids
        )
        for required_port in ("V1", "K1"):
            if not any(required_port in row.service_ports for row in apartment_fixtures):
                add(
                    "apartment.service_source",
                    f"{apartment.apartment_id}: нет источника {required_port}.",
                )
    for room in topology.rooms:
        if room.archetype_id not in known_room_archetypes:
            add("room.archetype", f"{room.room_id}: неизвестный тип помещения.")
        if room.level_id not in level_ids:
            add("room.level", f"{room.room_id}: неизвестный уровень.")
        if room.section_id is not None and room.section_id not in section_ids:
            add("room.section", f"{room.room_id}: неизвестная секция.")
        if room.apartment_id is not None and room.apartment_id not in apartment_map:
            add("room.apartment", f"{room.room_id}: неизвестная квартира.")
        if room.requires_sanitary_shaft:
            resolved_shaft = shaft_map.get(room.sanitary_shaft_id or "")
            level = next(
                (row for row in topology.levels if row.level_id == room.level_id),
                None,
            )
            if resolved_shaft is None:
                add("room.shaft", f"{room.room_id}: нет сантехнической шахты.")
            elif (
                room.section_id != resolved_shaft.section_id
                or level is None
                or level.floor_number not in resolved_shaft.served_floors
            ):
                add("room.shaft_link", f"{room.room_id}: шахта не обслуживает помещение.")
    for fixture in topology.fixtures:
        if fixture.archetype_id not in known_fixture_archetypes:
            add("fixture.archetype", f"{fixture.fixture_id}: неизвестный тип прибора.")
        if fixture.room_id not in room_map:
            add("fixture.room", f"{fixture.fixture_id}: неизвестное помещение.")
        if not fixture.service_ports or set(fixture.service_ports) - known_ports:
            add("fixture.ports", f"{fixture.fixture_id}: неверные инженерные порты.")
    return tuple(issues)


__all__ = [
    "ApartmentUnit",
    "BuildingLevel",
    "BuildingProgramTopology",
    "BuildingSection",
    "ProgramDecision",
    "ProgramEvidence",
    "ProgramFixture",
    "ProgramIssue",
    "ProgramQuestion",
    "ProgramRoom",
    "ResidentialProgramInput",
    "SanitaryShaft",
    "audit_building_program",
    "build_residential_program",
]
