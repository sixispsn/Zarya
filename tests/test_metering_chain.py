from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET

import pytest

from app.pz.metering_chain import build_metering_chain
from app.pz.metering_detail import drawing_state, build_metering_detail_pages, _label_width
from app.pz.metering_product_selection import resolve_metering_products
from scripts.preview_metering_detail import review_project, catalogue_review_project


def chain(p):
    state = drawing_state(p)
    selection = resolve_metering_products(p, state.meter, bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    return build_metering_chain(p.metering_detail, state, selection)


def reachable(c, start, end):
    visited, pending = set(), [start]
    while pending:
        ident = pending.pop()
        if ident == end:
            return True
        if ident not in visited:
            visited.add(ident)
            pending.extend(b for a,b in c.links if a == ident)
    return False


@pytest.mark.parametrize("count", [1,2,3])
def test_graph_has_continuous_flow_and_all_service_branches(count):
    p = review_project(count)
    before = deepcopy(asdict(p))
    c = chain(p)
    assert asdict(p) == before
    ids = [n.id for n in c.nodes]
    assert len(ids) == len(set(ids)) and c.instances == count
    assert reachable(c,"inlet","outlet")
    for ident in ids:
        assert reachable(c,"inlet",ident)
    for end in ("control_cap_1", "control_cap_2", "gauge", "outlet"):
        assert not any(a == end for a,b in c.links)
    paths = {path.id:path.nodes for path in c.paths}
    assert ("bypass" in paths) == drawing_state(p).bypass
    if "bypass" in paths:
        assert paths["bypass"][0] == "bypass_start" and paths["bypass"][-1] == "bypass_end"
        assert "meter" not in paths["bypass"]
    if count == 2:
        assert paths["fire"][0] == "fire_takeoff"
        assert paths["main"].index("fire_takeoff") < paths["main"].index("meter")
    assert not c.installation_complete


def test_reducers_outside_meter_kit_and_never_added_at_equal_dn():
    p = catalogue_review_project()
    c = chain(p)
    main = c.paths[0].nodes
    assert main.index("reducer_in") < main.index("valve_before") < main.index("kit_in")
    assert main.index("kit_out") < main.index("valve_after") < main.index("reducer_out")
    p.metering_detail.inlet_dn = drawing_state(p).meter.dn
    assert not any(n.id.startswith("reducer") for n in chain(p).nodes)


def test_current_products_counted_without_guessing_connection_parts():
    p = catalogue_review_project()
    c = chain(p)
    counts = Counter(n.catalogue_id for n in c.nodes if n.catalogue_id)
    assert counts["valtec-vt214-dn32"] == 2
    assert counts["valtec-vt214-dn50"] == 2  # inlet + accepted bypass
    assert counts["decast-vskm90-dg-dn32"] == 1
    assert counts["proaqua-pa22524p"] == counts["valtec-vtr582-0009"] == 1
    assert c.node("service_before").catalogue_id is None
    assert c.node("kit_in").catalogue_id == c.node("kit_out").catalogue_id == "decast-vskm90-kit-dn32"
    from app.pz.metering_spec import build_metering_spec_section
    kit_rows=[r for r in build_metering_spec_section(p).rows if "kit_in" in r.component_ids or "kit_out" in r.component_ids]
    assert len(kit_rows)==1 and kit_rows[0].qty==1  # two mating interfaces, ONE purchase kit
    p.metering_detail.pipe_sections["outlet"] = replace(p.metering_detail.pipe_sections["outlet"],material="pe")
    changed = chain(p)
    assert changed.node("outlet_connector").catalogue_id is None
    assert changed.node("outlet_thread").catalogue_id is None
    assert reachable(changed,"inlet","outlet")  # failed choice doesn't erase topology


def test_no_additional_chain_pages_without_catalogue_and_all_text_fits():
    assert not any('data-meter-chain' in s for s in build_metering_detail_pages(review_project()))
    pages = build_metering_detail_pages(catalogue_review_project())
    chain_pages = [s for s in pages if 'data-meter-chain' in s]
    assert chain_pages
    assert "Комплект учитывается один раз" in ''.join(chain_pages)
    for svg in chain_pages:
        root = ET.fromstring(svg)
        for e in root.iter():
            if not e.tag.endswith("text") or e.get("data-text-height-mm") is None:
                continue
            x,y = float(e.get("x")),float(e.get("y"))
            if y < 230:
                assert y <= 227
                assert x+_label_width(e.text or "",float(e.get("data-text-height-mm"))) <= 412
