from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import YamlFormatError, dump_request, load_request, load_request_file
from app.pz.wastewater_scheme_service import assess_wastewater_scheme_readiness
from app.pz.wastewater_sp30 import audit_wastewater_sp30
from app.pz.wastewater_ventilation import (
    FanRiser, FanTerminal, FanVentilationInput, audit_fan_ventilation,
    audit_project_fan_ventilation, fan_drafting_limitations,
)
from tests.fan_fixtures import confirm_independent_fans

DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _risers(n=4, mode="ventilated"):
    return tuple(FanRiser(f"К1-Ст{i}", 100., mode, "КК-1") for i in range(1, n + 1))


def _roof(n=4, **overrides):
    data = dict(
        terminal_id="Вытяжка-1", riser_ids=tuple(r.riser_id for r in _risers(n)),
        kind="roof", source_ref="АР-5 / ВК-3", height_m=3., diameter_mm=100.,
        collector_diameter_mm=100., opening_distance_m=4., open_end_confirmed=True,
        separate_from_other_systems=True, condensate_drains_to_risers=True,
        cold_attic=True, attic_insulated=True, plastic_exposed=True, uv_protected=True,
    )
    return FanTerminal(**(data | overrides))


def _audit(terminal=None, *, risers=None, roof_kind="flat_accessible"):
    return audit_fan_ventilation(
        roof_kind=roof_kind, risers=risers if risers is not None else _risers(),
        evidence=FanVentilationInput(terminals=(terminal or _roof(),)), residential=True,
    )


def _check(audit, code):
    return [c for c in audit.checks if c.code == code]


def test_confirmed_group_of_four_can_pass_normative_validation():
    assert _audit().ready


@pytest.mark.parametrize("n", [1, 2, 3])
def test_three_metres_without_four_connected_risers_fails(n):
    report = _audit(_roof(n), risers=_risers(n))
    assert not report.ready
    assert _check(report, "FAN-FOUR")[0].status == "fail"


def test_four_independent_roof_terminals_are_not_a_group():
    report = audit_fan_ventilation(
        roof_kind="flat_accessible", risers=_risers(), residential=True,
        evidence=FanVentilationInput(terminals=tuple(
            replace(_roof(), terminal_id=r.riser_id, riser_ids=(r.riser_id,)) for r in _risers()
        )),
    )
    assert all(c.status == "fail" for c in _check(report, "FAN-FOUR"))


@pytest.mark.parametrize("kind,minimum", [
    ("flat_non_accessible", .2), ("pitched", .2), ("gable", .2), ("single_slope", .2),
    ("collecting_vent_shaft", .1), ("flat_accessible", 3.),
])
def test_height_is_a_minimum_not_a_fixed_value(kind, minimum):
    for height in (minimum, minimum + .5):
        assert _audit(_roof(height_m=height), roof_kind=kind).ready
    assert _check(_audit(_roof(height_m=minimum - .01), roof_kind=kind), "FAN-HEIGHT")[0].status == "fail"


def test_complex_roof_needs_local_roof_type_not_a_global_height():
    for height in (.2, 3, 10):
        report = _audit(_roof(height_m=height), roof_kind="complex")
        assert not report.ready
        assert _check(report, "FAN-HEIGHT")[0].status == "pending"


@pytest.mark.parametrize("field,code", [
    ("open_end_confirmed", "FAN-OPEN"), ("separate_from_other_systems", "FAN-SEPARATE"),
    ("condensate_drains_to_risers", "FAN-CONDENSATE"), ("attic_insulated", "FAN-INSULATION"),
    ("uv_protected", "FAN-UV"),
])
def test_explicit_violation_fails_and_unknown_stays_pending(field, code):
    assert _check(_audit(_roof(**{field: False})), code)[0].status == "fail"
    assert _check(_audit(_roof(**{field: None})), code)[0].status == "pending"


def test_optional_exposures_do_not_require_fictional_insulation():
    assert _audit(_roof(cold_attic=False, attic_insulated=None, plastic_exposed=False, uv_protected=None)).ready


