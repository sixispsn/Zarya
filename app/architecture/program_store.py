"""Persistent, checksum-verified drafts of typological building programmes."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import uuid

from app.architecture.residential_program import (
    BuildingProgramTopology,
    ResidentialProgramInput,
    build_residential_program,
)


_ID_RE = re.compile(r"^[a-f0-9]{10}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class BuildingProgramDraft:
    model_id: str
    title: str
    updated_at: str
    program_input: ResidentialProgramInput
    topology: BuildingProgramTopology
    topology_sha256: str
    basis_confirmed: bool
    confirmed_at: str | None
    confirmed_by: str
    confirmation_note: str


@dataclass(frozen=True)
class BuildingProgramDraftSummary:
    model_id: str
    title: str
    updated_at: str
    basis_confirmed: bool


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _topology_sha256(topology: BuildingProgramTopology) -> str:
    return sha256(_canonical_json(topology.to_dict()).encode("utf-8")).hexdigest()


def residential_input_to_dict(value: ResidentialProgramInput) -> dict[str, Any]:
    return asdict(value)


def _required_int(value: dict[str, Any], key: str) -> int:
    row = value.get(key)
    if isinstance(row, bool) or not isinstance(row, int):
        raise ValueError(f"invalid building programme input: {key}")
    return row


def _required_string(value: dict[str, Any], key: str) -> str:
    row = value.get(key)
    if not isinstance(row, str):
        raise ValueError(f"invalid building programme input: {key}")
    return row


def _optional_bool(value: dict[str, Any], key: str) -> bool | None:
    row = value.get(key)
    if row is not None and not isinstance(row, bool):
        raise ValueError(f"invalid building programme input: {key}")
    return row


def _pairs(
    value: dict[str, Any],
    key: str,
    first_type: type[int] | type[str],
    second_type: type[int] | type[float] | type[bool],
) -> tuple[tuple[Any, Any], ...]:
    rows = value.get(key, [])
    if not isinstance(rows, list):
        raise ValueError(f"invalid building programme input: {key}")
    result: list[tuple[Any, Any]] = []
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 2
            or (isinstance(row[0], bool) and first_type is int)
            or not isinstance(row[0], first_type)
            or isinstance(row[1], bool) != (second_type is bool)
            or not isinstance(row[1], second_type)
        ):
            raise ValueError(f"invalid building programme input: {key}")
        result.append((row[0], row[1]))
    return tuple(result)


def residential_input_from_dict(value: Any) -> ResidentialProgramInput:
    if not isinstance(value, dict):
        raise ValueError("invalid building programme input")
    return ResidentialProgramInput(
        floors_above=_required_int(value, "floors_above"),
        apartments_total=_required_int(value, "apartments_total"),
        source_ref=_required_string(value, "source_ref"),
        floors_below=_required_int(value, "floors_below"),
        sections_count=_required_int(value, "sections_count"),
        sanitary_shafts_per_section=_required_int(
            value,
            "sanitary_shafts_per_section",
        ),
        lift_shafts_per_section=_required_int(value, "lift_shafts_per_section"),
        apartments_by_floor=_pairs(value, "apartments_by_floor", int, int),
        floor_elevations_m=_pairs(value, "floor_elevations_m", int, float),
        apartment_sanitary_room_id=_required_string(
            value,
            "apartment_sanitary_room_id",
        ),
        fixture_condition_answers=_pairs(
            value,
            "fixture_condition_answers",
            str,
            bool,
        ),
        has_refuse_chamber=_optional_bool(value, "has_refuse_chamber"),
        has_underground_parking=_optional_bool(
            value,
            "has_underground_parking",
        ),
    )


class BuildingProgramStore:
    def __init__(self, root: str | Path | None = None):
        project_root = Path(
            os.environ.get(
                "ZARYA_PROJECTS_DIR",
                os.path.expanduser("~/.zarya/projects"),
            )
        )
        self.root = Path(root) if root is not None else project_root / "_building_models"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, model_id: str) -> Path:
        if not _ID_RE.fullmatch(model_id):
            raise ValueError("invalid building model id")
        return self.root / f"{model_id}.json"

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> None:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=self.root,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def save(
        self,
        program_input: ResidentialProgramInput,
        *,
        title: str,
        model_id: str | None = None,
    ) -> BuildingProgramDraft:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("Название модели не задано.")
        topology = build_residential_program(program_input)
        topology_hash = _topology_sha256(topology)
        resolved_id = model_id or uuid.uuid4().hex[:10]
        path = self._path(resolved_id)
        existing: dict[str, Any] = {}
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        unchanged = existing.get("topology_sha256") == topology_hash
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "model_id": resolved_id,
            "title": clean_title,
            "updated_at": stamp,
            "input": residential_input_to_dict(program_input),
            "topology": topology.to_dict(),
            "topology_sha256": topology_hash,
            "basis_confirmed": bool(existing.get("basis_confirmed")) and unchanged,
            "confirmed_at": existing.get("confirmed_at") if unchanged else None,
            "confirmed_by": existing.get("confirmed_by", "") if unchanged else "",
            "confirmation_note": (
                existing.get("confirmation_note", "") if unchanged else ""
            ),
        }
        self._atomic_write(path, payload)
        return self.load(resolved_id)

    def load(self, model_id: str) -> BuildingProgramDraft:
        path = self._path(model_id)
        if not path.is_file():
            raise FileNotFoundError("Модель здания не найдена.")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("Неподдерживаемая версия модели здания.")
        if value.get("model_id") != model_id:
            raise ValueError("Идентификатор модели здания повреждён.")
        program_input = residential_input_from_dict(value.get("input"))
        topology = build_residential_program(program_input)
        topology_hash = _topology_sha256(topology)
        stored_hash = value.get("topology_sha256")
        if not isinstance(stored_hash, str) or not _SHA256_RE.fullmatch(stored_hash):
            raise ValueError("Контрольная сумма модели здания повреждена.")
        if stored_hash != topology_hash or value.get("topology") != topology.to_dict():
            raise ValueError("Модель здания не прошла проверку целостности.")
        title = value.get("title")
        updated_at = value.get("updated_at")
        if not isinstance(title, str) or not isinstance(updated_at, str):
            raise ValueError("Метаданные модели здания повреждены.")
        basis_confirmed = value.get("basis_confirmed") is True
        confirmed_at = value.get("confirmed_at")
        confirmed_by = value.get("confirmed_by", "")
        confirmation_note = value.get("confirmation_note", "")
        if confirmed_at is not None and not isinstance(confirmed_at, str):
            raise ValueError("Метаданные подтверждения повреждены.")
        if not isinstance(confirmed_by, str) or not isinstance(confirmation_note, str):
            raise ValueError("Метаданные подтверждения повреждены.")
        return BuildingProgramDraft(
            model_id=model_id,
            title=title,
            updated_at=updated_at,
            program_input=program_input,
            topology=topology,
            topology_sha256=topology_hash,
            basis_confirmed=basis_confirmed,
            confirmed_at=confirmed_at,
            confirmed_by=confirmed_by,
            confirmation_note=confirmation_note,
        )

    def confirm_basis(
        self,
        model_id: str,
        *,
        expected_topology_sha256: str,
        confirmed_by: str,
        confirmation_note: str = "",
    ) -> BuildingProgramDraft:
        draft = self.load(model_id)
        if draft.topology_sha256 != expected_topology_sha256:
            raise ValueError("Модель изменилась; перед подтверждением обновите страницу.")
        clean_name = confirmed_by.strip()
        if not clean_name:
            raise ValueError("Укажите, кто подтвердил типологическую основу.")
        path = self._path(model_id)
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update({
            "basis_confirmed": True,
            "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "confirmed_by": clean_name,
            "confirmation_note": confirmation_note.strip(),
        })
        self._atomic_write(path, value)
        return self.load(model_id)

    def list(self) -> tuple[BuildingProgramDraftSummary, ...]:
        rows: list[BuildingProgramDraftSummary] = []
        for path in self.root.glob("*.json"):
            if not _ID_RE.fullmatch(path.stem):
                continue
            try:
                draft = self.load(path.stem)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            rows.append(BuildingProgramDraftSummary(
                model_id=draft.model_id,
                title=draft.title,
                updated_at=draft.updated_at,
                basis_confirmed=draft.basis_confirmed,
            ))
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return tuple(rows)


__all__ = [
    "BuildingProgramDraft",
    "BuildingProgramDraftSummary",
    "BuildingProgramStore",
    "residential_input_from_dict",
    "residential_input_to_dict",
]
