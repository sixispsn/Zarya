from copy import deepcopy
from dataclasses import replace
from xml.etree import ElementTree as ET

from pypdf import PdfReader
import pytest

from app.pz.small_residential_calculation import calculate_residential_study
from app.pz.small_residential_calculation_pdf import generate_residential_calculation_pdf
from app.pz.small_residential_section import audit_calculated_section, build_small_residential_section_svg
from tests.test_small_residential_section import model as model_fixture, rows


@pytest.fixture
def model():
    return model_fixture.__wrapped__()


def test_calculation_reuses_legacy_results_and_exact_catalogue_bores(model):
    original = deepcopy(model)
    r = calculate_residential_study(model)
    assert r.storm.q_total_l_per_s == 5.395
    assert r.water.sewage_flow == 2.293
    assert r.k1 is None  # The old 9 m basement route was not L from table 5.1.
    assert r.k2.inner_diameter_mm == 103.
    assert r.rain_profile.end_invert_m == pytest.approx(-1.22)
    assert r.rain_profile.passage_height_m(-3.1) == pytest.approx(1.8465)
    assert r.hydrostatic_bar == pytest.approx(.867888525)
    assert all(row.section_id == "K2" for row in r.sensitivities)
    assert sum(r.catchments_m2) == 252
    assert model == original


def test_service_check_is_graph_reachability_not_unjustified_maintenance_approval(model):
    r = calculate_residential_study(model)
    assert [(s.system, s.length_m, s.limit_m) for s in r.services] == [("K1", 9., 10.), ("K2", 6., 15.)]
    assert all(s.graph_ok and s.distance_ok and not s.accessibility_confirmed for s in r.services)


@pytest.mark.parametrize("change", ["bore", "grade", "flow", "stations", "occupancy", "catchments", "service"])
def test_inconsistent_calculation_cannot_be_bound_to_the_scheme(model, change):
    r = calculate_residential_study(model)
    if change == "bore":
        r = replace(r, rain_profile=replace(r.rain_profile, wall_thickness_mm=4.))
    elif change == "grade":
        r = replace(r, rain_profile=replace(r.rain_profile, slope=.01))
    elif change == "flow":
        r = replace(r, k2=replace(r.k2, design_flow_lps=2.))
    elif change == "stations":
        r = replace(r, rain_chainages_m=(.3, 2., 3., 7.))
    elif change == "occupancy":
        r = replace(r, residents=500)
    elif change == "catchments":
        r = replace(r, catchments_m2=(63., 63., 63., 100.))
    else:
        r = replace(r, services=(replace(r.services[0], graph_ok=False), r.services[1]))
    with pytest.raises(ValueError):
        build_small_residential_section_svg(model, calculation=r)


@pytest.mark.parametrize("change", ["flow", "level", "hidden", "funnel", "outlet"])
def test_export_audit_catches_calculation_drawing_drift(model, change):
    r = calculate_residential_study(model)
    svg = build_small_residential_section_svg(model, calculation=r)
    assert not audit_calculated_section(model, r, svg)
    root = ET.fromstring(svg)
    if change == "flow":
        rows(root, "data-calculation-binding")[0].set("data-q-k2", "1")
    elif change == "level":
        rows(root, "data-collector-profile")[1].set("data-start-invert", "-3")
    elif change == "hidden":
        rows(root, "data-proposed-k2-station")[1].attrib.pop("data-proposed-k2-station")
    elif change == "funnel":
        rows(root, "data-k2-stack")[0].set("y1", "100")
    else:
        next(v for v in rows(root, "data-outlet") if v.get("data-outlet") == "K2").set("y2", "290")
    assert audit_calculated_section(model, r, ET.tostring(root, encoding="unicode"))


def test_calculation_attachment_has_same_numbers_and_explicit_unresolved_checks(model, tmp_path):
    r = calculate_residential_study(model)
    pdf = generate_residential_calculation_pdf(str(tmp_path / "calculation.pdf"), model, r, rain_source_sha256="a"*64)
    reader = PdfReader(pdf)
    assert len(reader.pages) == 3
    text = " ".join(p.extract_text() for p in reader.pages)
    for expected in ("5,395", "2,293", "104,6", "103,0", "-1,22", "1,847", "Физический доступ не подтверждён", "самоочищение не проверено"):
        assert expected in text
    assert "→" not in text and "ü" not in text
