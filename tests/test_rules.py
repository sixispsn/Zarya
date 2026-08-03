"""Тесты движка нормативных решений (ВК)."""
from app.pz.project import (
    BuildingFlags, BuildingPurpose, FireSystem, MeterRow, MetersSystem,
    NormativeRequirements, PipeMaterials, WaterSource,
)
from app.pz.rules import (
    PRESSURE_LIMIT_MPA, calc_head_paths, calc_required_head,
    decide_fire_network, decide_water_inlets,
)


def test_fire_none_when_not_required():
    assert decide_fire_network(FireSystem(required=False), PipeMaterials()) is None


def test_fire_combined_default():
    d = decide_fire_network(
        FireSystem(required=True, pressure_at_lowest_pk_mpa=0.40), PipeMaterials())
    assert d.combined and d.reasons == []


def test_fire_separate_high_pressure():
    d = decide_fire_network(
        FireSystem(required=True, pressure_at_lowest_pk_mpa=0.50), PipeMaterials())
    assert not d.combined and len(d.reasons) == 1


def test_fire_separate_plastic():
    d = decide_fire_network(
        FireSystem(required=True), PipeMaterials(cold_is_plastic_uncertified=True))
    assert not d.combined


def test_fire_separate_aupt():
    d = decide_fire_network(FireSystem(required=True, has_aupt=True), PipeMaterials())
    assert not d.combined


def test_fire_separate_all_three_reasons():
    d = decide_fire_network(
        FireSystem(required=True, pressure_at_lowest_pk_mpa=0.6, has_aupt=True),
        PipeMaterials(cold_is_plastic_uncertified=True))
    assert not d.combined and len(d.reasons) == 3


def test_fire_separate_in_high_rise_even_without_other_reasons():
    d = decide_fire_network(
        FireSystem(required=True),
        PipeMaterials(),
        NormativeRequirements(separate_v1_v2_required=True),
    )
    assert not d.combined
    assert "СП 253" in d.reasons[0]


def test_pressure_boundary_exactly_limit_is_combined():
    # ровно 0,45 МПа — не превышает порог, объединение допустимо
    d = decide_fire_network(
        FireSystem(required=True, pressure_at_lowest_pk_mpa=PRESSURE_LIMIT_MPA),
        PipeMaterials())
    assert d.combined


def test_explicit_pre_meter_fire_branch_is_not_silently_combined():
    d = decide_fire_network(
        FireSystem(
            required=True,
            network_topology="pre_meter_branch",
            topology_basis="ТУ СКС, п. 7",
            branch_electric_valves=True,
        ),
        PipeMaterials(),
    )
    assert not d.combined and d.topology == "pre_meter_branch"
    assert "до узлов учёта В1" in d.summary
    assert "электроприводом" in d.summary


def test_explicit_combined_does_not_override_mandatory_separation():
    d = decide_fire_network(
        FireSystem(required=True, network_topology="combined"),
        PipeMaterials(),
        NormativeRequirements(separate_v1_v2_required=True),
    )
    assert not d.combined and d.topology == "separate"


def test_two_inlets_required_from_pk_or_apartments():
    fire = FireSystem(required=True, pk_total=12)
    building = BuildingFlags(
        purpose=BuildingPurpose.RESIDENTIAL, apartments=401,
    )
    d = decide_water_inlets(building, fire, adopted_count=1)
    assert d.minimum_count == 2 and not d.compliant
    assert len(d.reasons) == 2


def test_head_paths_include_all_meters_and_heater_and_keep_legacy_aggregate():
    from app.calc.pumps import PumpInput, calculate_pump

    source = WaterSource(
        guaranteed_head_m=25.0,
        h_geom_m=30.0,
        h_il_m=4.0,
        h_pr_m=20.0,
        h_vvod_m=2.0,
        h_tepl_m=3.0,
        hws_heater_in_scope=True,
        h_apartment_c_meter_m=0.4,
        h_apartment_h_meter_m=0.5,
    )
    meters = MetersSystem(rows=[
        MeterRow(label="Счётчик на вводе (общий)", h_a=0.6),
        MeterRow(label="Счётчик ХВС", h_a=0.2),
        MeterRow(label="Счётчик перед водонагревателем (ГВС)", h_a=0.3),
    ])
    paths = calc_head_paths(
        source, meters, hws_type="local", apartment_meter_required=True,
    )
    assert paths.cold.meter_loss_m == 1.2
    assert paths.cold.head.h_required_m == 57.2
    assert paths.hot.meter_loss_m == 1.4
    assert paths.hot.head.h_required_m == 60.4
    assert paths.governing.code == "T3" and paths.complete

    legacy = calculate_pump(PumpInput(
        q_design_m3h=5.0,
        h_geom_manual=paths.governing.head.h_geom_m,
        h_losses=paths.governing.head.h_losses_dynamic_m,
        h_pr=paths.governing.head.h_pr_m,
        h_gar=paths.governing.head.h_guaranteed_m,
    ))
    assert legacy.h_required == paths.governing.head.h_pump_m


