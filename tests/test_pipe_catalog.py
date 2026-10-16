"""Единая геометрия труб для гидравлики, проходок и спецификации."""
import pytest

from app.data.pipe_catalog import (
    PEX, STEEL_VGP_ORDINARY, PipeSize, pipe_size, sleeve_for,
    preliminary_inlet_sleeve_for, steel_vgp_ordinary, steel_nominal_connection,
)


def test_steel_vgp_ordinary_dimensions_are_explicit():
    assert steel_vgp_ordinary(50).outer_mm == 60.0
    assert steel_vgp_ordinary(50).wall_mm == 3.5
    assert steel_vgp_ordinary(50).inner_mm == 53.0
    assert steel_vgp_ordinary(65).inner_mm == 67.5
    assert steel_vgp_ordinary(100).inner_mm == 105.0


def test_pex_dimensions_are_not_treated_as_dn_inner():
    assert PEX[32].outer_mm == 32.0
    assert PEX[32].inner_mm == pytest.approx(26.0)


def test_sleeve_is_selected_by_pipe_od_and_sleeve_id():
    assert sleeve_for(PEX[32]).dn == 40
    assert sleeve_for(steel_vgp_ordinary(50)).dn == 65
    assert sleeve_for(steel_vgp_ordinary(40)).inner_mm == 53
    assert sleeve_for(steel_vgp_ordinary(65)).inner_mm == 80.5


@pytest.mark.parametrize("pipe", [*PEX.values(), *STEEL_VGP_ORDINARY.values()])
def test_internal_sleeve_never_exceeds_either_clearance_limit(pipe):
    candidates = [s for s in STEEL_VGP_ORDINARY.values()
                  if 5 <= s.inner_mm - pipe.outer_mm <= 10]
    actual = sleeve_for(pipe)
    if candidates:
        assert actual == min(candidates, key=lambda s: s.inner_mm)
    else:
        assert actual is None


@pytest.mark.parametrize("outer,expected", [(48, 50), (43, 50), (42.9, None), (48.1, None)])
def test_internal_clearance_includes_5_and_10_but_not_nearest_oversize(outer, expected):
    actual = sleeve_for(PipeSize(0, outer, 2, "test", "test"))
    assert (actual.dn if actual else None) == expected


@pytest.mark.parametrize("outer", [0, -1, float('nan'), float('inf')])
def test_invalid_pipe_od_is_not_a_catalogue_miss(outer):
    with pytest.raises(ValueError, match="наружный диаметр"):
        sleeve_for(PipeSize(0, outer, 2, "test", "test"))


def test_external_inlet_keeps_separate_preliminary_selection():
    assert preliminary_inlet_sleeve_for(steel_vgp_ordinary(50)).dn == 80
    assert sleeve_for(steel_vgp_ordinary(150)) is None
    assert preliminary_inlet_sleeve_for(steel_vgp_ordinary(150)) is None


def test_unknown_material_fails_instead_of_falling_back_to_dn():
    with pytest.raises(ValueError, match="не задан точный сортамент"):
        pipe_size("неизвестный материал", 32)


def test_exact_weld_connection_does_not_replace_vgp_or_infer_unknown_sizes():
    connection = steel_nominal_connection(76, 3.5, 'Стальная 76x3,5')
    assert connection.dn == 65
    assert '17375-2001' in connection.basis
    assert steel_nominal_connection(75.5, 4, 'Стальная ВГП').dn == 65
    assert steel_nominal_connection(76, 3.5, 'Стальная ВГП') is None
    assert steel_nominal_connection(76, 3.5, 'Стальная ГОСТ 3262-75') is None
    assert steel_nominal_connection(76.1, 3.5, 'Стальная') is None
    assert steel_nominal_connection(76, 3.6, 'Стальная') is None
    assert steel_vgp_ordinary(65).inner_mm == 67.5
