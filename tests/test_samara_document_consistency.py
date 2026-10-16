"""Display corrections must not mutate design inputs or substitute another duty."""
from copy import deepcopy
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from app.intake import samara_study
from app.pz.drawing_numbers import water_elevation_text
from app.pz.generator import generate_v1_calculation_html, generate_wastewater_pz_html
from app.pz.metering_detail import build_metering_detail_pages
from app.pz.spec import build_water_specification, build_wastewater_specification
from app.pz.residential_concept_section import build_concept_section_svg
from app.pz.wastewater_graphic_exports import representative_document_model
from tests.test_section_calculation_binding import project as section_project
from tests.test_section_document_consistency import table


@pytest.fixture(scope="module")
def samara(tmp_path_factory):
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    bundle, _ = samara_study.build(draft, tmp_path_factory.mktemp("samara-consistency"))
    return bundle.project


@pytest.mark.parametrize("value,expected", [(-2.195, "-2,20"), (2.195, "+2,20"),
    (0, "0,00"), (-.001, "0,00"), (-3.25, "-3,25")])
def test_shared_water_elevation_rounding(value, expected):
    from app.pz.scheme import _fmt_mark
    assert water_elevation_text(value) == _fmt_mark(value) == expected


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_invalid_water_elevation_rejected(value):
    with pytest.raises(ValueError, match="конечным"):
        water_elevation_text(value)


def test_meter_detail_uses_same_mark_without_rounding_source(samara):
    p = deepcopy(samara)
    before = deepcopy(p.source)
    text = " ".join(" ".join(ET.fromstring(svg).itertext())
                    for svg in build_metering_detail_pages(p))
    assert "-2,20" in text and "-2,19" not in text
    assert p.source == before


def test_control_flows_and_pump_need_stay_unchanged(samara):
    f = samara.flows
    assert (f.q_day_tot, f.q_day_c, f.q_day_h) == (63, 38.5, 24.5)
    assert (f.q_sec_tot, f.q_sec_c, f.q_sec_h) == (3.185, 1.636, 1.902)
    assert (f.q_hr_tot, f.q_hr_c, f.q_hr_h) == (7.71, 3.806, 4.527)
    assert f.sewage_l_per_s == 4.785
    assert samara.storm.result.q_total_l_per_s == 11.518
    assert samara.pumps.q_design_m3h == pytest.approx(11.466, rel=0, abs=1e-10)
    assert samara.pumps.h_design_m == pytest.approx(50.25, rel=0, abs=1e-10)


def pump_row(p):
    return next(r for s in build_water_specification(p).sections for r in s.rows
                if r.name.startswith("Установка повысительная:"))


def test_booster_spec_separates_design_duty_and_estimated_intersection(samara):
    p = deepcopy(samara)
    before = deepcopy(p.pumps)
    row = pump_row(p)
    assert "Qрасч=11,466" in row.name and "Hтреб=50,25" in row.name
    assert "P2 одного насоса=4,00" in row.name
    assert "оценочное пересечение Q=14,78" in row.note and "H=58,22" in row.note
    assert "не уставка ПЧ" in row.note and row.qty == 1
    assert p.pumps == before
    p.pumps.q_design_m3h = 0
    assert "расчётная пара Q/H не задана" in pump_row(p).name
    assert "14,78" not in pump_row(p).name


def test_booster_calculation_summary_uses_same_design_duty(samara):
    import re
    p = deepcopy(samara)
    html = generate_v1_calculation_html(p)
    summary = re.search(r'<table[^>]*pump-summary.*?</table>', html, re.S).group()
    assert 'Расчётный расход Qрасч</th><td>11,466 м³/ч' in summary
    assert 'Требуемый напор насоса Hтреб</th><td>50,25 м' in summary
    assert 'не уставка ПЧ</th><td>14,78 м³/ч / 58,22 м' in summary


@pytest.mark.parametrize("heated,phrase", [(True, "с электрообогревом"),
    (False, "без электрообогрева"), (None, "Необходимость электрообогрева воронок не задана")])
def test_funnel_heating_consistent_across_pz_scheme_spec(heated, phrase):
    p = section_project()
    p.sewage.presentation = replace(p.sewage.presentation, funnel_heated=heated)
    p.storm.funnels_count = 8
    before = deepcopy(p)
    rows = [r for s in build_wastewater_specification(p).sections for r in s.rows
            if r.name.startswith("Воронка водосточная для внутреннего водостока")]
    assert len(rows) == 1 and rows[0].qty == 8
    assert phrase in generate_wastewater_pz_html(p)
    if heated is not None:
        assert phrase in rows[0].name
    else:
        assert "необходимость электрообогрева не задана" in rows[0].note
    m = representative_document_model(p)
    root = ET.fromstring(build_concept_section_svg(m))
    funnels = [n for n in root.iter() if n.get("data-section-funnel")]
    assert len(funnels) == 1
    assert funnels[0].get("data-section-funnel") == ("roof_funnel_heated" if heated else "roof_funnel")
    assert funnels[0].get("data-heating-known") == str(heated is not None).lower()
    # PZ lazily caches diagnostics; that derived cache is not a design input.
    before.sewage.hydraulic_assessment = p.sewage.hydraulic_assessment
    assert p == before


def test_main_table_per_mille_does_not_change_source(samara):
    p = deepcopy(samara)
    before = deepcopy(p.sewage.presentation)
    cells = table(p).get_text()
    assert "Уклон, ‰" in cells and "10,000" in cells
    assert "0,010" not in cells
    assert p.sewage.presentation == before
    assert all(main.slope == .01 for _, main in representative_document_model(p).mains)
