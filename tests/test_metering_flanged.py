from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from app.data.metering_products import get_metering_catalogue
from app.data.water_meters import WATER_METERS
from app.pz.metering_chain import build_metering_chain, ChainPath
from app.pz.metering_detail import drawing_state
from app.pz.metering_joint_audit import audit_direct_joints, meter_kit_topology_issues
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_mounting import resolve_mounting
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_spec import build_metering_spec_section
from scripts.preview_metering_flanged import flanged_review_project


def components(p):
    state = drawing_state(p)
    selection = resolve_metering_products(p, state.meter, bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    return selection, build_metering_chain(p.metering_detail, state, selection)


@pytest.mark.parametrize("dn", [m.d_mm for m in WATER_METERS])
def test_dimensional_coverage_for_every_hydraulic_meter_dn(dn):
    coverage = get_metering_catalogue().coverage(dn)
    assert all(coverage[role] for role in ("meter", "manual_valve", "filter", "check_valve"))


@pytest.mark.parametrize("dn", (65, 80, 100, 150, 200, 250))
def test_flanged_chain_scale_spec_and_calculation_preservation(dn):
    p = flanged_review_project(dn)
    before = deepcopy(asdict(p))
    selection, chain = components(p)
    assert not selection.errors
    assert selection.selected("meter").id == f"tvm-vshnd-dn{dn}"
    assert not any(n.role == "inline_nipple" for n in chain.nodes)
    assert not any(a.role == "meter_connections" for a in selection.accessories)
    assert not meter_kit_topology_issues(chain, get_metering_catalogue())
    assert chain.node("kit_in").minimum_length_mm == 3 * dn
    assert chain.node("kit_out").minimum_length_mm == dn
    layout = build_metering_layout(p)
    assert not layout.issues
    for part in layout.parts:
        if part.length_mm is not None:
            a, b = part.points[0], part.points[-1]
            assert ((b[0]-a[0])**2 + (b[1]-a[1])**2)**.5 == pytest.approx(part.length_mm/layout.scale)
    assert layout.part("kit_in").dimension_basis == "minimum"
    rows = build_metering_spec_section(p).rows
    assert not any("Присоединительный комплект счётчика" in r.name for r in rows)
    assert all(r.qty is None for r in rows if set(r.component_ids) & {"kit_in", "kit_out"})
    assert any("Задвижка" in r.name for r in rows)
    assert asdict(p) == before  # Geometry must not change S, DN, flow or head.
    checks = audit_direct_joints(chain, get_metering_catalogue(), inlet_dn=dn)
    c = next(c for c in checks if c.before == "valve_before" and c.after == "filter")
    assert c.status == "unresolved" and c.left.flange and c.right.flange
    assert "два одинаковых окончания" not in c.reason


def test_manufacturer_lengths_and_flange_dimensions_are_not_confused():
    from app.pz.metering_ugo import is_ball_cock
    c = get_metering_catalogue()
    for dn, meter, valve, filt, check in (
        (65, 200, 170, 290, 120), (100, 250, 190, 350, 170), (250, 450, 250, 730, 370)):
        for prefix, length in (("tvm-vshnd", meter), ("adl-kr20-pn16", valve),
                               ("adl-is16", filt), ("ridan-nvd402r", check)):
            p = c.products[f"{prefix}-dn{dn}"]
            assert p.body_length_mm == length
            assert p.flange and not p.thread and p.connection_sex == "flanged"
    flange = c.products["adl-kr20-pn16-dn250"].flange
    assert (flange.bolt_circle_mm, flange.bolt_count, flange.bolt_hole_mm) == (355, 12, 28)
    assert c.products["ridan-nvd402r-dn250"].flange.bolt_hole_mm is None  # M is not a hole diameter.
    assert c.products["tvm-vshnd-dn250"].flows_m3h["qmin_B"] == 10
    assert not is_ball_cock("adl-kr20-pn16-dn250")  # Notes say “не шаровой кран”.
    assert not is_ball_cock("adl-kr15-sa-pn16-dn100")


def test_unknown_or_russian_only_has_no_substitution():
    c = get_metering_catalogue()
    assert not any(c.coverage(300).values())
    assert not any(c.coverage(999).values())
    ru = c.coverage(250, russian_only=True)
    assert ru["meter"] == ("tvm-vshnd-dn250",)
    assert ru["manual_valve"] == ("adl-kr20-pn16-dn250",)
    assert not ru["filter"] and not ru["check_valve"] and not ru["electric_valve"]
    p = flanged_review_project()
    p.metering_detail.russian_equipment_only = True
    selection, _ = components(p)
    assert selection.selected("filter") is None and selection.selected("check_valve") is None
    assert selection.errors


def test_passport_straight_minimum_is_not_a_cut_length_and_is_protected():
    p = flanged_review_project(100)
    selection, chain = components(p)
    p.metering_detail.mounting.spans["kit_in"] = {"length_mm": 299, "source": "test"}
    audit = resolve_mounting(p)
    main = next(c for c in audit.chains if c.id == "main")
    assert any("меньше паспортного минимума 300" in text for text in main.issues)
    assert next(s for s in main.spans if s.id == "kit_in").length_mm is None
    p.metering_detail.mounting.spans["kit_in"]["length_mm"] = 300
    audit = resolve_mounting(p)
    main = next(c for c in audit.chains if c.id == "main")
    assert next(s for s in main.spans if s.id == "kit_in").length_mm == 300
    assert next(s for s in main.spans if s.id == "kit_out").length_mm is None
    damaged = replace(chain, paths=chain.paths+(ChainPath("bad", "Неверный отбор", ("kit_in", "gauge")),))
    assert meter_kit_topology_issues(damaged, get_metering_catalogue())
    svg = layout_contents(p)[0]
    assert 'data-dimension-basis="minimum"' in svg and "≥300" in svg


def test_source_trace_and_additive_revision():
    raw = json.loads(Path("app/data/metering_products_flanged.json").read_text())
    c = get_metering_catalogue()
    assert raw["revision"] in c.dimension_revisions
    assert sum(len(f["rows"]) for f in raw["families"]) == 39
    for f in raw["families"]:
        for source in f["source_ids"]:
            s = c.sources[source]
            assert s["url"].startswith("https://") and len(s["sha256"]) == 64 and s["pages"]
    assert c.revision == "2026-09-30.5"  # Unchanged small-meter bindings remain valid.
