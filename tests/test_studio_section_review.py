"""A human review belongs to an exact PDF, not a generic release checkbox."""
from copy import deepcopy
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.intake.pilot_objects import calculation_stamp
from app.intake.studio_intake import IntakeError, answer_field, accepted_values
from app.intake.studio_project import STUDIO_HANDOFF_VERSION
from app.pz.water_scheme_delivery import DOCUMENT_RENDER_VERSION
from app.intake.studio_section_review import content_checklist, review_state, record_review
from tests import test_studio as studio_tests
from tests.test_studio_apartment_meters import draft
from tests.test_pilot_access import pilot as pilot_fixture, client_for, WRITE

client = studio_tests.client
pilot = pilot_fixture
VERSION = STUDIO_HANDOFF_VERSION


def section_draft():
    return draft(floor_height_m=3.3, basement_kind="basement", basement_floor_m=-3.1,
                 roof_type="flat_non_accessible", storm_city="moscow",
                 storm_roof_area_m2=252, section_drainage="internal")


@pytest.fixture
def evidence(tmp_path):
    d = section_draft()
    d["project_calculation"] = dict(handoff_version=VERSION, sewer_scheme=dict(presentation="representative"),
                                     can_release=False, flows={"unchanged": 90})
    d["preview"] = dict(id="a"*32, handoff_version=VERSION, stamp=calculation_stamp(d),
                        render_version=DOCUMENT_RENDER_VERSION,
                        documents=[dict(kind="wastewater_scheme_pdf", name="section.pdf")])
    path = tmp_path / "previews" / ("a"*32) / "section.pdf"
    path.parent.mkdir(parents=True)
    # File-integrity unit fixture, not a generated/reviewable engineering PDF.
    path.write_bytes(b"%PDF-fixture")
    return d, tmp_path, path


def save(d, folder):
    status = review_state(d, folder, VERSION)
    record_review(d, folder, VERSION, fingerprint=status["current"]["fingerprint"],
                  reviewer="Инженер", architecture_ref="АР-3, лист 2, рев. 1",
                  confirm=True, actor_id="private-user")


def test_review_does_not_change_calculations_preview_inputs_or_release(evidence):
    d, folder, path = evidence
    before, data = deepcopy(d), path.read_bytes()
    save(d, folder)
    state = review_state(d, folder, VERSION)
    assert state["state"] == "reviewed" and not state["release_ready"] and not state["takeoff_eligible"]
    assert d["section_review"]["actor_id"] == "private-user"
    assert "actor_id" not in state["record"]
    assert {k: v for k, v in d.items() if k != "section_review"} == before
    assert path.read_bytes() == data


@pytest.mark.parametrize("change", ["answer", "pdf", "deleted", "version", "documents", "new_preview", "network"])
def test_review_expires_for_any_evidence_change(evidence, change):
    d, folder, path = evidence
    save(d, folder)
    version = VERSION
    if change == "answer": answer_field(d, "residents", 21)
    elif change == "pdf": path.write_bytes(b"%PDF-different")
    elif change == "deleted": path.unlink()
    elif change == "version": version = "future"
    elif change == "documents": d["documents"].append({"id": "new-document", "candidates": []})
    elif change == "new_preview": d["preview"]["id"] = "b"*32
    elif change == "network": d["project_calculation"]["sewer_scheme"]["presentation"] = "confirmed"
    assert review_state(d, folder, version)["state"] == "stale"


@pytest.mark.parametrize("change", ["traversal", "symlink", "empty", "not_pdf", "two_documents", "study", "old_inputs"])
def test_invalid_or_foreign_pdf_cannot_be_reviewed(evidence, change):
    d, folder, path = evidence
    if change == "traversal": d["preview"]["documents"][0]["name"] = "../../secret.pdf"
    elif change == "symlink":
        target = folder / "other.pdf"; target.write_bytes(b"%PDF-other")
        path.unlink(); path.symlink_to(target)
    elif change == "empty": path.write_bytes(b"")
    elif change == "not_pdf": path.write_bytes(b"not-pdf")
    elif change == "two_documents": d["preview"]["documents"] *= 2
    elif change == "study": d["study"] = {"kind": "samara"}
    elif change == "old_inputs": d["preview"]["stamp"] = {}
    state = review_state(d, folder, VERSION)
    assert not state or not state["can_record"]
    with pytest.raises(IntakeError):
        record_review(d, folder, VERSION, fingerprint="f"*64, reviewer="Инженер",
                      architecture_ref="АР", confirm=True, actor_id="local")


