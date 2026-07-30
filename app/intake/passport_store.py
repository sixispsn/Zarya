"""Неизменяемое файловое хранилище цифровых паспортов выпуска.

Каждый паспорт содержит манифест, доказательный граф и копии фактически
выпущенных PDF. Хранилище располагается внутри постоянного тома проектов,
поэтому ссылки переживают перезапуск приложения и обновление контейнера.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from app.pz.project import Project


_PROJECTS_ROOT = os.environ.get(
    "ZARYA_PROJECTS_DIR",
    os.path.expanduser("~/.zarya/projects"),
)
DEFAULT_ROOT = os.environ.get(
    "ZARYA_PASSPORTS_DIR",
    os.path.join(_PROJECTS_ROOT, "_passports"),
)
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")


class PassportNotFoundError(FileNotFoundError):
    pass


class PassportIntegrityError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _seal(manifest_without_seal: dict) -> str:
    return hashlib.sha256(_canonical_bytes(manifest_without_seal)).hexdigest()


class PassportStore:
    """Append-only хранилище: опубликованный паспорт не перезаписывается."""

    def __init__(self, root: str = DEFAULT_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _passport_dir(self, passport_id: str) -> Path:
        if not _ID_RE.fullmatch(passport_id or ""):
            raise ValueError("некорректный идентификатор паспорта")
        return self.root / passport_id

    def publish(
        self,
        *,
        passport_id: str,
        canonical_url: str,
        project_id: str | None,
        project: Project,
        commission,
        defense_payload: dict,
        documents: list[dict],
        outdir: str,
    ) -> dict:
        """Атомарно сохранить снимок выпуска и вернуть запечатанный манифест."""
        destination = self._passport_dir(passport_id)
        if destination.exists():
            raise FileExistsError("цифровой паспорт уже опубликован")
        temporary = Path(tempfile.mkdtemp(
            prefix=f".{passport_id}-",
            dir=str(self.root),
        ))
        try:
            documents_dir = temporary / "documents"
            documents_dir.mkdir()
            stored_documents = []
            by_name = {}
            for document in documents:
                name = os.path.basename(document["name"])
                if name != document["name"]:
                    raise ValueError("некорректное имя документа")
                source = Path(outdir) / name
                if not source.is_file():
                    raise FileNotFoundError(f"документ выпуска не найден: {name}")
                target = documents_dir / name
                shutil.copy2(source, target)
                record = {
                    "group": document["group"],
                    "label": document["label"],
                    "stored_name": name,
                    "sha256": _sha256(target),
                    "size_bytes": target.stat().st_size,
                    "url": f"{canonical_url}/file/{name}",
                }
                stored_documents.append(record)
                by_name[name] = record

            proof = copy.deepcopy(defense_payload)
            for decision in proof.get("decisions", []):
                for evidence in decision.get("documents", []):
                    stored = by_name.get(evidence.get("name"))
                    if stored is None:
                        continue
                    evidence["view_url"] = stored["url"]
                    evidence["download_url"] = stored["url"]

            purpose = getattr(
                project.building.purpose,
                "value",
                project.building.purpose,
            )
            manifest = {
                "schema_version": "1.0",
                "passport_id": passport_id,
                "canonical_url": canonical_url,
                "created_at": commission.generated_at,
                "project_id": project_id or "",
                "project": {
                    "title": project.document.object_name or "Комплект без реквизитов",
                    "cipher": project.document.cipher or "",
                    "stage": project.document.stage_label,
                    "purpose": str(purpose),
                    "floors": project.building.floors_above,
                    "height_m": project.building.height_m,
                    "fire_height_m": project.building.fire_height_m,
                    "systems": [
                        system for system, enabled in (
                            ("В1", True),
                            ("В2", project.fire.required),
                            ("Т3", project.building.hws_type.value != "none"),
                            ("Т4", project.building.hws_type.value != "none"),
                            ("К1", True),
                            ("К2", project.storm.roof_type != "not_set"),
                        ) if enabled
                    ],
                },
                "release": {
                    "status": commission.release_status,
                    "blocking_count": commission.blocking_count,
                    "pending_r_count": commission.pending_r_count,
                },
                "fingerprints": {
                    "project": commission.project_fingerprint,
                    "legacy": commission.legacy_fingerprint,
                    "build_commit": commission.build_commit,
                },
                "proof": proof,
                "documents": stored_documents,
            }
            manifest["seal_sha256"] = _seal(manifest)
            manifest_path = temporary / "manifest.json"
            with manifest_path.open("w", encoding="utf-8") as stream:
                json.dump(
                    manifest,
                    stream,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                stream.write("\n")
            os.replace(temporary, destination)
            return manifest
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def load(self, passport_id: str) -> dict:
        directory = self._passport_dir(passport_id)
        path = directory / "manifest.json"
        if not path.is_file():
            raise PassportNotFoundError("цифровой паспорт не найден")
        try:
            with path.open(encoding="utf-8") as stream:
                manifest = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise PassportIntegrityError("манифест паспорта повреждён") from exc
        if manifest.get("passport_id") != passport_id:
            raise PassportIntegrityError("идентификатор манифеста не совпадает")
        return manifest

    def verify(self, passport_id: str) -> dict:
        manifest = self.load(passport_id)
        expected_seal = manifest.get("seal_sha256", "")
        unsigned = dict(manifest)
        unsigned.pop("seal_sha256", None)
        actual_seal = _seal(unsigned)
        document_checks = []
        for document in manifest.get("documents", []):
            name = os.path.basename(document.get("stored_name", ""))
            path = self._passport_dir(passport_id) / "documents" / name
            exists = bool(name) and path.is_file()
            actual = _sha256(path) if exists else ""
            document_checks.append({
                "name": name,
                "label": document.get("label", name),
                "expected_sha256": document.get("sha256", ""),
                "actual_sha256": actual,
                "valid": exists and actual == document.get("sha256"),
            })
        manifest_valid = bool(expected_seal) and expected_seal == actual_seal
        documents_valid = all(
            row["valid"] for row in document_checks
        ) and bool(document_checks)
        return {
            "valid": manifest_valid and documents_valid,
            "manifest_valid": manifest_valid,
            "documents_valid": documents_valid,
            "seal_sha256": expected_seal,
            "documents": document_checks,
        }

    def document(self, passport_id: str, name: str) -> tuple[Path, dict]:
        if os.path.basename(name) != name:
            raise PassportNotFoundError("документ не найден")
        manifest = self.load(passport_id)
        expected_seal = manifest.get("seal_sha256", "")
        unsigned = dict(manifest)
        unsigned.pop("seal_sha256", None)
        if not expected_seal or _seal(unsigned) != expected_seal:
            raise PassportIntegrityError(
                "контрольная сумма манифеста не совпадает",
            )
        record = next(
            (
                row for row in manifest.get("documents", [])
                if row.get("stored_name") == name
            ),
            None,
        )
        if record is None:
            raise PassportNotFoundError("документ не найден")
        path = self._passport_dir(passport_id) / "documents" / name
        if not path.is_file():
            raise PassportNotFoundError("документ не найден")
        if _sha256(path) != record.get("sha256"):
            raise PassportIntegrityError("контрольная сумма документа не совпадает")
        return path, record
