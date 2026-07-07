# -*- coding: utf-8 -*-
"""Тесты app/calc/fire_normative.py — резолвер Rk (п.7.15 + формула 3) и
кратности струй (п.6.2.2)."""
import pytest

from app.calc.fire_normative import (
    FireBuildingKind, FireSpaceKind, FireJetRadiusMode, FireJetNozzleDiameterMM,
    FireNormativeContext, resolve_fire_normative, resolve_minimum_rk_by_p_7_15,
    compute_rk_by_formula_7_16, get_phi_for_nozzle, validate_context,
)
from app.calc.fire_models import PlacementMode


def _ctx(**kw):
    base = dict(building_kind=FireBuildingKind.PUBLIC, space_kind=FireSpaceKind.ROOM,
                room_height_m=4.0, room_width_m=8.0, building_height_m=18.0,
                required_jets_override=1)
    base.update(kw)
    return FireNormativeContext(**base)


# ── Rk по п. 7.15 ───────────────────────────────────────────────────────────

def test_rk_residential_low_is_6():
    assert resolve_minimum_rk_by_p_7_15(_ctx(building_kind=FireBuildingKind.RESIDENTIAL,
                                             building_height_m=30.0)) == 6.0


def test_rk_residential_high_is_8():
    assert resolve_minimum_rk_by_p_7_15(_ctx(building_kind=FireBuildingKind.RESIDENTIAL,
                                             building_height_m=60.0)) == 8.0


def test_rk_public_high_is_16():
    assert resolve_minimum_rk_by_p_7_15(_ctx(building_kind=FireBuildingKind.PUBLIC,
                                             building_height_m=60.0)) == 16.0


# ── формула (3) п. 7.16 + φ табл. 7.4 ───────────────────────────────────────

def test_phi_table_7_4():
    assert get_phi_for_nozzle(FireJetNozzleDiameterMM.D13) == 0.0165
    assert get_phi_for_nozzle(FireJetNozzleDiameterMM.D16) == 0.0129
    assert get_phi_for_nozzle(FireJetNozzleDiameterMM.D19) == 0.0097


def test_formula_7_16_value():
    # Hp = 100*0.82*P/(1+100*φ*P); P=0.2, φ=0.0165 (D13)
    val = compute_rk_by_formula_7_16(0.2, FireJetNozzleDiameterMM.D13)
    expected = (100 * 0.82 * 0.2) / (1 + 100 * 0.0165 * 0.2)
    assert val == pytest.approx(expected, rel=1e-9)


def test_formula_never_below_minimum():
    # public >50м → минимум 16; формула при P=0.2 даёт ~14.7 → берётся 16
    ctx = _ctx(building_kind=FireBuildingKind.PUBLIC, building_height_m=60.0,
               jet_radius_mode=FireJetRadiusMode.FORMULA_7_16,
               nozzle_diameter_mm=FireJetNozzleDiameterMM.D13, pressure_at_nozzle_mpa=0.2)
    r = resolve_fire_normative(ctx)
    assert r.jet_params.compact_jet_radius_m == 16.0


# ── кратность и разные стояки по п. 6.2.2 ────────────────────────────────────

def test_corridor_over_10m_requires_different_risers():
    ctx = _ctx(space_kind=FireSpaceKind.CORRIDOR, room_width_m=12.0, required_jets_override=2)
    r = resolve_fire_normative(ctx)
    assert r.jet_multiplicity.required_jets == 2
    assert r.jet_multiplicity.require_different_risers is True
    assert not r.jet_multiplicity.manual_review_required


def test_corridor_under_10m_allows_one_riser():
    ctx = _ctx(space_kind=FireSpaceKind.CORRIDOR, room_width_m=8.0, required_jets_override=2)
    r = resolve_fire_normative(ctx)
    assert r.jet_multiplicity.require_different_risers is False


def test_non_corridor_two_jets_flags_manual_review():
    ctx = _ctx(space_kind=FireSpaceKind.STORAGE, room_width_m=24.0, required_jets_override=2)
    r = resolve_fire_normative(ctx)
    # СП не нормирует разные стояки вне коридора → False + manual_review
    assert r.jet_multiplicity.require_different_risers is False
    assert r.jet_multiplicity.manual_review_required is True


def test_one_jet_no_different_risers():
    r = resolve_fire_normative(_ctx(required_jets_override=1))
    assert r.jet_multiplicity.required_jets == 1
    assert r.jet_multiplicity.require_different_risers is False


# ── резолвер собирает совместимые JetParams / FireCabinetNormative ──────────

def test_resolver_outputs_layout_compatible_models():
    r = resolve_fire_normative(_ctx(placement_mode=PlacementMode.TWO_OPPOSITE_SIDES,
                                    required_jets_override=2, space_kind=FireSpaceKind.CORRIDOR,
                                    room_width_m=12.0))
    assert r.jet_params.compact_jet_radius_m > 0
    assert r.cabinet_normative.placement_mode == PlacementMode.TWO_OPPOSITE_SIDES
    assert r.cabinet_normative.required_jets == 2


# ── валидации ────────────────────────────────────────────────────────────────

def test_formula_mode_requires_pressure_and_nozzle():
    with pytest.raises(ValueError):
        validate_context(_ctx(jet_radius_mode=FireJetRadiusMode.FORMULA_7_16))


def test_override_rejects_three():
    with pytest.raises(ValueError):
        validate_context(_ctx(required_jets_override=3))


def test_table_7_1_not_implemented_without_override():
    from app.calc.fire_normative import resolve_required_jets_from_context
    ctx = _ctx(required_jets_override=None)
    with pytest.raises(NotImplementedError):
        resolve_required_jets_from_context(ctx)
