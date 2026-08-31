"""Постоянное хранилище рабочих выпусков Wizard.

Цифровой паспорт остаётся неизменяемым публичным архивом PDF. ReleaseStore
сохраняет внутренний снимок, необходимый для восстановления Result, Proof и
Defense после перезапуска процесса: точный YAML, комиссионный отчёт,
доказательный граф, каталог документов и предупреждения выпуска.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from app.intake.advisories import InputAdvisory
from app.intake.request_dto import IOS2Request
from app.intake.yaml_io import dump_request, load_request
from app.pz.commission import (
    CommissionReport,
    ControlCheck,
    PassportItem,
    TraceRow,
)
from app.pz.proof import ProofDecision, ProofGraph, ProofStep


_PROJECTS_ROOT = os.environ.get(
    "ZARYA_PROJECTS_DIR",
    os.path.expanduser("~/.zarya/projects"),
)
DEFAULT_ROOT = os.environ.get(
    "ZARYA_RELEASES_DIR",
    os.path.join(_PROJECTS_ROOT, "_releases"),
)
_ID_RE = re.compile(r"^[a-f0-9]{10}$")
_PASSPORT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")
_ANSWER_NAME_RE = re.compile(r"^Ответ_эксперту_[A-Za-z0-9_-]+\.pdf$")


class ReleaseNotFoundError(FileNotFoundError):
    pass


class ReleaseIntegrityError(ValueError):
    pass


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _proof_from_dict(value: dict) -> ProofGraph:
    decisions = []
    for raw in value.get("decisions", []):
        decisions.append(ProofDecision(
            id=str(raw["id"]),
            system=str(raw["system"]),
            title=str(raw["title"]),
            value=str(raw.get("value", "")),
            unit=str(raw.get("unit", "")),
            status=str(raw["status"]),
            summary=str(raw.get("summary", "")),
            steps=[
                ProofStep(
                    kind=str(step["kind"]),
                    label=str(step["label"]),
                    value=str(step.get("value", "")),
                    detail=str(step.get("detail", "")),
                )
                for step in raw.get("steps", [])
            ],
            artifacts=[str(item) for item in raw.get("artifacts", [])],
            impact=[str(item) for item in raw.get("impact", [])],
        ))
    return ProofGraph(
        project_fingerprint=str(value["project_fingerprint"]),
        legacy_fingerprint=str(value["legacy_fingerprint"]),
        build_commit=str(value.get("build_commit", "")),
        generated_at=str(value["generated_at"]),
        decisions=decisions,
        version=str(value.get("version", "1.0")),
    )


def _commission_from_dict(value: dict) -> CommissionReport:
    return CommissionReport(
        passport=[PassportItem(**row) for row in value.get("passport", [])],
        trace_rows=[TraceRow(**row) for row in value.get("trace_rows", [])],
        checks=[ControlCheck(**row) for row in value.get("checks", [])],
        project_fingerprint=str(value.get("project_fingerprint", "")),
        legacy_fingerprint=str(value.get("legacy_fingerprint", "")),
        build_commit=str(value.get("build_commit", "")),
        generated_at=str(value.get("generated_at", "")),
    )


@dataclass(frozen=True)
class ReleaseSnapshot:
    release_id: str
    project_id: str
    passport_id: str
    passport_url: str
    source_yaml: str
    commission_payload: dict
    proof_payload: dict
    defense_payload: dict
    documents: list[dict]
    advisories_payload: list[dict]
    status: list[str]
    warnings: list[str]

    def request(self) -> IOS2Request:
        return load_request(self.source_yaml)

    def commission_report(self) -> CommissionReport:
        return _commission_from_dict(self.commission_payload)

    def proof_graph(self) -> ProofGraph:
        return _proof_from_dict(self.proof_payload)

    def advisories(self) -> list[InputAdvisory]:
        return [InputAdvisory(**row) for row in self.advisories_payload]


class ReleaseStore:
    """Append-only снимки успешно выпущенных комплектов."""

    def __init__(self, root: str | Path = DEFAULT_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _directory(self, release_id: str) -> Path:
        if not _ID_RE.fullmatch(release_id or ""):
            raise ValueError("некорректный идентификатор выпуска")
        return self.root / release_id

    def publish(
        self,
        *,
        release_id: str,
        project_id: str,
        passport_id: str,
        passport_url: str,
        request: IOS2Request,
        commission: CommissionReport,
        proof_graph: ProofGraph,
        defense_payload: dict,
        documents: list[dict],
        advisories: list[InputAdvisory],
        status: list[str],
        warnings: list[str],
    ) -> dict:
        destination = self._directory(release_id)
        if destination.exists():
            raise FileExistsError("выпуск уже существует")
        if not _ID_RE.fullmatch(project_id or ""):
            raise ValueError("некорректный project_id выпуска")
        if not _PASSPORT_ID_RE.fullmatch(passport_id or ""):
            raise ValueError("некорректный passport_id выпуска")

        temporary = Path(tempfile.mkdtemp(
            prefix=f".{release_id}-",
            dir=str(self.root),
        ))
        try:
            source_yaml = dump_request(request)
            payloads: dict[str, Any] = {
                "commission.json": asdict(commission),
                "proof.json": proof_graph.to_dict(),
                "defense.json": defense_payload,
                "documents.json": documents,
                "advisories.json": [asdict(row) for row in advisories],
                "state.json": {
                    "status": list(status),
                    "warnings": list(warnings),
                },
            }
            source_path = temporary / "source.yaml"
            source_path.write_text(source_yaml, encoding="utf-8")
            for name, payload in payloads.items():
                (temporary / name).write_text(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ) + "\n",
                    encoding="utf-8",
                )
            files = {
                path.name: _file_sha256(path)
                for path in temporary.iterdir()
                if path.is_file()
            }
            manifest = {
                "schema_version": 1,
                "release_id": release_id,
                "project_id": project_id,
                "passport_id": passport_id,
                "passport_url": passport_url,
                "created_at": commission.generated_at,
                "project_fingerprint": commission.project_fingerprint,
                "legacy_fingerprint": commission.legacy_fingerprint,
                "build_commit": commission.build_commit,
                "files": files,
            }
            manifest["seal_sha256"] = sha256(
                _canonical_bytes(manifest)
            ).hexdigest()
            (temporary / "manifest.json").write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, destination)
            return manifest
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def load(self, release_id: str) -> ReleaseSnapshot:
        directory = self._directory(release_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise ReleaseNotFoundError("выпуск не найден")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseIntegrityError("манифест выпуска повреждён") from exc
        if manifest.get("release_id") != release_id:
            raise ReleaseIntegrityError("идентификатор выпуска не совпадает")
        expected_seal = manifest.get("seal_sha256", "")
        unsigned = dict(manifest)
        unsigned.pop("seal_sha256", None)
        actual_seal = sha256(_canonical_bytes(unsigned)).hexdigest()
        if not expected_seal or actual_seal != expected_seal:
            raise ReleaseIntegrityError("контрольная сумма манифеста не совпадает")
        for name, expected in manifest.get("files", {}).items():
            if Path(name).name != name:
                raise ReleaseIntegrityError("манифест содержит небезопасное имя")
            path = directory / name
            if not path.is_file() or _file_sha256(path) != expected:
                raise ReleaseIntegrityError(f"файл выпуска повреждён: {name}")

        def read_json(name: str):
            try:
                return json.loads((directory / name).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReleaseIntegrityError(
                    f"файл выпуска не разобран: {name}"
                ) from exc

        state = read_json("state.json")
        return ReleaseSnapshot(
            release_id=release_id,
            project_id=str(manifest["project_id"]),
            passport_id=str(manifest["passport_id"]),
            passport_url=str(manifest["passport_url"]),
            source_yaml=(directory / "source.yaml").read_text(encoding="utf-8"),
            commission_payload=read_json("commission.json"),
            proof_payload=read_json("proof.json"),
            defense_payload=read_json("defense.json"),
            documents=read_json("documents.json"),
            advisories_payload=read_json("advisories.json"),
            status=[str(row) for row in state.get("status", [])],
            warnings=[str(row) for row in state.get("warnings", [])],
        )

    def answer_path(self, release_id: str, name: str) -> Path:
        if not _ANSWER_NAME_RE.fullmatch(name or ""):
            raise ValueError("некорректное имя ответа эксперту")
        directory = self._directory(release_id)
        if not directory.is_dir():
            raise ReleaseNotFoundError("выпуск не найден")
        answers = directory / "answers"
        answers.mkdir(exist_ok=True, mode=0o700)
        return answers / name
