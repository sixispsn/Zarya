"""An isolated quantity trial, not adoption of a new Samara hydraulic design."""
from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from app.intake import samara_study
from app.intake.studio_intake import answer_field, build_handoff_request
from app.intake.yaml_io import dump_request, load_request
from app.pz.spec import build_water_specification


PROPOSAL = samara_study.ROOT / 'demo/samara_riser_layout_proposal.json'


def test_proposal_is_separate_from_source_and_active_case():
    proposal = json.loads(PROPOSAL.read_text())
    data = samara_study.load_case()
    assert proposal['status'] == 'proposed_not_applied'
    assert proposal['scope'] == 'samara_section_3_2_only'
    assert proposal['base_payload_sha256'] == data['payload_sha256']
    assert proposal['source']['inferred_counts'] == dict(risers_v1=9, risers_t3=9, risers_t4=1)
    assert proposal['proposal']['values'] == dict(risers_v1=9, risers_t3=9, risers_t4=2)
    groups = proposal['proposal']['hws_groups']
    assert [len(g['draw_off_risers']) for g in groups] == [4, 5]
    assert sorted(n for g in groups for n in g['draw_off_risers']) == list(range(1, 10))
    assert len({g['return_riser'] for g in groups}) == 2
    _, _, active_values, _ = samara_study.reviewed_inputs(data)
    assert all(not active_values.get(key) for key in proposal['proposal']['values'])


def test_trial_uses_existing_inputs_and_preserves_calculations(tmp_path, monkeypatch):
    proposal = json.loads(PROPOSAL.read_text())['proposal']
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    draft_before = deepcopy(draft)
    req, station, result, fingerprint = samara_study.inputs(draft)
    baseline, _ = samara_study.build(draft, tmp_path / 'baseline', render=False)

    # Feed the three proposed counts through the same fields/DTO as a user.
    # Preserve all other signed Samara inputs, including unexposed extensions.
    ordinary = deepcopy(draft)
    ordinary.pop('study')
    for key, value in proposal['values'].items():
        answer_field(ordinary, key, value)
    typed = build_handoff_request(ordinary)
    trial_req = replace(req, **{key: getattr(typed, key) for key in proposal['values']})
    assert load_request(dump_request(trial_req)) == trial_req
    assert replace(trial_req, **{key: getattr(req, key) for key in proposal['values']}) == req

    # Trial only: the production loader must not start reading this proposal.
    monkeypatch.setattr(samara_study, 'inputs', lambda _: (trial_req, station, result, fingerprint))
    trial, _ = samara_study.build(draft, tmp_path / 'trial', render=False)
    before, after = asdict(baseline.project), asdict(trial.project)
    assert [key for key in before if before[key] != after[key]] == ['building']
    assert draft == draft_before
    assert (trial.project.flows.q_day_tot, trial.project.flows.q_sec_tot) == (63, 3.185)
    assert (trial.project.pumps.q_design_m3h, trial.project.pumps.h_design_m) == pytest.approx((11.466, 50.25))

    rows = [r for s in build_water_specification(trial.project).sections for r in s.rows]
    for key, qty in proposal['expected_components'].items():
        matches = [r for r in rows if r.component_ids == (key,)]
        # This old proposal sets only riser counts, not the new balancing choice.
        assert len(matches) == 1
        assert matches[0].qty == (None if key == 'circulation-balance' else qty)
    t4 = next(r for r in rows if r.component_ids == ('t4-network',))
    assert t4.qty is None  # Counts cannot manufacture metres or a Т4 diameter.
    assert 'по расчёту' in t4.name
    # Approved separate correction: riser counts no longer invent sectional valves.
    sectional = [r for r in rows if r.component_ids == ('v1-sectional-valves',)]
    assert len(sectional) == 1 and sectional[0].qty is None
    assert sectional[0].quantity_basis == 'needs_layout'