@pytest.mark.parametrize("distance,status", [(3.99, "fail"), (4., "verified"), (None, "pending")])
def test_windows_clearance_is_not_assumed(distance, status):
    assert _check(_audit(_roof(opening_distance_m=distance)), "FAN-OPENINGS")[0].status == status


def test_absence_of_openings_must_be_explicit_and_consistent():
    assert _audit(_roof(opening_distance_m=None, no_openings_confirmed=True)).ready
    assert _check(_audit(_roof(opening_distance_m=2, no_openings_confirmed=True)), "FAN-OPENINGS")[0].status == "fail"


def test_k2_ids_do_not_count_as_k1_risers():
    terminal = _roof(riser_ids=("К1-Ст1", "К2-Ст1", "К2-Ст2", "К2-Ст3"))
    audit = _audit(terminal, risers=_risers(1))
    assert len([c for c in _check(audit, "FAN-MEMBER") if c.status == "fail"]) == 3
    assert _check(audit, "FAN-FOUR")[0].status == "fail"


def test_group_uses_largest_connected_dn():
    risers = _risers()[:-1] + (replace(_risers()[-1], diameter_mm=150.),)
    assert _check(_audit(risers=risers), "FAN-DN")[0].status == "fail"
    assert _audit(_roof(diameter_mm=150., collector_diameter_mm=150.), risers=risers).ready


def test_duplicate_membership_is_rejected():
    report = audit_fan_ventilation(
        roof_kind="flat_accessible", risers=_risers(), residential=True,
        evidence=FanVentilationInput(terminals=(_roof(), replace(_roof(), terminal_id="second"))),
    )
    assert len(_check(report, "FAN-DUPLICATE")) == 4
    assert report.status == "fail"


def test_no_evidence_cannot_pass_and_does_not_mutate_input():
    risers = _risers()
    report = audit_fan_ventilation(roof_kind="flat_accessible", risers=risers, evidence=None, residential=True)
    assert report.status == "pending"
    assert risers == _risers()
    assert not report.ready


def test_missing_source_and_missing_outlet_stay_pending():
    assert _check(_audit(_roof(source_ref="")), "FAN-SOURCE")[0].status == "pending"
    assert _check(_audit(risers=tuple(replace(r, outlet_id=None) for r in _risers())), "FAN-OUTLETS")[0].status == "pending"


def _valve(rid="К1-Ст1", **overrides):
    return FanTerminal(**(dict(
        terminal_id="Клапан-1", riser_ids=(rid,), kind="valve", source_ref="ВК-3",
        separate_from_other_systems=True, valve_above_highest_fixture=True, valve_on_top_floor=True,
        valve_sizing_verified=True, valve_sizing_ref="Расчёт 19.8 / паспорт клапана",
    ) | overrides))


def test_all_valves_cannot_replace_residential_atmospheric_ventilation():
    report = audit_fan_ventilation(
        roof_kind="flat_accessible", risers=_risers(1, "vacuum_valve"), residential=True,
        evidence=FanVentilationInput((_valve(),), True, "Согласованная наружная сеть"),
    )
    assert _check(report, "FAN-ATMOSPHERE")[0].status == "fail"


@pytest.mark.parametrize("field,code", [
    ("valve_above_highest_fixture", "FAN-VALVE-LEVEL"),
    ("valve_on_top_floor", "FAN-VALVE-FLOOR"),
    ("valve_sizing_verified", "FAN-VALVE-SIZING"),
])
def test_valve_is_a_separate_verified_design_not_an_automatic_substitution(field, code):
    report = _audit(_valve(**{field: None}), risers=_risers(1, "vacuum_valve"))
    assert _check(report, code)[0].status == "pending"
    assert _check(report, "FAN-EXTERNAL")[0].status == "pending"


