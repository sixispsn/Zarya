"""Final VU delivery: sourced quantities and the ordinary PDF export path."""
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from pypdf import PdfReader

from app.pz.generator import generate_metering_scheme_pdf
from app.pz.metering_detail import build_metering_detail_pages
from app.pz.metering_layout import layout_contents
from app.pz.metering_mounting import resolve_mounting
from app.pz.metering_spec import build_metering_spec_section
from app.pz.spec import build_water_specification, format_spec_qty
from scripts.preview_metering_detail import catalogue_review_project


def assigned_project():
    p = catalogue_review_project()
    p.source.inputs_count = p.meters.inputs_count = 2
    p.metering_detail.mounting.pipe_cuts = {
        "inlet": {"length_mm": 1250, "source": "Заданная ведомость У1"},
        "outlet": {"length_mm": 750, "source": "Заданная ведомость У4"},
    }
    p.metering_detail.mounting.support_count = 3
    p.metering_detail.mounting.support_basis = "По принятой схеме опор на один ВУ"
    return p


def by_mark(section, mark):
    return next(r for r in section.rows if r.diagram_pos == mark)


def test_explicit_quantities_survive_without_fictitious_mounting_completion():
    p = assigned_project()
    before = deepcopy(asdict(p))
    result = resolve_mounting(p)
    section = build_metering_spec_section(p)
    assert result.pipe_lengths_m == {"inlet": 2.5, "outlet": 1.5}
    assert result.support_count == 6
    assert not result.dimensions_complete
    supports = next(r for r in section.rows if r.name.startswith("Опоры и крепления"))
    assert supports.qty == 6
    assert format_spec_qty(supports.qty, supports.unit) == "6"
    assert "на один ВУ" in supports.quantity_source
    assert supports.quantity_basis == "explicit_vu_supports"
    for mark, text in (("У1", "2,5 м"), ("У4", "1,5 м")):
        row = by_mark(section, mark)
        assert row.qty is None  # Not an extra procurement quantity.
        assert row.quantity_basis == "metering_mounting_reference"
        assert text in row.note and "повторно" in row.note
        assert "Заданная ведомость" in row.quantity_source
    text = "".join(layout_contents(p))
    assert "2,5 м" in text and "Опоры и крепления" in text and "6 компл." in text
    assert asdict(p) == before


def test_reference_cuts_do_not_modify_general_pipe_estimate_or_hydraulics():
    p = assigned_project()
    p.building.total_area_m2 = 1000
    without = deepcopy(p)
    without.metering_detail.mounting.pipe_cuts = {}
    without.metering_detail.mounting.support_count = None
    a, b = build_water_specification(p), build_water_specification(without)
    other = lambda spec: [asdict(s) for s in spec.sections if "Водомерный узел" not in s.title]
    assert other(a) == other(b)
    assert asdict(p.meters) == asdict(without.meters)
    assert asdict(p.flows) == asdict(without.flows)


@pytest.mark.parametrize("change", ["inactive", "dn", "unknown_material", "missing_source", "invalid_number"])
def test_stale_or_unverified_cuts_are_not_presented_as_accepted(change):
    p = assigned_project()
    d = p.metering_detail
    if change == "inactive":
        p.meters.has_bypass = False
        d.mounting.pipe_cuts = {"bypass": {"length_mm": 9999, "source": "old"}}
    elif change == "dn":
        d.inlet_dn = 65
    elif change == "unknown_material":
        d.pipe_sections["inlet"] = replace(d.pipe_sections["inlet"], material="unknown")
    elif change == "missing_source":
        d.pipe_sections["inlet"] = replace(d.pipe_sections["inlet"], geometry_source="")
    else:
        d.mounting.pipe_cuts["inlet"]["length_mm"] = float("nan")
    result = resolve_mounting(p)
    assert result.issues
    assert "inlet" not in result.pipe_lengths_m
    assert "bypass" not in result.pipe_lengths_m
    if change == "invalid_number":
        with pytest.raises(ValueError, match="length_mm"):
            build_metering_spec_section(p)
        return
    rows = build_metering_spec_section(p).rows
    assert all(r.qty is None for r in rows if r.unit == "м")
    assert not any("2,5 м" in r.note or "19,998 м" in r.note for r in rows)


def test_unsourced_support_count_is_not_a_confirmed_quantity():
    p = assigned_project()
    p.metering_detail.mounting.support_basis = ""
    assert resolve_mounting(p).support_count is None
    with pytest.raises(ValueError, match="support_basis"):
        build_metering_spec_section(p)


@pytest.mark.parametrize("scale", [5, 10, 20])
def test_complete_export_has_a3_frames_outlines_and_no_hidden_project_mutation(tmp_path, scale):
    p = catalogue_review_project()
    p.metering_detail.mounting.enabled = True
    p.metering_detail.mounting.scale = scale
    before = deepcopy(asdict(p))
    expected = build_metering_detail_pages(p)
    path = tmp_path / "vu.pdf"
    generate_metering_scheme_pdf(p, str(path))
    pdf = PdfReader(path)
    assert len(pdf.pages) == len(expected)
    for page in pdf.pages:
        assert float(page.mediabox.width) == pytest.approx(420 * 72 / 25.4, abs=.02)
        assert float(page.mediabox.height) == pytest.approx(297 * 72 / 25.4, abs=.02)
    titles = [item.title for item in pdf.outline]
    assert titles[0] == "Узлы учёта воды и вводы водопровода"
    assert "Водомерный узел. Связная размерная компоновка" in titles
    assert "ВУ. Состав компоновки и незавершённые соединения" in titles
    assert len(set(titles)) == len(titles)
    pages = [pdf.get_destination_page_number(item) for item in pdf.outline]
    assert pages == sorted(set(pages)) and pages[-1] < len(pdf.pages)
    assert asdict(p) == before
