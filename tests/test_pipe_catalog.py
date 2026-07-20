"""Единая геометрия труб для гидравлики, проходок и спецификации."""
import pytest

from app.data.pipe_catalog import PEX, pipe_size, sleeve_for, steel_vgp_ordinary


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
    assert sleeve_for(steel_vgp_ordinary(50)).dn == 80


def test_unknown_material_fails_instead_of_falling_back_to_dn():
    with pytest.raises(ValueError, match="не задан точный сортамент"):
        pipe_size("неизвестный материал", 32)
