# -*- coding: utf-8 -*-
"""Тесты app/calc/diameter_audit.py — два вердикта на участок и подбор Ду по target."""
import pytest

from app.calc.diameter_audit import (
    audit_segment, audit_sections, recommend_dn_by_target, AuditVerdict,
    DN_SERIES,
)
from app.calc.fire_hydraulics import (
    NetworkMode, SectionFlow, velocity_mps, NORMATIVE_VELOCITY_LIMIT_MPS,
    DESIGN_VELOCITY_TARGET_MPS,
)


# ── три типовых кейса (правило Антона) ───────────────────────────────────────

def test_case_a_all_ok():
    # медленный поток → и норматив, и target пройдены, Ду не менять
    a = audit_segment("s", flow_lps=4.0, current_dn=50, mode=NetworkMode.PURE_FIRE)
    assert a.normative_ok is True
    assert a.design_ok is True
    assert a.verdict == AuditVerdict.OK
    assert a.recommended_dn == 50


def test_case_b_normative_ok_target_fail():
    # v между 4 и 10 → норма OK, target нарушен → рекомендация, НЕ ошибка
    a = audit_segment("s", flow_lps=10.0, current_dn=50, mode=NetworkMode.PURE_FIRE)
    assert a.normative_ok is True
    assert a.design_ok is False
    assert a.verdict == AuditVerdict.OVERSIZED_TARGET
    assert a.recommended_dn > 50


def test_case_c_normative_fail():
    # v > 10 → нарушение норматива = ошибка
    a = audit_segment("s", flow_lps=25.0, current_dn=50, mode=NetworkMode.PURE_FIRE)
    assert a.normative_ok is False
    assert a.verdict == AuditVerdict.NORMATIVE_FAIL
    # рекомендуемый Ду по target, а не «лишь бы вписаться в норматив»
    assert a.recommended_dn is not None
    v_at_rec = velocity_mps(25.0, __import__("app.calc.fire_hydraulics", fromlist=["STEEL_INNER_DIAMETER_MM"]).STEEL_INNER_DIAMETER_MM[a.recommended_dn])
    assert v_at_rec <= DESIGN_VELOCITY_TARGET_MPS[NetworkMode.PURE_FIRE] + 1e-9


# ── подбор Ду ────────────────────────────────────────────────────────────────

def test_recommend_grows_with_flow():
    dn_small = recommend_dn_by_target(4.0, 4.0)
    dn_large = recommend_dn_by_target(20.0, 4.0)
    assert dn_large > dn_small


def test_recommend_by_target_not_normative():
    # для Q=12 target=4 требует бОльший Ду, чем если бы считали по 10
    dn_target = recommend_dn_by_target(12.0, 4.0)
    dn_norm = recommend_dn_by_target(12.0, 10.0)
    assert dn_target > dn_norm


def test_recommend_none_if_out_of_series():
    # экстремальный расход, ни один Ду не проходит target
    assert recommend_dn_by_target(1000.0, 4.0) is None


# ── режимы ───────────────────────────────────────────────────────────────────

def test_combined_mode_stricter():
    # тот же расход: в объединённом режиме норматив 3 → раньше fail
    q = 5.0
    pure = audit_segment("s", q, current_dn=50, mode=NetworkMode.PURE_FIRE)
    comb = audit_segment("s", q, current_dn=50, mode=NetworkMode.COMBINED_FIRE)
    assert pure.normative_limit_mps == 10.0
    assert comb.normative_limit_mps == 3.0
    # в объединённом норматив жёстче — при v>3 будет fail
    if pure.velocity_mps > 3.0:
        assert comb.normative_ok is False


# ── аудит по section-данным ──────────────────────────────────────────────────

def test_audit_sections_aggregates_verdicts():
    secs = [
        SectionFlow("mag", "src", "n", flow_lps=25.0, effective_length_m=20,
                    head_loss_m=1, inner_diameter_mm=53.0, velocity_mps=None,
                    velocity_normative_limit_mps=10, velocity_normative_ok=None,
                    velocity_design_limit_mps=4, velocity_design_ok=None, is_shared=True),
        SectionFlow("riser", "n", "a", flow_lps=4.0, effective_length_m=20,
                    head_loss_m=1, inner_diameter_mm=53.0, velocity_mps=None,
                    velocity_normative_limit_mps=10, velocity_normative_ok=None,
                    velocity_design_limit_mps=4, velocity_design_ok=None, is_shared=False),
    ]
    res = audit_sections(secs, NetworkMode.PURE_FIRE,
                         dn_by_segment={"mag": 50, "riser": 50})
    assert res.has_normative_fail is True   # магистраль 25 л/с через Ду50
    assert len(res.segments) == 2


def test_audit_sections_clean():
    secs = [SectionFlow("riser", "n", "a", flow_lps=2.6, effective_length_m=20,
                        head_loss_m=1, inner_diameter_mm=53.0, velocity_mps=None,
                        velocity_normative_limit_mps=10, velocity_normative_ok=None,
                        velocity_design_limit_mps=4, velocity_design_ok=None, is_shared=False)]
    res = audit_sections(secs, NetworkMode.PURE_FIRE, dn_by_segment={"riser": 50})
    assert res.has_normative_fail is False
    assert res.segments[0].verdict == AuditVerdict.OK


def test_no_diameter_no_crash():
    a = audit_segment("s", flow_lps=5.0, current_dn=None, mode=NetworkMode.PURE_FIRE)
    assert a.verdict == AuditVerdict.OK   # нет диаметра → не оцениваем
    assert a.velocity_mps is None
