"""Documented manual review cannot silently certify missing/stale rain inputs."""
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from app.calc.rainwater_design import SECTIONS, fingerprint
from app.calc.rainwater_reuse import assess, from_dict
from app.calc.rainwater_treatment import project_context
from app.intake.studio_intake import validate_value, IntakeError, build_handoff_request
from app.intake.project_builder import build_project
from app.intake.yaml_io import dump_request, load_request
from app.pz.commission import build_commission_report
from app.pz.generator import generate_rainwater_reuse_html, generate_pz_html, generate_wastewater_pz_html
from tests.test_rainwater_treatment import example, CTX
from tests import test_studio as studio
from tests.test_pilot_access import pilot as pilot_fixture, client_for, draft as pilot_draft, WRITE

client = studio.client
pilot = pilot_fixture


def documented():
    p = example()
    for key in SECTIONS:
        setattr(p.rainwater_reuse, key, f"Синтетическое условие регрессионного теста {key}; лист ДВ-01, рев. 1. Не проектное решение объекта.")
    d = p.rainwater_reuse
    d.design_storage_days = 3
    d.design_annual_saving_m3 = 42
    d.design_winter = "seasonal"
    d.design_discharge = "storm"
    return p


def confirm(p):
    p.rainwater_reuse.design_review = dict(fingerprint=fingerprint(p.rainwater_reuse, **project_context(p)),
        reviewer="Тестовый инженер", reviewed_at="2026-10-02T09:00:00+00:00")


def check(p):
    return next(c for c in build_commission_report(p).checks if c.code == "RAIN-01")


def test_missing_then_documented_then_manual_confirmation():
    p = example()
    assert check(p).blocking
    assert assess(p.rainwater_reuse, **CTX)["design"]["status"] == "needs_data"
    p = documented()
    r = assess(p.rainwater_reuse, **CTX)
    assert r["design"]["ready_for_review"] and not r["design"]["confirmed"]
    assert check(p).blocking
    confirm(p)
    before = deepcopy(asdict(p))
    r = assess(p.rainwater_reuse, **CTX)
    assert r["design"]["confirmed"] and not r["treatment"]["quality_verified"]
    assert not check(p).blocking
    assert asdict(p) == before
    # The same daily balance and hydraulic point, not new engineering formulae.
    old = assess(example().rainwater_reuse, **CTX)
    assert r["totals"] == old["totals"] and r["pump"]["duty"] == old["pump"]["duty"]


@pytest.mark.parametrize("patch", [{"design_storage_days": 8}, {"design_discharge": "other"},
    {"design_winter": ""}, {"design_quality": ""}, {"design_annual_saving_m3": None},
    {"pump_flow_lps": .3}, {"treatment_filter_loss_m": None}, {"profile": ""}])
def test_cannot_confirm_missing_or_inconsistent_data(patch):
    p = documented(); p.rainwater_reuse = replace(p.rainwater_reuse, **patch)
    confirm(p)  # Even a current hash cannot bypass a failed prerequisite.
    assert check(p).blocking
    assert not assess(p.rainwater_reuse, **CTX)["design"]["ready_for_review"]


@pytest.mark.parametrize("patch", [{"design_basis": "Новая ревизия ТЭО"}, {"design_storage_days": 2},
    {"design_annual_saving_m3": 40}, {"collection_factor": .7}, {"pump_network_loss_m": 3}])
def test_modification_invalidates_current_review(patch):
    p = documented(); confirm(p)
    p.rainwater_reuse = replace(p.rainwater_reuse, **patch)
    assert check(p).blocking
    assert assess(p.rainwater_reuse, **CTX)["design"]["status"] == "stale"


def test_other_roof_and_disabled_system():
    p = documented(); confirm(p); p.sewage.roof_kind = "gable"
    assert check(p).blocking
    p.rainwater_reuse.enabled = False
    assert not any(c.code == "RAIN-01" for c in build_commission_report(p).checks)


@pytest.mark.parametrize("key,value", [("design_basis", []), ("design_quality", "а" * 1201),
    ("design_storage_days", 0), ("design_storage_days", True),
    ("design_annual_saving_m3", float("inf")), ("design_annual_saving_m3", -1),
    ("design_winter", "".join(["invented"])), ("design_review", {"confirmed": True})])
def test_invalid_input(key, value):
    with pytest.raises(ValueError): from_dict({key: value})


def test_storage_shorter_than_three_not_forbidden_and_zero_saving_not_invented():
    p = documented(); p.rainwater_reuse.design_storage_days = .5
    p.rainwater_reuse.design_annual_saving_m3 = 0
    assert assess(p.rainwater_reuse, **CTX)["design"]["ready_for_review"]
    assert validate_value("rainwater_design_annual_saving_m3", "0") == 0
    with pytest.raises(IntakeError): validate_value("rainwater_design_storage_days", "0")


