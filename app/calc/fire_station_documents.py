"""Bound local study results to station evidence; no new hydraulic methodology.

This audit cannot release equipment: catalog dimensions are not manufacturer
approval, and a setting check is not a certified fire-control implementation.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from math import isfinite

from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_pressure_flow import handbook_characteristic, required_common_header
from app.calc.fire_pump_envelope import screen_pump_envelope
from app.data.fire_pump_study import STUDY_CANDIDATES
from app.data.fire_station_documents import PFFS32_ROW, SOURCES, MISSING_CONFIRMATIONS


def check_reserve_protections(*, dry_run_stop, current_trip, thermal_trip):
    """SP10 amendment 1, 12.3: unknown != off, off != station approval."""
    settings = dict(dry_run_stop=dry_run_stop, current_trip=current_trip,
                    thermal_trip=thermal_trip)
    if any(v is not None and type(v) is not bool for v in settings.values()):
        raise ValueError('Protection settings must be explicit bool or None')
    conflicts = [k for k, v in settings.items() if v is True]
    unknown = [k for k, v in settings.items() if v is None]
    return dict(status='conflict' if conflicts else ('needs_data' if unknown else 'settings_only'),
                conflicts=conflicts, unknown=unknown, clause='SP10 amendment 1:12.3',
                station_approved=False)


def review_station_documents(basis, station_result, station, apertures):
    """Validate provenance/completeness and report *necessary*, not sufficient bounds.

    Caller generates apertures from the current network. This additionally rejects
    mismatched basis, changed pump curves and incomplete scenario summaries.
    No value for an unknown internal station loss or product tolerance is returned.
    """
    fingerprint = sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if apertures['input_basis_sha256'] != fingerprint:
        raise ValueError('Stale diaphragm study: basis mismatch')
    candidate = next(c for c in STUDY_CANDIDATES if c.id == PFFS32_ROW['candidate_id'])
    pump = apertures['pump']
    if (pump['id'] != candidate.id or pump['station_model'] != candidate.station_model
            or tuple(map(tuple, pump['curve'])) != candidate.curve
            or pump['curve_sha256'] != candidate.curve_sha256):
        raise ValueError('Diaphragm study uses a different pump/source')
    variants = [v for v in apertures['variants'] if v['name'] in
                ('next_size', 'next_size_axis_minus_2', 'next_size_axis_plus_2')]
    if len(variants) != 3 or len({v['name'] for v in variants}) != 3:
        raise ValueError('Nominal and both graphical sensitivity studies required')
    floors = basis['study_assumptions']['residential_floors']
    expected = {(a, b, boundary) for a in range(1, floors+1) for b in range(1, floors+1)
                for boundary in ('one_supply_guaranteed', 'maximum_head_no_supply_loss_bound')}
    operations = []
    nominal = None
    for variant in variants:
        scenarios = variant['scenarios']
        if (len(scenarios) != len(expected) or
                {(s['floors'][0], s['floors'][1], s['boundary']) for s in scenarios} != expected):
            raise ValueError('Incomplete/duplicated scenario matrix')
        for scenario in scenarios:
            r = scenario['result']; op = r['operating']
            if (r['status'] != 'meets_minimum' or op is None or
                    not op['cabinets'] or any(not c['meets_minimum'] for c in op['cabinets'])):
                raise ValueError('A successful complete preliminary study is required')
            numbers = [r['pump_flow_m3h'], r['pump_head_m'], r['suction_head_m'],
                       op['header_head_m'], op['energy_residual_m']]
            if any(v is None or not isfinite(v) for v in numbers) or op['energy_residual_m'] > 1e-3:
                raise ValueError('Invalid numerical result')
            operations.append(r)
        if variant['name'] == 'next_size':
            nominal = variant

    net = station_result.network
    chars = [handbook_characteristic(c, hose_material='rubber_lined',
                                     nozzle_kind='non_shutoff') for c in net.cabinets]
    source_rows = [(s.guaranteed_head_m+s.source_elevation_m-station.pump_axis_m,
                    s.maximum_head_m+s.source_elevation_m-station.pump_axis_m,
                    sum(p.A*p.effective_length_m for p in s.segments)) for s in station.supplies]
    if len(source_rows) != 2 or len(set(source_rows)) != 1:
        raise ValueError('This study requires two identical explicit sources')
    hmin, hmax, resistance = source_rows[0]
    lowest_cabinet = min(net.nodes[c.node_id].elevation_m for c in net.cabinets)
    # In the representative graph cabinets are initially at the top floor.
    lowest_cabinet -= (floors-1)*basis['study_assumptions']['floor_to_floor_m']
    static_limit_header = .9*MPA_TO_M + lowest_cabinet - station.pump_axis_m
    required = required_common_header(net, chars, ceiling_head_m=static_limit_header)
    q = required.total_flow_lps
    required_boost = required.header_head_m - (hmin-resistance*q*q)
    screen = screen_pump_envelope(candidate.curve, required_q_m3h=q*3.6,
        required_boost_m=required_boost, maximum_suction_head_m=hmax,
        allowed_header_static_m=static_limit_header)
    maximum_shutoff = static_limit_header-hmax
    data = dict(
        method='L06 station evidence audit; no substituted losses',
        basis_sha256=fingerprint, candidate=asdict(candidate), evidence=deepcopy(PFFS32_ROW),
        sources=deepcopy(SOURCES), selection_confirmed=False, release_ready=False,
        selected_product=None, production_modified=False,
        duty_pumps=1, reserve_pumps=1, reserve_in_flow_sum=False,
        intended_application='standalone_vpv', internal_station_loss_m=None,
        guaranteed_station_curve=None, required_q_m3h=q*3.6,
        required_station_boost_m=required_boost, screen=asdict(screen),
        bound_note='Necessary bound at minimum-flow duty, NOT a permitted station loss for all scenarios',
        maximum_pump_shutoff_m=maximum_shutoff,
        nominal_shutoff_head_m=screen.shutoff_head_m,
        static_headroom_m=screen.static_margin_m,
        static_pressure_lowest_cabinet_mpa=(hmax+screen.shutoff_head_m+
            station.pump_axis_m-lowest_cabinet)/MPA_TO_M,
        suction_static_min_m=hmin, suction_static_max_m=hmax,
        source_maximum_is_study_assumption=True,
        nominal_apertures_mm=deepcopy(nominal['apertures_by_floor_mm']),
        scenario_count_per_variant=len(expected), checked_variants=len(variants),
        flow_range_m3h=[min(r['pump_flow_m3h'] for r in operations),
                       max(r['pump_flow_m3h'] for r in operations)],
        suction_range_m=[min(r['suction_head_m'] for r in operations),
                         max(r['suction_head_m'] for r in operations)],
        factory_control_check=check_reserve_protections(
            dry_run_stop=True, current_trip=None, thermal_trip=None),
        product_control_check=check_reserve_protections(
            dry_run_stop=None, current_trip=None, thermal_trip=None),
        requests=[dict(id=k, text=t) for k,t in MISSING_CONFIRMATIONS],
        inventory=deepcopy(PFFS32_ROW['included_components']),
        inventory_scope='included_in_one_station_not_separate_purchase_positions',
        retained_limits=('cabinet_products_and_diaphragm_tolerances', 'ring_failure_modes',
            'fire_coverage_on_plans', 'actual_utility_bounds', 'NPSH',
            'room_drainage_power_and_fire_automation_interfaces'),
    )
    return data
