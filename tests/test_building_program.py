from dataclasses import replace
import json

import pytest

from app.architecture.catalog import (
    CATALOG_PATH,
    building_typology_catalog_from_mapping,
    load_building_typology_catalog,
)
from app.architecture.residential_program import (
    ProgramEvidence,
    ResidentialProgramInput,
    audit_building_program,
    build_residential_program,
)


def _input(**changes):
    values = {
        "floors_above": 9,
        "apartments_total": 36,
        "source_ref": "ТЗ: контрольный жилой дом",
        "floors_below": 1,
        "sections_count": 2,
        "sanitary_shafts_per_section": 2,
        "lift_shafts_per_section": 1,
        "has_refuse_chamber": True,
        "has_underground_parking": True,
    }
    values.update(changes)
    return ResidentialProgramInput(**values)


def test_catalog_separates_functional_ports_from_hydraulic_design():
    catalog = load_building_typology_catalog()

    assert catalog.catalog_id == "zarya.building-typologies.v1"
    assert catalog.fixture("toilet").service_ports == ("V1", "K1")
    assert catalog.fixture("washbasin").service_ports == ("V1", "T3", "K1")
    assert catalog.room("apartment_kitchen").requires_sanitary_shaft

    raw = CATALOG_PATH.read_text(encoding="utf-8").casefold()
    assert "diameter" not in raw
    assert "hydraulic" not in raw
    assert "slope" not in raw


def test_catalog_rejects_unknown_fixture_service_port():
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["fixtures"][0]["service_ports"].append("UNKNOWN")

    with pytest.raises(ValueError, match="unknown ports"):
        building_typology_catalog_from_mapping(data)


def test_residential_program_expands_every_floor_apartment_and_source():
    topology = build_residential_program(_input())

    assert len(topology.apartments) == 36
    assert [len(topology.rooms_for_floor(floor)) for floor in range(1, 10)] == [
        15,
        14,
        14,
        14,
        14,
        14,
        14,
        14,
        14,
    ]
    assert len(topology.sanitary_shafts) == 4
    assert len(topology.fixtures_for_system("V1")) == 144
    assert len(topology.fixtures_for_system("T3")) == 108
    assert len(topology.fixtures_for_system("K1")) == 144
    assert topology.fixtures_for_system("K2") == ()
    assert topology.requires_confirmation
    assert all(
        row.evidence == ProgramEvidence.TYPOLOGY_TEMPLATE
        for row in topology.fixtures
    )
    assert audit_building_program(topology) == ()


def test_apartments_are_assigned_only_to_a_shaft_serving_their_floor():
    topology = build_residential_program(_input())
    shaft_map = {row.shaft_id: row for row in topology.sanitary_shafts}

    for room in topology.rooms:
        if not room.requires_sanitary_shaft:
            continue
        shaft = shaft_map[room.sanitary_shaft_id]
        apartment = next(
            row for row in topology.apartments
            if row.apartment_id == room.apartment_id
        )
        assert shaft.section_id == room.section_id
        assert apartment.floor_number in shaft.served_floors


def test_uneven_automatic_distribution_is_deterministic_and_disclosed():
    topology = build_residential_program(_input(
        floors_above=3,
        apartments_total=10,
        floors_below=0,
        sections_count=1,
        sanitary_shafts_per_section=1,
        has_underground_parking=False,
    ))

    counts = [
        sum(row.floor_number == floor for row in topology.apartments)
        for floor in range(1, 4)
    ]
    assert counts == [4, 3, 3]
    assert "typology.apartment_distribution" in {
        row.code for row in topology.decisions
    }


def test_explicit_floor_distribution_can_leave_nonresidential_first_floor():
    topology = build_residential_program(_input(
        floors_above=3,
        apartments_total=10,
        apartments_by_floor=((1, 0), (2, 5), (3, 5)),
        floors_below=0,
        sections_count=1,
        sanitary_shafts_per_section=1,
        has_underground_parking=False,
    ))

    assert not any(row.floor_number == 1 for row in topology.apartments)
    assert "typology.apartment_distribution" not in {
        row.code for row in topology.decisions
    }

    with pytest.raises(ValueError, match="does not match"):
        build_residential_program(_input(
            apartments_by_floor=((1, 1),),
        ))


def test_optional_equipment_is_added_only_after_explicit_answer():
    without_optional = build_residential_program(_input())
    with_optional = build_residential_program(_input(
        fixture_condition_answers=(
            ("apartment_has_washing_machine", True),
            ("apartment_has_dishwasher", True),
            ("refuse_chamber_has_drain", True),
        ),
    ))

    assert not any(
        row.archetype_id in {"washing_machine", "dishwasher", "floor_drain"}
        for row in without_optional.fixtures
    )
    assert sum(
        row.archetype_id == "washing_machine"
        for row in with_optional.fixtures
    ) == 36
    assert sum(
        row.archetype_id == "dishwasher"
        for row in with_optional.fixtures
    ) == 36
    assert sum(
        row.archetype_id == "floor_drain"
        for row in with_optional.fixtures
    ) == 1

    with pytest.raises(ValueError, match="unknown fixture conditions"):
        build_residential_program(_input(
            fixture_condition_answers=(("misspelled_answer", True),),
        ))


def test_answered_optional_question_disappears_even_when_answer_is_no():
    topology = build_residential_program(_input(
        fixture_condition_answers=(("apartment_has_dishwasher", False),),
    ))

    assert "apartment_has_dishwasher" not in {
        row.question_id for row in topology.questions
    }
    assert not any(
        row.archetype_id == "dishwasher" for row in topology.fixtures
    )


def test_structural_audit_detects_fixture_detached_from_room():
    topology = build_residential_program(_input())
    fixture = replace(topology.fixtures[0], room_id="missing-room")
    broken = replace(topology, fixtures=(fixture,) + topology.fixtures[1:])

    assert "fixture.room" in {
        row.code for row in audit_building_program(broken)
    }


def test_serialized_program_keeps_evidence_and_service_ports():
    payload = build_residential_program(_input()).to_dict()

    assert payload["schema_version"] == "1.0"
    assert payload["rooms"][0]["evidence"] == "typology_template"
    assert payload["fixtures"][0]["service_ports"] == ["V1", "T3", "K1"]
