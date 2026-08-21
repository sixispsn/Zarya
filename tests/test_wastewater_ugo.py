from pathlib import Path

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.generator import (
    generate_wastewater_scheme_result,
    generate_wastewater_ugo_pdf,
)
from app.pz.wastewater_registry import KIND_LABELS
from app.pz.wastewater_ugo import (
    UGO_CATALOG,
    build_wastewater_ugo_sheet,
    fixture_trap_mode,
    get_ugo_definition,
    get_ugo_connection_anchor,
    legend_definitions,
    render_ugo,
)


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_every_registry_kind_has_a_catalog_entry():
    assert set(KIND_LABELS) <= set(UGO_CATALOG)
    assert len(UGO_CATALOG) == len(set(UGO_CATALOG))


def test_normative_sewer_symbols_keep_table_and_position_traceability():
    expected = {
        "sink": ("табл. 3", "поз. 2"),
        "washbasin": ("табл. 3", "поз. 3"),
        "bath": ("табл. 3", "поз. 7"),
        "shower": ("табл. 3", "поз. 9"),
        "toilet": ("табл. 3", "поз. 11"),
        "floor_drain": ("табл. 3", "поз. 16"),
        "roof_funnel": ("табл. 3", "поз. 18"),
        "trap": ("табл. 4", "поз. 4"),
        "revision": ("табл. 4", "поз. 11"),
        "flow_direction": ("табл. 5", "поз. 1"),
        "pump": ("табл. 2", "поз. 3а"),
        "check_valve": ("табл. 6", "поз. 5а"),
        "ball_valve": ("табл. 6", "поз. 16"),
    }
    for key, fragments in expected.items():
        definition = get_ugo_definition(key)
        assert definition.is_normative
        assert "ГОСТ 21.205-2016" in definition.basis
        assert all(fragment in definition.basis for fragment in fragments)


def test_recommended_and_project_symbols_are_not_presented_as_normative():
    assert get_ugo_definition("cleanout").status == "project"
    assert get_ugo_definition("fire_collar").status == "recommended"
    assert get_ugo_definition("roof_funnel_heated").status == "recommended"
    assert "заглушённый доступный конец" in get_ugo_definition("cleanout").basis
    assert "не УГО ГОСТ 21.205-2016" in get_ugo_definition("fire_collar").basis
    assert "не отдельное УГО ГОСТ 21.205-2016" in get_ugo_definition("roof_funnel_heated").basis
    assert get_ugo_definition("outlet").status == "project"
    assert not get_ugo_definition("junction").is_normative


def test_legend_contains_only_used_kinds_plus_flow_direction():
    rows = legend_definitions(["toilet", "roof_funnel", "toilet"])
    assert [row.key for row in rows] == [
        "toilet",
        "roof_funnel",
        "flow_direction",
    ]


def test_svg_renderer_marks_symbol_key_and_unknown_as_other():
    assert 'data-ugo="toilet"' in render_ugo("toilet", 10, 20)
    assert 'data-ugo="other"' in render_ugo("not_registered", 10, 20)
    with pytest.raises(KeyError, match="неизвестный вид УГО"):
        get_ugo_definition("not_registered")


def test_sink_and_washbasin_use_extracted_pdf_vector_geometry():
    sink = render_ugo("sink", 0, 0)
    assert "matrix(0.313253012048 0 0 -0.313253012048" in sink
    assert "M4382,6099 L4548,6099" in sink
    assert "M4536,6099 L4536,6004 L4394,6004 L4394,6099" in sink
    assert "M4465,6004 L4465,5959" in sink

    washbasin = render_ugo("washbasin", 0, 0)
    assert "matrix(0.057264050901 0 0 -0.057264050901" in washbasin
    assert "M14314,15017 L15257,15017" in washbasin
    assert "C14428,14820.0586 14588.0586,14660 14785.5,14660" in washbasin
    assert "C14982.9414,14660 15143,14820.0586 15143,15017.5" in washbasin
    assert "M14797,14660 L14773,14660 L14797,14390 Z" in washbasin


def test_fixture_connection_anchors_match_the_drawn_outlets():
    assert get_ugo_connection_anchor("sink") == pytest.approx((0.0, 21.927710844522))
    assert get_ugo_connection_anchor("washbasin") == pytest.approx((0.0, 17.966595975755))
    assert get_ugo_connection_anchor("bath") == (25.0, 19.0)
    assert get_ugo_connection_anchor("toilet") == (0.0, 20.0)
    with pytest.raises(KeyError, match="не задана точка выпуска"):
        get_ugo_connection_anchor("revision")


