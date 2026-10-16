"""Presentation regression: a calculation section is not a template DN."""
from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET

import pytest

from app.intake import samara_study
from app.pz.project import BuildingPurpose, Project, V1SectionSpec
from app.pz.scheme import build_scheme, SchemeParams, PIPE
from app.pz.section_scaffold import build_section_scaffold
from app.pz.spec import build_specification
from app.pz.water_pipe_binding import bind_v1_pipes


def source_project():
    p = Project()
    p.building.purpose = BuildingPurpose.RESIDENTIAL
    p.building.floors_above = 16
    p.building.total_area_m2 = 9000
    p.v1_sections = [
        V1SectionSpec("В1-Подвод", 20, 96.8, 3.185, .01, role="input", material="ПЭ 110x6,6"),
        V1SectionSpec("В1-Магистраль", 20, 69, 1.636, .15, material="Стальная 76x3,5"),
        V1SectionSpec("В1-Стояк", 48, 41, .565, .15, material="Стальная 48x3,5"),
        V1SectionSpec("В1-Квартира", 8, 16, .217, .01, material="PE-X 20x2"),
    ]
    p.metering_detail.inlet_elevation_m = -2.195
    return p


def texts(svg):
    return " ".join(ET.fromstring(svg).itertext())


def test_sizes_and_materials_are_shared_without_nominal_rounding():
    p = source_project()
    original = deepcopy(asdict(p))
    binding = bind_v1_pipes(p)
    assert binding["main"].pipe.outer_mm == 76
    assert binding["main"].pipe.dn == 65
    assert binding["main"].pipe.inner_mm == 69  # not VGP 75.5×4 / inner 67.5
    assert "17375" in binding["main"].pipe.dn_basis
    assert binding["riser"].pipe.family == "steel"
    drawing = texts(build_scheme(p).svg)
    rows = build_specification(p, scope="water").sections[0].rows
    for role in binding:
        label = binding[role].pipe.label
        assert label in drawing
        assert any(label in row.type_mark for row in rows if row.name.startswith("Труба"))
    assert "Ст.В1-1 Ø48×3,5" in drawing
    assert "В1 Ø48×3,5" in drawing
    assert "Ø32" not in drawing and "∅80" not in drawing
    assert "Ø75,5×4" not in drawing
    assert sum(r.qty for r in rows if r.name.startswith("Труба") and r.qty is not None) == 2407.5
    sleeves = [r for r in rows if "Гильза" in r.name]
    assert len(sleeves) == 1 and "для трубы Ø110×6,6" in sleeves[0].note
    assert "DN125" in sleeves[0].type_mark
    assert not any("Муфта противопожарная" in r.name for r in rows)
    assert asdict(p) == original


@pytest.mark.parametrize("failure", ["mismatch", "missing", "ambiguous", "unknown_material"])
def test_unresolved_geometry_does_not_revert_to_template(failure):
    p = source_project()
    if failure == "mismatch":
        p.v1_sections[2].inner_diameter_mm = 40
    elif failure == "missing":
        p.v1_sections.pop(2)
    elif failure == "unknown_material":
        p.v1_sections[2].material = "Неизвестная 48×3,5"
    else:
        p.v1_sections.append(replace(p.v1_sections[2], section_id="В1-Стояк-2",
                                   inner_diameter_mm=54, material="Стальная 60×3"))
    assert bind_v1_pipes(p)["riser"].pipe is None
    result = build_scheme(p)
    assert "Ст.В1-1 Ø по расчёту" in texts(result.svg)
    assert any("стояк" in w for w in result.warnings)
    rows = build_specification(p, scope="water").sections[0].rows
    row = next(r for r in rows if r.name == "Трубы В1 — стояки")
    assert row.qty is None and row.note
    assert not any("Ø32×3" in r.type_mark for r in rows)


def covers_vertical(svg, x, lo, hi):
    spans = sorted((min(float(n.get("y1")), float(n.get("y2"))),
                    max(float(n.get("y1")), float(n.get("y2"))))
                   for n in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}line")
                   if n.get("stroke-width") == str(PIPE)
                   and float(n.get("x1")) == float(n.get("x2")) == x)
    end = lo
    for a, b in spans:
        if a <= end <= b:
            end = b
    return end >= hi


