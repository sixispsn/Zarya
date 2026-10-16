from copy import deepcopy
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from app.pz.small_residential_fan_binding import (
    audit_section_fan_svgs, build_section_fan_preview_svgs, generate_section_fan_preview_pdf,
)
from app.pz.small_residential_section import build_small_residential_section_svg, generate_small_residential_section_pdf
from tests.section_fan_fixture import section_fan_fixture


def test_compact_fan_view_covers_all_four_risers_without_changing_accepted_model():
    model, binding = section_fan_fixture()
    before = deepcopy(model)
    original = build_small_residential_section_svg(model)
    pages = build_section_fan_preview_svgs(model, binding)
    assert len(pages) == 2
    assert audit_section_fan_svgs(model, binding, pages) == ()
    assert model == before
    assert build_small_residential_section_svg(model) == original
    main, detail = map(ET.fromstring, pages)
    assert main.get("data-release-ready") == "false"
    assert len([r for r in main.iter() if r.get("data-section-apartment")]) == 4
    assert {r.get("data-section-fan-port") for r in main.iter() if r.get("data-section-fan-port")} == {"К1-1", "К1-4"}
    assert {r.get("data-fan-off-plane-riser") for r in main.iter() if r.get("data-fan-off-plane-riser")} == {"К1-2", "К1-3"}
    assert len([r for r in detail.iter() if r.get("data-fan-detail-port")]) == 4
    assert "Вне разреза л. 1" in " ".join(detail.itertext())
    assert len([r for r in detail.iter() if r.get("data-role") == "common_vent"]) == 1
    # Existing shared building/floor frame, K2, lower nodes and drops survive.
    for attr in ("data-k2-stack", "data-lower-system", "data-outlet-drop", "data-outlet-sleeve", "data-section-storey"):
        assert [ET.tostring(r) for r in main.iter() if r.get(attr)] == [
            ET.tostring(r) for r in ET.fromstring(original).iter() if r.get(attr)]


@pytest.mark.parametrize("change", ["unconfirmed", "stale_geometry", "roof_kind", "roof_level", "membership", "dn", "proof", "low_port", "non_residential", "duplicate"])
def test_section_rejects_unconfirmed_or_mismatched_fan_data(change):
    model, binding = section_fan_fixture()
    data, geo = binding.data, binding.geometry
    if change == "unconfirmed":
        geo = replace(geo, confirmed=False)
    elif change == "stale_geometry":
        geo = replace(geo, roofs=(replace(geo.roofs[0], scale=100),))
    elif change == "non_residential":
        data = replace(data, residential=False)
    elif change == "duplicate":
        data = replace(data, risers=(*data.risers, data.risers[0]))
    elif change == "roof_kind":
        data = replace(data, roof_kind="flat_accessible")
    elif change in {"roof_level", "low_port"}:
        d = data.roofs[0]
        d = replace(d, roof_level_m=6.7) if change == "roof_level" else replace(
            d, risers=tuple(replace(r, lower_port_m=4.0) for r in d.risers))
        data = replace(data, roofs=(d,))
        geo = replace(geo, roofs=(d,))
    elif change == "membership":
        data = replace(data, risers=data.risers[:-1])
    elif change == "dn":
        data = replace(data, risers=tuple(replace(r, diameter_mm=50) for r in data.risers))
    elif change == "proof":
        data = replace(data, evidence=replace(data.evidence, terminals=(replace(data.evidence.terminals[0], open_end_confirmed=None),)))
    with pytest.raises(ValueError):
        build_section_fan_preview_svgs(model, replace(binding, data=data, geometry=geo))


@pytest.mark.parametrize("change", ["lost_port", "lost_hidden", "wrong_sheet", "wrong_level", "disconnected", "lost_detail",
                                   "lost_collector", "moved_edge", "hidden_link", "hidden_duplicate", "wrong_terminal"])
def test_section_graphic_audit_detects_disappearing_or_disconnected_fan_ports(change):
    model, binding = section_fan_fixture()
    pages = list(build_section_fan_preview_svgs(model, binding))
    main, detail = map(ET.fromstring, pages)
    port = next(r for r in main.iter() if r.get("data-section-fan-port"))
    if change == "lost_port":
        port.attrib.pop("data-section-fan-port")
    elif change == "lost_hidden":
        next(r for r in main.iter() if r.get("data-fan-off-plane-riser")).attrib.pop("data-fan-off-plane-riser")
    elif change == "wrong_sheet":
        port.set("data-target-sheet", "3")
    elif change == "wrong_level":
        port.set("data-level-m", "4.7")
    elif change == "disconnected":
        port.set("data-y", "1")
    elif change == "lost_detail":
        next(r for r in detail.iter() if r.get("data-fan-detail-port")).attrib.pop("data-fan-detail-port")
    elif change == "lost_collector":
        next(r for r in detail.iter() if r.get("data-fan-edge") == "collector:1").attrib.pop("data-fan-edge")
    elif change == "moved_edge":
        next(r for r in detail.iter() if r.get("data-fan-edge")).set("x1", "99")
    elif change == "hidden_link":
        next(r for r in main.iter() if r.get("data-fan-off-plane-riser")).set("data-target-sheet", "9")
    elif change == "hidden_duplicate":
        main.append(deepcopy(next(r for r in main.iter() if r.get("data-fan-off-plane-riser"))))
    else:
        port.set("data-terminal", "К1-Вент999")
    pages = tuple(ET.tostring(r, encoding="unicode") for r in (main, detail))
    assert audit_section_fan_svgs(model, binding, pages)


def test_compact_group_without_architectural_routing_space_cannot_be_exported(tmp_path):
    model, binding = section_fan_fixture()
    # Previously this unplaced +5.40..+5.55 group was exported despite running
    # through the upper residential storey. Graph validity is insufficient.
    assert binding.geometry.confirmed
    assert all(3.3 < r.collector_m < 6.6 for r in binding.data.roofs[0].risers)
    output = tmp_path / "section.pdf"
    with pytest.raises(ValueError, match="пространству АР"):
        generate_section_fan_preview_pdf(str(output), model, binding)
    assert not output.exists()


def test_invalid_section_cannot_overwrite_existing_pdf(tmp_path):
    model, binding = section_fan_fixture()
    output = tmp_path / "section.pdf"
    generate_small_residential_section_pdf(str(output), model)
    before = output.read_bytes()
    with pytest.raises(ValueError):
        generate_section_fan_preview_pdf(str(output), model, replace(binding, geometry=replace(binding.geometry, confirmed=False)))
    assert output.read_bytes() == before
