"""Трассировка и подбор по каталогам CNP / Aikon 2025."""

from app.calc.fire_hydraulics import PumpDutyPoint, SourceKind
from app.calc.pumps import PumpInput, calculate_pump
from app.data.pumps import list_pumps
from app.pz.pump_bridge import compute_fire_pump_from_duty


def test_cnp_catalog_covers_three_product_families():
    current = [p for p in list_pumps(include_current=True) if not p.archived]
    models = {p.model for p in current}

    assert "PBS CDM10-8" in models
    assert "PFFS 2 CDM10-9 DS 16 S" in models
    assert "TD32-10(I)/2" in models


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
    assert suction.status == "pending"
    assert "не публикует NPSHr" in suction.decision


def test_cnp_fire_curve_covers_two_stream_duty():
    result = compute_fire_pump_from_duty(PumpDutyPoint(
        required_head_m=70.0,
        flow_lps=5.2,
        source_kind=SourceKind.CITY_MAIN,
    ))

    assert result.model == "CNP / Aikon PFFS 2 CDM15-7 DS 16 S"
    assert result.pump_head_at_design_m >= 70.0


def test_cnp_booster_is_selected_without_fabricated_npshr():
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
    assert accepted.pump.npshr is None
    assert accepted.npsh_ok is None
    assert any("NPSHr не опубликован" in reason for reason in accepted.reasons)


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