def test_head_paths_do_not_hide_missing_apartment_and_heater_losses():
    source = WaterSource(
        h_geom_m=30.0, h_il_m=4.0, h_vvod_m=2.0,
        hws_heater_in_scope=True, h_tepl_m=0.0,
    )
    meters = MetersSystem(rows=[MeterRow(label="Счётчик ХВС", h_a=0.2)])
    paths = calc_head_paths(
        source, meters, hws_type="central", apartment_meter_required=True,
    )
    assert not paths.complete
    assert "потери в квартирном узле учёта ХВС" in paths.cold.missing
    assert "потери в водонагревателе/теплообменнике" in paths.hot.missing


def test_head_formula14():
    # Hтр = Hgeom + ∑Hil + Hпр + ∑Hвод + Hтепл + Hlввод
    src = WaterSource(guaranteed_head_m=28.0, h_geom_m=33.0, h_il_m=4.5,
                      h_pr_m=20.0, h_vod_m=1.5, h_tepl_m=3.0, h_vvod_m=2.0)
    h = calc_required_head(src)
    assert h.h_required_m == 64.0
    assert h.pump_needed is True
    assert h.deficit_m == 36.0


def test_head_deficit_is_same_aggregate_input_as_legacy_pump_calculator():
    """В legacy все динамические потери входят одним полем ΣHl."""
    from app.calc.pumps import PumpInput, calculate_pump

    src = WaterSource(
        guaranteed_head_m=28.0, h_geom_m=33.0, h_il_m=4.5,
        h_pr_m=20.0, h_vod_m=1.5, h_tepl_m=3.0, h_vvod_m=2.0,
    )
    head = calc_required_head(src)
    legacy_equivalent = calculate_pump(PumpInput(
        q_design_m3h=5.0, h_geom_manual=head.h_geom_m,
        h_losses=head.h_losses_dynamic_m, h_pr=head.h_pr_m,
        h_gar=head.h_guaranteed_m,
    ))
    assert head.h_required_m == 64.0
    assert head.h_pump_m == 36.0
    assert legacy_equivalent.h_required == head.h_pump_m


def test_head_pump_not_needed():
    src = WaterSource(guaranteed_head_m=70.0, h_geom_m=33.0, h_il_m=4.5,
                      h_pr_m=20.0, h_vod_m=1.5, h_tepl_m=3.0, h_vvod_m=2.0)
    h = calc_required_head(src)
    assert h.h_required_m == 64.0 and h.pump_needed is False


def test_head_pr_default_20():
    # Hпр по умолчанию 20 м (п.8.21)
    assert WaterSource().h_pr_m == 20.0


def test_head_no_core_data():
    # без Hgeom/∑Hil итог не считается
    h = calc_required_head(WaterSource(h_pr_m=20.0))
    assert h.h_required_m is None and h.pump_needed is None


# --- проверка лимитов ТУ ---
from app.pz.project import FlowsData
from app.pz.rules import check_tu_limits


def test_tu_no_limits():
    r = check_tu_limits(FlowsData(q_day_tot=18.0, q_sec_tot=2.0), WaterSource())
    assert r.all_ok and r.checks == []


def test_tu_passes():
    f = FlowsData(q_day_tot=18.35, q_sec_tot=2.0)
    s = WaterSource(tu_limit_q_day=26.5, tu_limit_q_sec=2.15)
    r = check_tu_limits(f, s)
    assert r.all_ok and len(r.checks) == 2


def test_tu_exceeds_sec():
    f = FlowsData(q_day_tot=18.35, q_sec_tot=2.22)
    s = WaterSource(tu_limit_q_day=26.5, tu_limit_q_sec=2.15)
    r = check_tu_limits(f, s)
    assert not r.all_ok
    sec = [c for c in r.checks if "екунд" in c.label][0]
    assert not sec.ok and sec.margin < 0


def test_tu_day_margin():
    f = FlowsData(q_day_tot=18.35, q_sec_tot=2.0)
    s = WaterSource(tu_limit_q_day=26.5)
    r = check_tu_limits(f, s)
    day = r.checks[0]
    assert day.ok and abs(day.margin - 8.15) < 0.01
