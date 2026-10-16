"""Special-condition requirements survive standalone layout, catalogue and SO."""
from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET

import pytest

from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_mounting import resolve_mounting
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_rules import evaluate_metering_rules, seismic_metering_rules
from app.pz.metering_spec import build_metering_spec_section
from app.pz.generator import generate_spec_html
from scripts.preview_metering_detail import catalogue_review_project


def project_at(intensity):
    p = catalogue_review_project()
    p.building.seismicity = intensity
    p.metering_detail.mounting.enabled = True
    p.metering_detail.inline_joint_selection_mode = 'catalogue_proposal'
    p.metering_detail.service_selection_mode = 'catalogue_proposal'
    return p


@pytest.mark.parametrize('intensity', [0, 6, 7, 8, 9, 10])
def test_seismic_requirements_reach_all_views_without_becoming_product_counts(intensity):
    p = project_at(intensity)
    before = deepcopy(asdict(p))
    state = drawing_state(p)
    rules = seismic_metering_rules(p)
    expected = 2 if 7 <= intensity <= 9 else 1 if intensity > 9 else 0
    assert len(rules) == expected
    complete_rules = evaluate_metering_rules(p, state.meter,
        inputs_count=state.inputs_count, bypass=state.bypass)
    assert all(r in complete_rules for r in rules)
    selection = resolve_metering_products(p, state.meter,
        bypass=state.bypass, electric_bypass=state.electric_bypass)
    mounting = resolve_mounting(p, state, selection)
    layout = build_metering_layout(p, state)
    assert layout.special_layout_pending == (intensity >= 7)
    assert not layout.issues  # Base components remain viewable, not a blank sheet.
    rows = build_metering_spec_section(p).rows
    requirements = [r for r in rows if r.quantity_basis == 'metering_special_requirement']
    assert len(requirements) == expected
    for rule, row in zip(rules, requirements):
        assert rule.message in row.name and rule.clause == row.quantity_source
        assert row.qty is None and row.pos is None and row.unit == ''
        assert not row.catalogue_id and not row.component_ids
        assert any(rule.code in s for s in selection.pending)
        assert any(rule.code in s for s in mounting.issues)
    pages = layout_contents(p, state)
    assert ('data-special-layout="unresolved"' in pages[0]) == (intensity >= 7)
    # Empty catalogue and no exact mounting size are not a drawn flexible hose.
    assert not any('flex' in part.id or 'seismic' in part.id for part in layout.parts)
    text = ''.join(ET.fromstring('<svg>' + ''.join(pages) + '</svg>').itertext())
    for rule in rules:
        assert ''.join(rule.clause.split()) in ''.join(text.split())
    if rules:
        assert 'требование' in text and not mounting.dimensions_complete
    assert asdict(p) == before


@pytest.mark.parametrize('material', ['steel', 'galvanized_steel', 'stainless_steel', 'ppr', 'pe', 'pex'])
def test_material_and_written_basis_do_not_approve_seismic_compensation(material):
    p = project_at(8)
    d = p.metering_detail
    d.pipe_sections['inlet'] = replace(d.pipe_sections['inlet'], material=material)
    d.seismic_design_basis = 'КР лист 10; перемещения и изделие не назначены'
    assert seismic_metering_rules(p)[0].status == 'review'
    assert build_metering_layout(p).special_layout_pending
    assert not resolve_mounting(p).dimensions_complete
    from app.pz.commission import build_commission_report
    check = next(c for c in build_commission_report(p).checks if c.code == 'VU-COMPOSITION')
    assert check.blocking and check.status in ('missing', 'fail')


def test_recalculation_removes_requirements_and_does_not_retain_fake_seismic_parts():
    p = project_at(8)
    ordinary = build_metering_spec_section(project_at(0)).rows
    seismic = build_metering_spec_section(p).rows
    # Actual parts/quantities are unchanged: unspecified special joints have
    # not been counted twice under either the inlet or the meter diameter.
    actual = lambda rows: [(r.component_ids, r.catalogue_id, r.qty) for r in rows if r.component_ids]
    assert actual(ordinary) == actual(seismic)
    p.building.seismicity = 0
    assert build_metering_spec_section(p).rows == ordinary
    assert not build_metering_layout(p).special_layout_pending
    assert 'VU-SEISMIC' not in '\n'.join(resolve_mounting(p).issues)


def test_requirements_survive_full_pdf_and_specification_pipeline():
    p = project_at(8)
    pages = build_metering_detail_pages(p)
    layout = next(s for s in pages if 'data-vu-layout=' in s)
    assert 'data-special-layout="unresolved"' in layout
    assert 'data-protected-meter-kit="true"' in layout
    assert 'VU-SEISMIC-FLEX' in ''.join(pages)
    html = generate_spec_html(p)
    assert 'Требование к специальной комплектации ВУ' in html
    assert '15.2.6' in html


@pytest.mark.parametrize('condition', ['permafrost', 'outside'])
def test_other_existing_special_conditions_are_not_lost_in_dimensional_view(condition):
    p = project_at(0)
    if condition == 'permafrost':
        p.building.permafrost = True
    else:
        p.metering_detail.room_location = 'outside'
    assert 'data-special-layout="unresolved"' in layout_contents(p)[0]
    assert not resolve_mounting(p).dimensions_complete
    assert any('Специальная компоновка' in s for s in resolve_mounting(p).issues)
    assert seismic_metering_rules(p) == ()