@pytest.mark.parametrize("pump", [True, False])
@pytest.mark.parametrize("floors", [2, 3, 16])
def test_risers_connect_to_basement_and_first_floor_without_10px_gap(pump, floors):
    p = source_project()
    p.pumps.required = pump
    p.building.floors_above = floors
    scaffold = build_section_scaffold(p)
    svg = build_scheme(p).svg
    for x in (scaffold.shaft_left_x, scaffold.shaft_right_x):
        assert covers_vertical(svg, x, scaffold.ground_bottom_y - 20, scaffold.ground_bottom_y + 6)
        assert covers_vertical(svg, x, scaffold.tech_y - 10, scaffold.tech_y + 10)
    if not pump:
        assert covers_vertical(svg, scaffold.x_left + 144, scaffold.ground_bottom_y + 6, 1560)


def test_only_an_explicit_heater_has_a_continuation_to_hws():
    p = source_project()
    p.pumps.required = True
    p.source.hws_heater_in_scope = False
    assert "К узлу ГВС" not in texts(build_scheme(p).svg)
    p.source.hws_heater_in_scope = True
    assert "К узлу ГВС; см. отдельный лист" in texts(build_scheme(p).svg)


def test_known_inlet_elevation_and_representative_rooms():
    p = source_project()
    p.source.elev_header_m = -9.5  # not necessarily the inlet
    svg = build_scheme(p).svg
    value = texts(svg)
    assert "отм. оси -2,20" in value and "-9,50" not in value
    assert p.metering_detail.inlet_elevation_m == -2.195
    assert "На разрыве не показано этажей: 12" in value
    assert "Квартира (характерная)" in value
    assert "Мусорокамера" not in value and "Пом. 01" not in value and "ПУИ" not in value
    overridden = texts(build_scheme(p, SchemeParams(inlet_mark_m=-1.5)).svg)
    assert "отм. оси -1,50" in overridden


def test_drawing_override_cannot_contradict_current_calculation():
    p = source_project()
    with pytest.raises(ValueError, match="противоречит"):
        build_scheme(p, SchemeParams(riser_v1_dn=80))
    assert "Ст.В1-1 Ø48×3,5" in texts(build_scheme(p, SchemeParams(riser_v1_dn=40)).svg)


def test_signed_samara_binding_preserves_hydraulics_and_flows(tmp_path):
    draft = {"answers": {}, "documents": []}
    samara_study.initialize(draft, None)
    bundle, _ = samara_study.build(draft, tmp_path)
    p = bundle.project
    original = deepcopy(asdict(p))
    q = (p.flows.q_day_tot, p.flows.q_sec_tot, p.flows.q_sec_c, p.flows.q_sec_h)
    assert q == (63, 3.185, 1.636, 1.902)
    assert p.source.h_geom_m == 48.195
    assert p.source.guaranteed_head_m == 30
    assert p.pumps.wp_q == pytest.approx(14.78, abs=.01)
    assert p.pumps.wp_h == pytest.approx(58.22, abs=.01)
    build_scheme(p)
    build_specification(p, scope="water")
    assert asdict(p) == original


def test_spec_pages_balance_rows_without_losing_positions():
    import re
    from app.pz.generator import _build_env
    from app.pz.spec import Specification, SpecSection, SpecRow
    from app.pz.spec_pagination import render_specification_body
    spec = Specification(sections=[SpecSection("В1", rows=[
        SpecRow(i, f"Позиция {i}") for i in range(1, 18)
    ])])
    html = render_specification_body(spec, _build_env())
    sheets = re.findall(r'<div class="spec-sheet"[^>]*>(.*?)</div>', html, re.S)
    batches = [re.findall(r'<tr class="s-item"[^>]*>\s*<td class="c">(\d+)</td>', sheet) for sheet in sheets]
    assert [len(rows) for rows in batches] == [17]  # all short rows fit physically
    assert [int(r) for rows in batches for r in rows] == list(range(1, 18))
