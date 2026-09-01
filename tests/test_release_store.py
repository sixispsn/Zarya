import pytest

from app.intake.advisories import InputAdvisory
from app.intake.release_store import (
    ReleaseIntegrityError,
    ReleaseStore,
)
from app.intake.yaml_io import load_request
from app.intake.preflight import preflight_request
from app.pz.commission import CommissionReport, PassportItem
from app.pz.proof import ProofDecision, ProofGraph, ProofStep


YAML = """
document: {cipher: Т-ИОС2, object_name: Объект, organization: Орг}
building: {type: residential, floors: 9, height_m: 27}
fire: {mode: not_required}
"""


def _publish(store: ReleaseStore):
    commission = CommissionReport(
        passport=[PassportItem("Версия", "0.6.1")],
        project_fingerprint="A" * 16,
        legacy_fingerprint="B" * 16,
        build_commit="C" * 16,
        generated_at="2026-08-31T12:00:00",
    )
    graph = ProofGraph(
        project_fingerprint=commission.project_fingerprint,
        legacy_fingerprint=commission.legacy_fingerprint,
        build_commit=commission.build_commit,
        generated_at=commission.generated_at,
        decisions=[ProofDecision(
            id="v1-q-day",
            system="В1",
            title="Суточный расход",
            value="90,0",
            unit="м³/сут",
            status="verified",
            summary="Проверено",
            steps=[ProofStep("source", "Жители", "500")],
        )],
    )
    return store.publish(
        release_id="a1b2c3d4e5",
        project_id="f1e2d3c4b5",
        passport_id="A" * 32,
        passport_url="https://example.test/p/" + "A" * 32,
        request=load_request(YAML),
        commission=commission,
        proof_graph=graph,
        defense_payload={"decisions": []},
        documents=[{
            "group": "ios2", "label": "ПЗ", "name": "ПЗ.pdf",
            "state": "ready", "state_note": "",
        }],
        advisories=[InputAdvisory("warning", "x", "Проверить", "СП")],
        status=["готово"],
        warnings=["уточнить"],
        preflight=preflight_request(load_request(YAML)).to_dict(),
    )


def test_release_roundtrip_restores_typed_snapshot(tmp_path):
    store = ReleaseStore(tmp_path)
    _publish(store)
    snapshot = store.load("a1b2c3d4e5")
    assert snapshot.request().floors == 9
    assert snapshot.commission_report().build_commit == "C" * 16
    assert snapshot.proof_graph().decisions[0].steps[0].value == "500"
    assert snapshot.advisories()[0].reference == "СП"
    assert snapshot.documents[0]["name"] == "ПЗ.pdf"
    assert snapshot.status == ["готово"]
    assert snapshot.preflight_payload["can_release"] is True


def test_release_is_append_only(tmp_path):
    store = ReleaseStore(tmp_path)
    _publish(store)
    with pytest.raises(FileExistsError):
        _publish(store)


def test_release_detects_source_corruption(tmp_path):
    store = ReleaseStore(tmp_path)
    _publish(store)
    path = tmp_path / "a1b2c3d4e5" / "source.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "# damage\n", encoding="utf-8")
    with pytest.raises(ReleaseIntegrityError, match="source.yaml"):
        store.load("a1b2c3d4e5")


def test_answer_path_is_scoped_to_release(tmp_path):
    store = ReleaseStore(tmp_path)
    _publish(store)
    path = store.answer_path("a1b2c3d4e5", "Ответ_эксперту_v1-q-day.pdf")
    assert path.parent.name == "answers"
    with pytest.raises(ValueError):
        store.answer_path("a1b2c3d4e5", "../../answer.pdf")


def test_wizard_restores_release_after_memory_cache_is_cleared(
    tmp_path, monkeypatch,
):
    from app.intake.advisories import review_request
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    from app.pz.proof import build_proof_graph
    from app.web import wizard

    request = load_request(YAML)
    bundle = design_ios2(
        build_project(request),
        output_dir=str(tmp_path / "preview"),
        render_documents=False,
    )
    graph = build_proof_graph(bundle.project, bundle.commission_report)
    store = ReleaseStore(tmp_path / "releases")
    store.publish(
        release_id="0123456789",
        project_id="f1e2d3c4b5",
        passport_id="P" * 32,
        passport_url="https://example.test/p/" + "P" * 32,
        request=request,
        commission=bundle.commission_report,
        proof_graph=graph,
        defense_payload={"decisions": []},
        documents=[{
            "group": "ios2", "label": "ПЗ", "name": "ПЗ.pdf",
            "state": "ready", "state_note": "",
        }],
        advisories=review_request(request),
        status=bundle.status,
        warnings=bundle.warnings,
    )
    monkeypatch.setattr(wizard, "_RELEASE_STORE", store)
    monkeypatch.setattr(wizard, "_OUT_ROOT", str(tmp_path / "runs"))
    wizard._RUNS.clear()

    restored = wizard._get_run("0123456789")
    assert restored is not None
    assert restored["project_id"] == "f1e2d3c4b5"
    assert restored["bundle"].project.building.floors_above == 9
    assert restored["proof_graph"].project_fingerprint == graph.project_fingerprint
    assert restored["documents"][0]["name"] == "ПЗ.pdf"
    # Вызов publish без отчёта сохраняет совместимое пустое значение.
    assert restored["preflight"] == {}