def test_checklist_never_converts_complete_main_inputs_into_gost_approval():
    values = accepted_values(section_draft())
    for system in ("k1", "k2"):
        values.update({f"section_{system}_{k}": v for k, v in dict(dn_mm=150, slope=.01,
            outlet_invert_m=-2, discharge_point="Колодец", source_ref="АР, лист 2").items()})
    rows = {r["code"]: r for r in content_checklist(values)}
    assert rows["k1"]["state"] == rows["k2"]["state"] == "supplied"
    assert rows["ar"]["state"] == rows["levels"]["state"] == "drawing_work"
    values["section_drainage"] = "external"
    assert "k2" not in {r["code"] for r in content_checklist(values)}


def test_http_review_binds_real_pdf_no_release_and_rejects_other_session(client):
    state = studio_tests.new(client)
    state = client.post('/studio/api/calculate', json=dict(revision=state['revision'],
        answers={k: v['value'] for k, v in section_draft()['answers'].items()})).json()
    assert state['section_review']['state'] == 'needs_pdf'
    response = client.post('/studio/api/preview', json={'revision': state['revision']})
    assert response.status_code == 200, response.text
    state = response.json()
    before = deepcopy(state['project_calculation'])
    current = state['section_review']['current']
    url = f"/studio/api/preview/{current['preview_id']}/files/{current['filename']}"
    data = client.get(url).content
    assert hashlib.sha256(data).hexdigest() == current['pdf_sha256']
    payload = dict(revision=state['revision'], reviewer='Инженер', architecture_ref='АР-3, лист 2',
                   confirm=True, fingerprint=current['fingerprint'])
    for invalid in ({'confirm': False}, {'reviewer': ' '}, {'architecture_ref': ' '}, {'fingerprint': 'f'*64}):
        assert client.post('/studio/api/section/review', json={**payload, **invalid}).status_code == 422
    assert client.post('/studio/api/section/review', json=payload,
                       headers={'Origin': 'https://invalid.example'}).status_code == 403
    with TestClient(studio_tests.app) as other:
        other.headers['X-Zarya-Studio'] = '1'
        second = studio_tests.new(other)
        assert other.post('/studio/api/section/review', json={**payload, 'revision': second['revision']}).status_code == 422
        assert other.get(url).status_code == 404
    response = client.post('/studio/api/section/review', json=payload)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state['section_review']['state'] == 'reviewed'
    assert state['project_calculation'] == before and not before['can_release']
    assert client.get(url).content == data
    assert client.get('/studio/api/draft').json()['section_review'] == state['section_review']
    assert client.post('/studio/api/section/review', json=payload).status_code == 409
    state = studio_tests.answer(client, state, 'residents', 21)
    assert state['section_review']['state'] == 'stale'
    assert client.get(url).status_code == 404


def test_personal_participant_can_review_only_own_draft(pilot, evidence):
    from app.intake.studio_store import StudioStore
    access, users, root = pilot
    uid, key = users['alice']
    alice = client_for(key); bob = client_for(users['bob'][1])
    state = alice.post('/studio/api/draft', headers=WRITE).json()
    did = state['project_id']; storage = StudioStore(root / 'studio' / '_users' / uid)
    fixture, _, pdf = evidence
    with storage.edit(did, state['revision']) as d:
        d.update(deepcopy(fixture))
        d['project_id'] = did
    target = storage.folder(did) / 'previews' / ('a'*32) / 'section.pdf'
    target.parent.mkdir(parents=True); target.write_bytes(pdf.read_bytes())
    state = alice.get('/studio/api/draft').json()
    payload = dict(revision=state['revision'], fingerprint=state['section_review']['current']['fingerprint'],
                   reviewer='Алиса', architecture_ref='АР, 2', confirm=True)
    assert bob.post('/studio/api/section/review', headers=WRITE, json=payload).status_code == 404
    result = alice.post('/studio/api/section/review', headers=WRITE, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()['section_review']['state'] == 'reviewed'
    assert storage.load(did)['section_review']['actor_id'] == uid
    assert alice.get('/studio/api/section/review').status_code == 403
    assert alice.post('/studio/api/section/other', headers=WRITE, json=payload).status_code == 403
    access.revoke(uid)
    assert alice.post('/studio/api/section/review', headers=WRITE, json=payload).status_code == 401
