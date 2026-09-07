"""Versioned building, room and fixture archetype catalogue.

The catalogue describes a functional programme, not a measured architectural
plan.  It contains no pipe sizing, hydraulic formulae or invented geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping


CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "catalogs"
    / "building_typologies.v1.json"
)


@dataclass(frozen=True)
class FixtureArchetype:
    fixture_id: str
    label: str
    service_ports: tuple[str, ...]


@dataclass(frozen=True)
class FixtureSlot:
    fixture_id: str
    count: int
    required: bool
    condition_key: str = ""
    question: str = ""


@dataclass(frozen=True)
class RoomQuestion:
    question_id: str
    prompt: str


@dataclass(frozen=True)
class RoomArchetype:
    room_id: str
    label: str
    role: str
    requires_sanitary_shaft: bool
    fixture_slots: tuple[FixtureSlot, ...]
    questions: tuple[RoomQuestion, ...]


@dataclass(frozen=True)
class BuildingTypology:
    typology_id: str
    label: str
    apartment_rooms: tuple[str, ...]
    common_rooms_per_section: tuple[str, ...]
    optional_rooms: tuple[str, ...]


@dataclass(frozen=True)
class BuildingTypologyCatalog:
    schema_version: str
    catalog_id: str
    service_ports: tuple[str, ...]
    fixtures: tuple[FixtureArchetype, ...]
    rooms: tuple[RoomArchetype, ...]
    building_typologies: tuple[BuildingTypology, ...]

    def fixture(self, fixture_id: str) -> FixtureArchetype:
        try:
            return next(row for row in self.fixtures if row.fixture_id == fixture_id)
        except StopIteration as exc:
            raise KeyError(f"unknown fixture archetype: {fixture_id}") from exc

    def room(self, room_id: str) -> RoomArchetype:
        try:
            return next(row for row in self.rooms if row.room_id == room_id)
        except StopIteration as exc:
            raise KeyError(f"unknown room archetype: {room_id}") from exc

    def typology(self, typology_id: str) -> BuildingTypology:
        try:
            return next(
                row
                for row in self.building_typologies
                if row.typology_id == typology_id
            )
        except StopIteration as exc:
            raise KeyError(f"unknown building typology: {typology_id}") from exc


def _objects(value: Any, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(row, Mapping) for row in value
    ):
        raise ValueError(f"building catalogue: {field} must be a list of objects")
    return value


def _unique(values: list[str], owner: str) -> None:
    if any(not value.strip() for value in values):
        raise ValueError(f"building catalogue: {owner} contains an empty id")
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(
            f"building catalogue: duplicate {owner}: {', '.join(duplicates)}"
        )


def building_typology_catalog_from_mapping(
    data: Mapping[str, Any],
) -> BuildingTypologyCatalog:
    """Parse and cross-check the strict versioned catalogue."""
    schema_version = str(data.get("schema_version", ""))
    catalog_id = str(data.get("catalog_id", ""))
    if schema_version != "1.0" or not catalog_id.strip():
        raise ValueError("building catalogue: unsupported schema or missing catalog id")

    raw_ports = data.get("service_ports")
    if not isinstance(raw_ports, list) or not all(
        isinstance(row, str) and row.strip() for row in raw_ports
    ):
        raise ValueError("building catalogue: service_ports must be non-empty strings")
    service_ports = tuple(raw_ports)
    _unique(list(service_ports), "service ports")

    fixtures = tuple(
        FixtureArchetype(
            fixture_id=str(row.get("id", "")),
            label=str(row.get("label", "")),
            service_ports=tuple(str(value) for value in row.get("service_ports", [])),
        )
        for row in _objects(data.get("fixtures"), "fixtures")
    )
    _unique([row.fixture_id for row in fixtures], "fixture ids")
    for fixture in fixtures:
        if not fixture.label.strip() or not fixture.service_ports:
            raise ValueError(
                f"building catalogue: fixture {fixture.fixture_id} is incomplete"
            )
        unknown = sorted(set(fixture.service_ports) - set(service_ports))
        if unknown:
            raise ValueError(
                f"building catalogue: fixture {fixture.fixture_id} has unknown ports: "
                + ", ".join(unknown)
            )

    rooms: list[RoomArchetype] = []
    for row in _objects(data.get("rooms"), "rooms"):
        slots = tuple(
            FixtureSlot(
                fixture_id=str(slot.get("fixture_id", "")),
                count=int(slot.get("count", 0)),
                required=bool(slot.get("required", False)),
                condition_key=str(slot.get("condition_key", "")),
                question=str(slot.get("question", "")),
            )
            for slot in _objects(row.get("fixture_slots", []), "fixture_slots")
        )
        room = RoomArchetype(
            room_id=str(row.get("id", "")),
            label=str(row.get("label", "")),
            role=str(row.get("role", "")),
            requires_sanitary_shaft=bool(
                row.get("requires_sanitary_shaft", False)
            ),
            fixture_slots=slots,
            questions=tuple(
                RoomQuestion(
                    question_id=str(question.get("id", "")),
                    prompt=str(question.get("prompt", "")),
                )
                for question in _objects(row.get("questions", []), "questions")
            ),
        )
        rooms.append(room)
    _unique([row.room_id for row in rooms], "room ids")
    fixture_ids = {row.fixture_id for row in fixtures}
    for room in rooms:
        if not room.label.strip() or not room.role.strip():
            raise ValueError(f"building catalogue: room {room.room_id} is incomplete")
        for slot in room.fixture_slots:
            if slot.fixture_id not in fixture_ids or slot.count < 1:
                raise ValueError(
                    f"building catalogue: invalid fixture slot in {room.room_id}"
                )
            if not slot.required and not slot.condition_key.strip():
                raise ValueError(
                    f"building catalogue: optional fixture in {room.room_id} "
                    "must have a condition key"
                )
            if not slot.required and not slot.question.strip():
                raise ValueError(
                    f"building catalogue: optional fixture in {room.room_id} "
                    "must have a question"
                )
        question_ids = [row.question_id for row in room.questions]
        _unique(question_ids, f"question ids in {room.room_id}")
        if any(not row.prompt.strip() for row in room.questions):
            raise ValueError(
                f"building catalogue: room {room.room_id} has an empty question"
            )

    typologies = tuple(
        BuildingTypology(
            typology_id=str(row.get("id", "")),
            label=str(row.get("label", "")),
            apartment_rooms=tuple(str(value) for value in row.get("apartment_rooms", [])),
            common_rooms_per_section=tuple(
                str(value) for value in row.get("common_rooms_per_section", [])
            ),
            optional_rooms=tuple(str(value) for value in row.get("optional_rooms", [])),
        )
        for row in _objects(data.get("building_typologies"), "building_typologies")
    )
    _unique([row.typology_id for row in typologies], "typology ids")
    room_ids = {row.room_id for row in rooms}
    for typology in typologies:
        referenced = (
            typology.apartment_rooms
            + typology.common_rooms_per_section
            + typology.optional_rooms
        )
        unknown = sorted(set(referenced) - room_ids)
        if not typology.label.strip() or not typology.apartment_rooms or unknown:
            raise ValueError(
                f"building catalogue: typology {typology.typology_id} is incomplete"
                + (f"; unknown rooms: {', '.join(unknown)}" if unknown else "")
            )
    return BuildingTypologyCatalog(
        schema_version=schema_version,
        catalog_id=catalog_id,
        service_ports=service_ports,
        fixtures=fixtures,
        rooms=tuple(rooms),
        building_typologies=typologies,
    )


@lru_cache(maxsize=1)
def load_building_typology_catalog() -> BuildingTypologyCatalog:
    with CATALOG_PATH.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, Mapping):
        raise ValueError("building catalogue root must be an object")
    return building_typology_catalog_from_mapping(data)


__all__ = [
    "BuildingTypology",
    "BuildingTypologyCatalog",
    "FixtureArchetype",
    "FixtureSlot",
    "RoomArchetype",
    "building_typology_catalog_from_mapping",
    "load_building_typology_catalog",
]
