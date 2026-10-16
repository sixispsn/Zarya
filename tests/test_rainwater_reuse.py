"""Rainwater study is isolated from legacy demands and peak K2."""
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from app.calc.rainwater_reuse import RainwaterReuseInput, assess, from_dict, parse_profile
from app.intake.request_dto import IOS2Request, DocumentRequest
from app.intake.yaml_io import dump_request, load_request
from app.intake.project_builder import build_project
from app.pz.project import Project
from app.pz.generator import generate_pz_html, generate_wastewater_pz_html, generate_rainwater_reuse_html
from app.pz.rainwater_reuse import functional_svg, specification_rows
from app.pz.commission import build_commission_report
from app.intake.studio_intake import validate_value, IntakeError, build_handoff_request
from tests import test_studio as studio

client = studio.client


def example():
    return RainwaterReuseInput(
        enabled=True, purpose="irrigation", location="site", demand_m3_day=1,
        useful_volume_m3=2, collection_area_m2=100, collection_factor=0.8,
        profile="2026-06-01; 50\n2026-06-02; 0\n2026-06-03; 0",
        source="Синтетический контрольный ряд; η=0,8 — условие теста, не норматив.",
    )


def test_mass_balance_with_overflow_and_dry_days():
    r = assess(example())
    assert r["status"] == "preliminary"
    t = r["totals"]
    assert t["inflow_m3"] == 4
    assert t["supplied_m3"] == 2
    assert t["overflow_m3"] == 2
    assert t["deficit_m3"] == 1
    assert t["stored_m3"] == 0
    assert t["mass_residual_m3"] == 0
    assert t["coverage_percent"] == pytest.approx(200 / 3)
    assert [day["stored_m3"] for day in r["days"]] == [1, 0, 0]


def test_zero_demand_has_no_fake_coverage_and_dry_weather_no_supply():
    d = replace(example(), profile="2026-06-01; 0; 0")
    r = assess(d)
    assert r["totals"]["coverage_percent"] is None
    assert r["totals"]["supplied_m3"] == 0
    assert assess(replace(d, profile="2026-06-01; 0; 5"))["totals"]["deficit_m3"] == 5


def test_explicit_profile_overrides_constant_demand_without_default_capacity():
    d = replace(example(), demand_m3_day=None, profile="2026-06-01; 50; 0,5")
    assert assess(d)["totals"]["supplied_m3"] == 0.5
    assert assess(replace(d, useful_volume_m3=None))["status"] == "needs_data"
    assert assess(RainwaterReuseInput(enabled=True))["totals"] is None


@pytest.mark.parametrize("profile", ["2026-06-01; -1", "2026-06-01; nan", "2026-06-01; inf",
    "2026-06-01; 1\n2026-06-03; 2", "2026-06-01; 1\n2026-06-01; 2", "bad; 1", "1,2,3", "2026-06-01; 1; -2"])
def test_profile_rejects_invalid_or_missing_days(profile):
    with pytest.raises(ValueError):
        parse_profile(profile)


@pytest.mark.parametrize("data", [{"enabled": "false"}, {"collection_factor": 1.1},
    {"collection_area_m2": float("nan")}, {"useful_volume_m3": -1}, {"demand_m3_day": True},
    {"purpose": "potable"}, {"profile": None}, {"hidden_default": 1}])
def test_strict_input(data):
    with pytest.raises(ValueError):
        from_dict(data)


def test_numeric_overflow_does_not_produce_fictitious_balance():
    d = replace(example(), collection_area_m2=1e308, profile="2026-06-01; 1e308")
    assert assess(d)["status"] == "invalid"
    assert assess(d)["totals"] is None


def test_roundtrip_and_no_alias_or_implicit_roof_area():
    req = IOS2Request(DocumentRequest("", "", ""), "residential", 2, 6.6,
                     rainwater_reuse=example(), storm_roof_area_m2=500, storm_walls_area_m2=200,
                     fire_height_m=4.8)
    loaded = load_request(dump_request(req))
    assert loaded.rainwater_reuse == req.rainwater_reuse
    p = build_project(loaded)
    assert p.rainwater_reuse.collection_area_m2 == 100
    p.rainwater_reuse.useful_volume_m3 = 10
    assert loaded.rainwater_reuse.useful_volume_m3 == 2


