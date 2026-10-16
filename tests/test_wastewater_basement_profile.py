"""The preliminary profile is elevation-driven and never confirms missing design."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import re
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.calc.sewer_outlet_depth import preliminary_k1_frost_bound
from app.intake.yaml_io import load_request_file
from app.pz import wastewater_basement_profile as profile
from app.pz.wastewater_ugo import REVISION_CENTRE_ANCHOR


EXAMPLE = Path(__file__).parents[1] / "demo/residential_2floors_8apartments.yaml"


def request():
    return load_request_file(str(EXAMPLE))


def context(req=None, *, proposed=-2.2):
    return profile.basement_profile_from_request(
        req or request(), proposed_invert_m=proposed,
        proposed_invert_basis="Предварительный вариант, не готовая трасса.", preview_dn_mm=100,
    )


def svg(data=None):
    return ET.fromstring(profile.build_basement_profile_svg(data or context()))


def marked(root, name, value):
    return next(row for row in root.iter() if row.get(name) == value)


def test_frost_bound_is_not_a_final_outlet_elevation():
    bound = preliminary_k1_frost_bound(
        ground_elevation_m=-1, zero_temperature_depth_m=1.5, diameter_mm=100,
    )
    assert bound.highest_invert_m == pytest.approx(-2.2)
    assert bound.zero_temperature_level_m == -2.5
    assert bound.minimum_crown_cover_m == .7
    assert not bound.release_ready
    changed = preliminary_k1_frost_bound(
        ground_elevation_m=-1.2, zero_temperature_depth_m=1.7, diameter_mm=110,
    )
    assert changed.highest_invert_m == pytest.approx(-2.6)


@pytest.mark.parametrize("kwargs", [
    {"ground_elevation_m": float("nan")},
    {"zero_temperature_depth_m": -1.5},
    {"zero_temperature_depth_m": 0},
    {"diameter_mm": 0}, {"diameter_mm": 501}, {"diameter_mm": float("inf")},
])
def test_frost_bound_rejects_invalid_or_unsupported_inputs(kwargs):
    values = dict(ground_elevation_m=-1, zero_temperature_depth_m=1.5, diameter_mm=100)
    with pytest.raises(ValueError):
        preliminary_k1_frost_bound(**(values | kwargs))


def test_vertical_geometry_follows_elevations_and_clear_height():
    data = context()
    root = svg(data)
    scale = 1000 / float(root.get("data-vertical-scale-denominator"))
    first = marked(root, "data-profile-slab", "first-floor")
    floor = marked(root, "data-profile-slab", "basement")
    outlet = marked(root, "data-profile-pipe", "outlet")
    ground = marked(root, "data-profile-level", "ground")
    frost = marked(root, "data-profile-level", "frost")
    clear = marked(root, "data-clear-height-dimension", "true")
    assert scale == 40
    assert float(floor.get("y")) - float(first.get("y")) == pytest.approx(3.1 * scale)
    assert float(clear.get("y2")) - float(clear.get("y1")) == pytest.approx(2.8 * scale)
    assert float(floor.get("y")) - float(outlet.get("y1")) == pytest.approx(.9 * scale)
    assert float(frost.get("y1")) - float(ground.get("y1")) == pytest.approx(1.5 * scale)
    assert data.ceiling_m == pytest.approx(-.3)
    changed = svg(replace(data, basement_floor_m=-3.2, proposed_invert_m=-2.3))
    assert float(marked(changed, "data-profile-pipe", "outlet").get("y1")) == pytest.approx(
        float(outlet.get("y1")) + .1 * scale,
    )
    assert float(marked(changed, "data-profile-slab", "basement").get("y")) == pytest.approx(
        float(floor.get("y")) + .1 * scale,
    )


def test_proposal_does_not_change_request_or_confirm_canonical_assembly(monkeypatch):
    req = request()
    before = deepcopy(req)
    real_builder = profile.build_wastewater_basement_assembly
    captured = []

    def observe(**kwargs):
        result = real_builder(**kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(profile, "build_wastewater_basement_assembly", observe)
    data = context(req)
    root = svg(data)
    assert req == before
    assert req.sewer_pipes == req.sewer_first_manholes == []
    assert not data.release_ready
    assert root.get("data-release-ready") == "false"
    assert len(captured) == 1
    assert captured[0].outlet_invert_elevation_m is None
    assert captured[0].collector_slope_per_mille is None
    assert not captured[0].project_inputs_complete
    assert not captured[0].draft.validate()


def test_cleanout_is_coaxial_and_continues_to_outside_wall():
    root = svg()
    assembly = marked(root, "data-lower-connection", "elbow-wye-cleanout")
    assert assembly.get("data-accessible-capped-end") == "true"
    access = next(row for row in assembly.iter()
                  if row.get("data-carries-flow") == "false")
    access_line = next(iter(access))
    main = next(iter(marked(root, "data-draft-segment", "main")))
    outlet = marked(root, "data-profile-pipe", "outlet")
    # A horizontal service end aimed downstream, not a 45 degree branch.
    assert float(access_line.get("y1")) == float(access_line.get("y2")) == float(main.get("y1"))
    assert float(access_line.get("x1")) < float(access_line.get("x2"))
    assert float(main.get("x2")) == float(outlet.get("x1"))
    assert float(main.get("y2")) == float(outlet.get("y1"))
    wall = marked(root, "data-profile-wall", "schematic")
    assert float(outlet.get("x2")) > float(wall.get("x")) + float(wall.get("width"))
    assert not any(row.get("data-external-manhole") for row in root.iter())


def test_revision_dimension_targets_actual_access_centre_without_caption_overlap():
    root = svg()
    dimension = marked(root, "data-revision-dimension", "1000")
    symbol = marked(root, "data-ugo", "revision")
    tx, ty, rotation, sx, sy = map(float, re.findall(r"[-+]?\d+(?:\.\d+)?", symbol.get("transform")))
    assert rotation == 90
    circle = next(row for row in symbol.iter() if row.tag.endswith("circle"))
    assert (float(circle.get("cx")), float(circle.get("cy"))) == REVISION_CENTRE_ANCHOR
    centre_y = ty + sx * float(circle.get("cx"))
    assert centre_y == pytest.approx(float(dimension.get("y1")))
    caption = marked(root, "data-profile-revision-caption", "true")
    assert float(caption.get("y")) < centre_y - 2
    assert float(dimension.get("y2")) - centre_y == pytest.approx(40)  # 1000 mm at 1:25
    assert tx - sy * float(circle.get("cy")) == 128


def test_explicit_missing_fields_and_inconsistent_basement_are_rejected():
    with pytest.raises(ValueError, match="missing profile inputs"):
        context(replace(request(), wastewater_ground_relative_elevation_m=None))
    with pytest.raises(ValueError, match="disagree"):
        context(replace(request(), wastewater_basement_floor_elevation_m=-2.8))
    with pytest.raises(ValueError, match="conflicts"):
        svg(replace(context(), clear_height_m=3.5))
    with pytest.raises(ValueError, match="exposed basement outlet"):
        context(proposed=-3.2)


def test_paper_style_and_unknown_slope_remain_explicit():
    root = svg()
    assert (root.get("width"), root.get("height")) == ("420mm", "297mm")
    assert len([r for r in root.iter() if r.get("data-vector-diameter-sign") == "true"]) == 2
    assert {r.get("data-paper-text-height-mm") for r in root.iter()
            if r.get("data-paper-text-height-mm")} == {"2.5", "3.5", "5"}
    assert marked(root, "data-profile-pipe", "outlet").get("stroke-width") == "0.6"
    assert marked(root, "data-clear-height-dimension", "true").get("stroke-width") == "0.25"
    assert "Уклон: требуется расчёт" in "".join(root.itertext())
    assert "DN150 - компоновочный вариант" in profile.build_basement_profile_svg(
        replace(context(), preview_dn_mm=150),
    )


def test_pdf_is_one_vector_a3_sheet_with_cyrillic_text(tmp_path):
    path = tmp_path / "basement.pdf"
    profile.generate_basement_profile_pdf(str(path), context())
    reader = PdfReader(path)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width) == pytest.approx(420 * 72 / 25.4)
    assert float(page.mediabox.height) == pytest.approx(297 * 72 / 25.4)
    text = page.extract_text()
    for expected in ("Подвал", "Прочистка", "Ревизия", "2800", "-2,20", "-3,10"):
        assert expected in text
