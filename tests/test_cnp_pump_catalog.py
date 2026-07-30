"""Трассировка и подбор по каталогам CNP / Aikon 2025."""

from app.calc.fire_hydraulics import PumpDutyPoint, SourceKind
from app.calc.pumps import (
    PumpInput,
    calculate_pump,
    interpolate_pump_npshr,
)
from app.data.pumps import list_pumps
from app.api.pumps import calculate as calculate_pump_api
from app.pz.pump_bridge import compute_fire_pump_from_duty
from app.schemas.pumps import PumpRequest


def test_cnp_catalog_covers_three_product_families():
    current = [p for p in list_pumps(include_current=True) if not p.archived]
    models = {p.model for p in current}

    assert "PBS CDM10-8" in models
    assert "PFFS 2 CDM10-9 DS 16 S" in models
    assert "TD32-10(I)/2" in models
    assert len([p for p in current if p.brand.startswith("CNP")]) == 32


def test_cnp_fire_curve_covers_one_stream_duty():
    result = compute_fire_pump_from_duty(PumpDutyPoint(
        required_head_m=70.0,
        flow_lps=2.6,
        source_kind=SourceKind.CITY_MAIN,
    ), npsh_a_m=8.0)

    assert result.model == "CNP / Aikon PFFS 2 CDM10-9 DS 16 S"
    assert result.pump_head_at_design_m >= 70.0
    suction = next(
        check for check in result.sp10_checks
        if check.clause == "12.20-12.21"
    )
    assert suction.status == "verified"
    assert suction.decision == "NPSHa=8.0 м; NPSHr+0,5=2.5 м"


def test_cnp_fire_curve_covers_two_stream_duty():
    result = compute_fire_pump_from_duty(PumpDutyPoint(
        required_head_m=70.0,
        flow_lps=5.2,
        source_kind=SourceKind.CITY_MAIN,
    ))

    assert result.model == "CNP / Aikon PFFS 2 CDM15-7 DS 16 S"
    assert result.pump_head_at_design_m >= 70.0


def test_cnp_booster_uses_npshr_of_base_pump_at_working_point():
    result = calculate_pump(PumpInput(
        q_design_m3h=10.0,
        pump_type="boost",
        h_geom_manual=55.0,
        h_losses=0.0,
        h_pr=0.0,
        h_gar=0.0,
        npsh_a=8.0,
        include_current_catalog=True,
    ))

    accepted = result.candidates[0]
    assert accepted.pump.model == "PBS CDM10-8"
    # Постоянного условного NPSHr нет: используется Q-NPSHr кривая.
    assert accepted.pump.npshr is None
    assert accepted.npshr_at_working_point == 2.14
    assert accepted.npsh_ok is True
    assert any("кавитации нет" in reason for reason in accepted.reasons)


def test_cnp_cdm_qh_tables_replace_digitized_installation_curves():
    pumps = {
        p.model: p
        for p in list_pumps(include_current=True)
        if p.brand.startswith("CNP")
    }

    assert [(p.q, p.h) for p in pumps["PBS CDM10-8"].curve] == [
        (0, 90), (5, 85), (6, 84), (8, 79),
        (10, 71), (12, 60), (14, 46),
    ]
    assert [
        (p.q, p.h)
        for p in pumps["PFFS 2 CDM15-7 DS 16 S"].curve
    ] == [
        (0, 96), (8, 89), (10, 88), (12, 86), (14, 83),
        (15, 81), (16, 79), (18, 74), (20, 68), (22, 61), (24, 51),
    ]


def test_cnp_npshr_is_interpolated_from_vector_catalog_curve():
    pump = next(
        p for p in list_pumps("boost", include_current=True)
        if p.model == "PBS CDM10-8"
    )

    assert interpolate_pump_npshr(pump, 0) == 1.0
    assert interpolate_pump_npshr(pump, 9) == 1.85
    assert interpolate_pump_npshr(pump, 14) == 2.8


def test_cnp_fire_npsh_failure_reaches_sp10_check():
    result = compute_fire_pump_from_duty(PumpDutyPoint(
        required_head_m=70.0,
        flow_lps=2.6,
        source_kind=SourceKind.CITY_MAIN,
    ), npsh_a_m=2.0)

    suction = next(
        check for check in result.sp10_checks
        if check.clause == "12.20-12.21"
    )
    assert suction.status == "fail"
    assert suction.decision == "NPSHa=2.0 м; NPSHr+0,5=2.5 м"


def test_pump_api_exposes_npshr_at_working_point():
    response = calculate_pump_api(PumpRequest(
        q_design_m3h=10.0,
        pump_type="boost",
        h_geom_manual=55.0,
        h_losses=0.0,
        h_pr=0.0,
        h_gar=0.0,
        npsh_a=8.0,
    ))

    accepted = response.candidates[0]
    assert accepted.pump.model == "PBS CDM10-8"
    assert accepted.npshr_at_working_point == 2.14
    assert accepted.npsh_ok is True


def test_cnp_td_curve_is_tabular_not_digitized():
    pump = next(
        p for p in list_pumps("circ", include_current=True)
        if p.model == "TD32-10(I)/2"
    )

    assert [(point.q, point.h) for point in pump.curve] == [
        (2, 11.0), (3, 10.8), (4, 10.6), (5, 10.3),
        (6, 10.0), (7, 9.2), (8, 7.8), (9, 6.0),
    ]
    assert "стр. 74-75" in pump.source_note
