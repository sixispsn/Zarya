"""One active cutaway supplies drawing, text and quantity-unknown spec rows."""
from dataclasses import replace
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
import re

import pytest

from app.intake.project_builder import build_project
from app.intake.studio_intake import build_handoff_request
from app.pz.generator import generate_wastewater_pz_html
from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg
from app.pz.section_level_mark import level_text
from app.pz.spec import build_wastewater_specification, build_water_specification
from app.pz.wastewater_graphic_exports import representative_document_model
from app.pz.wastewater_gost import audit_wastewater_gost
from tests.test_section_design_inputs import designed_draft
from tests.test_studio_concept_section import ready_draft
from tests.test_wastewater_presentation import confirmed_project


def project():
    return build_project(build_handoff_request(designed_draft()))


def main_rows(p):
    return [row for sec in build_wastewater_specification(p).sections for row in sec.rows
            if row.name.startswith("Магистраль и выпуск")]


class TableText(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.parts = []
        self.feed(html)

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self, separator=" ", strip=True):
        return separator.join(part.strip() if strip else part for part in self.parts)


def table(p):
    match = re.search(r'<table[^>]*data-section-mains="true".*?</table>', generate_wastewater_pz_html(p), re.S)
    return TableText(match.group()) if match else None


@pytest.mark.parametrize("value,expected", [(0, "0,00"), (-.001, "0,00"), (3.3, "+3,30"), (-1.806, "-1,81")])
def test_level_format_no_unit_no_signed_zero(value, expected):
    assert level_text(value) == expected


def test_marks_anchored_to_floors_and_outlets_with_shelf_and_open_arrow():
    m = representative_document_model(project())
    root = ET.fromstring(build_concept_section_svg(m))
    marks = {r.get("data-level-mark"): r for r in root.iter() if r.get("data-level-mark")}
    for floor in m.shown_floors:
        boundary = next(r for r in root.iter() if r.get("data-floor-boundary") == str(floor))
        assert marks[f"floor-{floor}"].get("data-tip-y") == boundary.get("y")
    for system, main in m.mains:
        mark = marks["outlet-"+system]
        outlet = next(r for r in root.iter() if r.get("data-section-outlet") == system)
        assert float(mark.get("data-tip-y")) == float(outlet.get("y2"))
        assert float(mark.get("data-elevation-m")) == main.outlet_invert_m
    for mark in marks.values():
        shelf = next(r for r in mark if r.get("data-level-shelf"))
        arrow = next(r for r in mark if r.get("data-level-arrow"))
        assert shelf.get("y1") == shelf.get("y2")
        assert arrow.get("fill") == "none" and arrow.get("stroke-width") == ".25"
        assert any(r.get("data-paper-text-height-mm") == "3.5" for r in mark)
    # Guard against a future cosmetic pass dropping the actual symbol.
    first = marks["floor-1"]
    first.remove(next(r for r in first if r.get("data-level-arrow")))
    assert "invalid elevation symbol: floor-1" in audit_concept_section_svg(m, ET.tostring(root, encoding="unicode"))


def test_same_main_data_in_pz_drawing_and_spec_without_inventing_quantities():
    p = project()
    m = representative_document_model(p)
    html = generate_wastewater_pz_html(p)
    cells = table(p).get_text(" ", strip=True)
    svg = build_concept_section_svg(m)
    rows = main_rows(p)
    assert len(rows) == 2
    for system, main in m.mains:
        assert str(main.dn_mm) in cells and level_text(main.outlet_invert_m) in cells
        assert f"{main.slope * 1000:.3f}".replace(".", ",") in cells
        assert main.source_ref in cells and main.discharge_point in cells
        assert main.discharge_point in svg and level_text(main.outlet_invert_m) in svg
        row = next(r for r in rows if r.name.endswith(system))
        assert row.type_mark == f"DN{main.dn_mm}" and row.qty is None
        assert main.source_ref in row.note
    assert m.fan_notice in html and m.fan_notice in svg
    assert m.boundary_notice in html and "наружная сеть не моделируется" in svg.lower()
    assert "сформирована в комплекте" not in html
    checks = {r.code:r for r in audit_wastewater_gost(p).checks}
    assert checks["K-GOST-16"].status == "missing"
    assert "КК-1" in checks["K-GOST-05"].evidence and checks["K-GOST-05"].status == "missing"
    assert checks["K-GOST-13"].status == "missing" and "Характерный разрез" in checks["K-GOST-13"].evidence
    assert "внутренний водосток К2 не предусмотрен" not in html
    assert "В характерном разрезе принят внутренний водосток" in html
    assert "None" not in html
    assert not p.sewage.pipes and not p.sewage.elements and not p.sewage.risers
    assert all("Магистраль и выпуск" not in r.name for s in build_water_specification(p).sections for r in s.rows)


def test_edits_propagate_without_stale_spec_or_pz_and_keep_full_input_precision():
    p = project()
    p.sewage.presentation = replace(p.sewage.presentation,
        k1=replace(p.sewage.presentation.k1, dn_mm=200, slope=.015, outlet_invert_m=-1.806, discharge_point="КК-новый"))
    assert "КК-новый" in table(p).get_text() and "-1,81" in table(p).get_text()
    assert "КК-1" not in table(p).get_text()
    assert main_rows(p)[0].type_mark == "DN200"
    assert representative_document_model(p).k1.outlet_invert_m == -1.806


def test_unknown_and_zero_outlet_not_conflated():
    p = build_project(build_handoff_request(ready_draft()))
    assert not main_rows(p)
    m = representative_document_model(p)
    assert 'data-level-mark="outlet-' not in build_concept_section_svg(m)
    assert "не задана" in table(p).get_text()
    p.sewage.presentation = replace(p.sewage.presentation, k1=replace(p.sewage.presentation.k1, outlet_invert_m=0))
    m = representative_document_model(p)
    assert 'data-level-mark="outlet-К1"' in build_concept_section_svg(m)
    assert "0,00" in table(p).get_text()


def test_external_drainage_ignores_stale_k2_and_accessible_roof_keeps_pending_fan():
    p = project()
    p.sewage.presentation = replace(p.sewage.presentation, drainage="external")
    p.storm.system_kind = "external"
    p.sewage.roof_kind = "flat_accessible"
    m = representative_document_model(p)
    assert len(main_rows(p)) == 1 and "ДК-2" not in table(p).get_text()
    assert "Трасса объединения не задана" in m.fan_notice
    assert m.fan_notice in generate_wastewater_pz_html(p) and m.fan_notice in build_concept_section_svg(m)


def test_supplied_network_wins_even_if_broken_and_old_presentation_exists():
    p = confirmed_project()
    p.sewage.presentation = project().sewage.presentation
    for floor_height in (p.sewage.floor_height_m, None):
        p.sewage.floor_height_m = floor_height
        assert representative_document_model(p) is None
        assert table(p) is None and not main_rows(p)


def test_missing_geometry_does_not_claim_a_generated_scheme():
    p = project()
    p.sewage.floor_height_m = None
    assert representative_document_model(p) is None
    assert table(p) is None and not main_rows(p)
    assert "Не сформирована" in generate_wastewater_pz_html(p)