def test_fixture_trap_policy_does_not_duplicate_integral_water_seals():
    for kind in ("sink", "washbasin", "bath", "shower"):
        assert fixture_trap_mode(kind) == "external"
    for kind in ("toilet", "floor_drain"):
        assert fixture_trap_mode(kind) == "integral"
    assert fixture_trap_mode("roof_funnel") == "none"


def test_normative_fixture_shapes_match_gost_21205_geometry():
    bath = render_ugo("bath", 0, 0)
    assert 'x="-27" y="-12.5" width="54" height="25"' in bath
    assert 'd="M-27,-12.5 L-12,12.5 M25,12.5 V19"' in bath

    shower = render_ugo("shower", 0, 0)
    assert 'x="-25" y="-9" width="50" height="18"' in shower

    toilet = render_ugo("toilet", 0, 0)
    assert 'x="-12" y="-20" width="24" height="21"' in toilet
    assert 'd="M-12,1 L0,20 L12,1 Z"' in toilet

    floor_drain = render_ugo("floor_drain", 0, 0)
    assert 'd="M-21,-10 H21 L16,10 H-16 Z"' in floor_drain

    roof_funnel = render_ugo("roof_funnel", 0, 0)
    assert "matrix(0.008192524322 0 0 -0.008192524322" in roof_funnel
    assert "M6400.38672,6147.68994" in roof_funnel
    assert "C6245.09668,6985.32129 5514.4043,7593 4662.5,7593" in roof_funnel
    assert "M1733,6147 L2924,6147 M6400,6147 L7592,6147" in roof_funnel
    assert "M4662,4057 L4662,3045" in roof_funnel

    heated = render_ugo("roof_funnel_heated", 0, 0)
    assert "matrix(0.015187470337 0 0 -0.015187470337" in heated
    assert "M5833.61035,5902.11816" in heated
    assert "M7213,8174 L6334,7607" in heated
    assert "M2999,8174 L3878,7607" in heated
    assert "M5106,5028 L5106,4605" in heated

    pump = render_ugo("pump", 0, 0)
    assert 'd="M0,-12 L-5,-5 H5 Z"' in pump

    flow = render_ugo("flow_direction", 0, 0)
    assert 'd="M-25,0 H-8 M8,0 H25"' in flow
    assert 'd="M-8,-9 L8,0 L-8,9 Z"' in flow

    trap = render_ugo("trap", 0, 0)
    assert 'd="M-14,-20 V9 Q-14,20 -4,20 Q5,20 5,9 V-8' in trap
    assert 'Q5,-19 14,-19 Q23,-19 23,-8 V20"' in trap
    mirrored_trap = render_ugo("trap", 0, 0, scale=0.42, mirror_x=True)
    assert "scale(-0.420 0.420)" in mirrored_trap


def test_cleanout_uses_capped_access_end_from_vector_reference():
    cleanout = render_ugo("cleanout", 0, 0)
    assert "matrix(0.007919485233 0 0 -0.007919485233" in cleanout
    assert "M8019,7656 L2419,7656" in cleanout
    assert "M2419,8594 L2419,6850" in cleanout
    assert "M1958,8594 L1958,6850" in cleanout
    assert ">Пр</text>" not in cleanout


def test_scheme_legend_is_driven_by_demo_registry():
    svg = generate_wastewater_scheme_result(_project()).svg
    assert 'data-ugo="sink"' in svg
    assert 'data-ugo="flow_direction"' in svg
    assert 'data-ugo="system_k1"' in svg
    assert 'data-ugo="system_k2"' in svg
    assert 'data-ugo="roof_funnel_heated"' in svg
    assert 'data-ugo="trap"' in svg
    assert 'data-ugo="pump"' not in svg
    assert "нормативная трассировка - лист 2" in svg


def test_ugo_sheet_is_a3_and_contains_only_used_source_classes(tmp_path):
    project = _project()
    svg = build_wastewater_ugo_sheet(project)
    assert 'width="420mm"' in svg
    assert "нормативное УГО" in svg
    assert "рекомендуемый пример" in svg
    assert "проектное обозначение" not in svg
    assert "заглушённый доступный конец" not in svg
    assert "систем К1, К2" in svg
    assert "систем К1, К2 и К3" not in svg
    assert "ГОСТ 21.205-2016, табл. 3, поз. 11" in svg
    assert "ГОСТ 21.205-2016, табл. 4, поз. 4" in svg

    output = tmp_path / "ugo.pdf"
    generate_wastewater_ugo_pdf(project, str(output))
    page = PdfReader(str(output)).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    assert width_mm == pytest.approx(420.0, abs=0.02)
    assert height_mm == pytest.approx(297.0, abs=0.02)