def test_mixed_roof_and_valve_needs_external_ventilation_evidence():
    risers = _risers() + (FanRiser("К1-Ст5", 100., "vacuum_valve", "КК-1"),)
    evidence = FanVentilationInput((_roof(), _valve("К1-Ст5")))
    audit = audit_fan_ventilation(roof_kind="flat_accessible", risers=risers, evidence=evidence, residential=True)
    assert audit.status == "pending"
    assert audit_fan_ventilation(roof_kind="flat_accessible", risers=risers,
                                evidence=replace(evidence, external_ventilation_verified=True,
                                                 external_ventilation_ref="ВК / п.18.25"), residential=True).ready


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1., True, "3"])
def test_invalid_measurements_are_rejected(value):
    with pytest.raises(ValueError):
        _roof(height_m=value)


def test_boolean_strings_and_duplicate_ids_are_rejected():
    with pytest.raises(ValueError):
        _roof(open_end_confirmed="false")
    with pytest.raises(ValueError):
        _roof(riser_ids=("К1-Ст1", "К1-Ст1"))


def test_yaml_roundtrip_and_builder_preserve_exact_evidence():
    request = load_request_file(str(DEMO))
    request.wastewater_fan_ventilation = FanVentilationInput((_roof(),))
    restored = load_request(dump_request(request))
    assert restored.wastewater_fan_ventilation == request.wastewater_fan_ventilation
    assert build_project(restored).sewage.fan_ventilation == request.wastewater_fan_ventilation


def test_yaml_rejects_bad_evidence_and_legacy_yaml_remains_unknown():
    request = load_request_file(str(DEMO))
    assert request.wastewater_fan_ventilation is None
    with pytest.raises(YamlFormatError, match="fan_ventilation"):
        load_request("document: {}\nbuilding: {}\nsewage:\n  fan_ventilation:\n    terminals: invalid\n")


def test_canonical_scheme_gate_rejects_unknown_fan_data_without_changing_project():
    project = build_project(load_request_file(str(DEMO)))
    before = deepcopy(project)
    assert not assess_wastewater_scheme_readiness(project).ready
    assert audit_project_fan_ventilation(project).status == "pending"
    assert project == before
    confirm_independent_fans(project)
    assert audit_project_fan_ventilation(project).ready
    assert assess_wastewater_scheme_readiness(project).ready


def test_project_roof_change_catches_three_metre_isolated_fans_and_reaches_sp30_audit():
    project = confirm_independent_fans(build_project(load_request_file(str(DEMO))))
    project.sewage.roof_kind = "flat_accessible"
    project.sewage.fan_ventilation = replace(project.sewage.fan_ventilation, terminals=tuple(
        replace(t, height_m=3.) for t in project.sewage.fan_ventilation.terminals
    ))
    audit = audit_wastewater_sp30(project)
    assert audit.fan_ventilation.status == "fail"
    assert any("минимум 4" in e for e in audit.errors)
    assert not assess_wastewater_scheme_readiness(project).ready


def test_missing_real_outlet_is_not_treated_as_ventilated_outlet():
    project = confirm_independent_fans(build_project(load_request_file(str(DEMO))))
    project.sewage.elements = [e for e in project.sewage.elements if e.kind != "outlet"]
    assert _check(audit_project_fan_ventilation(project), "FAN-OUTLETS")[0].status == "pending"


def test_renderer_never_replaces_group_or_valve_with_independent_roof_lines():
    project = build_project(load_request_file(str(DEMO)))
    project.sewage.fan_ventilation = FanVentilationInput((_roof(),))
    assert "графический модуль" in " ".join(fan_drafting_limitations(project))
    project.sewage.fan_ventilation = FanVentilationInput((_valve(),))
    assert fan_drafting_limitations(project)
    confirm_independent_fans(project)
    assert not fan_drafting_limitations(project)
    project.sewage.fan_ventilation = replace(project.sewage.fan_ventilation, terminals=tuple(
        replace(t, height_m=.3) for t in project.sewage.fan_ventilation.terminals
    ))
    assert fan_drafting_limitations(project)


def test_k2_only_does_not_need_fan_validation_but_cannot_accept_fake_k1_group():
    assert audit_fan_ventilation(roof_kind="unknown", risers=(), evidence=None, residential=True).ready
    assert _audit(risers=()).status == "fail"
