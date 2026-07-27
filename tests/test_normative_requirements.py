"""Применимость СП 54/118/253 и нормативные решения стадии П."""
from app.pz.normative import (
    decide_grease_trap,
    decide_storm_system,
    derive_requirements,
)
from app.pz.project import BuildingFlags, BuildingPurpose


def test_sp54_requires_dn15_apartment_hose_tap():
    requirements = derive_requirements(
        BuildingFlags(
            purpose=BuildingPurpose.RESIDENTIAL,
            height_m=48,
            apartments=160,
        ),
        ["residential_full_bath"],
    )
    assert requirements.sp54_applicable
    assert requirements.apartment_hose_tap_required
    assert not requirements.sp253_applicable


def test_sp253_high_rise_public_requirements():
    requirements = derive_requirements(
        BuildingFlags(purpose=BuildingPurpose.PUBLIC, height_m=51),
        ["office"],
        owner_groups_count=3,
    )
    assert requirements.sp253_applicable
    assert requirements.separate_v1_v2_required
    assert requirements.hvs_min_insulation_mm == 10
    assert requirements.gvs_min_insulation_mm == 25
    assert requirements.frequency_drive_required
    assert requirements.pump_full_reserve_required
    assert requirements.pump_dispatch_required
    assert requirements.separate_owner_metering_required


def test_high_rise_mixed_use_requires_separate_k1():
    requirements = derive_requirements(
        BuildingFlags(purpose=BuildingPurpose.RESIDENTIAL, height_m=76),
        ["residential_full_bath", "office"],
    )
    assert requirements.mixed_use
    assert requirements.separate_k1_required


def test_storm_system_by_roof_and_floors():
    assert decide_storm_system("flat", 3).system_kind == "internal"
    assert decide_storm_system("sloped", 5).system_kind == "organized"
    assert decide_storm_system("sloped", 6).system_kind == "internal_or_heated_external"
    assert decide_storm_system("sloped", 7).system_kind == "internal"


def test_grease_trap_thresholds_are_exact():
    assert not decide_grease_trap("semi_finished", 499, 0, False).required
    assert decide_grease_trap("semi_finished", 500, 0, False).required
    assert not decide_grease_trap("raw", 199, 1499, False).required
    assert decide_grease_trap("raw", 200, 0, False).required
    assert decide_grease_trap("raw", 0, 1500, False).required
    assert decide_grease_trap("school", 0, 0, True).required
