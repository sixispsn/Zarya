import json
import stat

import pytest

from app.architecture.engineering_handoff import build_engineering_handoff
from app.architecture.program_store import BuildingProgramStore
from app.architecture.residential_program import (
    ResidentialProgramInput,
    build_residential_program,
)


def _input(**changes) -> ResidentialProgramInput:
    values = {
        "floors_above": 3,
        "apartments_total": 6,
        "source_ref": "ТЗ: тест сохранения",
        "floors_below": 0,
        "sections_count": 1,
        "sanitary_shafts_per_section": 1,
        "lift_shafts_per_section": 1,
        "has_refuse_chamber": False,
        "has_underground_parking": False,
        "fixture_condition_answers": (
            ("apartment_has_washing_machine", False),
            ("apartment_has_dishwasher", False),
            ("refuse_chamber_has_drain", False),
        ),
    }
    values.update(changes)
    return ResidentialProgramInput(**values)


def test_programme_draft_is_atomic_private_and_checksum_verified(tmp_path):
    store = BuildingProgramStore(tmp_path / "models")
    draft = store.save(_input(), title="Корпус 1")

    path = tmp_path / "models" / f"{draft.model_id}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(".*.tmp"))
    loaded = store.load(draft.model_id)
    assert loaded.title == "Корпус 1"
    assert loaded.topology == draft.topology
    assert len(loaded.topology_sha256) == 64
    assert not loaded.basis_confirmed

    value = json.loads(path.read_text(encoding="utf-8"))
    value["topology"]["requested_apartments_total"] = 999
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="целостности"):
        store.load(draft.model_id)


def test_confirmation_is_bound_to_exact_topology_and_reset_after_change(tmp_path):
    store = BuildingProgramStore(tmp_path / "models")
    draft = store.save(_input(), title="Корпус 1")

    with pytest.raises(ValueError, match="изменилась"):
        store.confirm_basis(
            draft.model_id,
            expected_topology_sha256="0" * 64,
            confirmed_by="Иванов И.И.",
        )
    confirmed = store.confirm_basis(
        draft.model_id,
        expected_topology_sha256=draft.topology_sha256,
        confirmed_by="Иванов И.И.",
        confirmation_note="Сверено с заданием",
    )
    assert confirmed.basis_confirmed
    assert confirmed.confirmed_by == "Иванов И.И."
    assert confirmed.confirmed_at
    assert store.list()[0].basis_confirmed

    unchanged = store.save(_input(), title="Корпус 1А", model_id=draft.model_id)
    assert unchanged.basis_confirmed
    changed = store.save(
        _input(apartments_total=9),
        title="Корпус 1А",
        model_id=draft.model_id,
    )
    assert not changed.basis_confirmed
    assert changed.confirmed_at is None


def test_unconfirmed_programme_cannot_feed_any_system_adapter():
    topology = build_residential_program(_input())
    handoff = build_engineering_handoff(topology, basis_confirmed=False)

    assert all(not row.quantities_ready for row in handoff.systems)
    assert all(not row.scheme_ready for row in handoff.systems)
    with pytest.raises(ValueError, match="Типологическая основа"):
        handoff.sources_for_system("V1")


def test_confirmed_complete_apartment_basis_exposes_sources_but_not_geometry():
    topology = build_residential_program(_input())
    handoff = build_engineering_handoff(topology, basis_confirmed=True)

    assert handoff.status("V1").quantities_ready
    assert handoff.status("T3").quantities_ready
    assert handoff.status("K1").quantities_ready
    assert not handoff.status("K2").quantities_ready
    assert not handoff.status("V1").scheme_ready
    assert handoff.sources_for_system("V1")
    assert {
        row.level_id for row in handoff.sources_for_system("K1")
    } == {"F01", "F02", "F03"}
    assert "architecture.geometry" in {
        row.code for row in handoff.status("V1").scheme_blockers
    }


def test_open_optional_question_blocks_only_affected_quantity_adapters():
    topology = build_residential_program(_input(
        fixture_condition_answers=(
            ("apartment_has_dishwasher", False),
            ("refuse_chamber_has_drain", False),
        ),
    ))
    handoff = build_engineering_handoff(topology, basis_confirmed=True)

    assert not handoff.status("V1").quantities_ready
    assert not handoff.status("K1").quantities_ready
    assert handoff.status("T3").quantities_ready
    assert "question.apartment_has_washing_machine" in {
        row.code for row in handoff.status("V1").quantity_blockers
    }