def test_pdf_content_escapes_notes_and_distinguishes_external_economy():
    p = documented(); p.rainwater_reuse.design_storage = "<script>bad</script> лист 3"
    confirm(p)
    for render in (generate_rainwater_reuse_html, generate_pz_html, generate_wastewater_pz_html):
        html = render(p)
        assert "Проверено проектировщиком" in html
        assert "Годовая экономия по отдельному обоснованию" in html
        assert "<script>bad" not in html and "&lt;script&gt;" in html


def seed(client):
    state = studio.residential_project(client)
    answers = {"rainwater_" + k: v for k, v in asdict(documented().rainwater_reuse).items()
               if k not in {"enabled", "design_review"}}
    answers.update(rainwater_enabled="yes", roof_type="flat_accessible")
    response = client.post("/studio/api/calculate", json={"revision": state["revision"], "answers": answers})
    assert response.status_code == 200, response.text
    return response.json()


def test_studio_review_stale_revision_csrf_roundtrip_and_source_changes(client):
    state = seed(client)
    data = dict(revision=state["revision"], reviewer="Инженер теста", confirm=True)
    denied = client.post("/studio/api/rainwater/review", json=data, headers={"origin": "https://foreign.example"})
    assert denied.status_code == 403
    response = client.post("/studio/api/rainwater/review", json=data)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["rainwater_reuse"]["design"]["confirmed"]
    assert not state["project_calculation"]["can_release"]  # unrelated checks still apply
    assert client.post("/studio/api/rainwater/review", json=data).status_code == 409
    from app.web.studio import store
    draft = store().load(client.cookies.get("zarya_studio_draft"))
    req = load_request(dump_request(build_handoff_request(draft)))
    assert not check(build_project(req)).blocking
    # Changed architecture / added evidence invalidates even if Q/H stayed equal.
    state = studio.answer(client, state, "floors", 3)
    assert state["rainwater_reuse"]["design"]["status"] == "stale"
    state = client.post("/studio/api/rainwater/review", json=dict(data, revision=state["revision"])).json()
    assert state["rainwater_reuse"]["design"]["confirmed"]
    state = studio.upload(client, state, "Новый лист АР, ревизия 2")
    assert state["rainwater_reuse"]["design"]["status"] == "stale"


def test_review_not_an_ordinary_input_and_missing_fields_cannot_be_bypassed(client):
    state = studio.residential_project(client)
    assert client.post("/studio/api/rainwater/review", json=dict(revision=state["revision"], reviewer="И", confirm=True)).status_code == 422
    assert client.patch("/studio/api/answer", json=dict(revision=state["revision"], field="rainwater_design_review", value="yes")).status_code == 422
    state = seed(client)
    assert client.post("/studio/api/rainwater/review", json=dict(revision=state["revision"], reviewer=" ", confirm=True)).status_code == 422
    assert client.post("/studio/api/rainwater/review", json=dict(revision=state["revision"], reviewer="И", confirm=False)).status_code == 422


def test_pilot_review_cannot_target_another_user_draft(pilot):
    _, users, _ = pilot
    alice, bob = client_for(users["alice"][1]), client_for(users["bob"][1])
    a, b = pilot_draft(alice), pilot_draft(bob)
    payload = dict(revision=b["revision"], reviewer="Боб", confirm=True)
    r = bob.post("/studio/api/rainwater/review", headers={**WRITE, "X-Zarya-Draft": a["project_id"]}, json=payload)
    assert r.status_code == 409
    assert alice.get("/studio/api/draft").json() == a
    assert bob.get("/studio/api/draft").json() == b
    answers = {"rainwater_" + k: v for k, v in asdict(documented().rainwater_reuse).items()
               if k not in {"enabled", "design_review"}}
    answers.update(residents=20, apartments=8, consumer_code="residential_full_bath", floors=2,
                   building_height_m=6.6, fire_height_m=4.8, hws_type="central",
                   rainwater_enabled="yes", roof_type="flat_accessible")
    r = alice.post("/studio/api/calculate", headers=WRITE, json=dict(revision=a["revision"], answers=answers))
    assert r.status_code == 200, r.text
    state = r.json()
    r = alice.post("/studio/api/rainwater/review", headers=WRITE,
                   json=dict(revision=state["revision"], reviewer="Инженер", confirm=True))
    assert r.status_code == 200, r.text
    assert r.json()["rainwater_reuse"]["design"]["confirmed"]
    assert bob.get("/studio/api/draft").json() == b


def test_catalogue_change_invalidates_approval(monkeypatch):
    from app.data import rainwater_treatment
    p = documented(); confirm(p)
    changed = deepcopy(rainwater_treatment.CATALOG)
    changed[0]["pressure_screen_bar"] -= .01
    monkeypatch.setattr(rainwater_treatment, "CATALOG", changed)
    assert assess(p.rainwater_reuse, **CTX)["design"]["status"] == "stale"
