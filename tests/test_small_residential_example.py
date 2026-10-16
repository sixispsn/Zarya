"""Исходные условия малого примера не превращаются в выдуманный расчёт."""
from dataclasses import replace
from pathlib import Path

import pytest

from app.data.sewer_pipe_catalog import (
    OSTENDORF_HT, catalog_pipe_fields, sewer_pipe_geometry,
)
from app.intake.project_builder import build_project, RequestValidationError
from app.intake.request_dto import SewerPipeRequest
from app.intake.yaml_io import (
    YamlFormatError, dump_request, load_request, load_request_file,
)


EXAMPLE = Path(__file__).parents[1] / "demo/residential_2floors_8apartments.yaml"


def example_request():
    return load_request_file(str(EXAMPLE))


def test_example_preserves_confirmed_inputs_through_yaml():
    req = example_request()
    assert load_request(dump_request(req)) == req
    assert (req.floors, req.floors_below, req.apartments, req.residents) == (2, 1, 8, 20)
    assert req.apartments_by_floor == {1: 4, 2: 4}
    assert req.basement_clear_height_m == 2.8
    assert req.floor_elevations_m == {-1: -3.1, 1: 0.0, 2: 3.3}
    assert req.wastewater_basement_floor_elevation_m == -3.1
    assert req.wastewater_ground_relative_elevation_m == -1.0
    assert req.wastewater_frost_depth_m == 1.5
    assert req.wastewater_outlet_plan_side == "bottom"
    assert req.wastewater_first_manhole_cover_relative_elevation_m == -1.0
    assert req.source_data.guaranteed_head_m == 5.0
    assert req.source_data.elev_header_m == -2.0
    assert req.source_data.h_pr_m == 20.0
    assert req.wastewater_roof_kind == "flat_non_accessible"
    assert req.wastewater_roof_relative_elevation_m == 6.6
    assert req.storm_funnels_count == 4


def test_cover_is_not_water_level_and_floor_elevation_is_explicit():
    req = example_request()
    assert req.wastewater_basement_floor_elevation_m == -3.1
    assert req.wastewater_floor_height_m is None
    assert req.building_height_m == 0  # незадано в существующем DTO
    assert req.fire_height_m is None
    assert req.sewer_first_manholes == []
    assert req.sewer_pipes == []
    assert req.consumers == []  # жители не означают подтверждение нормы ГВС
    assert req.hws_type == "unknown"
    assert req.source_data.h_geom_m is None
    assert req.source_data.elev_fixture_m is None
    with pytest.raises(RequestValidationError):
        build_project(req)  # неполный черновик не выдаётся за готовый проект


def test_builder_passes_metadata_without_creating_hydraulic_boundaries():
    req = example_request()
    # Только тестовый набор: дополняем отсутствующие входы, не меняя пример.
    req = replace(req, building_height_m=7.0, fire_height_m=4.5, hws_type="local",
                  source_data=replace(req.source_data, elev_fixture_m=4.0))
    assert req.validate() == []
    p = build_project(req)
    assert p.building.floors_below == 1
    assert p.building.basement_clear_height_m == 2.8
    assert p.building.floor_elevations_m == {-1: -3.1, 1: 0.0, 2: 3.3}
    assert p.building.apartments_by_floor == {1: 4, 2: 4}
    assert p.building.residents == 20
    assert p.sewage.first_manhole_cover_relative_elevation_m == -1.0
    assert p.sewage.basement_floor_elevation_m == -3.1
    assert p.sewage.ground_relative_elevation_m == -1.0
    assert p.sewage.frost_depth_m == 1.5
    assert p.sewage.outlet_plan_side == "bottom"
    assert p.sewage.pipe_series_id == OSTENDORF_HT.series_id
    assert p.sewage.roof_relative_elevation_m == 6.6
    assert p.sewage.first_manholes == p.sewage.pipes == []
    assert p.source.guaranteed_head_m == 5.0
    req.floor_elevations_m[2] = 9.0
    assert p.building.floor_elevations_m[2] == 3.3  # не общая mutable-ссылка


@pytest.mark.parametrize("outer,wall,inner", [(50, 1.8, 46.4), (110, 2.7, 104.6)])
def test_ht_dimensions_from_manufacturer(outer, wall, inner):
    size = sewer_pipe_geometry(OSTENDORF_HT.series_id, outer)
    assert size.wall_thickness_mm == wall
    assert size.inner_diameter_mm == inner
    assert size.series.source_pdf_page == 2
    assert size.series.source_url.startswith("https://ostendorf.ru/")


@pytest.mark.parametrize("outer", [100, 110.1, float("nan"), 0])
def test_catalog_never_guesses_outer_diameter_from_dn(outer):
    with pytest.raises(ValueError):
        sewer_pipe_geometry(OSTENDORF_HT.series_id, outer)