def test_optional_disabled_leaves_outputs_and_hydraulics_unchanged():
    p = Project()
    before = generate_pz_html(p)
    p.rainwater_reuse = replace(example(), enabled=False)
    assert generate_pz_html(p) == before
    assert not functional_svg(p) and not specification_rows(p)
    p.rainwater_reuse.enabled = True
    model = deepcopy(asdict(p))
    for render in (generate_pz_html, generate_wastewater_pz_html, generate_rainwater_reuse_html):
        assert "дождевой воды" in render(p)
    # The pre-existing wastewater renderer fills diagnostic assessments; the
    # rainwater feature must not change demands, head, meters or peak rainfall.
    for key in ("flows", "source", "storm", "meters", "pumps", "rainwater_reuse"):
        assert asdict(p)[key] == model[key]
    assert all(row.qty is None for row in specification_rows(p))


def test_sanitation_review_cannot_be_confused_with_ready_design():
    p = Project(rainwater_reuse=example())
    rule = next(c for c in build_commission_report(p).checks if c.code == "RAIN-01")
    assert rule.blocking
    assert "К2 в К1 не соединяется" in functional_svg(p)
    p.rainwater_reuse.purpose = "irrigation_toilets"
    assert "не более суток" in assess(p.rainwater_reuse)["storage_rule"]


def test_xss_is_escaped_in_pz_and_svg():
    p = Project(rainwater_reuse=replace(example(), source="<script>alert(1)</script>",
                                      technical_use='<img src=x onerror="x">'))
    html = generate_rainwater_reuse_html(p)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert '<img src=x' not in generate_pz_html(p)


def test_studio_optional_choice_persists_and_off_removes_results(client):
    state = studio.new(client)
    assert not state["rainwater_reuse"]["enabled"]
    state = studio.answer(client, state, "rainwater_enabled", "yes")
    assert state["rainwater_reuse"]["status"] == "needs_data"
    d = asdict(example())
    for key, value in d.items():
        if key not in {"enabled", "design_review"} and value not in (None, ""):
            state = studio.answer(client, state, "rainwater_" + key, value)
    assert state["rainwater_reuse"]["totals"]["supplied_m3"] == 2
    state = studio.answer(client, state, "rainwater_enabled", "no")
    assert state["rainwater_reuse"]["status"] == "disabled"
    assert state["rainwater_reuse"]["totals"] is None
    assert "rainwater_enabled" in state["options"]
    with pytest.raises(IntakeError):
        validate_value("rainwater_collection_factor", "1.1")


def test_studio_handoff_and_real_preview_keep_rainwater_and_legacy_flows(client):
    import io
    from pypdf import PdfReader
    state = studio.residential_project(client)
    original = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    answers = {"rainwater_" + k: v for k, v in asdict(example()).items() if k not in {"enabled", "design_review"}}
    answers["rainwater_enabled"] = "yes"
    response = client.post("/studio/api/calculate", json={"revision": original["revision"], "answers": answers})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["calculation"] == original["calculation"]
    assert state["project_calculation"]["flows"] == original["project_calculation"]["flows"]
    assert state["project_calculation"]["can_preview"] and not state["project_calculation"]["can_release"]
    preview = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert preview.status_code == 200, preview.text
    state = preview.json()
    document = next(d for d in state["preview"]["documents"] if d["kind"] == "rainwater_reuse_pdf")
    assert document["state"] == "incomplete"
    pdf = client.get(f'/studio/api/preview/{state["preview"]["id"]}/files/{document["name"]}')
    assert pdf.status_code == 200
    pages = PdfReader(io.BytesIO(pdf.content)).pages
    assert len(pages) == 3
    assert "Функциональная структура" in pages[1].extract_text()
    assert "К2 в К1 не соединяется" in pages[1].extract_text()