def test_catalog_entry_reaches_existing_pipe_dto_and_project_spec():
    row = {"catalog_series_id": OSTENDORF_HT.series_id, "outer_diameter_mm": 110}
    req = example_request()
    req = replace(req, building_height_m=7.0, fire_height_m=4.5, hws_type="local",
                  source_data=replace(req.source_data, elev_fixture_m=4.0))
    req.sewer_pipes = [SewerPipeRequest(
        system="K1", section_id="test", purpose="тестовый участок", length_m=2.0,
        catalog_series_id=OSTENDORF_HT.series_id, **catalog_pipe_fields(row),
    )]
    req = load_request(dump_request(req))
    pipe = build_project(req).sewage.pipes[0]
    assert pipe.catalog_series_id == OSTENDORF_HT.series_id
    assert pipe.inner_diameter_mm == pytest.approx(104.6)
    assert pipe.slope_per_mille is None
    assert pipe.design_flow_lps is None
    assert pipe.manning_n is None
    assert pipe.pressure_rated is None
    req.sewer_pipes[0].wall_thickness_mm = 3.4
    assert any("противоречит каталогу" in error for error in req.validate())
    with pytest.raises(YamlFormatError, match="противоречит каталогу"):
        load_request(dump_request(req))


@pytest.mark.parametrize("extra", [
    {"wall_thickness_mm": 3.4}, {"material": "cast_iron"},
    {"system": "K2"}, {"pressure_rated": True}, {"pressure_class_bar": 5},
    {"catalog_series_id": "unknown"},
])
def test_catalog_rejects_conflicting_or_out_of_scope_selection(extra):
    with pytest.raises(ValueError):
        catalog_pipe_fields({
            "catalog_series_id": OSTENDORF_HT.series_id,
            "outer_diameter_mm": 110, **extra,
        })


@pytest.mark.parametrize("field,value,message", [
    ("basement_clear_height_m", -2.8, "basement_clear_height_m"),
    ("basement_clear_height_m", float("nan"), "basement_clear_height_m"),
    ("floor_elevations_m", {1: 0, 2: -3.3}, "отметки должны возрастать"),
    ("floor_elevations_m", {3: 3.3}, "неизвестный этаж"),
    ("apartments_by_floor", {1: 4, 2: 3}, "apartments_by_floor"),
    ("wastewater_outlet_plan_side", "vertical_down", "сторона плана"),
    ("wastewater_first_manhole_cover_relative_elevation_m", float("inf"), "крышки"),
    ("wastewater_pipe_series_id", "unknown", "неизвестная серия"),
    ("wastewater_ground_relative_elevation_m", float("nan"), "отметка земли"),
    ("wastewater_frost_depth_m", -1.5, "глубина промерзания"),
    ("wastewater_frost_depth_m", float("inf"), "глубина промерзания"),
    ("wastewater_basement_floor_elevation_m", -2.8, "отметки пола подвала"),
    ("wastewater_roof_relative_elevation_m", float("inf"), "отметка кровли"),
    ("wastewater_roof_relative_elevation_m", 3.3, "выше верхнего этажа"),
])
def test_new_inputs_are_validated(field, value, message):
    req = replace(example_request(), **{field: value})
    assert any(message in error for error in req.validate())


@pytest.mark.parametrize("mapping", ["[0, 3.3]", "{1.2: 3.3}", "{1: 0, '1': 3.3}"])
def test_yaml_rejects_invalid_floor_maps_without_silent_conversion(mapping):
    with pytest.raises(YamlFormatError, match="floor_elevations_m"):
        load_request(f"document: {{}}\nbuilding: {{floor_elevations_m: {mapping}}}")


def test_yaml_resolves_selected_series_without_manual_wall_value():
    req = load_request("""
document: {}
building: {}
sewage:
  pipes:
    - id: test
      catalog_series_id: ostendorf_ht_pp
      outer_diameter_mm: 50
""")
    pipe = req.sewer_pipes[0]
    assert pipe.wall_thickness_mm == 1.8
    assert pipe.material == "pp"
    assert pipe.length_m == 0  # каталожная геометрия не подставляет длину участка


def test_clear_basement_height_never_sets_floor_elevation_by_itself():
    req = load_request("document: {}\nbuilding: {basement_clear_height_m: 2.8}")
    assert req.wastewater_basement_floor_elevation_m is None
    assert req.floor_elevations_m == {}


def test_frost_depth_and_ground_do_not_create_final_outlet_or_manhole_water_level():
    req = example_request()
    # Простая привязка глубины к принятому нулю, не расчёт окончательного выпуска.
    assert req.wastewater_ground_relative_elevation_m - req.wastewater_frost_depth_m == -2.5
    assert req.sewer_pipes == req.sewer_first_manholes == []
    assert "предварительный предел" in req.wastewater_design_assignment_ref
